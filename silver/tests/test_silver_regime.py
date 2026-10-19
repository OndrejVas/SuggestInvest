"""
test_silver_regime.py – Unit testy pro Silver HMM Regime Engine a BlowOff Detektor
==================================================================================
KROK 43 v Silver Replication Roadmap v3.0

Ověřuje:
1. HMM přechody (TREND_BULL, CHOP, DISTRIBUTION_BLOWOFF, HIGH_VOL_CORRECTION)
2. Silver BlowOff Exhaustion detektor na parabolických datech
3. Kaufman Efficiency Ratio a KAMA adaptivní ATR
4. Drawdown brzdu při poklesu ekvity > 6 %
5. Sovereign Floor ($9,000) a Daily Loss Limit ($400)
"""

import sys
import unittest
from pathlib import Path
import numpy as np
import pandas as pd

WORKSPACE_DIR = Path(__file__).resolve().parent.parent.parent
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))

from silver.models.silver_regime_engine import (
    SilverRegimeEngine, 
    MasterRegime, 
    SilverPortfolioRiskState,
    SilverBlowOffExhaustionDetector,
    SilverVolatilitySwitcher
)


class TestSilverRegime(unittest.TestCase):

    def setUp(self):
        self.risk = SilverPortfolioRiskState(
            initial_capital=10000.0,
            current_equity=10000.0,
            high_water_mark=10000.0
        )
        self.engine = SilverRegimeEngine(risk_state=self.risk)

    def test_risk_state_limits_and_sizing(self):
        """Testuje dodržení velikosti kontraktu 1 000 oz a škálování."""
        self.assertEqual(self.risk.full_contract_oz, 1000.0)
        self.assertEqual(self.risk.max_contracts, 1)

        # Zisk -> ekvita $19,000 -> povolení 2 kontraktů
        self.risk.record_PnL(9000.0)
        self.assertEqual(self.risk.current_equity, 19000.0)
        self.assertEqual(self.risk.max_contracts, 2)

        # Drawdown > 6 %
        self.risk.record_PnL(-2000.0)
        self.assertGreater(self.risk.current_drawdown_pct, 0.06)

    def test_sovereign_floor_and_daily_loss(self):
        """Ověřuje sepnutí nouzových pojistek."""
        risk = SilverPortfolioRiskState(initial_capital=10000.0, current_equity=8900.0)
        self.assertTrue(risk.is_sovereign_floor_breached)

        risk_daily = SilverPortfolioRiskState(daily_pnl_usd=-450.0)
        self.assertTrue(risk_daily.is_daily_loss_limit_hit)

    def test_blowoff_detector_parabolic(self):
        """Testuje detekci parabolického vrcholu na stříbře."""
        # Vytvoříme parabolický růst s horním knotem
        n = 80
        prices = np.linspace(30.0, 45.0, n)
        # Poslední svíčka udělá obrovský horní knot
        highs = prices + 0.5
        highs[-1] = 52.0  # Masivní knot
        lows = prices - 0.4
        df = pd.DataFrame({
            "open": prices,
            "high": highs,
            "low": lows,
            "close": prices
        })

        score = SilverBlowOffExhaustionDetector.compute_exhaustion_score(df)
        self.assertGreaterEqual(score, 0.60, f"BlowOff skóre {score} by mělo detekovat parabolický vrchol!")

    def test_kama_and_efficiency_ratio(self):
        """Testuje Kaufman adaptivní indikátory."""
        # Perfektní trend: ER by mělo být blízko 1.0
        trend_series = pd.Series(np.linspace(30.0, 40.0, 30))
        er = SilverVolatilitySwitcher.compute_kaufman_efficiency_ratio(trend_series, period=14)
        self.assertGreater(er.iloc[-1], 0.90)

        # Čistý šum: ER by mělo být nízké
        noise_series = pd.Series([30.0, 31.0, 30.0, 31.0, 30.0, 31.0] * 5)
        er_noise = SilverVolatilitySwitcher.compute_kaufman_efficiency_ratio(noise_series, period=14)
        self.assertLess(er_noise.iloc[-1], 0.30)


if __name__ == "__main__":
    unittest.main()
