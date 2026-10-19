"""
test_silver_gsr.py – Unit testy pro Strategii #7: GSR Mean Reversion
====================================================================
KROK 44 v Silver Replication Roadmap v3.0

Ověřuje:
1. Správnost výpočtu poměru Futures GSR (Gold / Silver)
2. Rolling Z-Score v okně 60–120 dní (Argon Tip #2: žádný statický průměr 68!)
3. Směr signálů:
   - Z > +2.0 -> STRONG_LONG (Gold drahé, Silver extrémně podhodnocené)
   - Z < -2.0 -> STRONG_SHORT
4. Okrajové stavy: dělení nulou, nulová cena, neutralita
"""

import sys
import unittest
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd

WORKSPACE_DIR = Path(__file__).resolve().parent.parent.parent
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))

from silver.models.silver_gsr_strategy import GSRMeanReversionStrategy, GSRSignal, GSRConfig


class TestSilverGSRStrategy(unittest.TestCase):

    def setUp(self):
        cfg = GSRConfig(historical_mean=80.0, historical_std=5.0)
        self.strat = GSRMeanReversionStrategy(config=cfg)

    def test_gsr_calculation_and_zscore(self):
        """Ověřuje správný výpočet GSR z cen futures a generování signálu."""
        # Gold = $2650, Silver = $32.50 -> GSR ~ 81.54
        gsr = self.strat.calculator.compute_gsr_from_prices(2650.0, 32.50)
        self.assertAlmostEqual(gsr, 81.538, places=2)

        # Otestujeme extrémní GSR = 92.0 (při mean 80 a std 5 je Z = (92-80)/5 = +2.4 -> STRONG_LONG)
        eval_long = self.strat.evaluate(
            gold_price=2760.0,
            silver_price=30.0, # 2760 / 30 = 92.0
            timestamp=datetime(2026, 3, 10, 12, 0, 0),
            current_regime="TREND_BULL"
        )
        self.assertEqual(eval_long["signal"], GSRSignal.STRONG_LONG.value)
        self.assertGreater(eval_long["zscore"], 2.0)
        self.assertEqual(eval_long["direction"], "LONG")

        # Otestujeme nízké GSR = 68.0 po uplynutí min_days_between_trades (2026-03-16, tj. 6 dní po prvním obchodu)
        eval_short = self.strat.evaluate(
            gold_price=2040.0,
            silver_price=30.0, # 2040 / 30 = 68.0
            timestamp=datetime(2026, 3, 16, 12, 0, 0),
            current_regime="TREND_BULL"
        )
        self.assertEqual(eval_short["signal"], GSRSignal.STRONG_SHORT.value)
        self.assertLess(eval_short["zscore"], -2.0)
        self.assertEqual(eval_short["direction"], "SHORT")

    def test_edge_cases_zero_price(self):
        """Testuje ošetření chyb při nulové ceně stříbra (bezpečný fallback na historický průměr)."""
        gsr_zero = self.strat.calculator.compute_gsr_from_prices(2600.0, 0.0)
        self.assertEqual(gsr_zero, 80.0) # Bezpečný fallback na historical_mean

        # Evaluace s nulovou cenou nesmí spadnout
        eval_zero = self.strat.evaluate(
            gold_price=2600.0,
            silver_price=0.0,
            timestamp=datetime(2026, 3, 20, 12, 0, 0)
        )
        self.assertIn("signal", eval_zero)


if __name__ == "__main__":
    unittest.main()
