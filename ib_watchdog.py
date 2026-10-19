"""
ib_watchdog.py
---------------
Automatický dohledový démon a synchronizátor pro Interactive Brokers Gateway (port 7497).

Funkce:
1. Pravidelná kontrola běžícího procesu IB Gateway (C:\\Jts\\ibgateway\\1051\\ibgateway.exe) na portu 7497.
2. Neustálá synchronizace reálných pozic, dostupné hotovosti a hodnoty portfolia do data/live_portfolio.json.
3. Garance zdroje pravdy: Na webu trading.html a scalping.html se zobrazují výhradně pozice potvrzené z IBKR.
"""

import os
import sys
import time
import json
import logging
import argparse
from datetime import datetime
from typing import Dict, Any, Tuple, Optional

from ibkr_sync_service import sync_ibkr

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("IB-Watchdog")

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))


def run_watchdog_daemon(interval_sec: int = 30):
    logger.info(f"=== Spouštím IBKR Gateway Watchdog & Sync Daemon (Port 7497, Interval: {interval_sec}s) ===")
    
    while True:
        try:
            ok = sync_ibkr(host="127.0.0.1", port=7497, client_id=990, account_id="DUR222134")
            if ok:
                logger.info("💓 IB Gateway (Port 7497) aktivní | Stav účtu a pozice synchronizovány do live_portfolio.json.")
            else:
                logger.warning("⚠️ IB Gateway na portu 7497 neodpovídá. Ověřte, zda je spuštěna aplikace IB Gateway.")
        except KeyboardInterrupt:
            logger.info("Watchdog byl zastaven uživatelem (Ctrl+C).")
            break
        except Exception as e:
            logger.error(f"Chyba v dohledové smyčce: {e}")

        time.sleep(interval_sec)


def main():
    parser = argparse.ArgumentParser(description="Interactive Brokers Gateway Watchdog & Sync Daemon")
    parser.add_argument("--check", "-c", action="store_true", help="Provede pouze jednorázovou synchronizaci a skončí")
    parser.add_argument("--interval", "-i", type=int, default=30, help="Interval synchronizace v sekundách (výchozí 30s)")
    args = parser.parse_args()

    if args.check:
        sync_ibkr(host="127.0.0.1", port=7497, client_id=990, account_id="DUR222134")
    else:
        run_watchdog_daemon(interval_sec=args.interval)


if __name__ == "__main__":
    main()
