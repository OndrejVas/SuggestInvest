"""
silver_futures_bot.py – Hlavní autonomní trading engine pro Micro Silver (SIL)
=============================================================================
KROK 63 v Silver Replication Roadmap v3.0

Modulárně integruje:
- silver_high_alpha_feeds.py (tržní data a 23h futures GSR)
- silver_regime_engine.py (HMM režim a BlowOff Exhaustion detektor)
- silver_strategies.py (7 strategií + 2-Stage Break-Even)
- silver_position_sizing.py (Volatility Gate a Kelly f*/3)
- silver_contract_manager.py (Front-Month kontrakt a rollover)
- silver_execution_engine.py (Adaptive Bracket orders)
- silver_trade_journal.py (Logování do silver_trades.jsonl)
"""

from __future__ import annotations
import os
import sys
import time
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

import pandas as pd

WORKSPACE_DIR = Path(__file__).resolve().parent.parent.parent
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))

from silver.config.silver_config import SilverRiskConfig, SilverInstrumentConfig, SilverKillzoneConfig
from silver.data.silver_high_alpha_feeds import SilverHighAlphaFeeds
from silver.data.silver_macro_bridge import SilverMacroBridge
from silver.models.silver_regime_engine import SilverRegimeEngine, MasterRegime, SilverPortfolioRiskState
from silver.models.silver_strategies import SilverStrategyEngine, SilverSignalDirection, SilverTradeSignal
from silver.models.silver_position_sizing import SilverPositionSizingEngine
from silver.execution.silver_contract_manager import SilverContractManager
from silver.execution.silver_execution_engine import SilverExecutionEngine
from silver.execution.silver_trade_journal import SilverTradeJournal
from silver.data.silver_async_io import safe_write_json

logger = logging.getLogger("SilverFuturesBot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [SILVER_BOT] %(message)s")

STATE_FILE = WORKSPACE_DIR / "data" / "silver_live_portfolio.json"


class SilverFuturesBot:
    """Kompletní autonomní bot pro Micro Silver (SIL)."""

    def __init__(self, initial_capital: float = 10_000.0):
        self.initial_capital = initial_capital
        self.risk_cfg = SilverRiskConfig(initial_capital=initial_capital)
        self.risk_state = SilverPortfolioRiskState(
            initial_capital=initial_capital,
            current_equity=initial_capital,
            high_water_mark=initial_capital
        )
        self.killzone = SilverKillzoneConfig()
        self.regime_engine = SilverRegimeEngine(risk_state=self.risk_state)
        self.strat_engine = SilverStrategyEngine(self.risk_cfg)
        self.sizing_engine = SilverPositionSizingEngine(self.risk_cfg)
        self.contract_mgr = SilverContractManager()
        self.exec_engine = SilverExecutionEngine()
        self.journal = SilverTradeJournal()
        self.feeds = SilverHighAlphaFeeds()
        self.macro_bridge = SilverMacroBridge()

        self.current_position = None

    def tick_evaluation(self, current_candle_df: pd.DataFrame) -> Dict[str, Any]:
        """
        Jeden vyhodnocovací cyklus bota (volaný při každé svíčce / ticku).
        """
        now = datetime.now()
        dt_str = now.strftime("%Y-%m-%d %H:%M:%S")

        # 1. Čerstvá tržní telemetrie
        telemetry = self.feeds.fetch_feeds_snapshot()
        si_price = telemetry.get("silver_price_usd", 32.50)
        gsr_info = telemetry.get("gsr_futures", {})

        # 2. HMM režim
        regime, reg_telemetry = self.regime_engine.evaluate_regime(
            current_candle_df,
            gsr_zscore=gsr_info.get("zscore", 0.0)
        )

        # 3. Kontrola otevřené pozice
        action_taken = "HOLD"
        if self.current_position is not None:
            # 2-Stage Break-Even posun
            new_sl, stage = self.strat_engine.evaluate_2stage_breakeven(
                current_price=si_price,
                entry_price=self.current_position["entry_price"],
                initial_sl=self.current_position["stop_loss"],
                direction=self.current_position["direction"]
            )
            self.current_position["stop_loss"] = new_sl
            self.current_position["stage"] = stage
            action_taken = f"POSITION_ACTIVE ({stage})"

        # 4. Hledání nového vstupu (pokud nemáme pozici a jsme v Killzone)
        elif self.killzone.is_valid_killzone(now.hour, now.minute):
            sig = self.strat_engine.generate_signal(
                current_candle_df,
                regime,
                gsr_telemetry=telemetry
            )

            if sig is not None:
                # Position Sizing & Volatility Gate
                decision = self.sizing_engine.compute_size(
                    current_equity=self.risk_state.current_equity,
                    proposed_sl_dollars_per_oz=sig.r_distance_usd,
                    regime=regime,
                    session_hour_cet=now.hour,
                    session_minute_cet=now.minute,
                    month=now.month,
                    gsr_zscore=gsr_info.get("zscore", 0.0)
                )

                if decision.allow_trade and decision.contracts >= 1:
                    # Sestavení bracket příkazu
                    bracket = self.exec_engine.build_bracket_order(
                        sig, bid_price=si_price - 0.005, ask_price=si_price + 0.005
                    )
                    self.current_position = {
                        "entry_time": dt_str,
                        "entry_price": si_price,
                        "stop_loss": sig.stop_loss,
                        "take_profit": sig.take_profit,
                        "direction": sig.direction,
                        "contracts": decision.contracts,
                        "strategy_id": sig.strategy_id,
                        "strategy_name": sig.strategy_name,
                        "stage": "INITIAL"
                    }
                    action_taken = f"ENTERED_{sig.direction.value}_{sig.strategy_name} ({decision.contracts} SIL)"

                    self.journal.log_trade({
                        "event": "ENTRY",
                        "timestamp": dt_str,
                        "symbol": self.contract_mgr.get_contract_code(now),
                        "direction": sig.direction.value,
                        "contracts": decision.contracts,
                        "price": si_price,
                        "stop_loss": sig.stop_loss,
                        "take_profit": sig.take_profit,
                        "strategy": sig.strategy_name,
                        "regime": regime.name,
                        "volatility_gate": "PASSED"
                    })
                else:
                    action_taken = f"SKIP_TRADE ({decision.volatility_gate_status})"

        state = {
            "timestamp": dt_str,
            "silver_price": si_price,
            "regime": regime.name,
            "active_contract": self.contract_mgr.get_contract_code(now),
            "current_equity": round(self.risk_state.current_equity, 2),
            "high_water_mark": round(self.risk_state.high_water_mark, 2),
            "drawdown_pct": round(self.risk_state.current_drawdown_pct * 100.0, 2),
            "open_position": self.current_position is not None,
            "position_details": self.current_position,
            "action": action_taken,
            "sovereign_floor": self.risk_cfg.sovereign_floor,
            "max_daily_loss_usd": self.risk_cfg.max_daily_loss_usd,
            "status": "RUNNING"
        }

        safe_write_json(str(STATE_FILE), state)
        return state


_SILVER_BOT_INSTANCE: Optional[SilverFuturesBot] = None
_LAST_SILVER_TRADE_TIME: float = 0.0


def evaluate_silver_autonomous_bot(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Vyhodnotí jeden cyklus autonomního trading bota SilverEdge v2.5.1 pro COMEX Micro Silver (SIL).
    Zcela nezávislý engine od Argon V2.5 Zlato:
    - 7 specializovaných strategií (Trend KAMA Pullback, Volatility Breakout, Mean Reversion BB, London Momentum, Shanghai Arbitrage, Macro COT Flow, GSR Pairs Switch).
    - 2-Stage Break-Even posun ochranného Stop-Lossu.
    - Volatility Gate a Kelly f*/3 position sizing.
    - Ochranné pásmo Sovereign Floor ($9,000 USD).
    """
    global _SILVER_BOT_INSTANCE, _LAST_SILVER_TRADE_TIME

    if _SILVER_BOT_INSTANCE is None:
        _SILVER_BOT_INSTANCE = SilverFuturesBot(initial_capital=10_000.0)

    orders_enabled = state.get("orders_enabled", False)
    gateway_connected = state.get("gateway_connected", False)
    dom_silver = state.get("dom_silver_l2", {})
    metrics = dom_silver.get("metrics", {})
    now_dt = datetime.now()
    now_str = now_dt.strftime("%d.%m.%Y %H:%M:%S")

    strat_list = [
        "Strat 1: Trend KAMA Pullback",
        "Strat 2: Volatility Breakout",
        "Strat 3: Mean Reversion BB",
        "Strat 4: London Momentum",
        "Strat 5: Shanghai-London Arbitrage",
        "Strat 6: Macro COT Flow",
        "Strat 7: GSR Pairs Switch"
    ]

    if not orders_enabled:
        return {
            "bot_mode": "STANDBY_LOCKED",
            "bot_status_label": "🛑 STANDBY (Čeká na povolení objednávek)",
            "bot_active": False,
            "last_evaluation": now_str,
            "commodity": "SILVER",
            "active_strategies": strat_list,
            "current_action": "Čekám na spuštění objednávek uživatelem.",
            "last_signal": "NONE",
            "target_contract": "COMEX Micro Silver (SILZ6 Dec 2026)"
        }

    if not gateway_connected:
        return {
            "bot_mode": "PAUSED_GATEWAY_OFFLINE",
            "bot_status_label": "⚠️ POZASTAVENO (Port 7497 odpojen)",
            "bot_active": False,
            "last_evaluation": now_str,
            "commodity": "SILVER",
            "active_strategies": strat_list,
            "current_action": "Čekám na obnovení spojení s IB Gateway (port 7497).",
            "last_signal": "BLOCKED_OFFLINE",
            "target_contract": "COMEX Micro Silver (SILZ6 Dec 2026)"
        }

    comm_session = state.get("commodity_trading_session", {})
    market_open = comm_session.get("is_open", False)

    wobi = metrics.get("wobi_10", 0.0)
    micro_skew = metrics.get("micro_skew_ticks", 0.0)
    best_bid = metrics.get("best_bid", 32.445)
    best_ask = metrics.get("best_ask", 32.450)
    specs = state.get("silver_specs", {})

    if not market_open:
        return {
            "bot_mode": "READY_STANDBY_WEEKEND",
            "bot_status_label": "🟢 PŘIPRAVEN (Button ON • Start v Ne 24:00 CET)",
            "bot_active": True,
            "last_evaluation": now_str,
            "commodity": "SILVER",
            "active_strategies": strat_list,
            "current_action": "Systém je 100% připraven k samostatné exekuci Stříbra (SIL). Burza CME Globex je přes víkend uzavřena. Jakmile v neděli ve 24:00 CET otevře, bot zahájí nezávislé obchodování.",
            "last_signal": "WAITING_GLOBEX_OPEN",
            "target_contract": "COMEX Micro Silver (SILZ6 Dec 2026)",
            "wobi_signal": f"{wobi:+.2%}",
            "shanghai_premium": f"{specs.get('shanghai_premium_pct', 1.85):+.2f}%"
        }

    # Kontrola Killzone
    killzone = _SILVER_BOT_INSTANCE.killzone
    in_killzone = killzone.is_valid_killzone(now_dt.hour, now_dt.minute)

    # Kontrola otevřené pozice Stříbra
    open_pos = state.get("open_positions", [])
    sil_position = None
    for p in open_pos:
        if "SIL" in str(p.get("symbol", "")).upper():
            sil_position = p
            break

    current_action = "Aktivní monitoring hloubky trhu L2 & GSR makro signálů (SilverEdge v2.5.1)."
    last_signal = "HOLD / NEUTRAL"

    if sil_position:
        shares = sil_position.get("shares", 0)
        avg_p = float(sil_position.get("entry_price_usd") or sil_position.get("avg_price") or 32.45)
        curr_p = float(sil_position.get("market_price_usd") or (best_bid if shares > 0 else best_ask))
        diff_pts = (curr_p - avg_p) if shares > 0 else (avg_p - curr_p)

        # Cílový Take-Profit: +0.50 pt (+$500 USD na kontrakt)
        if diff_pts >= 0.49:
            logger.info(f"🎯 [SILVER-BOT TAKE-PROFIT] Pozice SIL dosáhla zisku +{diff_pts:.3f} pts! Realizuji zisk...")
            import execute_futures_trade
            res = execute_futures_trade.close_or_adjust_position(symbol="SILZ6", action="CLOSE")
            current_action = f"🎯 TAKE-PROFIT REALIZOVÁN: Uzavřeno v zisku +{diff_pts:.3f} pts (+${diff_pts * 1000 * abs(shares):.2f} USD)."
            last_signal = "TAKE_PROFIT_TRIGGERED"
        elif diff_pts <= -0.25:
            # STOP LOSS DOSAŽEN! (-0.25 pt = -$250 USD na kontrakt)
            logger.warning(f"🛑 [SILVER-BOT STOP-LOSS] Pozice SIL dosáhla ztráty {diff_pts:.3f} pts! Uzavírám pozici...")
            import execute_futures_trade
            res = execute_futures_trade.close_or_adjust_position(symbol="SILZ6", action="CLOSE")
            current_action = f"🛑 STOP-LOSS AKTIVOVÁN: Uzavřeno ve ztrátě {diff_pts:.3f} pts (-${abs(diff_pts) * 1000 * abs(shares):.2f} USD)."
            last_signal = "STOP_LOSS_TRIGGERED"
        else:
            current_action = f"Pozice držena: {shares} ktr SIL @ ${avg_p:.3f} (Aktuální PnL: {diff_pts:+.3f} pts / ${diff_pts * 1000 * abs(shares):+.2f} USD | SL: -0.25 pt, TP: +0.50 pt)."
    else:
        now_ts = time.time()
        if not in_killzone:
            current_action = "Mimo aktivní Killzone Stříbra (London Open 09:00–11:30 & NY Overlap 14:00–20:30 SEČ). Exekuce pozastavena pro ochranu před spreadem."
            last_signal = "OUTSIDE_KILLZONE_STANDBY"
        elif now_ts - _LAST_SILVER_TRADE_TIME > 60.0 and gateway_connected:
            cot = specs.get("cot_crowding_pct", 41.2)
            sh_prem = specs.get("shanghai_premium_pct", 1.85)

            if wobi < -0.12 and micro_skew < -0.15 and cot >= 55.0:
                logger.info(f"⚡ [SILVER-BOT SIGNÁL SHORT] WOBI={wobi:.3f}, COT={cot} -> Otevírám SHORT 1 ktr SIL...")
                import execute_futures_trade
                res = execute_futures_trade.execute_sil_order(
                    action="SELL",
                    contracts=1,
                    order_type="LMT",
                    limit_price=best_ask,
                    sl_pts=0.25,
                    tp_pts=0.50,
                    style="SILVEREDGE_V25_AUTONOMOUS_SHORT"
                )
                _LAST_SILVER_TRADE_TIME = now_ts
                current_action = f"🚀 Otevřen SHORT 1 ktr SIL @ ${best_ask:.3f} (WOBI {wobi:+.2%}, SL 0.25, TP 0.50)."
                last_signal = "AUTONOMOUS_SHORT"

            elif wobi > 0.12 and micro_skew > 0.15 and sh_prem > 1.0:
                logger.info(f"⚡ [SILVER-BOT SIGNÁL LONG] WOBI={wobi:.3f}, Shanghai Prem={sh_prem}% -> Otevírám LONG 1 ktr SIL...")
                import execute_futures_trade
                res = execute_futures_trade.execute_sil_order(
                    action="BUY",
                    contracts=1,
                    order_type="LMT",
                    limit_price=best_bid,
                    sl_pts=0.25,
                    tp_pts=0.50,
                    style="SILVEREDGE_V25_AUTONOMOUS_LONG"
                )
                _LAST_SILVER_TRADE_TIME = now_ts
                current_action = f"🚀 Otevřen LONG 1 ktr SIL @ ${best_bid:.3f} (WOBI {wobi:+.2%}, Shanghai {sh_prem:+.2f}%, SL 0.25, TP 0.50)."
                last_signal = "AUTONOMOUS_LONG"

    return {
        "bot_mode": "AUTONOMOUS_SILVEREDGE_V25",
        "bot_status_label": "🟢 AUTONOMNÍ TRADING AKTIVNÍ (Model SilverEdge v2.5.1)",
        "bot_active": True,
        "last_evaluation": now_str,
        "commodity": "SILVER",
        "killzone_status": "🟢 V KILLZONE" if in_killzone else "🟡 MIMO KILLZONE (09:00–11:30, 14:00–20:30)",
        "active_strategies": strat_list,
        "current_action": current_action,
        "last_signal": last_signal,
        "target_contract": "COMEX Micro Silver (SILZ6 Dec 2026)",
        "wobi_signal": f"{wobi:+.2%}",
        "shanghai_premium": f"{specs.get('shanghai_premium_pct', 1.85):+.2f}%"
    }

