"""
ARGON V2 - CME GLOBEX LEVEL 2 (MDP 3.0) ORDER BOOK IMBALANCE FILTER
===================================================================
Řeší Hypotézu 3 (04_ARGON_RESEARCH_CHECKLIST.md):
Filtrace vstupů v Killzones 12:00–16:59 SEČ pomocí 5-úrovňové hloubky trhu
(Weighted Order Book Imbalance + Micro-Price Skew + Order Flow Imbalance).
Obsahuje i automatický OHLCV Bar-Delta fallback pro historický backtest.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple
import numpy as np
import pandas as pd
@dataclass
class Level2BookSnapshot:
    """Snapshot prvních 5 úrovní knihy objednávek CME Globex (MGC / GC)."""
    bid_prices: List[float]   # Délka 5 (od Best Bid index 0 po úroveň 4)
    bid_sizes: List[float]    # Délka 5
    ask_prices: List[float]   # Délka 5 (od Best Ask index 0 po úroveň 4)
    ask_sizes: List[float]    # Délka 5
class CMEGlobexLevel2Filter:
    """
    Počítá exponenciálně váženou nerovnováhu knihy objednávek (WOBI)
    a Micro-Price odchylku pro potvrzení vstupu v Killzones 12:00–16:59 SEČ.
    """
    # Exponenciální váhy pro 5 úrovní hloubky trhu: w_i = exp(-0.5 * i)
    LEVEL_WEIGHTS = np.exp(-0.5 * np.arange(5, dtype=np.float64))
    @classmethod
    def compute_weighted_obi(cls, snap: Level2BookSnapshot) -> Tuple[float, float]:
        """
        Vrací:
        - wobi in [-1.0, +1.0]: Vážená Order Book Imbalance přes 5 úrovní.
        - micro_price_skew_ticks: Odchylka Micro-Price od středu spreadu v ticích ($0.10).
        """
        b_sizes = np.asarray(snap.bid_sizes[:5], dtype=np.float64)
        a_sizes = np.asarray(snap.ask_sizes[:5], dtype=np.float64)
        w = cls.LEVEL_WEIGHTS[: len(b_sizes)]
        wb = float(np.sum(w * b_sizes))
        wa = float(np.sum(w * a_sizes))
        wobi = (wb - wa) / max(1e-9, wb + wa)
        # Výpočet Stoikov Micro-Price na 1. úrovni (Best Bid / Best Ask)
        best_bid, best_ask = snap.bid_prices[0], snap.ask_prices[0]
        b0, a0 = max(1e-6, b_sizes[0]), max(1e-6, a_sizes[0])
        mid_price = 0.5 * (best_bid + best_ask)
        micro_price = (b0 * best_ask + a0 * best_bid) / (b0 + a0)
        micro_skew_ticks = (micro_price - mid_price) / 0.10  # 1 tick MGC = $0.10
        return float(wobi), float(micro_skew_ticks)
    @classmethod
    def confirm_killzone_entry_l2(
        cls, snap: Level2BookSnapshot, direction: str, min_wobi_threshold: float = 0.18
    ) -> bool:
        """
        Potvrdí vstup v Killzone 12:00–16:59 SEČ pouze tehdy, pokud hloubka trhu
        podporuje směr obchodu (zabraňuje nákupu do institucionální Iceberg distribuce).
        """
        wobi, micro_skew = cls.compute_weighted_obi(snap)
        if direction.upper() == "LONG":
            return wobi >= min_wobi_threshold and micro_skew >= 0.0
        else:
            return wobi <= -min_wobi_threshold and micro_skew <= 0.0
    @staticmethod
    def ohlcv_bar_imbalance_fallback(df: pd.DataFrame, window: int = 10) -> float:
        """
        Pokud v historickém OOS testu nejsou k dispozici plné MDP 3.0 L2 snapshoty,
        aproximuje Order Book Imbalance pomocí intrabar Buying/Selling Pressure (CLV * Volume).
        """
        high = df["high"].iloc[-window:]
        low = df["low"].iloc[-window:]
        close = df["close"].iloc[-window:]
        vol = df["volume"].iloc[-window:] if "volume" in df.columns else pd.Series(1.0, index=close.index)
        # Close Location Value (CLV) in [-1, +1]
        clv = ((close - low) - (high - close)) / (high - low + 1e-9)
        signed_vol = (clv * vol).sum()
        total_vol = vol.sum() + 1e-9
        return float(np.clip(signed_vol / total_vol, -1.0, 1.0))
