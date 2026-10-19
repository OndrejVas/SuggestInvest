"""
silver_bot_main.py – Lehká orchestrace bota (< 5 kB) pro Micro Silver
=====================================================================
KROK 63 v Silver Replication Roadmap v3.0

Spouštěcí CLI pro SilverEdge bota:
- python silver/silver_bot_main.py --status
- python silver/silver_bot_main.py --run-tick
- python silver/silver_bot_main.py --daemon
"""

from __future__ import annotations
import os
import sys
import argparse
import time
from pathlib import Path
import pandas as pd

WORKSPACE_DIR = Path(__file__).resolve().parent.parent
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))

from silver.execution.silver_futures_bot import SilverFuturesBot
from silver.config.silver_config import SilverRiskConfig


def main():
    parser = argparse.ArgumentParser(description="SilverEdge v1.0 Autonomous Bot")
    parser.add_argument("--status", action="store_true", help="Vypíše aktuální stav bota")
    parser.add_argument("--run-tick", action="store_true", help="Provede jeden vyhodnocovací tick")
    parser.add_argument("--daemon", action="store_true", help="Spustí bota jako daemon smyčku")
    args = parser.parse_args()

    bot = SilverFuturesBot(initial_capital=10_000.0)

    # Vytvoření testovacího rámce pro okamžitou evaluaci
    sample_df = pd.DataFrame({
        "open": [32.0, 32.1, 32.2] * 12,
        "high": [32.3, 32.4, 32.5] * 12,
        "low": [31.9, 32.0, 32.1] * 12,
        "close": [32.2, 32.3, 32.4] * 12
    })

    if args.status or (not args.run_tick and not args.daemon):
        res = bot.tick_evaluation(sample_df)
        print("=" * 60)
        print("SILVEREDGE v1.0 • BOT STATUS REPORT (Krok 63)")
        print("=" * 60)
        print(f"Stav:            {res['status']}")
        print(f"Aktivní kontrakt:{res['active_contract']}")
        print(f"Tržní režim:     {res['regime']}")
        print(f"Ekvita:          ${res['current_equity']:,} (Drawdown: {res['drawdown_pct']}%)")
        print(f"Pozice:          {'OTEVŘENA' if res['open_position'] else 'ŽÁDNÁ'}")
        print(f"Akce:            {res['action']}")
        print("✅ Orchestrace připravena.")

    elif args.run_tick:
        res = bot.tick_evaluation(sample_df)
        print(f"[{res['timestamp']}] Tick proveden: {res['action']}")

    elif args.daemon:
        print("Spouštím SilverEdge daemona (Ctrl+C pro ukončení)...")
        try:
            while True:
                bot.tick_evaluation(sample_df)
                time.sleep(5.0)
        except KeyboardInterrupt:
            print("\nDaemon bezpečně zastaven.")


if __name__ == "__main__":
    main()
