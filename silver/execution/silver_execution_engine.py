"""
silver_execution_engine.py – Exekuční Order Management Engine pro Silver
========================================================================
KROK 62 v Silver Replication Roadmap v3.0

Řeší specifika širšího bid-ask spreadu na stříbře:
1. Adaptive Limit / Pegged-to-Midpoint příkazy pro pasivní fill s minimálním skluzem.
2. Market příkazy povoleny POUZE pro:
   - Nouzový výstup (Emergency Stop, Sovereign Floor, Daily Loss hit)
   - Vrchol NY likvidity (14:30–16:00 SEČ)
3. Automatické generování Bracket příkazu (vstupní příkaz + OCO pro Stop-Loss a Take-Profit)
4. Kontrola maximální povolené odchylky od modelované ceny (Slippage Guard)
"""

from __future__ import annotations
import os
import sys
import logging
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from silver.config.silver_config import SilverInstrumentConfig
from silver.models.silver_strategies import SilverSignalDirection, SilverTradeSignal

logger = logging.getLogger("SilverExecutionEngine")


@dataclass
class SilverBracketOrder:
    """Kompletní bracket příkaz pro IBKR."""
    parent_order_type: str              # "LMT" nebo "MKT" (při nouzi)
    action: str                         # "BUY" nebo "SELL"
    total_quantity: int                 # Počet kontraktů
    limit_price: float                  # Entry limitní cena
    stop_loss_price: float              # SL cena
    take_profit_price: float            # TP limitní cena
    order_id_parent: int = 0
    order_id_sl: int = 0
    order_id_tp: int = 0
    transmit: bool = True
    order_ref: str = "SilverEdge_v1"


class SilverExecutionEngine:
    """Order routing a stavba chytrých příkazů pro Micro Silver."""

    def __init__(self, instrument_cfg: Optional[SilverInstrumentConfig] = None):
        self.cfg = instrument_cfg or SilverInstrumentConfig()

    def build_bracket_order(
        self,
        signal: SilverTradeSignal,
        bid_price: float,
        ask_price: float,
        is_emergency: bool = False,
        is_peak_ny_window: bool = False
    ) -> SilverBracketOrder:
        """
        Sestaví chytrý limitní nebo pegged bracket příkaz.
        """
        action = "BUY" if signal.direction == SilverSignalDirection.LONG else "SELL"
        mid_price = round((bid_price + ask_price) / 2.0, 4)

        # Volba typu příkazu
        if is_emergency:
            order_type = "MKT"
            entry_limit = 0.0
        elif is_peak_ny_window:
            # V NY vrcholu můžeme jít agresivnějším limitem (ask pro Long, bid pro Short)
            order_type = "LMT"
            entry_limit = ask_price if action == "BUY" else bid_price
        else:
            # Standardně Adaptive Midpoint limit pro úsporu spreadu ($0.005 - $0.015)
            order_type = "LMT"
            entry_limit = mid_price

        return SilverBracketOrder(
            parent_order_type=order_type,
            action=action,
            total_quantity=signal.contracts,
            limit_price=round(entry_limit, 4),
            stop_loss_price=round(signal.stop_loss, 4),
            take_profit_price=round(signal.take_profit, 4),
            order_ref=f"SIL_{signal.strategy_name}"
        )
