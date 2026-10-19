"""
silver_macro_bridge.py – Cross-Asset Macro Bridge pro SilverEdge v1.0
====================================================================
KROK 31 v Silver Replication Roadmap v3.0

Převádí makroekonomická data, industriální metriky a cross-market telemetrii
na kvantitativní makro skóre pro stříbro.

Kalibrované váhy pro Silver (na rozdíl od Gold zohledňuje 55% industriální charakter):
1. real_yield_spike:        -0.40  (Růst reálných výnosů = silný medvědí tlak)
2. gold_silver_ratio_high:  +0.35  (Vysoké GSR = extrémně podhodnocené stříbro vůči zlatu)
3. china_pmi_weak:          -0.30  (Slabý čínský průmysl = pokles asijské poptávky)
4. ism_manufacturing_weak:  -0.25  (Americký výrobní pokles = průmyslový útlum)
5. solar_copper_spike:      +0.20  (Růst mědi a solární fotovoltaiky = silný impuls)
6. india_festival_demand:   +0.10  (Sezónní nákupy šperků a stříbrných slitků v Indii)
"""

from __future__ import annotations
import os
import sys
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

import numpy as np

WORKSPACE_DIR = Path(__file__).resolve().parent.parent.parent
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))

from silver.data.silver_async_io import safe_write_json, DynamicTTLCacheManager

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logger = logging.getLogger("SilverMacroBridge")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [SILVER_MACRO] %(message)s")

OUTPUT_PATH = WORKSPACE_DIR / "data" / "silver_macro_state.json"


@dataclass
class SilverMacroScore:
    """Výsledné makro skóre a sizing multiplikátory pro stříbro."""
    composite_score: float             # [-1.0, +1.0]
    direction_bias: str                # BULLISH, BEARISH, NEUTRAL
    sizing_multiplier: float           # 0.50 až 1.25
    allow_long: bool
    allow_short: bool
    components: Dict[str, float]
    updated_at: str


class SilverMacroBridge:
    """Integrační můstek spojující všechny makro a fundamentální toky pro stříbro."""

    # Kalibrované váhy podle Argon Roadmap v3.0
    WEIGHTS = {
        "real_yield": -0.40,
        "gsr_reversion": +0.35,
        "china_pmi": -0.30,
        "ism_manufacturing": -0.25,
        "solar_copper": +0.20,
        "india_demand": +0.10
    }

    def __init__(self, cache_mgr: Optional[DynamicTTLCacheManager] = None):
        self.cache_mgr = cache_mgr or DynamicTTLCacheManager()

    def compute_macro_score(
        self,
        real_yield_change_pct: float = 0.0,
        gsr_zscore: float = 0.0,
        china_caixin_pmi: float = 50.5,
        us_ism_pmi: float = 49.8,
        solar_copper_score: float = 0.0,
        is_india_festival_season: bool = False
    ) -> SilverMacroScore:
        """
        Kalkuluje kompozitní makro skóre pro stříbro.
        """
        # 1. Real Yield komponenta (růst TIP/IEF výnosu je pro drahé kovy negativní)
        c_real_yield = np.clip(-real_yield_change_pct / 2.0, -1.0, 1.0)

        # 2. GSR Z-score komponenta (Z > 0 znamená vysoké GSR -> Long bias pro Silver)
        c_gsr = np.clip(gsr_zscore / 2.0, -1.0, 1.0)

        # 3. China Caixin PMI (50.0 je hranice expanze/kontrakce)
        c_china_pmi = np.clip((china_caixin_pmi - 50.0) / 3.0, -1.0, 1.0)

        # 4. US ISM PMI (50.0 je hranice)
        c_ism = np.clip((us_ism_pmi - 50.0) / 4.0, -1.0, 1.0)

        # 5. Solar & Copper proxy score
        c_solar_copper = np.clip(solar_copper_score, -1.0, 1.0)

        # 6. India demand
        c_india = 1.0 if is_india_festival_season else 0.0

        # Vážený součet
        score = (
            self.WEIGHTS["real_yield"] * (-c_real_yield) +
            self.WEIGHTS["gsr_reversion"] * c_gsr +
            self.WEIGHTS["china_pmi"] * (-c_china_pmi) +  # china_pmi_weak váha je -0.30
            self.WEIGHTS["ism_manufacturing"] * (-c_ism) + # ism_manufacturing_weak váha je -0.25
            self.WEIGHTS["solar_copper"] * c_solar_copper +
            self.WEIGHTS["india_demand"] * c_india
        )

        composite = float(round(np.clip(score, -1.0, 1.0), 3))

        # Sizing multiplikátor a směrový bias
        if composite > 0.40:
            bias = "STRONG_BULLISH"
            sizing = 1.20
            allow_long, allow_short = True, False
        elif composite > 0.15:
            bias = "MODERATE_BULLISH"
            sizing = 1.00
            allow_long, allow_short = True, True
        elif composite < -0.40:
            bias = "STRONG_BEARISH"
            sizing = 1.20
            allow_long, allow_short = False, True
        elif composite < -0.15:
            bias = "MODERATE_BEARISH"
            sizing = 1.00
            allow_long, allow_short = True, True
        else:
            bias = "NEUTRAL"
            sizing = 0.85
            allow_long, allow_short = True, True

        components = {
            "real_yield": round(float(c_real_yield), 3),
            "gsr_reversion": round(float(c_gsr), 3),
            "china_pmi": round(float(c_china_pmi), 3),
            "ism_manufacturing": round(float(c_ism), 3),
            "solar_copper": round(float(c_solar_copper), 3),
            "india_demand": round(float(c_india), 3)
        }

        result = SilverMacroScore(
            composite_score=composite,
            direction_bias=bias,
            sizing_multiplier=sizing,
            allow_long=allow_long,
            allow_short=allow_short,
            components=components,
            updated_at=datetime.now(timezone.utc).isoformat()
        )

        safe_write_json(str(OUTPUT_PATH), {
            "composite_score": result.composite_score,
            "direction_bias": result.direction_bias,
            "sizing_multiplier": result.sizing_multiplier,
            "allow_long": result.allow_long,
            "allow_short": result.allow_short,
            "components": result.components,
            "updated_at": result.updated_at
        })
        return result


def main():
    bridge = SilverMacroBridge()
    # Test se simulovanými tržními podmínkami
    score = bridge.compute_macro_score(
        real_yield_change_pct=0.2,
        gsr_zscore=1.85,
        china_caixin_pmi=51.2,
        us_ism_pmi=48.5,
        solar_copper_score=0.35,
        is_india_festival_season=True
    )
    print("\n" + "=" * 60)
    print("SILVER MACRO BRIDGE EVALUATION (Krok 31)")
    print("=" * 60)
    print(f"Kompozitní makro skóre: {score.composite_score} ({score.direction_bias})")
    print(f"Sizing multiplikátor:   {score.sizing_multiplier}×")
    print(f"Povoleno LONG:          {score.allow_long}")
    print(f"Povoleno SHORT:         {score.allow_short}")
    print("Komponenty:")
    for k, v in score.components.items():
        print(f"  - {k:20s}: {v}")
    print(f"Uloženo do:             {OUTPUT_PATH}")
    print("✅ KROK 31 DOKONČEN!")

if __name__ == "__main__":
    main()
