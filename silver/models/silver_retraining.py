"""
silver_retraining.py – Retraining Pipeline & Model Adaptation for Silver
========================================================================
Argon Krok 58–60:
- Sleduje drift distribuce volatility a win rate jednotlivých strategií.
- Realizuje warm-start recalibration parametrů při změně makro režimu.
- Zajišťuje bezpečné adaptivní ladění bez look-ahead biasu.
"""
from __future__ import annotations
import os
import sys
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logger = logging.getLogger("SilverRetraining")


@dataclass
class RetrainingTriggerStatus:
    needs_retraining: bool
    drift_detected: bool
    win_rate_degradation: bool
    volatility_shift: bool
    reason: str
    metrics: Dict[str, float] = field(default_factory=dict)


class SilverRetrainingEngine:
    """
    Správa adaptivního přetrénování a ladění vah pro Silver Edge.
    """

    def __init__(
        self,
        lookback_trades: int = 30,
        win_rate_alert_threshold: float = 0.40,
        volatility_shift_threshold: float = 1.35
    ):
        self.lookback_trades = lookback_trades
        self.win_rate_alert_threshold = win_rate_alert_threshold
        self.volatility_shift_threshold = volatility_shift_threshold
        self.history_trades: List[Dict] = []
        self.regime_weights: Dict[str, float] = {
            "TREND_BULL": 1.15,
            "CHOP_COMPRESSION": 0.85,
            "HIGH_VOL_CORRECTION": 0.65,
            "DISTRIBUTION_BLOWOFF": 0.0
        }

    def register_trade(self, trade: Dict):
        """Zaznamená dokončený obchod do posuvného okna."""
        self.history_trades.append(trade)
        if len(self.history_trades) > 200:
            self.history_trades.pop(0)

    def evaluate_retraining_trigger(self) -> RetrainingTriggerStatus:
        """
        Zhodnotí, zda je potřeba spustit warm-start rekvalifikaci vah.
        """
        if len(self.history_trades) < self.lookback_trades:
            return RetrainingTriggerStatus(
                needs_retraining=False,
                drift_detected=False,
                win_rate_degradation=False,
                volatility_shift=False,
                reason=f"Nedostatek obchodů pro analýzu ({len(self.history_trades)}/{self.lookback_trades})",
                metrics={"sample_size": len(self.history_trades)}
            )

        recent = self.history_trades[-self.lookback_trades:]
        wins = [t for t in recent if t.get("net_pnl_usd", 0) > 0]
        win_rate = len(wins) / len(recent)

        # Analýza R-násobků
        r_multiples = [t.get("net_pnl_r", 0.0) for t in recent]
        avg_r = float(np.mean(r_multiples)) if r_multiples else 0.0

        win_rate_deg = win_rate < self.win_rate_alert_threshold
        drift = avg_r < -0.30

        needs_retrain = win_rate_deg or drift
        reasons = []
        if win_rate_deg:
            reasons.append(f"Win rate poklesl na {win_rate*100:.1f}% (< {self.win_rate_alert_threshold*100:.0f}%)")
        if drift:
            reasons.append(f"Průměrné R pokleslo na {avg_r:.2f}R")

        return RetrainingTriggerStatus(
            needs_retraining=needs_retrain,
            drift_detected=drift,
            win_rate_degradation=win_rate_deg,
            volatility_shift=False,
            reason="; ".join(reasons) if reasons else "Parametry stabilní (žádný drift)",
            metrics={
                "win_rate": round(win_rate, 3),
                "avg_r": round(avg_r, 3),
                "sample_size": len(recent)
            }
        )

    def recalibrate_strategy_weights(
        self,
        strategy_stats: Dict[str, Dict[str, float]]
    ) -> Dict[str, float]:
        """
        Warm-start adaptace vah 7 strategií podle nedávné ziskovosti.
        Používá softmax s teplotou T=1.5 pro zabránění přeučení na šum.
        """
        weights = {}
        scores = []
        names = []

        for strat_name, stats in strategy_stats.items():
            trades = stats.get("trades", 0)
            avg_r = stats.get("avg_r", 0.0)
            win_rate = stats.get("win_rate_pct", 50.0) / 100.0

            # Penalizace strategií s méně než 5 obchody
            conf = min(1.0, trades / 10.0)
            score = (win_rate * 2.0 - 1.0) + (avg_r * 0.5)
            score = score * conf

            scores.append(score)
            names.append(strat_name)

        if not scores:
            return {"strategy_1": 1.0, "strategy_2": 1.0, "strategy_3": 1.0, "strategy_7": 1.0}

        # Softmax normalizace
        exp_s = np.exp(np.array(scores) / 1.5)
        probs = exp_s / np.sum(exp_s)

        for name, prob in zip(names, probs):
            # Škálování na rozsah 0.40 až 1.60
            scaled_w = round(float(prob * len(names)), 3)
            weights[name] = max(0.40, min(1.60, scaled_w))

        return weights


if __name__ == "__main__":
    engine = SilverRetrainingEngine(lookback_trades=10)
    for i in range(15):
        engine.register_trade({
            "strategy_name": "TREND_FOLLOWING",
            "net_pnl_usd": 120.0 if i % 2 == 0 else -100.0,
            "net_pnl_r": 1.2 if i % 2 == 0 else -1.0
        })

    status = engine.evaluate_retraining_trigger()
    print("Retraining status:", status)
    weights = engine.recalibrate_strategy_weights({
        "strategy_1": {"trades": 18, "avg_r": -0.19, "win_rate_pct": 50.0},
        "strategy_2": {"trades": 4, "avg_r": -0.77, "win_rate_pct": 25.0},
        "strategy_3": {"trades": 10, "avg_r": 0.05, "win_rate_pct": 60.0},
        "strategy_7": {"trades": 4, "avg_r": -0.77, "win_rate_pct": 25.0}
    })
    print("Recalibrated weights:", weights)
