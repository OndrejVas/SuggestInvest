"""
silver_scalping_mode.py – Intradenní Scalping Modul pro NY Window (14:30–17:00 SEČ)
=================================================================================
KROK 42 v Silver Replication Roadmap v3.0

Izolovaný sub-modul pro ultra-likvidní okno otevírání amerických trhů:
- Časové okno: 14:30 – 17:00 SEČ (nejvyšší hloubka order booku na COMEXu)
- Cíl zisku: 2 až 4 ticky ($0.010 až $0.020/oz = $10 až $20 na 1 SIL kontrakt)
- Stop-Loss: 3 ticky ($0.015/oz = $15 na 1 SIL)
- Bezpečnostní brzda: Circuit Breaker po 3 po sobě jdoucích ztrátách (zastaví scalping pro daný den)
- Max 10 obchodů za den
"""

from __future__ import annotations
import os
import sys
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple
from datetime import datetime

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from silver.config.silver_config import SilverInstrumentConfig


@dataclass
class ScalpOrder:
    direction: str                     # "BUY" nebo "SELL"
    entry_price: float
    target_price: float                # +2 až +4 ticky ($0.010 - $0.020)
    stop_price: float                  # -3 ticky ($0.015)
    ticks_target: int
    dollar_profit_target: float
    dollar_risk: float
    timestamp: str


class SilverScalpingEngine:
    """Specializovaný mikroskalpovací engine pro NY otevírací hodiny."""

    NY_SCALP_START_MINUTES = 14 * 60 + 30   # 14:30 SEČ
    NY_SCALP_END_MINUTES = 17 * 60          # 17:00 SEČ
    MAX_TRADES_PER_DAY = 10
    MAX_CONSECUTIVE_LOSSES = 3

    def __init__(self):
        self.instrument = SilverInstrumentConfig()
        self.today_trades_count = 0
        self.consecutive_losses = 0
        self.circuit_breaker_active = False

    def is_scalping_window(self, dt: Optional[datetime] = None) -> bool:
        """Ověří, zda je čas v povoleném scalping okně 14:30–17:00 SEČ."""
        now = dt or datetime.now()
        minutes = now.hour * 60 + now.minute
        return self.NY_SCALP_START_MINUTES <= minutes <= self.NY_SCALP_END_MINUTES

    def reset_daily_stats(self):
        self.today_trades_count = 0
        self.consecutive_losses = 0
        self.circuit_breaker_active = False

    def record_scalp_result(self, won: bool):
        self.today_trades_count += 1
        if won:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            if self.consecutive_losses >= self.MAX_CONSECUTIVE_LOSSES:
                self.circuit_breaker_active = True

    def generate_scalp_order(
        self,
        bid: float,
        ask: float,
        dom_imbalance_bid_ask: float,
        dt: Optional[datetime] = None
    ) -> Tuple[Optional[ScalpOrder], str]:
        """
        Vygeneruje mikroskalpovací příkaz s cílem 2–4 ticky.
        """
        if not self.is_scalping_window(dt):
            return None, "OUTSIDE_NY_SCALPING_WINDOW"

        if self.circuit_breaker_active:
            return None, f"CIRCUIT_BREAKER_ACTIVE ({self.consecutive_losses} consecutive losses)"

        if self.today_trades_count >= self.MAX_TRADES_PER_DAY:
            return None, f"MAX_DAILY_SCALPS_REACHED ({self.today_trades_count}/{self.MAX_TRADES_PER_DAY})"

        tick = self.instrument.tick_size        # 0.005
        tick_val = self.instrument.tick_value   # $5.00

        # L2 DOM imbalance: > 1.8 = silný nákupní tlak v booku
        if dom_imbalance_bid_ask >= 1.8:
            entry = ask
            target = entry + 3 * tick            # +3 ticky ($0.015) = +$15
            sl = entry - 3 * tick                # -3 ticky ($0.015) = -$15
            order = ScalpOrder(
                direction="BUY",
                entry_price=round(entry, 4),
                target_price=round(target, 4),
                stop_price=round(sl, 4),
                ticks_target=3,
                dollar_profit_target=3 * tick_val,
                dollar_risk=3 * tick_val,
                timestamp=datetime.now().isoformat()
            )
            return order, "DOM_BUY_IMBALANCE"

        elif dom_imbalance_bid_ask <= (1.0 / 1.8):
            entry = bid
            target = entry - 3 * tick
            sl = entry + 3 * tick
            order = ScalpOrder(
                direction="SELL",
                entry_price=round(entry, 4),
                target_price=round(target, 4),
                stop_price=round(sl, 4),
                ticks_target=3,
                dollar_profit_target=3 * tick_val,
                dollar_risk=3 * tick_val,
                timestamp=datetime.now().isoformat()
            )
            return order, "DOM_SELL_IMBALANCE"

        return None, "NO_SCALP_SETUP"
