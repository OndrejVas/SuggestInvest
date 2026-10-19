"""
ARGON QUANT V2 - CONTINUOUS ONLINE WALK-FORWARD TRAINER
=======================================================
Zajišťuje průběžnou rekalibraci centroidů HMM, prahů volatility a Bayesovskou
aktualizaci Kellyho vah na živých M1/M15 datech z Interactive Brokers (MGC).
"""
from __future__ import annotations
from collections import deque
from typing import Deque, Dict, Tuple
import numpy as np
import pandas as pd
from argon_v2_core_engine import ArgonRegimeEngine, MarketRegime
class OnlineBayesianKellyTracker:
    """
    Udržuje Beta-Binomial (pro Win-Rate p) a Gamma-Normal (pro Payoff Ratio b)
    posteriorní odhady zvlášť pro každý režim trhu s exponenciálním zapomínáním.
    """
    def __init__(self, prior_win_rate: float = 0.52, prior_payoff: float = 1.41, pseudo_counts: float = 25.0):
        self.prior_p = prior_win_rate
        self.prior_b = prior_payoff
        self.n0 = pseudo_counts
        self.decay = 0.97  # Exponenciální vážení novějších obchodů
        self.stats: Dict[MarketRegime, Dict[str, float]] = {
            r: {
                "wins": prior_win_rate * pseudo_counts,
                "losses": (1.0 - prior_win_rate) * pseudo_counts,
                "avg_win": prior_payoff,
                "avg_loss": 1.0,
            }
            for r in MarketRegime
        }
    def record_trade(self, regime: MarketRegime, net_pnl_r: float) -> None:
        st = self.stats[regime]
        st["wins"] *= self.decay
        st["losses"] *= self.decay
        if net_pnl_r > 0:
            st["wins"] += 1.0
            st["avg_win"] = 0.92 * st["avg_win"] + 0.08 * net_pnl_r
        elif net_pnl_r < 0:
            st["losses"] += 1.0
            st["avg_loss"] = 0.92 * st["avg_loss"] + 0.08 * abs(net_pnl_r)
    def get_shrunk_quarter_kelly_multiplier(self, regime: MarketRegime, ref_kelly: float = 0.045) -> float:
        st = self.stats[regime]
        p = st["wins"] / max(1e-6, st["wins"] + st["losses"])
        b = st["avg_win"] / max(1e-6, st["avg_loss"])
        q = 1.0 - p
        raw_kelly = max(0.0, (p * b - q) / max(1e-6, b))
        quarter_kelly = 0.25 * raw_kelly
        return float(np.clip(quarter_kelly / ref_kelly, 0.35, 1.35))
class RollingHMMCalibrator:
    """
    Průběžně rekalibruje škálovací parametry 4D observačního prostoru HMM
    pomocí robusního mediánu a MAD (Median Absolute Deviation), aby model
    automaticky dýchal s posunem nominální ceny zlata ($4,000 -> $5,000+).
    """
    def __init__(self, lookback_bars: int = 14_400):  # ~10 obchodních dnů M1 barů
        self.lookback_bars = lookback_bars
        self.vol_buffer: Deque[float] = deque(maxlen=lookback_bars)
    def update_and_get_vol_floor(self, current_yz_vol: float) -> Tuple[float, float]:
        """
        Vrací (log_vol_zscore, dynamic_vol_floor_35pct) bez look-ahead biasu.
        """
        self.vol_buffer.append(current_yz_vol)
        arr = np.array(self.vol_buffer, dtype=np.float64)
        if len(arr) < 100:
            return 0.0, current_yz_vol
        log_arr = np.log(np.clip(arr, 1e-8, None))
        med = float(np.median(log_arr))
        mad = float(np.median(np.abs(log_arr - med))) * 1.4826 + 1e-6
        log_vol_z = (np.log(max(current_yz_vol, 1e-8)) - med) / mad
        vol_floor_35 = float(np.percentile(arr, 35))
        return float(log_vol_z), vol_floor_35
