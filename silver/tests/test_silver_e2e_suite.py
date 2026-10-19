"""
test_silver_e2e_suite.py – End-to-End ověřovací testovací sada SilverEdge V3.0
=============================================================================
Prověřuje:
1. Integritu databáze silver_m1_history.db a rozdělení In-Sample / OOS 2026.
2. Správce uzamčení 2026 (Zero Look-Ahead Bias, 0/10 odemčeno).
3. Hard Volatility Gate ($0.40/oz max stop-loss) a Sizing (max 1 kontrakt na $10k účtu).
4. 2-Stage Break-Even logiku (+0.80R a +1.00R posun).
5. Portfolio Synergy 70% Gold / 30% Silver kalkulátor.
6. Funkčnost HTTP API endpointů na portu 8000.
"""
import os
import sys
import json
import sqlite3
import unittest
import urllib.request

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from silver.config.silver_config import SilverRiskConfig
from silver.models.silver_regime_engine import MasterRegime
from silver.models.silver_position_sizing import SilverPositionSizingEngine
from silver.models.silver_strategies import SilverStrategyEngine, SilverSignalDirection
from silver_walkforward_manager import build_or_refresh_manifest, MANIFEST_PATH
from silver.backtest.silver_portfolio_synergy import calculate_synergy


class TestSilverE2ESuite(unittest.TestCase):

    def test_01_database_and_manifest_integrity(self):
        """Ověření, že databáze obsahuje data a rok 2026 je striktně uzamčen."""
        manifest = build_or_refresh_manifest(force_relock=False)
        self.assertIn("asset", manifest)
        self.assertIn("in_sample_baseline", manifest)
        self.assertIn("out_of_sample_2026", manifest)

        ins = manifest["in_sample_baseline"]
        self.assertGreater(ins["bars_count"], 1_400_000, "In-sample musí mít > 1.4M svíček")

        oos = manifest["out_of_sample_2026"]
        self.assertEqual(len(oos["months"]), 10, "Rok 2026 musí mít 10 měsíců")
        # Všechny měsíce musí být uzamčeny před testováním
        locked_cnt = sum(1 for m in oos["months"] if m["status"] == "LOCKED")
        self.assertEqual(locked_cnt, 10, "Všech 10 měsíců roku 2026 musí být na startu UZAMČENO!")

    def test_02_volatility_gate_and_sizing(self):
        """Ověření Argon Tip #1: 1 SIL = 1000 oz, max 1 kontrakt na $10k, stop-loss limit $0.40/oz."""
        sizing = SilverPositionSizingEngine()
        
        # Normální SL ($0.20/oz = $200 risk) -> Povoleno 1 kontrakt
        dec1 = sizing.compute_size(
            current_equity=10000.0,
            proposed_sl_dollars_per_oz=0.20,
            regime=MasterRegime.TREND_BULL
        )
        self.assertTrue(dec1.allow_trade)
        self.assertEqual(dec1.contracts, 1)

        # Příliš široký SL ($0.55/oz = $550 risk > $0.40) -> Volatility Gate BLOKUJE
        dec2 = sizing.compute_size(
            current_equity=10000.0,
            proposed_sl_dollars_per_oz=0.55,
            regime=MasterRegime.TREND_BULL
        )
        self.assertFalse(dec2.allow_trade)
        self.assertEqual(dec2.contracts, 0)
        self.assertEqual(dec2.volatility_gate_status, "BLOCKED_WIDE_SL")

        # Účet $10k nesmí mít 2 kontrakty SIL (nominál $65k = 6.5x páka)
        dec3 = sizing.compute_size(
            current_equity=10000.0,
            proposed_sl_dollars_per_oz=0.10,
            regime=MasterRegime.TREND_BULL
        )
        self.assertLessEqual(dec3.contracts, 1, "Účet $10,000 nesmí otevřít více než 1 kontrakt SIL!")

    def test_03_two_stage_breakeven(self):
        """Ověření 2-Stage BE: +0.80R -> -0.30R, +1.00R -> +$0.025/oz Fee-Plus."""
        engine = SilverStrategyEngine()
        entry = 30.00
        initial_sl = 29.80 # R = 0.20
        direction = SilverSignalDirection.LONG

        # 1. Cena stoupne o +0.50R (30.10) -> INITIAL
        sl_a, stage_a = engine.evaluate_2stage_breakeven(30.10, entry, initial_sl, direction)
        self.assertEqual(stage_a, "INITIAL")
        self.assertEqual(sl_a, initial_sl)

        # 2. Cena stoupne o +0.85R (30.17) -> STAGE_1_BE (-0.30R od vstupu = 29.94)
        sl_b, stage_b = engine.evaluate_2stage_breakeven(30.17, entry, initial_sl, direction)
        self.assertEqual(stage_b, "STAGE_1_BE")
        self.assertAlmostEqual(sl_b, 29.94, places=2)

        # 3. Cena stoupne o +1.05R (30.21) -> STAGE_2_FEE_PLUS (+0.025 nad vstup = 30.025)
        sl_c, stage_c = engine.evaluate_2stage_breakeven(30.21, entry, initial_sl, direction)
        self.assertEqual(stage_c, "STAGE_2_FEE_PLUS")
        self.assertAlmostEqual(sl_c, 30.025, places=3)

    def test_04_portfolio_synergy_70_30(self):
        """Ověření výpočtu synergie 70% Gold / 30% Silver."""
        synergy = calculate_synergy()
        self.assertIn("performance_comparison", synergy)
        port = synergy["performance_comparison"]["combined_portfolio_70_30"]
        self.assertGreater(port["sharpe_ratio"], 2.0, "Kombinované Sharpe musí být > 2.0")
        self.assertLess(port["max_drawdown_pct"], 5.0, "Kombinovaný Max DD musí být < 5.0%")

    def test_05_http_server_api_endpoints(self):
        """Ověření, že HTTP server naslouchá na portu 8000 a vrací správná data pro Silver."""
        endpoints = [
            ("http://127.0.0.1:8000/api/silver/walkforward-manifest", "manifest"),
            ("http://127.0.0.1:8000/api/silver/telemetry", "telemetry"),
            ("http://127.0.0.1:8000/api/silver/state", "state"),
            ("http://127.0.0.1:8000/api/silver/comparison", "comparison")
        ]

        for url, expected_key in endpoints:
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    self.assertEqual(resp.status, 200)
                    body = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(body.get("ok"), f"Endpoint {url} nevrátil ok=true")
                    self.assertIn(expected_key, body, f"Klíč {expected_key} chybí v {url}")
            except Exception as e:
                self.fail(f"Selhalo volání {url}: {e}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
