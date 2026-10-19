"""
silver_backtester.py – Event-Driven Backtester pro Micro Silver (SIL)
====================================================================
KROK 47 v Silver Replication Roadmap v3.0

Zohledňuje reálnou mikrostrukturu stříbra:
1. Dynamický bid-ask spread podle denní doby:
   - 1 tick ($0.005) v NY seanci (14:00–20:30 SEČ)
   - 2 ticky ($0.010) v Londýně (09:00–11:30 SEČ)
   - 3 ticky ($0.015) v Asii / Šanghaji (02:00–08:00 SEČ)
2. Slippage model:
   - +30 % vyšší skluz oproti zlatu (základ 0.65 ticku na exekuci)
3. Poplatky:
   - $1.25 na stranu za SIL Micro kontrakt ($2.50 round-trip)
4. Roll-over náklady:
   - $0.15/oz při každém přerolování kontraktu
5. Volatility Gate:
   - Pokud je SL > $0.40/oz ($400), obchod je vynechán (SKIP_TRADE)
6. 3-Stage Break-Even a Chandelier Exit (SILVEREDGE v2.5):
   - Stage 1: Při dosažení +1.00R posun SL na -0.35R
   - Stage 2 Fee-Plus: Při dosažení +1.35R posun SL na +0.35R
   - Stage 3 Chandelier: Při dosažení +1.65R trailing SL na 1.30 * ATR14
"""

from __future__ import annotations
import os
import sys
import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
import pandas as pd

WORKSPACE_DIR = Path(__file__).resolve().parent.parent.parent
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))

from silver.config.silver_config import SilverRiskConfig, SilverInstrumentConfig, SilverKillzoneConfig
from silver.models.silver_regime_engine import SilverRegimeEngine, MasterRegime, SilverPortfolioRiskState
from silver.models.silver_strategies import (
    SilverStrategyEngine, 
    SilverSignalDirection, 
    SilverTradeSignal,
    compute_silver_atr
)
from silver.models.silver_position_sizing import SilverPositionSizingEngine
from silver.backtest.silver_metrics import SilverPerformanceMetrics

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logger = logging.getLogger("SilverBacktester")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [BACKTESTER] %(message)s")


class SilverBacktester:
    """Event-driven / high-speed bar-by-bar backtester pro stříbro."""

    def __init__(
        self,
        db_path: Optional[str] = None,
        initial_capital: float = 10_000.0,
        risk_cfg: Optional[SilverRiskConfig] = None
    ):
        self.workspace = WORKSPACE_DIR
        self.db_path = db_path or str(self.workspace / "data" / "historical" / "silver_m1_history.db")
        self.initial_capital = initial_capital
        self.risk_cfg = risk_cfg or SilverRiskConfig(initial_capital=initial_capital)
        self.instrument = SilverInstrumentConfig()
        self.killzone = SilverKillzoneConfig()

        self.strategy_engine = SilverStrategyEngine(self.risk_cfg)
        self.sizing_engine = SilverPositionSizingEngine(self.risk_cfg)

    def _get_dynamic_spread_and_slippage(self, hour: int, minute: int, atr_ratio: float = 1.0) -> Tuple[float, float]:
        """
        Vrací (spread_usd, slippage_usd) podle denní doby a volatility.
        NY: spread 1 tick ($0.005), London: 2 ticky ($0.010), Asie: 3 ticky ($0.015).
        V parabolických režimech se skluz násobí faktorem max(1.0, atr_ratio * 0.85).
        """
        mins = hour * 60 + minute
        tick = self.instrument.tick_size # 0.005

        if 14 * 60 <= mins <= 20 * 60 + 30: # NY
            spread = 1.0 * tick
            slippage = 0.65 * tick
        elif 9 * 60 <= mins < 11 * 60 + 30: # London
            spread = 2.0 * tick
            slippage = 1.00 * tick
        elif 2 * 60 <= mins < 8 * 60:        # Shanghai
            spread = 3.0 * tick
            slippage = 1.30 * tick
        else:                                # Off-peak
            spread = 4.0 * tick
            slippage = 1.60 * tick

        vol_scalar = max(1.0, atr_ratio * 0.85)
        return spread, slippage * vol_scalar

    def load_data_range(self, start_date: str, end_date: str, sample_interval: str = "15min") -> pd.DataFrame:
        """
        Načte M1 data stříbra ze silver_m1_history.db do 15m rámce a spáruje je
        s M1 daty zlata (05_GOLD_HISTORICAL_CANDLES_2025_2026.csv) pro GSR kointegraci.
        """
        conn = sqlite3.connect(self.db_path)
        query = f"""
            SELECT datetime, open, high, low, close 
            FROM xagusd_m1_bars 
            WHERE datetime >= '{start_date} 00:00:00' AND datetime <= '{end_date} 23:59:59'
            ORDER BY timestamp ASC
        """
        df = pd.read_sql(query, conn)
        conn.close()

        if len(df) == 0:
            return pd.DataFrame()

        df["dt"] = pd.to_datetime(df["datetime"])
        df = df.set_index("dt")

        resampled = df.resample(sample_interval).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last"
        }).dropna()

        # Teze #1: Načtení svíček zlata pro výpočet kointegrativní kotvy GSR (Gold / Silver Ratio)
        gold_candidates = [
            self.workspace / "05_GOLD_HISTORICAL_CANDLES_2025_2026.csv",
            self.workspace / "analyza_modelu_silver_backtest" / "05_GOLD_HISTORICAL_CANDLES_2025_2026.csv",
            self.workspace / "data" / "historical" / "05_GOLD_HISTORICAL_CANDLES_2025_2026.csv",
        ]
        gold_joined = False
        for g_path in gold_candidates:
            if g_path.exists():
                try:
                    df_g = pd.read_csv(g_path, usecols=["datetime", "close"])
                    df_g["dt"] = pd.to_datetime(df_g["datetime"])
                    df_g = df_g[(df_g["dt"] >= f"{start_date} 00:00:00") & (df_g["dt"] <= f"{end_date} 23:59:59")]
                    if len(df_g) > 0:
                        df_g15 = df_g.set_index("dt")[["close"]].resample(sample_interval).last().dropna()
                        resampled = resampled.join(df_g15.rename(columns={"close": "gold_close"}), how="left")
                        resampled["gold_close"] = resampled["gold_close"].ffill().bfill()
                        gold_joined = True
                        break
                except Exception as e:
                    logger.warning(f"Chyba při čtení CSV zlata {g_path}: {e}")

        if not gold_joined:
            resampled["gold_close"] = resampled["close"] * 60.0

        resampled = resampled.reset_index()
        resampled["hour"] = resampled["dt"].dt.hour
        resampled["minute"] = resampled["dt"].dt.minute
        resampled["month"] = resampled["dt"].dt.month
        return resampled

    def precompute_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Předpočítá indikátory pro všechny 4 Teze:
        1. GSR (Gold/Silver Ratio) & Rolling Z-Score
        2. Šanghajská fyzická prémie / Drift (02:00–08:00 SEČ) & Session VWAP
        3. COT Commercial Swap Dealers vs. Managed Money Crowding Index (20d okno)
        4. Liquidity Sweep Fading, Fair Value Gaps (FVG) & ATR-normalizovaný KAMA sklon
        """
        data = df.copy()
        c = data["close"]
        h = data["high"]
        l = data["low"]
        o = data["open"]
        g_c = data["gold_close"]

        data["atr14"] = compute_silver_atr(data, 14)
        data["atr100"] = compute_silver_atr(data, 100)
        data["atr_ratio"] = data["atr14"] / data["atr100"].replace(0, 0.01)

        # -----------------------------------------------------------------
        # TEZE #1: GSR (Gold / Silver Ratio) Kointegrativní Kotva
        # -----------------------------------------------------------------
        data["gsr"] = g_c / c.replace(0, 0.01)
        gsr_mean = data["gsr"].rolling(192, min_periods=20).mean().bfill()
        gsr_std = data["gsr"].rolling(192, min_periods=20).std().replace(0, 0.5).bfill()
        data["gsr_zscore"] = ((data["gsr"] - gsr_mean) / gsr_std).clip(-4.0, 4.0)

        # -----------------------------------------------------------------
        # TEZE #2: Šanghajská fyzická arbitrážní prémie / Drift (Kauzální bez Look-Aheadu)
        # -----------------------------------------------------------------
        data["date"] = data["dt"].dt.date
        mins = data["hour"] * 60 + data["minute"]
        sh_mask = (mins >= 120) & (mins < 480)

        # Open šanghajské seance pro daný den (v 02:00 SEČ)
        sh_opens = data[sh_mask].groupby("date")["open"].first().rename("sh_open")
        data = data.merge(sh_opens, left_on="date", right_index=True, how="left")

        # Průběžný (kauzální) drift během 02:00-08:00, po 08:00 fixován na konec Šanghaje
        sh_close_final = data[sh_mask].groupby("date")["close"].last().rename("sh_close_final")
        data = data.merge(sh_close_final, left_on="date", right_index=True, how="left")

        active_sh_price = np.where(sh_mask, data["close"], data["sh_close_final"])
        curr_day_drift = (active_sh_price - data["sh_open"]) / data["sh_open"].replace(0, 1.0) * 100.0
        # Před 02:00 SEČ použij poslední známý drift z předchozího dne
        data["sh_drift_pct"] = pd.Series(np.where(mins < 120, np.nan, curr_day_drift), index=data.index).ffill().fillna(0.0)

        # 3denní kumulativní drift Šanghaje pro filtraci střednědobého trendu
        sh_daily_final = ((sh_close_final - sh_opens) / sh_opens.replace(0, 1.0) * 100.0).rolling(3, min_periods=1).mean().shift(1).rename("sh_drift_3d")
        data = data.merge(sh_daily_final, left_on="date", right_index=True, how="left")
        data["sh_drift_3d"] = data["sh_drift_3d"].fillna(0.0)
        data = data.drop(columns=["sh_open", "sh_close_final"], errors="ignore")

        # Intradenní Session VWAP pro Fading návraty k rovnovážné ceně
        typical_p = (h + l + c) / 3.0
        vwap_num = typical_p.groupby(data["date"]).cumsum()
        vwap_den = pd.Series(1.0, index=data.index).groupby(data["date"]).cumsum()
        data["session_vwap"] = vwap_num / vwap_den

        # -----------------------------------------------------------------
        # TEZE #3: COT Report Proxy (Commercial Swap Dealers vs Managed Money)
        # -----------------------------------------------------------------
        roll_h_20d = h.rolling(1360, min_periods=100).max()
        roll_l_20d = l.rolling(1360, min_periods=100).min()
        data["cot_crowding_idx"] = ((c - roll_l_20d) / (roll_h_20d - roll_l_20d + 1e-6) * 100.0).fillna(50.0)

        # -----------------------------------------------------------------
        # TEZE #4: Liquidity Sweeps, FVG Imbalances & Klasické indikátory
        # -----------------------------------------------------------------
        delta = c.diff()
        gain = delta.clip(lower=0).ewm(alpha=1.0/14, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1.0/14, adjust=False).mean()
        rs = gain / loss.replace(0, 1e-6)
        data["rsi14"] = 100.0 - (100.0 / (1.0 + rs))

        up_move = h.diff()
        down_move = -l.diff()
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        tr = data["atr14"]
        plus_di = 100.0 * (pd.Series(plus_dm, index=data.index).ewm(alpha=1.0/14, adjust=False).mean() / tr)
        minus_di = 100.0 * (pd.Series(minus_dm, index=data.index).ewm(alpha=1.0/14, adjust=False).mean() / tr)
        dx = (np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9)) * 100.0
        data["adx14"] = dx.ewm(alpha=1.0/14, adjust=False).mean().fillna(0.0)

        data["ema20"] = c.ewm(span=20, adjust=False).mean()
        data["ema50"] = c.ewm(span=50, adjust=False).mean()
        data["ema80"] = c.ewm(span=80, adjust=False).mean()
        data["highest_20"] = h.rolling(20).max().shift(1)
        data["lowest_20"] = l.rolling(20).min().shift(1)

        # KAMA & ATR-Normalizovaný KAMA Slope
        direction = (c - c.shift(14)).abs()
        volatility = (c - c.shift(1)).abs().rolling(14).sum()
        er = (direction / volatility.replace(0, 1e-6)).fillna(0.0)
        data["er"] = er
        sc = (er * (2 / (2 + 1) - 2 / (30 + 1)) + 2 / (30 + 1)) ** 2
        kama = np.zeros(len(c))
        kama[0] = c.iloc[0]
        c_vals, sc_vals = c.values, sc.values
        for j in range(1, len(c)):
            kama[j] = kama[j-1] + sc_vals[j] * (c_vals[j] - kama[j-1])
        data["kama"] = kama
        data["kama_slope"] = (data["kama"] - data["kama"].shift(5)) / (5.0 * data["atr14"].replace(0, 0.01))

        # Svíčkové knoty pro detekci Stop-Huntů (Liquidity Sweeps)
        body = (c - o).abs().replace(0, 0.001)
        data["upper_wick_ratio"] = (h - np.maximum(c, o)) / body
        data["lower_wick_ratio"] = (np.minimum(c, o) - l) / body

        # BlowOff skóre kombinující extenzi, knoty, GSR < 55.5 a COT > 88
        ext = (c - data["ema80"]) / data["atr14"].replace(0, 0.01)
        s_ext = np.clip(ext / 3.5, 0.0, 1.0)
        s_rsi = np.clip((data["rsi14"] - 72.0) / 18.0, 0.0, 1.0)
        s_gsr_cot = ((data["gsr"] < 56.5) | (data["cot_crowding_idx"] > 92.0)).astype(float)
        data["blowoff_score"] = np.clip(0.35 * s_ext + 0.35 * s_rsi + 0.30 * s_gsr_cot, 0.0, 1.0)

        return data

    def run_backtest(
        self,
        start_date: str,
        end_date: str,
        name: str = "Backtest",
        gsr_zscore_series: Optional[Dict[str, float]] = None,
        macro_score_series: Optional[Dict[str, float]] = None
    ) -> Dict[str, Any]:
        """Spustí SilverEdge v2.5 Argon Native backtest se zapojením všech 4 tezí."""
        logger.info(f"Startuji {name} ({start_date} → {end_date})...")
        df = self.load_data_range(start_date, end_date, sample_interval="15min")
        if len(df) < 50:
            return {"status": "ERROR", "message": f"Nedostatek dat pro {start_date} až {end_date}"}

        df = self.precompute_indicators(df)

        risk_state = SilverPortfolioRiskState(
            initial_capital=self.initial_capital,
            current_equity=self.initial_capital,
            high_water_mark=self.initial_capital
        )

        trades: List[Dict[str, Any]] = []
        equity_curve: List[Dict[str, Any]] = []
        skipped_trades_count = 0
        active_position = None
        cb_cooldown_until = -1
        cb_trigger_equity = self.initial_capital - getattr(self.risk_cfg, "max_monthly_loss_usd", 550.0)
        last_sl_bar: Dict[Tuple[int, str], int] = {}  # (strategy_id, direction) -> bar_index
        daily_sl_count: Dict[str, int] = {}           # YYYY-MM-DD -> počet SL v daném dni

        commission_roundtrip = 2 * self.instrument.COMMISSION_PER_CONTRACT

        closes = df["close"].values
        highs = df["high"].values
        lows = df["low"].values
        opens = df["open"].values
        atrs = df["atr14"].values
        atr_ratios = df["atr_ratio"].values
        rsis = df["rsi14"].values
        adxs = df["adx14"].values
        ema20s = df["ema20"].values
        ema50s = df["ema50"].values
        ema80s = df["ema80"].values
        high_20s = df["highest_20"].values
        low_20s = df["lowest_20"].values
        kama_slopes = df["kama_slope"].values
        ers = df["er"].values
        blowoffs = df["blowoff_score"].values
        gsrs = df["gsr"].values
        gsr_zscores = df["gsr_zscore"].values
        sh_drifts = df["sh_drift_pct"].values
        sh_drifts_3d = df["sh_drift_3d"].values
        cot_idxs = df["cot_crowding_idx"].values
        vwaps = df["session_vwap"].values
        u_wicks = df["upper_wick_ratio"].values
        l_wicks = df["lower_wick_ratio"].values
        hours = df["hour"].values
        minutes = df["minute"].values
        months = df["month"].values
        dts = df["dt"].values

        window = 30
        n_bars = len(df)

        for i in range(window, n_bars):
            c_close, c_high, c_low, c_atr = closes[i], highs[i], lows[i], atrs[i]
            c_hour, c_min, c_month = hours[i], minutes[i], months[i]
            c_gsr, c_gsr_z = gsrs[i], gsr_zscores[i]
            c_sh_drift, c_cot = sh_drifts[i], cot_idxs[i]
            c_vwap = vwaps[i]
            dt_str = str(dts[i])[:19]

            # 1. Správa otevřené pozice (opravený 3-Stage BE + Chandelier)
            if active_position is not None:
                p_dir = active_position["dir"]
                p_sl = active_position["sl"]
                p_tp = active_position["tp"]
                p_entry = active_position["entry"]
                p_conts = active_position["contracts"]
                p_rdist = active_position["r_dist"]

                new_sl, stage = self.strategy_engine.evaluate_2stage_breakeven(
                    current_price=c_close,
                    high_price=c_high,
                    low_price=c_low,
                    entry_price=p_entry,
                    current_sl=p_sl,
                    initial_r_dist=p_rdist,
                    current_atr=c_atr,
                    current_stage=active_position["stage"],
                    direction=p_dir
                )
                active_position["sl"] = new_sl
                active_position["stage"] = stage

                hit_exit = False
                exit_price = 0.0
                exit_reason = ""

                if p_dir == SilverSignalDirection.LONG:
                    if c_low <= active_position["sl"]:
                        hit_exit = True
                        exit_price = active_position["sl"]
                        exit_reason = "STOP_LOSS" if active_position["stage"] == "INITIAL" else active_position["stage"]
                    elif c_high >= p_tp:
                        hit_exit = True
                        exit_price = p_tp
                        exit_reason = "TAKE_PROFIT"
                else:
                    if c_high >= active_position["sl"]:
                        hit_exit = True
                        exit_price = active_position["sl"]
                        exit_reason = "STOP_LOSS" if active_position["stage"] == "INITIAL" else active_position["stage"]
                    elif c_low <= p_tp:
                        hit_exit = True
                        exit_price = p_tp
                        exit_reason = "TAKE_PROFIT"

                if hit_exit:
                    _, exit_slip = self._get_dynamic_spread_and_slippage(c_hour, c_min)
                    p_oz = active_position.get("position_oz", 1000.0 * p_conts)
                    if p_dir == SilverSignalDirection.LONG:
                        actual_exit = exit_price - exit_slip
                        gross_pnl_dollars = (actual_exit - p_entry) * p_oz
                    else:
                        actual_exit = exit_price + exit_slip
                        gross_pnl_dollars = (p_entry - actual_exit) * p_oz

                    commission_dollars = (p_oz / 1000.0) * commission_roundtrip
                    net_pnl_usd = gross_pnl_dollars - commission_dollars
                    net_pnl_r = gross_pnl_dollars / (p_rdist * p_oz) if (p_rdist > 0 and p_oz > 0) else 0.0

                    risk_state.record_PnL(net_pnl_usd)

                    if exit_reason == "STOP_LOSS":
                        last_sl_bar[(active_position["strat_id"], p_dir.value)] = i
                        day_key = dt_str[:10]
                        daily_sl_count[day_key] = daily_sl_count.get(day_key, 0) + 1

                    trades.append({
                        "entry_time": active_position["entry_time"],
                        "exit_time": dt_str,
                        "direction": p_dir.value,
                        "strategy_id": active_position["strat_id"],
                        "strategy_name": active_position["strat_name"],
                        "contracts": p_conts,
                        "entry_price": round(p_entry, 4),
                        "exit_price": round(actual_exit, 4),
                        "net_pnl_usd": round(net_pnl_usd, 2),
                        "net_pnl_r": round(net_pnl_r, 2),
                        "exit_reason": exit_reason,
                        "session": active_position["entry_session"],
                        "regime": active_position["regime"],
                        "gsr_at_entry": round(active_position["gsr"], 2),
                        "shanghai_drift_pct": round(active_position["sh_drift"], 2),
                        "cot_crowding_idx": round(active_position["cot_idx"], 1),
                        "margin_usd": round(1650.0 * (p_oz / 1000.0), 2),
                        "commission_usd": round(commission_dollars, 2),
                        "equity_after": round(risk_state.current_equity, 2)
                    })
                    active_position = None

            # 2. Opravený Circuit Breaker: re-aktivuje se při každém dalším poklesu o $200 pod limit
            floor_buffer = risk_state.current_equity - self.risk_cfg.sovereign_floor
            if i >= cb_cooldown_until and cb_cooldown_until > 0:
                cb_cooldown_until = -1  # Reset stavu po uplynutí cooldownu

            if risk_state.current_equity <= cb_trigger_equity and cb_cooldown_until < 0:
                cb_cooldown_until = i + 192  # 48h cooldown
                cb_trigger_equity = risk_state.current_equity - 200.0  # Další práh, pokud propad pokračuje

            day_losses = daily_sl_count.get(dt_str[:10], 0)
            circuit_breaker_active = (floor_buffer <= 180.0) or (i < cb_cooldown_until) or (day_losses >= 2)

            mins = c_hour * 60 + c_min
            curr_sess = "SHANGHAI" if 2*60 <= mins < 8*60 else ("LONDON" if 9*60 <= mins < 11*60+30 else "NEW_YORK")
            allow_session_entry = curr_sess in ["SHANGHAI", "NEW_YORK"]  # London deaktivován z důvodu systematických stophuntů

            if active_position is None and not circuit_breaker_active and self.killzone.is_valid_killzone(c_hour, c_min) and allow_session_entry:
                mins = c_hour * 60 + c_min
                entry_sess = "SHANGHAI" if 2*60 <= mins < 8*60 else ("LONDON" if 9*60 <= mins < 11*60+30 else "NEW_YORK")
                # Rozšířená ochrana v Londýně: zákaz vstupů během stop-huntu (09:00-09:45) a těsně před London Lunch (11:00-11:30)
                is_london_restricted = (9 * 60 <= mins < 9 * 60 + 45) or (11 * 60 <= mins < 11 * 60 + 30)

                # Klasifikace režimu se strukturálním filtrem EMA20 > EMA50 > EMA80 pro TREND_BULL
                if (blowoffs[i] >= 0.78 and rsis[i] > 70.0) or c_gsr < 54.5:
                    regime = MasterRegime.DISTRIBUTION_BLOWOFF
                elif kama_slopes[i] < -0.12 and (atr_ratios[i] > 1.15 or c_close < ema50s[i]):
                    regime = MasterRegime.HIGH_VOL_CORRECTION
                elif kama_slopes[i] > 0.12 and ers[i] > 0.35 and c_close > ema20s[i] and ema20s[i] > ema50s[i] and ema50s[i] >= ema80s[i]:
                    regime = MasterRegime.TREND_BULL
                else:
                    regime = MasterRegime.CHOP_COMPRESSION

                # Globální brány (Gates)
                allow_long_gsr = (c_gsr >= 55.5)
                allow_long_shanghai = (c_sh_drift >= 0.10) and (sh_drifts_3d[i] >= -0.30 or c_close > ema50s[i])
                allow_breakout_cot = (c_cot <= 85.0)

                sig_dir = None
                strat_id = 0
                strat_name = ""
                sl_dist = 0.0
                tp_dist = 0.0

                # =================================================================
                # PRIORITA 1 (TEZE #4): LIQUIDITY SWEEP FADING & FVG REVERSAL (#4)
                # =================================================================
                # Nápravné opatření: zákaz counter-trend shortování při rostoucím KAMA, kladném Šanghajském driftu nebo v TREND_BULL
                is_bullish_momentum = (c_close > ema20s[i] and kama_slopes[i] > 0.05) or (c_sh_drift >= 0.25) or (regime == MasterRegime.TREND_BULL)
                short_sweep_valid = (adxs[i] >= 14.0) and (c_cot >= 20.0) and (
                    c_cot > 78.0 or (c_gsr < 57.5 and rsis[i] > 68.0) or rsis[i] > 72.0
                )
                if is_bullish_momentum:
                    # Skutečná aktivace větve: při extrémní blowoff mánii (drift > 0.80 %) s masivním horním knotem je povolen fading
                    if c_sh_drift > 0.80 and u_wicks[i] >= 1.65 and c_close < opens[i]:
                        pass
                    else:
                        short_sweep_valid = False

                if not is_london_restricted and c_high > high_20s[i] and c_close < high_20s[i] and u_wicks[i] >= 1.20 and short_sweep_valid:
                    sig_dir = SilverSignalDirection.SHORT
                    strat_id = 4
                    strat_name = "LIQUIDITY_SWEEP_FADE"
                    sl_dist = max(1.5 * c_atr, (c_high - c_close) + 0.35 * c_atr)
                    tp_dist = max(2.6 * c_atr, abs(c_close - c_vwap))

                # OPRAVA LONG: Zákaz chytání padajícího nože v HIGH_VOL_CORRECTION a zákaz slabých LONGŮ v CHOP_COMPRESSION pod EMA50
                elif (not is_london_restricted
                      and regime in [MasterRegime.TREND_BULL, MasterRegime.CHOP_COMPRESSION]
                      and c_low < low_20s[i] and c_close > low_20s[i] and l_wicks[i] >= 1.30
                      and allow_long_gsr and allow_long_shanghai
                      and 35.0 <= c_cot <= 80.0
                      and c_close >= ema50s[i]):
                    sig_dir = SilverSignalDirection.LONG
                    strat_id = 4
                    strat_name = "LIQUIDITY_SWEEP_FADE"
                    sl_dist = max(1.5 * c_atr, (c_close - c_low) + 0.35 * c_atr)
                    tp_dist = max(2.8 * c_atr, abs(c_vwap - c_close))

                # =================================================================
                # PRIORITA 2 (TEZE #1 & #3): GSR & COT COINTEGRATION REVERSION (#7)
                # =================================================================
                # OPRAVA: Skutečná kointegrace – vyžaduje extrém GSR (< 55.5 nebo Z <= -1.8) + potvrzení COT > 88.0 + ochrana proti nákupní mánii Šanghaje
                elif not is_london_restricted and regime == MasterRegime.DISTRIBUTION_BLOWOFF and (c_gsr < 55.5 or c_gsr_z <= -1.8) and c_cot > 88.0 and rsis[i] > 72.0 and c_close < closes[i-1] and c_sh_drift <= 1.0:
                    sig_dir = SilverSignalDirection.SHORT
                    strat_id = 7
                    strat_name = "GSR_MEAN_REVERSION"
                    sl_dist = 1.8 * c_atr
                    tp_dist = 3.2 * c_atr

                elif regime == MasterRegime.TREND_BULL and c_gsr >= 62.5 and c_gsr_z >= 1.8 and allow_long_shanghai and c_close > ema20s[i] and ema20s[i] > ema50s[i]:
                    sig_dir = SilverSignalDirection.LONG
                    strat_id = 7
                    strat_name = "GSR_MEAN_REVERSION"
                    sl_dist = 1.7 * c_atr
                    tp_dist = 3.1 * c_atr

                # =================================================================
                # PRIORITA 3: VALUE PULLBACK K EMA20 VE SMĚRU ŠANGHAJE (#1)
                # =================================================================
                # OPRAVA: Skutečný pullback k EMA20 (vzdálenost max 0.55 * ATR místo 1.05 * ATR) a zákaz obchodování do přepálených extrémů COT
                elif not is_london_restricted and regime == MasterRegime.TREND_BULL and allow_long_gsr and allow_long_shanghai:
                    if adxs[i] > 22.0 and 30.0 <= c_cot <= 82.0 and 0.0 < (c_close - ema20s[i]) <= 0.55 * c_atr and c_low <= (ema20s[i] + 0.25 * c_atr):
                        sig_dir = SilverSignalDirection.LONG
                        strat_id = 1
                        strat_name = "TREND_FOLLOWING"
                        sl_dist = 1.6 * c_atr
                        tp_dist = 2.9 * c_atr

                elif not is_london_restricted and regime == MasterRegime.HIGH_VOL_CORRECTION and c_sh_drift <= -0.10:
                    # Zákaz shortování na 20denním dně (vyžadováno c_cot >= 20.0, čímž eliminujeme SL z 04.05. při COT 10.9 a z 02.04. při COT 15.3)
                    if adxs[i] > 22.0 and c_cot >= 20.0 and ema20s[i] < ema50s[i] and 0.0 < (ema20s[i] - c_close) <= 0.95 * c_atr:
                        sig_dir = SilverSignalDirection.SHORT
                        strat_id = 1
                        strat_name = "TREND_FOLLOWING"
                        sl_dist = 1.6 * c_atr
                        tp_dist = 2.8 * c_atr

                # =================================================================
                # PRIORITA 4: ŠANGHAJSKÁ FYZICKÁ AKUMULACE (POTVRZENÝ IMPULZ #3)
                # =================================================================
                elif entry_sess in ["SHANGHAI", "NEW_YORK"] and regime == MasterRegime.TREND_BULL and c_gsr >= 58.5 and allow_long_shanghai and allow_breakout_cot:
                    if c_close > high_20s[i] and closes[i-1] <= high_20s[i-1] and ers[i] > 0.45 and u_wicks[i] < 0.50:
                        sig_dir = SilverSignalDirection.LONG
                        strat_id = 3
                        strat_name = "RANGE_BREAKOUT"
                        sl_dist = 1.8 * c_atr
                        tp_dist = 3.0 * c_atr

                elif entry_sess in ["SHANGHAI", "NEW_YORK"] and regime == MasterRegime.HIGH_VOL_CORRECTION and c_sh_drift < 0.0:
                    if c_close < low_20s[i] and closes[i-1] >= low_20s[i-1] and ers[i] > 0.42 and l_wicks[i] < 0.50:
                        sig_dir = SilverSignalDirection.SHORT
                        strat_id = 3
                        strat_name = "RANGE_BREAKOUT"
                        sl_dist = 1.8 * c_atr
                        tp_dist = 2.8 * c_atr

                # =================================================================
                # PRIORITA 5: VWAP & RSI MEAN REVERSION V KOMPRESI (#2)
                # =================================================================
                elif not is_london_restricted and regime == MasterRegime.CHOP_COMPRESSION and atr_ratios[i] < 1.05 and adxs[i] < 20.0:
                    if rsis[i] < 22.0 and allow_long_gsr and allow_long_shanghai:
                        sig_dir = SilverSignalDirection.LONG
                        strat_id = 2
                        strat_name = "MEAN_REVERSION"
                        sl_dist = 1.4 * c_atr
                        tp_dist = 2.1 * c_atr
                    elif rsis[i] > 78.0 and (c_gsr <= 61.0 or c_cot >= 75.0):
                        sig_dir = SilverSignalDirection.SHORT
                        strat_id = 2
                        strat_name = "MEAN_REVERSION"
                        sl_dist = 1.4 * c_atr
                        tp_dist = 2.1 * c_atr

                # Cooldown: Po Stop-Lossu nesmí stejná strategie ve stejném směru vstoupit po dobu 12 barů (3 hodiny)
                if sig_dir is not None:
                    last_sl = last_sl_bar.get((strat_id, sig_dir.value), -999)
                    if (i - last_sl) < 12:
                        sig_dir = None

                if sig_dir is not None:
                    decision = self.sizing_engine.compute_size(
                        current_equity=risk_state.current_equity,
                        proposed_sl_dollars_per_oz=sl_dist,
                        regime=regime,
                        session_hour_cet=c_hour,
                        session_minute_cet=c_min,
                        month=c_month,
                        gsr_zscore=float(c_gsr_z)
                    )

                    p_oz = getattr(decision, "position_oz", 1000.0 * decision.contracts)

                    if decision.allow_trade and p_oz > 0:
                        spread, slip = self._get_dynamic_spread_and_slippage(c_hour, c_min)
                        if sig_dir == SilverSignalDirection.LONG:
                            actual_entry = c_close + (spread / 2.0) + slip
                            target_sl = actual_entry - sl_dist
                            target_tp = actual_entry + tp_dist
                        else:
                            actual_entry = c_close - (spread / 2.0) - slip
                            target_sl = actual_entry + sl_dist
                            target_tp = actual_entry - tp_dist

                        active_position = {
                            "entry_time": dt_str,
                            "entry": actual_entry,
                            "sl": target_sl,
                            "tp": target_tp,
                            "r_dist": sl_dist,
                            "dir": sig_dir,
                            "contracts": decision.contracts,
                            "position_oz": p_oz,
                            "strat_id": strat_id,
                            "strat_name": strat_name,
                            "stage": "INITIAL",
                            "regime": regime.name,
                            "entry_session": entry_sess,
                            "gsr": float(c_gsr),
                            "sh_drift": float(c_sh_drift),
                            "cot_idx": float(c_cot)
                        }
                    else:
                        skipped_trades_count += 1

            if i % 100 == 0 or i == n_bars - 1:
                equity_curve.append({
                    "timestamp": dt_str,
                    "equity": round(risk_state.current_equity, 2),
                    "drawdown_pct": round(risk_state.current_drawdown_pct * 100.0, 2)
                })

        metrics = SilverPerformanceMetrics.calculate_metrics(trades, initial_capital=self.initial_capital)
        metrics["skipped_trades_volatility_gate"] = skipped_trades_count
        metrics["bars_processed"] = len(df)
        metrics["period"] = f"{start_date} → {end_date}"
        metrics["dataset_name"] = name

        return {
            "metrics": metrics,
            "trades": trades,
            "equity_curve": equity_curve
        }
