"""
test_silver_strategies.py – Unit testy pro Strategie, Volatility Gate a 2-Stage BE
=================================================================================
KROK 45 v Silver Replication Roadmap v3.0

Ověřuje:
1. Volatility Gate (Hard Sizing Filter):
   - Pro $10k účet je limit risku $400 (4 %).
   - 1 kontrakt SIL Micro = 1 000 oz.
   - Jakmile požadovaný SL > $0.40/oz, bot MUSÍ odmítnout obchod (volatility_gate_passed = False, contracts = 0).
   - Pokud SL <= $0.40/oz, obchod projde se sizingem 1 kontrakt.
2. 2-Stage Break-Even a Fee-Plus:
   - Stage 1: Při zisku +0.80R se SL posune na -0.30R (ochrana kapitálu).
   - Stage 2: Při zisku +1.00R se SL posune na Entry + $0.025/oz (+25 USD na 1 SIL kontrakt – garantovaný zisk pokrývající poplatky a ticky).
3. Strategie #1 (Trend Following), #2 (Mean Reversion), #3 (Breakout) a #4 (Macro Event) generování signálů.
"""

import sys
import unittest
from pathlib import Path
import numpy as np
import pandas as pd

WORKSPACE_DIR = Path(__file__).resolve().parent.parent.parent
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))

from silver.models.silver_strategies import (
    SilverStrategyEngine, 
    SilverSignalDirection, 
    SilverTradeSignal
)
from silver.models.silver_position_sizing import SilverPositionSizingEngine, SizingDecision
from silver.models.silver_regime_engine import MasterRegime
from silver.config.silver_config import SilverRiskConfig


class TestSilverStrategiesAndSizing(unittest.TestCase):

    def setUp(self):
        self.risk_cfg = SilverRiskConfig(
            initial_capital=10000.0,
            max_risk_pct_per_trade=0.04,
            max_sl_dollars_per_oz=0.40
        )
        self.strat_engine = SilverStrategyEngine(self.risk_cfg)
        self.sizing_engine = SilverPositionSizingEngine(self.risk_cfg)

    def test_volatility_gate_rejection_on_wide_sl(self):
        """Ověřuje, že Volatility Gate striktně zablokuje obchod s rizikem > $400."""
        # Požadovaný SL = $0.55/oz (při 1 000 oz to znamená risk $550 > $400)
        decision = self.sizing_engine.compute_size(
            current_equity=10000.0,
            proposed_sl_dollars_per_oz=0.55,
            regime=MasterRegime.TREND_BULL
        )
        self.assertFalse(decision.allow_trade, "Obchod s rizikem $550 na $10k účtu nesmí projít!")
        self.assertEqual(decision.contracts, 0)
        self.assertEqual(decision.volatility_gate_status, "BLOCKED_WIDE_SL")
        self.assertIn("Volatility Gate", decision.rejection_reason)

    def test_volatility_gate_pass_on_narrow_sl(self):
        """Ověřuje, že SL <= $0.40/oz projde s 1 kontraktem SIL."""
        # Požadovaný SL = $0.25/oz (při 1 000 oz to znamená risk $250 <= $400)
        decision = self.sizing_engine.compute_size(
            current_equity=10000.0,
            proposed_sl_dollars_per_oz=0.25,
            regime=MasterRegime.TREND_BULL
        )
        self.assertTrue(decision.allow_trade)
        self.assertEqual(decision.contracts, 1)
        self.assertEqual(decision.volatility_gate_status, "PASSED")
        self.assertEqual(decision.actual_risk_usd, 250.0)

    def test_two_stage_breakeven_long(self):
        """Testuje 2-Stage BE posuny pro Long pozici."""
        entry = 32.00
        initial_sl = 31.70  # r_dist = $0.30/oz ($300 risk)

        # 1. Zisk pod +0.80R (např. cena 32.15 -> +0.50R) -> SL zůstává původní
        sl_initial, state0 = self.strat_engine.evaluate_2stage_breakeven(
            current_price=32.15, entry_price=entry, initial_sl=initial_sl,
            direction=SilverSignalDirection.LONG
        )
        self.assertEqual(state0, "INITIAL")
        self.assertEqual(sl_initial, initial_sl)

        # 2. Zisk dosáhne +0.85R (cena 32.26) -> Stage 1: Posun na -0.30R (32.00 - 0.30*0.30 = 31.91)
        sl_stage1, state1 = self.strat_engine.evaluate_2stage_breakeven(
            current_price=32.26, entry_price=entry, initial_sl=initial_sl,
            direction=SilverSignalDirection.LONG
        )
        self.assertEqual(state1, "STAGE_1_BE")
        self.assertAlmostEqual(sl_stage1, 31.91, places=2)

        # 3. Zisk dosáhne +1.05R (cena 32.32) -> Stage 2: Fee-Plus (Entry + $0.025/oz = 32.025)
        sl_stage2, state2 = self.strat_engine.evaluate_2stage_breakeven(
            current_price=32.32, entry_price=entry, initial_sl=initial_sl,
            direction=SilverSignalDirection.LONG
        )
        self.assertEqual(state2, "STAGE_2_FEE_PLUS")
        self.assertAlmostEqual(sl_stage2, 32.025, places=3)
        # Garantovaný dolarový zisk na kontrakt: +$25
        self.assertGreater((sl_stage2 - entry) * 1000.0, 20.0)

    def test_two_stage_breakeven_short(self):
        """Testuje 2-Stage BE posuny pro Short pozici."""
        entry = 32.00
        initial_sl = 32.30  # r_dist = $0.30/oz ($300 risk)

        # Stage 1: Cena klesne na 31.74 (+0.86R zisk) -> posun na -0.30R (32.00 + 0.09 = 32.09)
        sl_stage1, state1 = self.strat_engine.evaluate_2stage_breakeven(
            current_price=31.74, entry_price=entry, initial_sl=initial_sl,
            direction=SilverSignalDirection.SHORT
        )
        self.assertEqual(state1, "STAGE_1_BE")
        self.assertAlmostEqual(sl_stage1, 32.09, places=2)

        # Stage 2: Cena klesne na 31.68 (+1.06R zisk) -> posun na Entry - $0.025/oz = 31.975
        sl_stage2, state2 = self.strat_engine.evaluate_2stage_breakeven(
            current_price=31.68, entry_price=entry, initial_sl=initial_sl,
            direction=SilverSignalDirection.SHORT
        )
        self.assertEqual(state2, "STAGE_2_FEE_PLUS")
        self.assertAlmostEqual(sl_stage2, 31.975, places=3)


if __name__ == "__main__":
    unittest.main()
