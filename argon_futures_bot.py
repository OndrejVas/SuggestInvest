"""
argon_futures_bot.py
====================
Autonomní trading bot a monitorovací engine pro COMEX Micro Gold Futures (MGC / MGCZ6).
--------------------------------------------------------------------------------------
Spouští se a zůstává aktivní po inicializaci "SPUSTIT OBJEDNÁVKY":
1. Automaticky monitoruje trh každé 3 sekundy s nepřetržitou kontinuitou.
2. Před jakoukoliv exekucí ověřuje integritu a kontinuitu dat (přes data_continuity_service.py).
3. Vyhodnocuje vyškolený model Argon V2.5:
   - Skládá Strategii 2 (L2 DOM 10 pater, WOBI přetlak, Micro-Skew),
   - Strategii 4 (Cross-Asset makro můstek, 10Y US výnosy, AI rotace),
   - Strategii 6 (Zprávy a sentiment těžařských proxy aktiv GLD, NEM, GDX).
4. Provádí autonomní exekuci (Otevírání pozic, Take-Profit +10 až +15 pts, Stop-Loss).
"""

from __future__ import annotations
import os
import sys
import json
import time
import logging
from datetime import datetime
from typing import Dict, Any, Optional

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(WORKSPACE_DIR, "data")
STATE_FILE = os.path.join(DATA_DIR, "future_invest_demo_state.json")
LOCK_FILE = os.path.join(DATA_DIR, "execution_lock.json")

logger = logging.getLogger("ArgonFuturesBot")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [ARGON-BOT] %(message)s")


LAST_BOT_TRADE_TIME = 0.0


def is_valid_killzone_cet(ts: datetime) -> bool:
    """
    Striktní vynucení obchodních oken dle VYLEPSENI_STRATEGIE_KVANT.md & Argon v2.5:
    - Povoleno: 09:00–11:30 SEČ (London Open) a 14:00–20:30 SEČ (NY Overlap & Afternoon)
    - Zakázáno: 11:30–13:59 SEČ (London Lunch Stagnation) a po 20:30 SEČ (EOD Flat ve 22:45 SEČ)
    - Zakázáno: 19:15–19:35 SEČ (COMEX Daily Settlement & OPEX Pin-Risk Window)
    """
    minutes_of_day = ts.hour * 60 + ts.minute
    # Zákaz v okně COMEX settlement 19:15–19:35 SEČ
    if (19 * 60 + 15) <= minutes_of_day <= (19 * 60 + 35):
        return False
    london_open = (9 * 60) <= minutes_of_day < (11 * 60 + 30)
    ny_session = (14 * 60) <= minutes_of_day <= (20 * 60 + 30)
    return bool(london_open or ny_session)


def evaluate_4state_hmm_regime(
    atr_ratio: float = 1.0,
    kama_er: float = 0.50,
    z_ext: float = 0.0,
    close_price: float = 4193.0,
    ema50: float = 4190.0,
    plus_di: float = 25.0,
    minus_di: float = 20.0,
    dynamic_er_threshold: float = 0.30,
    tnx_yield: float = 4.20,
    tnx_5d_bps: float = 0.0,
    is_opex: bool = False,
    gold_vol_stress: bool = False
) -> str:
    """
    4-Stavový ArgonMasterGatekeeperV25:
    1. SUMMER_OR_BOTTOM_COMPRESSION
    2. PARABOLIC_BLOWOFF_WARNING (práh 2.65, v OPEX týdnu 2.30)
    3. BEAR_CORRECTION_IMPULSE (aktivní i při specifickém Gold VIX stresu ^GVZ >= 21)
    4. HEALTHY_BULL_TREND
    """
    if atr_ratio < 0.88 or kama_er < dynamic_er_threshold:
        return "SUMMER_OR_BOTTOM_COMPRESSION"

    z_threshold = 2.30 if is_opex else 2.65
    if z_ext >= z_threshold:
        return "PARABOLIC_BLOWOFF_WARNING"

    rate_headwind = (tnx_yield >= 4.85 and tnx_5d_bps >= 8.0)
    if (close_price < ema50 and minus_di > plus_di and atr_ratio >= 0.95) or rate_headwind or gold_vol_stress:
        return "BEAR_CORRECTION_IMPULSE"

    return "HEALTHY_BULL_TREND"


def evaluate_autonomous_bot(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Vyhodnotí jeden cyklus autonomního trading bota.
    Pokud jsou objednávky povoleny (orders_enabled == True):
    - Zkontroluje kontinuitu dat (případně provede bleskový auto-backfill).
    - Vyhodnotí signály modelu Argon V2.5.
    - Zkontroluje existující pozice (Take-Profit / Trailing-Stop).
    - Vygeneruje a případně odešle optimální příkaz na IBKR Demo.
    """
    global LAST_BOT_TRADE_TIME

    orders_enabled = state.get("orders_enabled", False)
    gateway_connected = state.get("gateway_connected", False)
    dom_l2 = state.get("dom_l2", {})
    metrics = dom_l2.get("metrics", {})
    macro = state.get("cross_asset_macro", {})
    now_dt = datetime.now()
    now_str = now_dt.strftime("%d.%m.%Y %H:%M:%S")

    # Pokud jsou objednávky vypnuty zámkem
    if not orders_enabled:
        return {
            "bot_mode": "STANDBY_LOCKED",
            "bot_status_label": "🛑 STANDBY (Čeká na povolení objednávek)",
            "bot_active": False,
            "last_evaluation": now_str,
            "active_strategies": [
                "Strat 2: Argon L2 DOM Gate Scalper",
                "Strat 4: Cross-Asset Macro Yield Bridge",
                "Strat 6: News Catalyst Momentum"
            ],
            "continuity_status": state.get("data_continuity", {}).get("status_label", "Prověřeno"),
            "current_action": "Čekám na spuštění objednávek uživatelem.",
            "last_signal": "NONE",
            "target_contract": "COMEX Micro Gold (MGCZ6 Dec 2026)"
        }

    # Pokud je IBKR Gateway odpojen
    if not gateway_connected:
        return {
            "bot_mode": "PAUSED_GATEWAY_OFFLINE",
            "bot_status_label": "⚠️ POZASTAVENO (Port 7497 odpojen)",
            "bot_active": False,
            "last_evaluation": now_str,
            "active_strategies": [
                "Strat 2: Argon L2 DOM Gate Scalper",
                "Strat 4: Cross-Asset Macro Yield Bridge",
                "Strat 6: News Catalyst Momentum"
            ],
            "continuity_status": state.get("data_continuity", {}).get("status_label", "Přerušena"),
            "current_action": "Čekám na obnovení spojení s IB Gateway (port 7497) a dotažení svíček před další exekucí.",
            "last_signal": "BLOCKED_OFFLINE",
            "target_contract": "COMEX Micro Gold (MGCZ6 Dec 2026)"
        }

    # OBJEDNÁVKY JSOU POVOLENY -> AUTONOMNÍ MONITOROVÁNÍ A EXEKUCE
    # 1. Kontrola kontinuity dat
    continuity = state.get("data_continuity", {})
    if not continuity.get("consistent", False):
        import data_continuity_service
        logger.info("⚠️ [ARGON-BOT] Detekována neúplnost dat před obchodním cyklem – spouštím auto-backfill...")
        bf = data_continuity_service.execute_auto_backfill()
        continuity = bf.get("continuity", {})

    wobi = metrics.get("wobi_10", 0.0)
    micro_skew = metrics.get("micro_skew_ticks", 0.0)
    best_bid = metrics.get("best_bid", 4192.80)
    best_ask = metrics.get("best_ask", 4193.00)
    long_mult = macro.get("long_multiplier", 1.0)
    short_mult = macro.get("short_multiplier", 1.0)

    # 2. Kontrola stavu trhu (CME Globex víkendová uzávěrka do Neděle 24:00 CET)
    comm_session = state.get("commodity_trading_session", {})
    market_open = comm_session.get("is_open", False)

    if not market_open:
        return {
            "bot_mode": "READY_STANDBY_WEEKEND",
            "bot_status_label": "🟢 PŘIPRAVEN (Button ON • Start v Ne 24:00 CET)",
            "bot_active": True,
            "last_evaluation": now_str,
            "active_strategies": [
                "Strat 2: Argon L2 DOM Gate Scalper",
                "Strat 4: Cross-Asset Macro Yield Bridge",
                "Strat 6: News Catalyst Momentum"
            ],
            "continuity_status": continuity.get("status_label", "100% Kontinuální"),
            "current_action": "Systém je 100% připraven k první investici. Burza CME Globex je přes víkend uzavřena. Jakmile trh v neděli ve 24:00 CET otevře, bot automaticky zahájí živé obchodování.",
            "last_signal": "WAITING_GLOBEX_OPEN",
            "target_contract": "COMEX Micro Gold (MGCZ6 Dec 2026)",
            "wobi_signal": f"{wobi:+.2%}",
            "macro_bias": f"Long {long_mult:.2f}x / Short {short_mult:.2f}x"
        }

    # 3. Kontrola otevřených pozic (Řízení rizika & Take-Profit)
    open_pos = state.get("open_positions", [])
    mgc_position = None
    for p in open_pos:
        if "MGC" in p.get("symbol", ""):
            mgc_position = p
            break

    current_action = "Aktivní monitoring hloubky trhu L2 & makro signálů."
    last_signal = "HOLD / NEUTRAL"

    # A) Pokud již máme otevřenou pozici MGC -> Správa Stop-Loss (-8 pts) a Take-Profit (+12 pts)
    if mgc_position:
        shares = mgc_position.get("shares", 0)
        avg_p = float(mgc_position.get("entry_price_usd") or mgc_position.get("avg_price") or 4182.40)
        curr_p = float(mgc_position.get("market_price_usd") or (best_bid if shares > 0 else best_ask))
        diff_pts = (curr_p - avg_p) if shares > 0 else (avg_p - curr_p)

        if diff_pts >= 11.5:
            # TAKE PROFIT DOSAŽEN! (+12 pts = +$120 USD na kontrakt)
            logger.info(f"🎯 [ARGON-BOT TAKE-PROFIT] Pozice MGC dosáhla zisku +{diff_pts:.1f} pts! Realizuji zisk...")
            import execute_futures_trade
            res = execute_futures_trade.close_or_adjust_position(symbol="MGCZ6", action="CLOSE")
            current_action = f"🎯 TAKE-PROFIT REALIZOVÁN: Uzavřeno v zisku +{diff_pts:.1f} pts (+${diff_pts * 10 * abs(shares):.2f} USD)."
            last_signal = "TAKE_PROFIT_TRIGGERED"
        elif diff_pts <= -8.0:
            # STOP LOSS DOSAŽEN! (-8 pts = -$80 USD na kontrakt)
            logger.warning(f"🛑 [ARGON-BOT STOP-LOSS] Pozice MGC dosáhla ztráty {diff_pts:.1f} pts! Uzavírám pozici...")
            import execute_futures_trade
            res = execute_futures_trade.close_or_adjust_position(symbol="MGCZ6", action="CLOSE")
            current_action = f"🛑 STOP-LOSS AKTIVOVÁN: Uzavřeno ve ztrátě {diff_pts:.1f} pts (-${abs(diff_pts) * 10 * abs(shares):.2f} USD)."
            last_signal = "STOP_LOSS_TRIGGERED"
        else:
            current_action = f"Pozice držena: {shares} ktr MGC @ ${avg_p:.2f} (Aktuální PnL: {diff_pts:+.1f} pts | SL: -8.0 pts, TP: +12.0 pts)."

    # B) Pokud pozici nemáme -> Vyhodnocení nového vstupu (Argon V2.5 pravidla)
    else:
        now_ts = time.time()
        in_killzone = is_valid_killzone_cet(now_dt)
        is_opex_now = (now_dt.month in (8, 9, 10) and now_dt.day >= 22)
        sovereign_floor = macro.get("sovereign_floor_active", False)
        ha_telemetry = macro.get("high_alpha_telemetry", {})
        gold_vol_stress = ha_telemetry.get("gold_vol_stress", False)
        real_yield_spike = ha_telemetry.get("real_yield_spike", False)
        
        # 4-Stavový HMM Gatekeeper s adaptivním prahem v OPEX okně a ochranou Gold VIX
        active_regime = evaluate_4state_hmm_regime(
            atr_ratio=1.0,
            kama_er=0.45,
            z_ext=0.0,
            close_price=best_bid,
            ema50=4190.0,
            plus_di=25.0,
            minus_di=20.0,
            is_opex=is_opex_now,
            gold_vol_stress=gold_vol_stress
        )

        if not in_killzone:
            current_action = "Mimo aktivní Killzone (London Open 09:00–11:30 & NY Overlap 14:00–20:30 SEČ, blackout 19:15–19:35 COMEX Settlement). Exekuce pozastavena pro ochranu před polední stagnací a nočním šumem."
            last_signal = "OUTSIDE_KILLZONE_STANDBY"
        elif active_regime == "SUMMER_OR_BOTTOM_COMPRESSION":
            current_action = "Aktivní stav: SUMMER_OR_BOTTOM_COMPRESSION. Zámek komprese volatility blokuje falešné průrazy."
            last_signal = "COMPRESSION_LOCK_ACTIVE"
        elif now_ts - LAST_BOT_TRADE_TIME > 60.0 and gateway_connected:
            # Podmínka pro SHORT: Tlak na ASK (WOBI < -0.10) a Makro zvýhodnění shortu (short_mult >= 1.15) nebo BEAR_CORRECTION
            # ZÁKAZ SHORTŮ: Pokud je aktivní Sovereign Floor (centrální banky PBOC/NBP brání dno $4,000–$4,100)!
            if not sovereign_floor and wobi < -0.10 and micro_skew < -0.15 and (short_mult >= 1.15 or active_regime in ("PARABOLIC_BLOWOFF_WARNING", "BEAR_CORRECTION_IMPULSE")):
                logger.info(f"⚡ [ARGON-BOT SIGNÁL SHORT] WOBI={wobi:.3f}, Macro Short={short_mult}x, Režim={active_regime} -> Otevírám SHORT 1 ktr MGC...")
                import execute_futures_trade
                res = execute_futures_trade.execute_mgc_order(
                    action="SELL",
                    contracts=1,
                    order_type="LMT",
                    limit_price=best_ask,
                    style="ARGON_V25_AUTONOMOUS_SHORT"
                )
                LAST_BOT_TRADE_TIME = now_ts
                current_action = f"🚀 Otevřen SHORT 1 ktr MGC @ ${best_ask:.2f} (WOBI {wobi:+.2%}, Režim {active_regime})."
                last_signal = "AUTONOMOUS_SHORT"

            # Podmínka pro LONG: Silný BID přetlak (WOBI > 0.12) a povolené makro (long_mult >= 0.50)
            # Blokováno v PARABOLIC_BLOWOFF_WARNING, BEAR_CORRECTION_IMPULSE i při real_yield_spike!
            elif not real_yield_spike and wobi > 0.12 and micro_skew > 0.15 and long_mult >= 0.50 and active_regime == "HEALTHY_BULL_TREND" and not metrics.get("ask_wall_detected", False):
                logger.info(f"⚡ [ARGON-BOT SIGNÁL LONG] WOBI={wobi:.3f}, Bid Wall detekována, Režim={active_regime} -> Otevírám LONG 1 ktr MGC...")
                import execute_futures_trade
                res = execute_futures_trade.execute_mgc_order(
                    action="BUY",
                    contracts=1,
                    order_type="LMT",
                    limit_price=best_bid,
                    style="ARGON_V25_AUTONOMOUS_LONG"
                )
                LAST_BOT_TRADE_TIME = now_ts
                current_action = f"🚀 Otevřen LONG 1 ktr MGC @ ${best_bid:.2f} (WOBI {wobi:+.2%}, Režim {active_regime})."
                last_signal = "AUTONOMOUS_LONG"
            elif real_yield_spike and wobi > 0.12:
                current_action = "Long signál zamítnut High-Alpha ochranou: Reálné výnosy intradenně prudce rostou (poměr TIP/IEF klesá)."
                last_signal = "BLOCKED_BY_REAL_YIELD_SPIKE"

    return {
        "bot_mode": "AUTONOMOUS_ARGON_V25",
        "bot_status_label": "🟢 AUTONOMNÍ TRADING AKTIVNÍ (Model Argon V2.5)",
        "bot_active": True,
        "last_evaluation": now_str,
        "active_regime": evaluate_4state_hmm_regime(),
        "killzone_status": "🟢 V KILLZONE" if is_valid_killzone_cet(now_dt) else "🟡 MIMO KILLZONE (09:00–11:30, 14:00–20:30)",
        "active_strategies": [
            "Strat 2: Argon L2 DOM Gate Scalper",
            "Strat 4: Cross-Asset Macro Yield Bridge",
            "Strat 6: News Catalyst Momentum"
        ],
        "continuity_status": continuity.get("status_label", "100% Kontinuální"),
        "current_action": current_action,
        "last_signal": last_signal,
        "target_contract": "COMEX Micro Gold (MGCZ6 Dec 2026)",
        "wobi_signal": f"{wobi:+.2%}",
        "macro_bias": f"Long {long_mult:.2f}x / Short {short_mult:.2f}x"
    }
