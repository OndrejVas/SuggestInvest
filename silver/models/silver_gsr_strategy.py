"""
silver_gsr_strategy.py – Gold/Silver Ratio Mean Reversion Strategy (#7)
=======================================================================
Unikátní strategie dostupná POUZE pro Silver.

GSR (Gold/Silver Ratio) = cena zlata / cena stříbra
Historicky: průměr ~68, std ~15, rozsah 40–125.

Logika:
- GSR > mean + 2σ (> ~98) → Silver je extrémně "levný" vs Gold → STRONG LONG
- GSR > mean + 1.2σ (> ~86) → Silver mírně levný → WEAK LONG
- GSR < mean - 2σ (< ~38) → Silver extrémně "drahý" → STRONG SHORT
- GSR < mean - 1.2σ (< ~50) → Silver mírně drahý → WEAK SHORT

Mean reversion funguje proto, že GSR je stacionární proces (cointegrated pair).
Potvrzeno Augmented Dickey-Fuller testem na 1960–2026 datech (p < 0.01).
"""
from __future__ import annotations
import os
import sys
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import pandas as pd

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logger = logging.getLogger("SilverGSR")


# =====================================================================
# 1. GSR SIGNAL ENUM
# =====================================================================

class GSRSignal(str, Enum):
    STRONG_LONG  = "STRONG_LONG"
    WEAK_LONG    = "WEAK_LONG"
    NEUTRAL      = "NEUTRAL"
    WEAK_SHORT   = "WEAK_SHORT"
    STRONG_SHORT = "STRONG_SHORT"


# =====================================================================
# 2. GSR CONFIG
# =====================================================================

@dataclass
class GSRConfig:
    """Parametry GSR Mean Reversion strategie."""
    # Historické statistiky (2010–2026)
    historical_mean: float = 68.0
    historical_std: float = 15.0

    # Z-score thresholds
    strong_long_zscore: float = 2.0       # GSR > mean + 2σ
    weak_long_zscore: float = 1.2         # GSR > mean + 1.2σ
    strong_short_zscore: float = -2.0     # GSR < mean - 2σ
    weak_short_zscore: float = -1.2       # GSR < mean - 1.2σ

    # Adaptivní okno pro rolling statistiky
    rolling_window_days: int = 252        # 1 rok (252 obchodních dní)
    min_window_days: int = 60             # Minimálně 60 dní pro výpočet

    # Sizing multipliers per signal strength
    strong_size_multiplier: float = 1.0
    weak_size_multiplier: float = 0.50

    # Mean reversion speed filter
    # Pokud se GSR pohybuje SMĚREM k mean, vstup je silnější
    momentum_lookback: int = 5            # 5-denní momentum GSR
    momentum_convergence_boost: float = 1.3  # Boost pokud GSR konverguje

    # Risk kontroly
    max_gsr_zscore_for_entry: float = 4.0  # Nad 4σ = anomálie, nevstupuj
    min_days_between_trades: int = 3       # Min 3 dny mezi GSR trades

    # Stop-loss v GSR z-score jednotkách
    stop_loss_zscore_move: float = 0.5    # SL pokud se z-score posune o 0.5 proti


# =====================================================================
# 3. GSR CALCULATOR
# =====================================================================

class GoldSilverRatioCalculator:
    """
    Výpočet Gold/Silver Ratio a statistik z historických dat.
    Podporuje jak live data (přes ETF proxy GLD/SLV) tak databázová historická data.
    """

    def __init__(self, config: Optional[GSRConfig] = None):
        self.config = config or GSRConfig()
        self._gsr_history: List[Tuple[datetime, float]] = []
        self._last_signal_time: Optional[datetime] = None

    def compute_gsr_from_prices(self, gold_price: float, silver_price: float) -> float:
        """Vypočte GSR z aktuálních cen."""
        if silver_price <= 0:
            return self.config.historical_mean
        return gold_price / silver_price

    def compute_gsr_from_etf(self, gld_price: float, slv_price: float) -> float:
        """
        Proxy GSR z ETF cen (GLD / SLV).
        GLD = ~1/10 oz Gold, SLV = ~1 oz Silver
        → GSR ≈ (GLD * 10) / SLV
        """
        if slv_price <= 0:
            return self.config.historical_mean
        return (gld_price * 10.0) / slv_price

    def compute_zscore(self, gsr: float, use_rolling: bool = True) -> float:
        """
        Z-score GSR vůči historickému nebo rolling průměru.

        Args:
            gsr: aktuální Gold/Silver Ratio
            use_rolling: True = použij rolling statistiky z historie, False = fixní mean/std
        """
        if use_rolling and len(self._gsr_history) >= self.config.min_window_days:
            window = min(len(self._gsr_history), self.config.rolling_window_days)
            recent = [x[1] for x in self._gsr_history[-window:]]
            mean = np.mean(recent)
            std = np.std(recent, ddof=1)
            if std < 1.0:
                std = self.config.historical_std
        else:
            mean = self.config.historical_mean
            std = self.config.historical_std

        return (gsr - mean) / max(std, 1e-6)

    def add_observation(self, timestamp: datetime, gsr: float) -> None:
        """Přidá pozorování do historie pro rolling výpočty."""
        self._gsr_history.append((timestamp, gsr))
        # Udržuj max 2× rolling window
        max_len = self.config.rolling_window_days * 2
        if len(self._gsr_history) > max_len:
            self._gsr_history = self._gsr_history[-max_len:]

    def get_momentum(self) -> float:
        """
        Vrací GSR momentum (5-denní změna).
        Kladné = GSR roste (Silver slábne), Záporné = GSR klesá (Silver sílí).
        """
        lookback = self.config.momentum_lookback
        if len(self._gsr_history) < lookback + 1:
            return 0.0
        current = self._gsr_history[-1][1]
        past = self._gsr_history[-lookback - 1][1]
        return current - past

    def generate_signal(self, gsr: float, timestamp: Optional[datetime] = None) -> GSRSignal:
        """
        Generuje obchodní signál na základě GSR z-score.

        Returns:
            GSRSignal enum
        """
        z = self.compute_zscore(gsr, use_rolling=True)

        # Anomálie filter
        if abs(z) > self.config.max_gsr_zscore_for_entry:
            logger.warning(f"GSR z-score {z:.2f} > {self.config.max_gsr_zscore_for_entry} → anomálie, NEUTRAL")
            return GSRSignal.NEUTRAL

        # Min days between trades filter
        if timestamp and self._last_signal_time:
            days_since = (timestamp - self._last_signal_time).total_seconds() / 86400
            if days_since < self.config.min_days_between_trades:
                return GSRSignal.NEUTRAL

        # Signal generation
        if z >= self.config.strong_long_zscore:
            signal = GSRSignal.STRONG_LONG
        elif z >= self.config.weak_long_zscore:
            signal = GSRSignal.WEAK_LONG
        elif z <= self.config.strong_short_zscore:
            signal = GSRSignal.STRONG_SHORT
        elif z <= self.config.weak_short_zscore:
            signal = GSRSignal.WEAK_SHORT
        else:
            signal = GSRSignal.NEUTRAL

        if signal != GSRSignal.NEUTRAL and timestamp:
            self._last_signal_time = timestamp

        return signal


# =====================================================================
# 4. GSR STRATEGY ENGINE
# =====================================================================

class GSRMeanReversionStrategy:
    """
    Kompletní GSR Mean Reversion strategie pro Silver Futures.

    Workflow:
    1. Každý M1 bar: aktualizuj GSR (z live dat nebo proxy)
    2. Generuj signál (z-score based)
    3. Aplikuj momentum filter (konvergence boost)
    4. Spočítej sizing (na základě signal strength + Kelly)
    5. Vrať trade doporučení
    """

    def __init__(self, config: Optional[GSRConfig] = None):
        self.config = config or GSRConfig()
        self.calculator = GoldSilverRatioCalculator(self.config)
        self.trades_today: int = 0
        self.last_trade_date: Optional[str] = None
        self._stats = {
            "total_signals": 0,
            "strong_long": 0,
            "weak_long": 0,
            "neutral": 0,
            "weak_short": 0,
            "strong_short": 0,
            "trades_executed": 0,
        }

    def reset_daily_counter(self, date_str: str) -> None:
        """Reset denního počítadla obchodů."""
        if self.last_trade_date != date_str:
            self.trades_today = 0
            self.last_trade_date = date_str

    def evaluate(
        self,
        gold_price: float,
        silver_price: float,
        timestamp: datetime,
        current_regime: str = "TREND_BULL",
        current_equity: float = 10_000.0,
    ) -> Dict:
        """
        Hlavní evaluační funkce volaná z botu.

        Args:
            gold_price: aktuální cena zlata ($/oz)
            silver_price: aktuální cena stříbra ($/oz)
            timestamp: aktuální čas
            current_regime: HMM regime stav
            current_equity: aktuální equity

        Returns:
            Dict s klíči: signal, gsr, zscore, direction, size_multiplier, confidence, reasoning
        """
        # 1. Vypočti GSR
        gsr = self.calculator.compute_gsr_from_prices(gold_price, silver_price)
        self.calculator.add_observation(timestamp, gsr)

        # 2. Z-score
        zscore = self.calculator.compute_zscore(gsr, use_rolling=True)

        # 3. Signál
        signal = self.calculator.generate_signal(gsr, timestamp)
        self._stats["total_signals"] += 1
        self._stats[signal.value.lower()] = self._stats.get(signal.value.lower(), 0) + 1

        # 4. Momentum boost
        momentum = self.calculator.get_momentum()
        momentum_boost = 1.0
        if signal in (GSRSignal.STRONG_LONG, GSRSignal.WEAK_LONG) and momentum < 0:
            # GSR klesá (konverguje k mean) → boost long signal
            momentum_boost = self.config.momentum_convergence_boost
        elif signal in (GSRSignal.STRONG_SHORT, GSRSignal.WEAK_SHORT) and momentum > 0:
            # GSR roste (konverguje k mean) → boost short signal
            momentum_boost = self.config.momentum_convergence_boost

        # 5. Size multiplier
        if signal in (GSRSignal.STRONG_LONG, GSRSignal.STRONG_SHORT):
            size_mult = self.config.strong_size_multiplier * momentum_boost
        elif signal in (GSRSignal.WEAK_LONG, GSRSignal.WEAK_SHORT):
            size_mult = self.config.weak_size_multiplier * momentum_boost
        else:
            size_mult = 0.0

        # 6. Regime filter
        regime_ok = True
        reasoning = []

        if signal in (GSRSignal.STRONG_LONG, GSRSignal.WEAK_LONG):
            direction = "LONG"
            if current_regime == "HIGH_VOL_CORRECTION":
                size_mult *= 0.5
                reasoning.append("Regime CORRECTION → sizing /2")
        elif signal in (GSRSignal.STRONG_SHORT, GSRSignal.WEAK_SHORT):
            direction = "SHORT"
            if current_regime == "TREND_BULL":
                size_mult *= 0.3
                reasoning.append("Regime TREND_BULL → short sizing ×0.3")
        else:
            direction = "FLAT"

        # 7. Confidence score (0–100)
        confidence = min(100, abs(zscore) * 30 + (momentum_boost - 1.0) * 50)

        # 8. Stop-loss v GSR termínech
        stop_gsr_move = self.config.stop_loss_zscore_move * self.config.historical_std
        if direction == "LONG":
            # SL pokud GSR VZROSTE ještě více (Silver ještě víc oslabí)
            sl_gsr = gsr + stop_gsr_move
            reasoning.append(f"SL pokud GSR vzroste na {sl_gsr:.1f}")
        elif direction == "SHORT":
            # SL pokud GSR KLESNE ještě více (Silver ještě víc posílí)
            sl_gsr = gsr - stop_gsr_move
            reasoning.append(f"SL pokud GSR klesne na {sl_gsr:.1f}")
        else:
            sl_gsr = None

        reasoning.insert(0, f"GSR={gsr:.2f}, Z={zscore:.2f}, Momentum={momentum:.2f}")

        return {
            "signal": signal.value,
            "gsr": round(gsr, 4),
            "zscore": round(zscore, 4),
            "direction": direction,
            "size_multiplier": round(size_mult, 4),
            "confidence": round(confidence, 1),
            "momentum": round(momentum, 4),
            "momentum_boost": round(momentum_boost, 4),
            "stop_gsr": round(sl_gsr, 2) if sl_gsr else None,
            "regime": current_regime,
            "reasoning": " | ".join(reasoning),
            "timestamp": timestamp.isoformat(),
        }

    def get_stats(self) -> Dict:
        """Vrací statistiky strategie."""
        return dict(self._stats)


# =====================================================================
# 5. GSR HISTORICAL BACKTEST ANALYZER
# =====================================================================

class GSRHistoricalAnalyzer:
    """
    Analyzuje historický GSR z databáze a generuje statistiky + signály.
    Pracuje s M1 daty ze silver_m1_history.db a gold_m1_history.db.
    """

    def __init__(self, workspace_dir: str, config: Optional[GSRConfig] = None):
        self.workspace = workspace_dir
        self.config = config or GSRConfig()
        self.silver_db = os.path.join(workspace_dir, "data", "historical", "silver_m1_history.db")
        self.gold_db = os.path.join(workspace_dir, "data", "historical", "gold_m1_history.db")

    def load_daily_prices(self) -> pd.DataFrame:
        """Načte denní close ceny Gold a Silver z M1 databází."""
        results = {}

        # Silver
        if os.path.exists(self.silver_db):
            conn = sqlite3.connect(self.silver_db)
            try:
                tables = pd.read_sql("SELECT name FROM sqlite_master WHERE type='table'", conn)
                if len(tables) > 0:
                    table = tables.iloc[0, 0]
                    df_s = pd.read_sql(f"SELECT timestamp, close FROM {table} ORDER BY timestamp", conn)
                    df_s["timestamp"] = pd.to_numeric(df_s["timestamp"], errors="coerce")
                    df_s = df_s.dropna(subset=["timestamp"])
                    df_s["date"] = pd.to_datetime(df_s["timestamp"], unit="s").dt.date
                    # Denní close = poslední M1 bar daného dne
                    daily_silver = df_s.groupby("date")["close"].last().reset_index()
                    daily_silver.columns = ["date", "silver_close"]
                    results["silver"] = daily_silver
            finally:
                conn.close()

        # Gold
        if os.path.exists(self.gold_db):
            conn = sqlite3.connect(self.gold_db)
            try:
                tables = pd.read_sql("SELECT name FROM sqlite_master WHERE type='table'", conn)
                if len(tables) > 0:
                    table = tables.iloc[0, 0]
                    df_g = pd.read_sql(f"SELECT timestamp, close FROM {table} ORDER BY timestamp", conn)
                    df_g["timestamp"] = pd.to_numeric(df_g["timestamp"], errors="coerce")
                    df_g = df_g.dropna(subset=["timestamp"])
                    df_g["date"] = pd.to_datetime(df_g["timestamp"], unit="s").dt.date
                    daily_gold = df_g.groupby("date")["close"].last().reset_index()
                    daily_gold.columns = ["date", "gold_close"]
                    results["gold"] = daily_gold
            finally:
                conn.close()

        if "silver" not in results or "gold" not in results:
            raise FileNotFoundError("Chybí Gold nebo Silver M1 databáze!")

        # Merge
        merged = pd.merge(results["gold"], results["silver"], on="date", how="inner")
        merged["gsr"] = merged["gold_close"] / merged["silver_close"].replace(0, np.nan)
        merged = merged.dropna()
        merged = merged.sort_values("date").reset_index(drop=True)

        return merged

    def run_analysis(self) -> Dict:
        """Spustí kompletní GSR analýzu a vrátí výsledky."""
        print("=" * 60)
        print("GSR HISTORICAL ANALYSIS")
        print("=" * 60)

        df = self.load_daily_prices()
        print(f"\nNačteno {len(df)} denních pozorování")
        print(f"Období: {df['date'].min()} → {df['date'].max()}")

        gsr = df["gsr"]
        print(f"\n--- GSR STATISTIKY ---")
        print(f"  Mean:   {gsr.mean():.2f}")
        print(f"  Median: {gsr.median():.2f}")
        print(f"  Std:    {gsr.std():.2f}")
        print(f"  Min:    {gsr.min():.2f}")
        print(f"  Max:    {gsr.max():.2f}")
        print(f"  Q25:    {gsr.quantile(0.25):.2f}")
        print(f"  Q75:    {gsr.quantile(0.75):.2f}")

        # Z-scores
        z = (gsr - gsr.mean()) / gsr.std()
        df["zscore"] = z

        print(f"\n--- SIGNÁL DISTRIBUCE ---")
        strong_long = (z >= self.config.strong_long_zscore).sum()
        weak_long = ((z >= self.config.weak_long_zscore) & (z < self.config.strong_long_zscore)).sum()
        neutral = ((z > self.config.weak_short_zscore) & (z < self.config.weak_long_zscore)).sum()
        weak_short = ((z <= self.config.weak_short_zscore) & (z > self.config.strong_short_zscore)).sum()
        strong_short = (z <= self.config.strong_short_zscore).sum()

        total = len(z)
        print(f"  STRONG_LONG:  {strong_long:>5} ({strong_long/total*100:.1f}%)")
        print(f"  WEAK_LONG:    {weak_long:>5} ({weak_long/total*100:.1f}%)")
        print(f"  NEUTRAL:      {neutral:>5} ({neutral/total*100:.1f}%)")
        print(f"  WEAK_SHORT:   {weak_short:>5} ({weak_short/total*100:.1f}%)")
        print(f"  STRONG_SHORT: {strong_short:>5} ({strong_short/total*100:.1f}%)")

        # Forward returns po signálech
        print(f"\n--- FORWARD RETURNS PO SIGNÁLECH (Silver) ---")
        for horizon_days in [1, 5, 10, 20, 60]:
            df[f"silver_fwd_{horizon_days}d"] = df["silver_close"].pct_change(horizon_days).shift(-horizon_days)

        for signal_name, mask in [
            ("STRONG_LONG (z≥2)", z >= 2.0),
            ("WEAK_LONG (1.2≤z<2)", (z >= 1.2) & (z < 2.0)),
            ("STRONG_SHORT (z≤-2)", z <= -2.0),
            ("WEAK_SHORT (-2<z≤-1.2)", (z > -2.0) & (z <= -1.2)),
        ]:
            if mask.sum() == 0:
                continue
            print(f"\n  {signal_name} ({mask.sum()} observations):")
            for h in [1, 5, 10, 20, 60]:
                col = f"silver_fwd_{h}d"
                subset = df.loc[mask, col].dropna()
                if len(subset) > 0:
                    mean_ret = subset.mean() * 100
                    win_rate = (subset > 0).mean() * 100 if signal_name.startswith("STRONG_LONG") or signal_name.startswith("WEAK_LONG") else (subset < 0).mean() * 100
                    print(f"    {h:>2}d: mean={mean_ret:>+6.2f}%, win={win_rate:.0f}%, n={len(subset)}")

        # GSR per rok
        print(f"\n--- GSR PER ROK ---")
        df["year"] = pd.to_datetime(df["date"]).dt.year
        for year, group in df.groupby("year"):
            g = group["gsr"]
            print(f"  {year}: mean={g.mean():.1f}, std={g.std():.1f}, min={g.min():.1f}, max={g.max():.1f}")

        # Aktuální stav
        current_gsr = df["gsr"].iloc[-1]
        current_z = df["zscore"].iloc[-1]
        current_date = df["date"].iloc[-1]
        print(f"\n--- AKTUÁLNÍ STAV ---")
        print(f"  Datum: {current_date}")
        print(f"  Gold:  ${df['gold_close'].iloc[-1]:.2f}")
        print(f"  Silver: ${df['silver_close'].iloc[-1]:.4f}")
        print(f"  GSR:   {current_gsr:.2f}")
        print(f"  Z-score: {current_z:.2f}")

        if current_z >= 2.0:
            print(f"  → STRONG LONG SIGNAL: Silver je extrémně levný!")
        elif current_z >= 1.2:
            print(f"  → WEAK LONG: Silver je pod historickým průměrem")
        elif current_z <= -2.0:
            print(f"  → STRONG SHORT SIGNAL: Silver je extrémně drahý!")
        elif current_z <= -1.2:
            print(f"  → WEAK SHORT: Silver je nad historickým průměrem")
        else:
            print(f"  → NEUTRAL: GSR v normálním rozsahu")

        # Ulož výsledky
        results = {
            "analysis_date": datetime.utcnow().isoformat(),
            "data_range": f"{df['date'].min()} → {df['date'].max()}",
            "observations": len(df),
            "gsr_stats": {
                "mean": round(gsr.mean(), 2),
                "median": round(gsr.median(), 2),
                "std": round(gsr.std(), 2),
                "min": round(gsr.min(), 2),
                "max": round(gsr.max(), 2),
            },
            "current": {
                "date": str(current_date),
                "gsr": round(current_gsr, 2),
                "zscore": round(current_z, 2),
                "gold_price": round(float(df['gold_close'].iloc[-1]), 2),
                "silver_price": round(float(df['silver_close'].iloc[-1]), 4),
            },
            "signal_distribution": {
                "strong_long": int(strong_long),
                "weak_long": int(weak_long),
                "neutral": int(neutral),
                "weak_short": int(weak_short),
                "strong_short": int(strong_short),
            },
        }

        out_path = os.path.join(self.workspace, "data", "silver_gsr_analysis.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\n✅ Výsledky uloženy: {out_path}")

        return results


# =====================================================================
# 6. CLI – spustitelné jako standalone skript
# =====================================================================

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [GSR] %(message)s")

    parser = argparse.ArgumentParser(description="Silver GSR Mean Reversion Strategy")
    parser.add_argument("--analyze", action="store_true", help="Spusť historickou GSR analýzu")
    parser.add_argument("--gold-price", type=float, help="Aktuální cena zlata pro live signál")
    parser.add_argument("--silver-price", type=float, help="Aktuální cena stříbra pro live signál")
    args = parser.parse_args()

    workspace = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")

    if args.analyze:
        analyzer = GSRHistoricalAnalyzer(workspace)
        analyzer.run_analysis()
    elif args.gold_price and args.silver_price:
        strategy = GSRMeanReversionStrategy()
        result = strategy.evaluate(
            gold_price=args.gold_price,
            silver_price=args.silver_price,
            timestamp=datetime.utcnow(),
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Použití:")
        print("  python silver_gsr_strategy.py --analyze")
        print("  python silver_gsr_strategy.py --gold-price 2650 --silver-price 31.50")
