"""
silver_correlation_monitor.py – Cross-Commodity Monitor & Gold/Silver Korelace
=============================================================================
KROK 40 v Silver Replication Roadmap v3.0

Počítá 20denní rolling korelaci mezi Zlatem (MGC / GC=F) a Stříbrem (SIL / SI=F).
Pravidlo řízení kombinovaného rizika:
Pokud je 20denní korelace Gold ↔ Silver > 0.85 a na zlatě je již otevřená pozice ve stejném směru,
snižuje se risk stříbra o 40 % (multiplier = 0.60), aby nedošlo k nechtěnému zdvojení sázky
na stejný makro faktor (dolar / sazby).
"""

from __future__ import annotations
import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import numpy as np
import pandas as pd

WORKSPACE_DIR = Path(__file__).resolve().parent.parent.parent
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))

from silver.data.silver_async_io import safe_write_json

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logger = logging.getLogger("SilverCorrelationMonitor")
OUTPUT_PATH = WORKSPACE_DIR / "data" / "silver_gold_correlation.json"


class SilverCorrelationMonitor:
    """Monitoruje korelaci mezi Gold a Silver a navrhuje redukci kombinovaného rizika."""

    CORRELATION_THRESHOLD: float = 0.85
    HIGH_CORRELATION_RISK_REDUCTION: float = 0.60  # Snížení na 60 % (o 40 %)

    def compute_rolling_correlation(
        self, 
        silver_returns: pd.Series, 
        gold_returns: pd.Series, 
        window: int = 20
    ) -> float:
        """Spočítá 20denní rolling korelaci denních výnosů."""
        if len(silver_returns) < window or len(gold_returns) < window:
            return 0.80  # Default konzervativní korelace
            
        combined = pd.concat([silver_returns, gold_returns], axis=1).dropna()
        corr_series = combined.iloc[:, 0].rolling(window).corr(combined.iloc[:, 1])
        last_corr = float(corr_series.iloc[-1])
        return round(float(np.clip(last_corr, -1.0, 1.0)), 3)

    def evaluate_cross_hedge_risk(
        self,
        current_correlation: float,
        is_gold_position_open: bool,
        gold_direction: str,
        silver_direction: str
    ) -> Tuple[float, str]:
        """
        Vyhodnotí, zda je nutné redukovat velikost pozice stříbra kvůli otevřenému obchodu na zlatě.
        """
        if not is_gold_position_open:
            return 1.0, "NO_GOLD_POSITION"

        # Pokud jsou ve stejném směru (např. obě LONG) a korelace je vysoká:
        same_direction = (gold_direction.upper() == silver_direction.upper())
        if same_direction and current_correlation >= self.CORRELATION_THRESHOLD:
            return self.HIGH_CORRELATION_RISK_REDUCTION, f"HIGH_CORRELATION_RISK_REDUCTION (Corr: {current_correlation} >= 0.85)"

        # Pokud jsou v opačném směru, jde o přirozený hedge (např. Long Silver vs Short Gold)
        if not same_direction and current_correlation >= self.CORRELATION_THRESHOLD:
            return 1.0, f"NATURAL_HEDGE_SPREAD (Long {silver_direction} vs Gold {gold_direction})"

        return 1.0, f"NORMAL_CORRELATION ({current_correlation})"


def main():
    monitor = SilverCorrelationMonitor()
    # Testovací výpočet
    mult, reason = monitor.evaluate_cross_hedge_risk(
        current_correlation=0.88,
        is_gold_position_open=True,
        gold_direction="LONG",
        silver_direction="LONG"
    )
    print("\n" + "=" * 60)
    print("SILVER/GOLD CORRELATION & CROSS-HEDGE (Krok 40)")
    print("=" * 60)
    print(f"Korelace:             0.88 (Prahová hodnota: 0.85)")
    print(f"Stav:                 Otevřen Gold LONG i Silver LONG")
    print(f"Sizing multiplikátor: {mult * 100}% pozice")
    print(f"Důvod:                {reason}")
    print("✅ KROK 40 DOKONČEN!")

if __name__ == "__main__":
    main()
