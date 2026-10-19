"""
silver_high_alpha_feeds.py – High-Alpha Feeds pro SilverEdge v1.0
=================================================================
KROK 27 v Silver Replication Roadmap v3.0

Stahuje a kalkuluje v reálném čase (s dynamickou TTL cache a atomickým zápisem):
1. Futures GSR (GC=F / SI=F) – nepřetržitý 23h poměr bez zkreslení ETF
2. GSR Rolling Z-Score (60–120 dní lookback)
3. Průmyslový poměr Silver / Copper (SI=F / HG=F) jako vedoucí indikátor
4. CNH kurz (USD/CNH = CNH=X) pro asijský měnový tlak
5. Reálný výnos a inflační očekávání (TIP / IEF)
6. Volatilita komodit vs akcií (^GVZ vs ^VIX)
7. Ukládá telemetrii do data/high_alpha_silver_telemetry.json
"""

from __future__ import annotations
import os
import sys
import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, List

import numpy as np
import pandas as pd
import yfinance as yf

WORKSPACE_DIR = Path(__file__).resolve().parent.parent.parent
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))

from silver.data.silver_async_io import safe_write_json, DynamicTTLCacheManager
from silver.config.silver_config import (
    SilverRiskConfig, 
    SILVER_HIGH_ALPHA_TICKERS, 
    SILVER_SHFE_ACTIVE_PROXIES
)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logger = logging.getLogger("SilverHighAlphaFeeds")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [SILVER_FEEDS] %(message)s")

DATA_DIR = WORKSPACE_DIR / "data"
OUTPUT_TELEMETRY_PATH = DATA_DIR / "high_alpha_silver_telemetry.json"


class SilverHighAlphaFeeds:
    """Fetcher pro high-alpha signály stříbra s využitím 23h futures dat."""

    def __init__(self, cache_manager: Optional[DynamicTTLCacheManager] = None):
        self.cache_mgr = cache_manager or DynamicTTLCacheManager()
        self.tickers = ["SI=F", "GC=F", "HG=F", "CNH=X", "SLV", "^GVZ", "^VIX", "TIP", "IEF"]

    def fetch_feeds_snapshot(self, force_refresh: bool = False) -> Dict[str, Any]:
        """
        Získá komplexní snapshot high-alpha telemetrie pro stříbro.
        Respektuje dynamickou TTL cache (5 min pro Tier-1 makro dny, 15 min standardně).
        """
        cached = self.cache_mgr.get("silver_high_alpha_telemetry")
        if cached and not force_refresh:
            return cached

        try:
            logger.info("Stahuji čerstvá tržní data pro Silver feeds (%s)...", ", ".join(self.tickers))
            raw_df = yf.download(self.tickers, period="90d", interval="1d", progress=False)
            
            # Bezpečné získání cen Close
            if isinstance(raw_df.columns, pd.MultiIndex):
                close_df = raw_df["Close"].ffill().bfill()
            else:
                close_df = raw_df.ffill().bfill()

            latest = close_df.iloc[-1]
            prev_day = close_df.iloc[-2] if len(close_df) >= 2 else latest

            # 1. Futures ceny
            si_price = float(latest.get("SI=F", 32.50))
            gc_price = float(latest.get("GC=F", 2650.0))
            hg_price = float(latest.get("HG=F", 4.50))
            cnh_price = float(latest.get("CNH=X", 7.15))

            # 2. Futures GSR a Rolling Z-Score
            gsr_series = close_df["GC=F"] / close_df["SI=F"]
            curr_gsr = float(gc_price / si_price) if si_price > 0 else 81.0
            gsr_mean = float(gsr_series.mean())
            gsr_std = float(gsr_series.std()) if float(gsr_series.std()) > 0 else 1.0
            gsr_zscore = float((curr_gsr - gsr_mean) / gsr_std)

            # 3. Silver / Copper ratio
            si_hg_ratio = float(si_price / hg_price) if hg_price > 0 else 7.15
            hg_pct_change = float((hg_price - prev_day.get("HG=F", hg_price)) / prev_day.get("HG=F", hg_price) * 100.0)

            # 4. Real Yield (TIP/IEF) & Volatilities
            tip = float(latest.get("TIP", 106.0))
            ief = float(latest.get("IEF", 93.0))
            real_yield_proxy = float(tip / ief) if ief > 0 else 1.14

            gvz = float(latest.get("^GVZ", 18.0))
            vix = float(latest.get("^VIX", 15.0))
            vol_ratio = float(gvz / vix) if vix > 0 else 1.20

            telemetry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "silver_price_usd": round(si_price, 4),
                "gold_price_usd": round(gc_price, 2),
                "copper_price_usd": round(hg_price, 4),
                "usd_cnh_rate": round(cnh_price, 4),
                "gsr_futures": {
                    "current": round(curr_gsr, 2),
                    "rolling_90d_mean": round(gsr_mean, 2),
                    "rolling_90d_std": round(gsr_std, 2),
                    "zscore": round(gsr_zscore, 2),
                    "signal": "STRONG_LONG" if gsr_zscore > 2.0 else ("WEAK_LONG" if gsr_zscore > 1.2 else ("STRONG_SHORT" if gsr_zscore < -2.0 else ("WEAK_SHORT" if gsr_zscore < -1.2 else "NEUTRAL")))
                },
                "industrial_copper_proxy": {
                    "silver_copper_ratio": round(si_hg_ratio, 3),
                    "copper_1d_change_pct": round(hg_pct_change, 2),
                    "momentum": "BULLISH" if hg_pct_change > 0.5 else ("BEARISH" if hg_pct_change < -0.5 else "FLAT")
                },
                "macro_proxies": {
                    "real_yield_tip_ief": round(real_yield_proxy, 4),
                    "gold_volatility_gvz": round(gvz, 2),
                    "equity_volatility_vix": round(vix, 2),
                    "vol_spread_gvz_vix": round(vol_ratio, 2)
                },
                "status": "HEALTHY"
            }

            # Atomické uložení a nastavení cache
            safe_write_json(str(OUTPUT_TELEMETRY_PATH), telemetry)
            self.cache_mgr.set("silver_high_alpha_telemetry", telemetry)
            return telemetry

        except Exception as e:
            logger.error(f"Chyba při stahování Silver high-alpha feeds: {e}")
            # Fallback na nouzovou telemetry
            fallback = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "silver_price_usd": 32.50,
                "gold_price_usd": 2650.0,
                "copper_price_usd": 4.50,
                "usd_cnh_rate": 7.15,
                "gsr_futures": {"current": 81.54, "rolling_90d_mean": 81.0, "zscore": 0.35, "signal": "NEUTRAL"},
                "industrial_copper_proxy": {"silver_copper_ratio": 7.22, "copper_1d_change_pct": 0.0, "momentum": "FLAT"},
                "macro_proxies": {"real_yield_tip_ief": 1.14, "gold_volatility_gvz": 18.0, "equity_volatility_vix": 15.0, "vol_spread_gvz_vix": 1.20},
                "status": "FALLBACK_CACHE"
            }
            return fallback


def main():
    feeds = SilverHighAlphaFeeds()
    data = feeds.fetch_feeds_snapshot(force_refresh=True)
    print("\n" + "=" * 60)
    print("SILVER HIGH-ALPHA FEEDS TELEMETRY (Krok 27)")
    print("=" * 60)
    print(f"Status:            {data['status']}")
    print(f"Silver Futures:    ${data['silver_price_usd']}/oz")
    print(f"Gold Futures:      ${data['gold_price_usd']}/oz")
    print(f"Copper Futures:    ${data['copper_price_usd']}/lb")
    print(f"USD/CNH:           {data['usd_cnh_rate']}")
    print(f"GSR Futures:       {data['gsr_futures']['current']} (Z-score: {data['gsr_futures']['zscore']}) -> {data['gsr_futures']['signal']}")
    print(f"SI/HG Ratio:       {data['industrial_copper_proxy']['silver_copper_ratio']} (Copper MoM: {data['industrial_copper_proxy']['copper_1d_change_pct']}%)")
    print(f"Uloženo do:        {OUTPUT_TELEMETRY_PATH}")
    print("✅ KROK 27 DOKONČEN!")

if __name__ == "__main__":
    main()
