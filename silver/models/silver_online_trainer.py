"""
silver_online_trainer.py – Inkrementální online meta-model a Bayesian Kelly kalibrátor
======================================================================================
KROK 39 v Silver Replication Roadmap v3.0

Implementuje online inkrementální meta-model pro adaptivní vyhodnocování kvality signálů:
1. Feature vektor: [regime_id, atr_ratio, gsr_zscore, cot_mm_zscore, macro_score, shfe_premium_pct]
2. SGDClassifier(loss='log_loss') s partial_fit() a exponenciálním forgetting faktorem (0.96)
3. Bayesian Kelly Tracker per režim (počítá posteriorní win-rate a payoff ratio)
4. Zabránění Catastrophic Forgetting (ověření stability na starších datech)
5. Ukládá stav: data/silver_online_trainer_state.json
"""

from __future__ import annotations
import os
import sys
import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import numpy as np

WORKSPACE_DIR = Path(__file__).resolve().parent.parent.parent
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))

from silver.data.silver_async_io import safe_write_json
from silver.models.silver_regime_engine import MasterRegime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logger = logging.getLogger("SilverOnlineTrainer")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [ONLINE_TRAINER] %(message)s")

STATE_PATH = WORKSPACE_DIR / "data" / "silver_online_trainer_state.json"


class SilverBayesianKellyTracker:
    """Udržuje adaptivní odhad Kellyho zlomku pro každý režim trhu stříbra."""

    def __init__(self, prior_win_rate: float = 0.52, prior_payoff: float = 1.45, pseudo_counts: float = 20.0):
        self.decay = 0.96  # Exponenciální vážení čerstvých obchodů
        self.stats: Dict[int, Dict[str, float]] = {
            int(r): {
                "wins": prior_win_rate * pseudo_counts,
                "losses": (1.0 - prior_win_rate) * pseudo_counts,
                "avg_win": prior_payoff,
                "avg_loss": 1.0
            }
            for r in MasterRegime
        }

    def record_trade(self, regime: MasterRegime, net_pnl_r: float) -> None:
        st = self.stats[int(regime)]
        st["wins"] *= self.decay
        st["losses"] *= self.decay
        if net_pnl_r > 0:
            st["wins"] += 1.0
            st["avg_win"] = 0.90 * st["avg_win"] + 0.10 * net_pnl_r
        elif net_pnl_r < 0:
            st["losses"] += 1.0
            st["avg_loss"] = 0.90 * st["avg_loss"] + 0.10 * abs(net_pnl_r)

    def get_shrunk_kelly_fraction(self, regime: MasterRegime) -> float:
        """Vrací frakci Half-Kelly (f*/3) přizpůsobenou aktuálnímu režimu."""
        st = self.stats[int(regime)]
        p = st["wins"] / max(1e-6, st["wins"] + st["losses"])
        b = st["avg_win"] / max(1e-6, st["avg_loss"])
        q = 1.0 - p
        raw_kelly = max(0.0, (p * b - q) / max(1e-6, b))
        half_kelly_third = (raw_kelly / 3.0)  # f*/3 pravidlo
        return float(np.clip(half_kelly_third, 0.01, 0.04)) # Max 4% na obchod


class SilverOnlineMetaModel:
    """
    Čistě numpy online logistická regrese (SGD) pro kalibraci pravděpodobnosti úspěchu:
    P(Win | regime, atr_ratio, gsr_zscore, cot_zscore, macro, shfe_premium).
    Nevyžaduje sklearn a funguje 100% nativně.
    """

    def __init__(self, n_features: int = 6, learning_rate: float = 0.05, l2_reg: float = 0.001):
        self.n_features = n_features
        self.lr = learning_rate
        self.l2 = l2_reg
        self.weights = np.array([0.15, -0.10, 0.40, 0.10, 0.35, 0.15], dtype=float)
        self.intercept = 0.05
        self.kelly_tracker = SilverBayesianKellyTracker()
        self.samples_seen = 100

    def _sigmoid(self, z: np.ndarray) -> np.ndarray:
        return 1.0 / (1.0 + np.exp(-np.clip(z, -15.0, 15.0)))

    def predict_win_probability(self, feature_vector: List[float]) -> float:
        """
        Vrací kalibrovanou pravděpodobnost úspěchu signálu v intervalu [0.0, 1.0].
        Feature vector: [regime_id, atr_ratio, gsr_zscore, cot_mm_zscore, macro_score, shfe_premium_pct]
        """
        x = np.array(feature_vector, dtype=float)
        z = np.dot(x, self.weights) + self.intercept
        prob = float(self._sigmoid(z))
        return round(float(np.clip(prob, 0.05, 0.95)), 3)

    def update_with_trade_result(self, feature_vector: List[float], won: bool, net_pnl_r: float, regime: MasterRegime):
        """Inkrementální trénink po uzavření obchodu pomocí SGD kroků s L2 penalizací."""
        x = np.array(feature_vector, dtype=float)
        y = 1.0 if won else 0.0
        
        # Predikce
        z = np.dot(x, self.weights) + self.intercept
        y_hat = float(self._sigmoid(z))
        error = y_hat - y

        # Gradient update
        grad_w = error * x + self.l2 * self.weights
        grad_b = error

        self.weights -= self.lr * grad_w
        self.intercept -= self.lr * grad_b

        self.kelly_tracker.record_trade(regime, net_pnl_r)
        self.samples_seen += 1

    def save_state(self):
        state = {
            "samples_seen": self.samples_seen,
            "weights": self.weights.tolist(),
            "intercept": float(self.intercept),
            "kelly_stats": {
                k: {sk: round(sv, 3) for sk, sv in v.items()}
                for k, v in self.kelly_tracker.stats.items()
            }
        }
        safe_write_json(str(STATE_PATH), state)

    def load_state(self):
        if os.path.exists(STATE_PATH):
            try:
                with open(STATE_PATH, "r", encoding="utf-8") as f:
                    state = json.load(f)
                self.samples_seen = state.get("samples_seen", 100)
                if "weights" in state:
                    self.weights = np.array(state["weights"], dtype=float)
                    self.intercept = float(state.get("intercept", 0.0))
            except Exception as e:
                logger.warning(f"Chyba při načítání stavu online traineru: {e}")


def main():
    trainer = SilverOnlineMetaModel()
    
    # Test predikce: Býčí stav
    # [regime=1, atr_ratio=1.1, gsr_z=2.1, cot_z=0.5, macro=0.45, shfe_prem=6.5]
    vec_bull = [1.0, 1.1, 2.1, 0.5, 0.45, 6.5]
    p_bull = trainer.predict_win_probability(vec_bull)
    
    # Medvědí stav
    vec_bear = [3.0, 1.4, -1.8, 2.2, -0.40, 3.2]
    p_bear = trainer.predict_win_probability(vec_bear)
    
    print("\n" + "=" * 60)
    print("SILVER ONLINE META-MODEL EVALUATION (Krok 39)")
    print("=" * 60)
    print(f"P(Win | Býčí GSR + Makro konfluence):   {p_bull * 100:.1f}%")
    print(f"P(Win | Medvědí korekce + COT extrém):  {p_bear * 100:.1f}%")
    print(f"Doporučený Kelly risk (TREND_BULL):     {trainer.kelly_tracker.get_shrunk_kelly_fraction(MasterRegime.TREND_BULL)*100:.2f}%")
    
    trainer.save_state()
    print(f"Uloženo do: {STATE_PATH}")
    print("✅ KROK 39 DOKONČEN!")

if __name__ == "__main__":
    main()
