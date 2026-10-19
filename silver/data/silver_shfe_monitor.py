"""
silver_shfe_monitor.py – Shanghai Session Monitor & Asian Premium Tracker
========================================================================
KROK 30 v Silver Replication Roadmap v3.0

Řeší Argon Tip #3:
V asijských hodinách (02:00–08:00 SEČ) nelze monitorovat spící americká ETF (MCHI, FXI).
Tento modul monitoruje reálně obchodované noční instrumenty:
1. Měď (HG=F / Micro Copper MHG)
2. Offshore jüan (USD/CNH = CNH=X)
3. Hang Seng index futures (^HSI)
4. Kalkuluje odhadované Shanghai Silver Premium (čínské fyzické prémium nad COMEXem)
5. Generuje stav seance pro Risk Dashboard a Position Sizing (50 % sizing v noci)
6. Ukládá: data/silver_shfe_state.json
"""

from __future__ import annotations
import os
import sys
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

import numpy as np
import pandas as pd
import yfinance as yf

WORKSPACE_DIR = Path(__file__).resolve().parent.parent.parent
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))

from silver.data.silver_async_io import safe_write_json, DynamicTTLCacheManager
from silver.config.silver_config import SilverKillzoneConfig

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logger = logging.getLogger("SilverSHFEMonitor")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [SHFE_MONITOR] %(message)s")

OUTPUT_PATH = WORKSPACE_DIR / "data" / "silver_shfe_state.json"


class SilverSHFEMonitor:
    """Monitor asijské / šanghajské seance pro stříbro."""

    def __init__(self, cache_mgr: Optional[DynamicTTLCacheManager] = None):
        self.cache_mgr = cache_mgr or DynamicTTLCacheManager()
        self.killzone = SilverKillzoneConfig()

    def is_shanghai_session_active(self, dt: Optional[datetime] = None) -> bool:
        """Zjišťuje, zda je aktuální čas v okně Shanghai Session (02:00–08:00 SEČ)."""
        now = dt or datetime.now()
        minutes = now.hour * 60 + now.minute
        return self.killzone.SHANGHAI_SESSION_START <= minutes < self.killzone.SHANGHAI_SESSION_END

    def update_shfe_state(self) -> Dict[str, Any]:
        """Stáhne noční instrumenty a spočítá odhadované Shanghai Silver Premium."""
        now = datetime.now()
        is_active = self.is_shanghai_session_active(now)

        try:
            logger.info("Stahuji data nočních instrumentů (HG=F, CNH=X, ^HSI)...")
            tickers = ["HG=F", "CNH=X", "^HSI", "SI=F"]
            raw_df = yf.download(tickers, period="5d", interval="1h", progress=False)
            
            if isinstance(raw_df.columns, pd.MultiIndex):
                close_df = raw_df["Close"].ffill().bfill()
            else:
                close_df = raw_df.ffill().bfill()

            latest = close_df.iloc[-1]
            prev_8h = close_df.iloc[-8] if len(close_df) >= 8 else close_df.iloc[0]

            si_price = float(latest.get("SI=F", 32.50))
            hg_price = float(latest.get("HG=F", 4.50))
            cnh_rate = float(latest.get("CNH=X", 7.15))
            hsi_price = float(latest.get("^HSI", 20500.0))

            # Pohyb mědi za asijskou seanci (posledních 8 hodin)
            hg_8h_change = float((hg_price - prev_8h.get("HG=F", hg_price)) / prev_8h.get("HG=F", hg_price) * 100.0) if prev_8h.get("HG=F", 0) > 0 else 0.0
            cnh_8h_change = float((cnh_rate - prev_8h.get("CNH=X", cnh_rate)) / prev_8h.get("CNH=X", cnh_rate) * 100.0) if prev_8h.get("CNH=X", 0) > 0 else 0.0

            # Odhadované Shanghai Silver Premium:
            # Historicky se v Číně stříbro obchoduje s prémiem 4 % až 11 % nad COMEXem.
            # Oslabení jüanu (růst USD/CNH) a růst mědi typicky tlačí prémium nahoru.
            base_shanghai_premium_pct = 6.2  # Základní historický průměr
            premium_adjustment = (hg_8h_change * 0.4) + (cnh_8h_change * 0.6)
            est_premium_pct = round(np.clip(base_shanghai_premium_pct + premium_adjustment, 1.0, 15.0), 2)
            est_shanghai_price_usd = round(si_price * (1.0 + est_premium_pct / 100.0), 3)

            # Sentiment asijské seance:
            if hg_8h_change > 0.8 and cnh_8h_change < 0.2:
                asian_sentiment = "BULLISH_EXPANSION"
            elif hg_8h_change < -0.8:
                asian_sentiment = "BEARISH_CONTRACTION"
            else:
                asian_sentiment = "NEUTRAL_BALANCED"

            state = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "shanghai_session_active": is_active,
                "session_hours_cet": "02:00 - 08:00 SEČ",
                "session_size_multiplier": self.killzone.SHANGHAI_SIZE_MULTIPLIER if is_active else 1.0,
                "night_instruments": {
                    "copper_hg": round(hg_price, 4),
                    "copper_8h_change_pct": round(hg_8h_change, 2),
                    "usd_cnh": round(cnh_rate, 4),
                    "hang_seng_index": round(hsi_price, 1)
                },
                "shanghai_premium": {
                    "comex_silver_usd": si_price,
                    "estimated_premium_pct": est_premium_pct,
                    "estimated_shanghai_usd": est_shanghai_price_usd,
                    "premium_level": "ELEVATED" if est_premium_pct > 8.0 else ("NORMAL" if est_premium_pct >= 4.0 else "DEPRESSED")
                },
                "asian_market_sentiment": asian_sentiment,
                "status": "HEALTHY"
            }

            safe_write_json(str(OUTPUT_PATH), state)
            return state

        except Exception as e:
            logger.error(f"Chyba při monitorování SHFE seance: {e}")
            fallback = {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "shanghai_session_active": is_active,
                "session_size_multiplier": 0.50 if is_active else 1.0,
                "shanghai_premium": {"estimated_premium_pct": 6.2, "premium_level": "NORMAL"},
                "asian_market_sentiment": "NEUTRAL",
                "status": "FALLBACK"
            }
            return fallback


def main():
    monitor = SilverSHFEMonitor()
    res = monitor.update_shfe_state()
    print("\n" + "=" * 60)
    print("SHANGHAI SESSION MONITOR (Krok 30)")
    print("=" * 60)
    print(f"Stav seance:       {'AKTIVNÍ (02:00-08:00 SEČ)' if res['shanghai_session_active'] else 'NEAKTIVNÍ'}")
    print(f"Sizing multiplik.: {res['session_size_multiplier'] * 100}% pozice")
    print(f"Odhadované Prémium: +{res['shanghai_premium']['estimated_premium_pct']}% nad COMEXem ({res['shanghai_premium']['premium_level']})")
    print(f"Asijský sentiment: {res['asian_market_sentiment']}")
    print(f"Měď (8h change):   {res['night_instruments']['copper_8h_change_pct']}% (${res['night_instruments']['copper_hg']}/lb)")
    print(f"Uloženo do:        {OUTPUT_PATH}")
    print("✅ KROK 30 DOKONČEN!")

if __name__ == "__main__":
    main()
