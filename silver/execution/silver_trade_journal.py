"""
silver_trade_journal.py – Strukturovaný deník obchodů pro SilverEdge (JSONL)
=============================================================================
KROK 65 v Silver Replication Roadmap v3.0

Zajišťuje zápis každého obchodu a exekuce do silver/logs/silver_trades.jsonl
pro forward testing, audit a live vizualizaci na dashboardu.

Zaznamenává:
- timestamp_entry, timestamp_exit
- strategy_id, strategy_name
- direction, contracts
- expected_fill_price, actual_fill_price
- slippage_usd, slippage_ticks
- bid_ask_spread_at_entry
- net_pnl_usd, net_pnl_r
- exit_reason (TP, SL, STAGE_1_BE, STAGE_2_FEE_PLUS, EMERGENCY)
- regime_at_entry, gsr_at_entry, atr_at_entry
"""

from __future__ import annotations
import os
import sys
import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

WORKSPACE_DIR = Path(__file__).resolve().parent.parent.parent
LOG_DIR = WORKSPACE_DIR / "silver" / "logs"
LOG_FILE = LOG_DIR / "silver_trades.jsonl"


class SilverTradeJournal:
    """Zapisovatel do auditu obchodů stříbra."""

    def __init__(self, log_path: Path = LOG_FILE):
        self.log_path = log_path
        os.makedirs(self.log_path.parent, exist_ok=True)

    def log_trade(self, trade_data: Dict[str, Any]) -> None:
        """Atomicky připíše záznam obchodu na konec .jsonl souboru."""
        record = trade_data.copy()
        if "logged_at" not in record:
            record["logged_at"] = datetime.now(timezone.utc).isoformat()

        line = json.dumps(record, ensure_ascii=False) + "\n"
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()

    def get_recent_trades(self, limit: int = 50) -> list:
        """Načte posledních N obchodů pro webové API a dashboard."""
        if not os.path.exists(self.log_path):
            return []

        trades = []
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        trades.append(json.loads(line))
        except Exception:
            pass
        return trades[-limit:]
