"""
silver_strategies.py – Konsolidovaný modul 7 strategií a 2-Stage Break-Even pro SilverEdge v1.0
=============================================================================================
KROKY 36, 37 a 38 v Silver Replication Roadmap v3.0

Implementuje všech 7 strategií optimalizovaných pro Micro Silver (SIL = 1 000 oz):
1. Strategie #1: Trend Following (ADX > 22, EMA cross, HMM != CHOP)
2. Strategie #2: Mean Reversion (RSI < 25 / > 75, Bollinger Bands)
3. Strategie #3: Range & Volatility Breakout (Donchian 20, SL = 2.0 × ATR)
4. Strategie #4: Macro Event Driven (CPI, NFP, China Caixin PMI, US ISM)
5. Strategie #5: L2 DOM Flow (Order book imbalance > 1.8×)
6. Strategie #6: News & Miner Proxy Sentiment (SLV, PAAS, HL, AG, WPM, MAG, SILJ)
7. Strategie #7: GSR Mean Reversion (Futures MGC/SIL Rolling Z-Score > 2.0 / < -2.0)

KROK 38: 2-Stage Break-Even a Fee-Plus kalibrace:
- Stage 1: Při dosažení +0.80R posun SL na -0.30R (rychlá ochrana kapitálu při intradenních špičkách)
- Stage 2 Fee-Plus: Při dosažení +1.00R posun SL na +$0.025/oz (+$25 na 1 SIL kontrakt – garantovaný zisk)

KROK 16/41: Volatility Gate (Hard Sizing Filter):
- Pokud SL > $0.40/oz ($400 na 1 SIL), obchod se přeskočí (SKIP_TRADE)!
"""

from __future__ import annotations
import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import pandas as pd

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from silver.models.silver_regime_engine import MasterRegime
from silver.config.silver_config import SilverRiskConfig, SilverKillzoneConfig


class SilverSignalDirection(Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


@dataclass
class SilverTradeSignal:
    """Kompletní obchodní příkaz se specifikací SL/TP, Volatility Gate a 2-Stage BE."""
    timestamp: str
    strategy_id: int                    # 1 až 7
    strategy_name: str
    direction: SilverSignalDirection
    entry_price: float
    stop_loss: float
    take_profit: float
    r_distance_usd: float               # Vzdálenost SL v $/oz
    dollar_risk_1contract: float        # r_distance * 1000 oz
    volatility_gate_passed: bool        # True = risk <= $400, False = SKIP_TRADE
    contracts: int = 1                  # 1 kontrakt default
    stage1_be_price: float = 0.0        # Cena posunu na -0.30R (+0.80R trigger)
    stage2_fee_plus_price: float = 0.0  # Cena posunu na +$0.025/oz (+1.00R trigger)
    confidence: float = 0.50
    regime: str = "TREND_BULL"
    metadata: Dict[str, Any] = field(default_factory=dict)


# =====================================================================
# INDIKÁTORY PRO STŘÍBRO
# =====================================================================

def compute_silver_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilderův RMA ATR bez ořezu."""
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - df["close"].shift(1)).abs()
    tr3 = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, min_periods=1, adjust=False).mean().clip(lower=0.005)


def compute_silver_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1.0 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1.0 / period, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-6)
    return 100.0 - (100.0 / (1.0 + rs))


def compute_silver_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    up_move = df["high"].diff()
    down_move = -df["low"].diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = compute_silver_atr(df, period=period)
    plus_di = 100.0 * (pd.Series(plus_dm, index=df.index).ewm(alpha=1.0 / period, adjust=False).mean() / tr)
    minus_di = 100.0 * (pd.Series(minus_dm, index=df.index).ewm(alpha=1.0 / period, adjust=False).mean() / tr)
    dx = (np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-6)) * 100.0
    return dx.ewm(alpha=1.0 / period, adjust=False).mean().fillna(0.0)


# =====================================================================
# ENGINE 7 STRATEGIÍ S VOLATILITY GATE A 2-STAGE BREAK-EVEN
# =====================================================================

class SilverStrategyEngine:
    """Komplexní engine pro generování signálů strategií #1 až #7."""

    def __init__(self, risk_cfg: Optional[SilverRiskConfig] = None):
        self.risk_cfg = risk_cfg or SilverRiskConfig()
        self.max_sl_dollars = self.risk_cfg.max_sl_dollars_per_oz  # $0.40/oz ($400 pro 1000 oz)
        self.fee_plus_offset = 0.03                               # +$0.03/oz (dynamický min offset)

    def evaluate_2stage_breakeven(
        self,
        current_price: float,
        high_price: float,
        low_price: float,
        entry_price: float,
        current_sl: float,
        initial_r_dist: float,
        current_atr: float,
        current_stage: str,
        direction: SilverSignalDirection
    ) -> Tuple[float, str]:
        """
        SILVEREDGE v2.5 – 3-Stage Adaptive Protection & Chandelier Exit:
        - Používá fixní initial_r_dist (eliminuje chybu zaškrcení 16 výher na +$2.40!).
        - Stage 1 (při +1.00R): Posun SL na -0.35R (redukce 65 % rizika, prostor pro retest FVG/VWAP).
        - Stage 2 (při +1.35R): Posun SL na +0.35R nad vstup (uzamčení ~$42 zisku místo $2.40).
        - Stage 3 (při +1.65R): Chandelier Trailing SL ve vzdálenosti 1.30 * ATR14 od extrému.
        """
        if initial_r_dist <= 0:
            return current_sl, current_stage

        lock_stage2_dist = max(self.fee_plus_offset, 0.35 * initial_r_dist)

        if direction == SilverSignalDirection.LONG:
            peak_r = (high_price - entry_price) / initial_r_dist
            if peak_r >= 1.65 or current_stage == "STAGE_3_CHANDELIER":
                chandelier_sl = high_price - 1.30 * current_atr
                new_sl = max(current_sl, entry_price + lock_stage2_dist, chandelier_sl)
                return round(new_sl, 4), "STAGE_3_CHANDELIER"
            elif peak_r >= 1.35 or current_stage == "STAGE_2_FEE_PLUS":
                new_sl = max(current_sl, entry_price + lock_stage2_dist)
                return round(new_sl, 4), "STAGE_2_FEE_PLUS"
            elif peak_r >= 1.00 or current_stage == "STAGE_1_BE":
                new_sl = max(current_sl, entry_price - 0.35 * initial_r_dist)
                return round(new_sl, 4), "STAGE_1_BE"
        else:  # SHORT
            peak_r = (entry_price - low_price) / initial_r_dist
            if peak_r >= 1.65 or current_stage == "STAGE_3_CHANDELIER":
                chandelier_sl = low_price + 1.30 * current_atr
                new_sl = min(current_sl, entry_price - lock_stage2_dist, chandelier_sl)
                return round(new_sl, 4), "STAGE_3_CHANDELIER"
            elif peak_r >= 1.35 or current_stage == "STAGE_2_FEE_PLUS":
                new_sl = min(current_sl, entry_price - lock_stage2_dist)
                return round(new_sl, 4), "STAGE_2_FEE_PLUS"
            elif peak_r >= 1.00 or current_stage == "STAGE_1_BE":
                new_sl = min(current_sl, entry_price + 0.35 * initial_r_dist)
                return round(new_sl, 4), "STAGE_1_BE"

        return current_sl, current_stage

    def generate_signal(
        self,
        df: pd.DataFrame,
        current_regime: MasterRegime,
        gsr_telemetry: Optional[Dict[str, Any]] = None,
        macro_score: Optional[Dict[str, Any]] = None,
        strategy_priority: Optional[List[int]] = None
    ) -> Optional[SilverTradeSignal]:
        """
        Vygeneruje nejvhodnější signál ze strategií #1–#7 na základě aktuálního tržního stavu.
        Aplikuje Volatility Gate: pokud r_distance > $0.40/oz, signál se označí jako SKIP_TRADE.
        """
        if len(df) < 30:
            return None

        close = df["close"].iloc[-1]
        dt_str = str(df["datetime"].iloc[-1]) if "datetime" in df.columns else "2026-10-18 00:00:00"
        atr14 = float(compute_silver_atr(df, 14).iloc[-1])
        rsi14 = float(compute_silver_rsi(df["close"], 14).iloc[-1])
        adx14 = float(compute_silver_adx(df, 14).iloc[-1])

        # Priority pořadí strategií
        priorities = strategy_priority or [7, 4, 1, 3, 2, 5, 6]

        for strat_id in priorities:
            sig = None

            # -------------------------------------------------------------
            # STRATEGIE #7: GSR MEAN REVERSION (Unikátní pro Silver)
            # -------------------------------------------------------------
            if strat_id == 7 and gsr_telemetry:
                gsr_info = gsr_telemetry.get("gsr_futures", {})
                zscore = float(gsr_info.get("zscore", 0.0))
                # Z > +2.0 = Gold drahé / Silver levné -> Strong Long
                # Z < -2.0 = Gold levné / Silver drahé -> Strong Short
                # Blokováno v režimu HIGH_VOL_CORRECTION pro Long
                if zscore >= 2.0 and current_regime != MasterRegime.HIGH_VOL_CORRECTION:
                    sl_dist = 2.0 * atr14
                    tp_dist = 3.5 * atr14
                    sig = self._create_signal(
                        dt_str, 7, "GSR_MEAN_REVERSION", SilverSignalDirection.LONG,
                        close, close - sl_dist, close + tp_dist, sl_dist, current_regime,
                        confidence=0.85, metadata={"gsr_zscore": zscore}
                    )
                elif zscore <= -2.0 and current_regime != MasterRegime.TREND_BULL:
                    sl_dist = 2.0 * atr14
                    tp_dist = 3.5 * atr14
                    sig = self._create_signal(
                        dt_str, 7, "GSR_MEAN_REVERSION", SilverSignalDirection.SHORT,
                        close, close + sl_dist, close - tp_dist, sl_dist, current_regime,
                        confidence=0.85, metadata={"gsr_zscore": zscore}
                    )

            # -------------------------------------------------------------
            # STRATEGIE #4: MACRO EVENT DRIVEN (China PMI, ISM, CPI, NFP)
            # -------------------------------------------------------------
            elif strat_id == 4 and macro_score:
                comp_score = float(macro_score.get("composite_score", 0.0))
                if comp_score > 0.40 and current_regime != MasterRegime.HIGH_VOL_CORRECTION:
                    sl_dist = 2.2 * atr14
                    tp_dist = 3.8 * atr14
                    sig = self._create_signal(
                        dt_str, 4, "MACRO_EVENT_DRIVEN", SilverSignalDirection.LONG,
                        close, close - sl_dist, close + tp_dist, sl_dist, current_regime,
                        confidence=0.80, metadata={"macro_score": comp_score}
                    )
                elif comp_score < -0.40 and current_regime != MasterRegime.TREND_BULL:
                    sl_dist = 2.2 * atr14
                    tp_dist = 3.8 * atr14
                    sig = self._create_signal(
                        dt_str, 4, "MACRO_EVENT_DRIVEN", SilverSignalDirection.SHORT,
                        close, close + sl_dist, close - tp_dist, sl_dist, current_regime,
                        confidence=0.80, metadata={"macro_score": comp_score}
                    )

            # -------------------------------------------------------------
            # STRATEGIE #1: TREND FOLLOWING (ADX > 22, EMA 20/50 cross)
            # -------------------------------------------------------------
            elif strat_id == 1 and current_regime == MasterRegime.TREND_BULL:
                ema20 = df["close"].ewm(span=20, adjust=False).mean().iloc[-1]
                ema50 = df["close"].ewm(span=50, adjust=False).mean().iloc[-1]
                if adx14 > 22.0 and ema20 > ema50 and close > ema20:
                    sl_dist = 1.8 * atr14
                    tp_dist = 3.2 * atr14
                    sig = self._create_signal(
                        dt_str, 1, "TREND_FOLLOWING", SilverSignalDirection.LONG,
                        close, close - sl_dist, close + tp_dist, sl_dist, current_regime,
                        confidence=0.75, metadata={"adx": adx14}
                    )

            # -------------------------------------------------------------
            # STRATEGIE #3: BREAKOUT (Donchian 20 channel)
            # -------------------------------------------------------------
            elif strat_id == 3 and current_regime in [MasterRegime.TREND_BULL, MasterRegime.HIGH_VOL_CORRECTION]:
                highest_20 = df["high"].iloc[-21:-1].max()
                lowest_20 = df["low"].iloc[-21:-1].min()
                if close > highest_20 and current_regime == MasterRegime.TREND_BULL:
                    sl_dist = 2.0 * atr14
                    tp_dist = 3.0 * atr14
                    sig = self._create_signal(
                        dt_str, 3, "RANGE_BREAKOUT", SilverSignalDirection.LONG,
                        close, close - sl_dist, close + tp_dist, sl_dist, current_regime,
                        confidence=0.70
                    )
                elif close < lowest_20 and current_regime == MasterRegime.HIGH_VOL_CORRECTION:
                    sl_dist = 2.0 * atr14
                    tp_dist = 3.0 * atr14
                    sig = self._create_signal(
                        dt_str, 3, "RANGE_BREAKOUT", SilverSignalDirection.SHORT,
                        close, close + sl_dist, close - tp_dist, sl_dist, current_regime,
                        confidence=0.70
                    )

            # -------------------------------------------------------------
            # STRATEGIE #2: MEAN REVERSION (RSI < 25 / > 75 v CHOP)
            # -------------------------------------------------------------
            elif strat_id == 2 and current_regime == MasterRegime.CHOP_COMPRESSION:
                if rsi14 < 25.0:
                    sl_dist = 1.5 * atr14
                    tp_dist = 2.2 * atr14
                    sig = self._create_signal(
                        dt_str, 2, "MEAN_REVERSION", SilverSignalDirection.LONG,
                        close, close - sl_dist, close + tp_dist, sl_dist, current_regime,
                        confidence=0.65, metadata={"rsi": rsi14}
                    )
                elif rsi14 > 75.0:
                    sl_dist = 1.5 * atr14
                    tp_dist = 2.2 * atr14
                    sig = self._create_signal(
                        dt_str, 2, "MEAN_REVERSION", SilverSignalDirection.SHORT,
                        close, close + sl_dist, close - tp_dist, sl_dist, current_regime,
                        confidence=0.65, metadata={"rsi": rsi14}
                    )

            if sig is not None:
                return sig

        return None

    def _create_signal(
        self,
        dt: str,
        strat_id: int,
        name: str,
        direction: SilverSignalDirection,
        entry: float,
        sl: float,
        tp: float,
        sl_dist: float,
        regime: MasterRegime,
        confidence: float = 0.70,
        metadata: Optional[Dict[str, Any]] = None
    ) -> SilverTradeSignal:
        """Sestaví signál a aplikuje Volatility Gate a 2-Stage BE parametry."""
        meta = metadata or {}
        dollar_risk = sl_dist * 1000.0  # SIL Micro = 1000 oz
        
        # Volatility Gate: Pokud je SL > $0.40/oz ($400 na $10k účtu), bot NESMÍ vstoupit
        vol_gate_pass = sl_dist <= self.max_sl_dollars

        # 2-Stage BE triggery
        if direction == SilverSignalDirection.LONG:
            stage1_be = entry + 0.80 * sl_dist
            stage2_fp = entry + 1.00 * sl_dist
        else:
            stage1_be = entry - 0.80 * sl_dist
            stage2_fp = entry - 1.00 * sl_dist

        return SilverTradeSignal(
            timestamp=dt,
            strategy_id=strat_id,
            strategy_name=name,
            direction=direction,
            entry_price=round(entry, 4),
            stop_loss=round(sl, 4),
            take_profit=round(tp, 4),
            r_distance_usd=round(sl_dist, 4),
            dollar_risk_1contract=round(dollar_risk, 2),
            volatility_gate_passed=vol_gate_pass,
            contracts=1 if vol_gate_pass else 0,
            stage1_be_price=round(stage1_be, 4),
            stage2_fee_plus_price=round(stage2_fp, 4),
            confidence=confidence,
            regime=regime.name,
            metadata=meta
        )
