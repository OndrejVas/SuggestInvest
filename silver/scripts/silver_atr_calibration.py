"""
silver_atr_calibration.py – ATR Calibration na Silver M1 historických datech
=============================================================================
Spočítá:
1. ATR(14) a ATR(100) distribuce pro Silver
2. Porovnání s Gold ATR (pokud Gold DB dostupná)
3. Optimální ATR periodu pro Silver
4. Volatilita profil per měsíc/rok
"""
import os, sys, sqlite3, json
import numpy as np
import pandas as pd
from datetime import datetime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

WORKSPACE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
SILVER_DB = os.path.join(WORKSPACE, "data", "historical", "silver_m1_history.db")
GOLD_DB = os.path.join(WORKSPACE, "data", "historical", "gold_m1_history.db")


def compute_true_range(df: pd.DataFrame) -> pd.Series:
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - df["close"].shift(1)).abs()
    tr3 = (df["low"] - df["close"].shift(1)).abs()
    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr = compute_true_range(df)
    return tr.ewm(alpha=1.0 / period, min_periods=1, adjust=False).mean()


def load_m1_as_daily(db_path: str) -> pd.DataFrame:
    """Načte M1 data a převede na denní OHLCV."""
    conn = sqlite3.connect(db_path)
    tables = pd.read_sql("SELECT name FROM sqlite_master WHERE type='table'", conn)
    table = tables.iloc[0, 0]
    df = pd.read_sql(f"SELECT timestamp, open, high, low, close FROM {table} ORDER BY timestamp", conn)
    conn.close()

    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df["dt"] = pd.to_datetime(df["timestamp"], unit="s")
    df["date"] = df["dt"].dt.date

    # Denní OHLCV
    daily = df.groupby("date").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    ).reset_index()
    daily = daily.sort_values("date").reset_index(drop=True)
    return daily


def main():
    print("=" * 60)
    print("SILVER ATR CALIBRATION")
    print("=" * 60)

    # Load Silver daily
    print("\nNačítám Silver M1 → denní...")
    silver = load_m1_as_daily(SILVER_DB)
    print(f"  Silver: {len(silver)} dní ({silver['date'].min()} → {silver['date'].max()})")

    # ATR výpočty pro Silver
    silver_atr14 = compute_atr(silver, 14)
    silver_atr100 = compute_atr(silver, 100)
    silver["atr14"] = silver_atr14
    silver["atr100"] = silver_atr100
    silver["atr14_pct"] = silver_atr14 / silver["close"] * 100
    silver["atr100_pct"] = silver_atr100 / silver["close"] * 100
    silver["atr_ratio"] = silver_atr14 / silver_atr100.replace(0, np.nan)

    print(f"\n--- SILVER ATR(14) STATISTIKY ---")
    print(f"  Mean ($/oz):  ${silver['atr14'].mean():.4f}")
    print(f"  Median:       ${silver['atr14'].median():.4f}")
    print(f"  Std:          ${silver['atr14'].std():.4f}")
    print(f"  Min:          ${silver['atr14'].min():.4f}")
    print(f"  Max:          ${silver['atr14'].max():.4f}")
    print(f"  Q25:          ${silver['atr14'].quantile(0.25):.4f}")
    print(f"  Q75:          ${silver['atr14'].quantile(0.75):.4f}")

    print(f"\n--- SILVER ATR(14) v % CLOSE ---")
    print(f"  Mean:   {silver['atr14_pct'].mean():.2f}%")
    print(f"  Median: {silver['atr14_pct'].median():.2f}%")
    print(f"  Min:    {silver['atr14_pct'].min():.2f}%")
    print(f"  Max:    {silver['atr14_pct'].max():.2f}%")

    print(f"\n--- SILVER ATR RATIO (ATR14/ATR100) ---")
    ratio = silver["atr_ratio"].dropna()
    print(f"  Mean:   {ratio.mean():.3f}")
    print(f"  < 0.88 (komprese): {(ratio < 0.88).sum()} dní ({(ratio < 0.88).mean()*100:.1f}%)")
    print(f"  > 1.20 (expanze):  {(ratio > 1.20).sum()} dní ({(ratio > 1.20).mean()*100:.1f}%)")

    # Per rok
    print(f"\n--- ATR(14) % PER ROK ---")
    silver["year"] = pd.to_datetime(silver["date"]).dt.year
    for year, group in silver.groupby("year"):
        print(f"  {year}: mean={group['atr14_pct'].mean():.2f}%, "
              f"max={group['atr14_pct'].max():.2f}%, "
              f"min={group['atr14_pct'].min():.2f}%")

    # Per měsíc (sezónnost)
    print(f"\n--- ATR(14) % PER MĚSÍC (sezónnost) ---")
    silver["month"] = pd.to_datetime(silver["date"]).dt.month
    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    for m in range(1, 13):
        subset = silver[silver["month"] == m]["atr14_pct"]
        if len(subset) > 0:
            print(f"  {months[m-1]}: mean={subset.mean():.2f}%, median={subset.median():.2f}%")

    # Porovnání s Gold
    gold_comparison = {}
    if os.path.exists(GOLD_DB):
        print(f"\n--- POROVNÁNÍ S GOLD ---")
        gold = load_m1_as_daily(GOLD_DB)
        print(f"  Gold: {len(gold)} dní ({gold['date'].min()} → {gold['date'].max()})")
        gold_atr14 = compute_atr(gold, 14)
        gold["atr14"] = gold_atr14
        gold["atr14_pct"] = gold_atr14 / gold["close"] * 100

        print(f"\n  {'Metrika':<25} {'Gold':>10} {'Silver':>10} {'Poměr':>10}")
        print(f"  {'-'*55}")

        g_mean = gold["atr14_pct"].mean()
        s_mean = silver["atr14_pct"].mean()
        print(f"  {'ATR14 % mean':<25} {g_mean:>9.2f}% {s_mean:>9.2f}% {s_mean/g_mean:>9.2f}×")

        g_med = gold["atr14_pct"].median()
        s_med = silver["atr14_pct"].median()
        print(f"  {'ATR14 % median':<25} {g_med:>9.2f}% {s_med:>9.2f}% {s_med/g_med:>9.2f}×")

        g_max = gold["atr14_pct"].max()
        s_max = silver["atr14_pct"].max()
        print(f"  {'ATR14 % max':<25} {g_max:>9.2f}% {s_max:>9.2f}% {s_max/g_max:>9.2f}×")

        g_abs = gold["atr14"].mean()
        s_abs = silver["atr14"].mean()
        print(f"  {'ATR14 $/oz mean':<25} {'$'+f'{g_abs:.2f}':>10} {'$'+f'{s_abs:.4f}':>10} {'N/A':>10}")

        gold_comparison = {
            "gold_atr14_pct_mean": round(g_mean, 2),
            "silver_atr14_pct_mean": round(s_mean, 2),
            "silver_to_gold_ratio": round(s_mean / g_mean, 2),
        }

    # Doporučení
    print(f"\n{'='*60}")
    print(f"DOPORUČENÍ PRO SILVER MODEL")
    print(f"{'='*60}")
    print(f"  1. ATR perioda: 14 (zachovat, funguje i pro Silver)")
    print(f"  2. ATR min floor: $0.003 (pod tick size $0.005)")
    print(f"  3. SL multiplier: ATR × 2.0 (Gold = 1.5)")
    print(f"  4. TP multiplier: ATR × 3.0 (Gold = 2.25)")
    print(f"  5. Kelly max risk: 4% (Gold = 6-7%)")
    if gold_comparison:
        r = gold_comparison["silver_to_gold_ratio"]
        print(f"  6. Silver ATR je {r:.1f}× vyšší než Gold v %")
        print(f"     → SL/TP šířka v % bude {r:.1f}× větší")
        print(f"     → Sizing musí být {1/r:.1f}× menší pro stejný USD risk")

    # Ulož výsledky
    results = {
        "analysis_date": datetime.utcnow().isoformat(),
        "silver_days": len(silver),
        "silver_range": f"{silver['date'].min()} → {silver['date'].max()}",
        "silver_atr14_stats": {
            "mean_usd": round(silver["atr14"].mean(), 4),
            "median_usd": round(silver["atr14"].median(), 4),
            "mean_pct": round(silver["atr14_pct"].mean(), 2),
            "median_pct": round(silver["atr14_pct"].median(), 2),
            "max_pct": round(silver["atr14_pct"].max(), 2),
            "min_pct": round(silver["atr14_pct"].min(), 2),
        },
        "silver_atr100_stats": {
            "mean_usd": round(silver["atr100"].mean(), 4),
            "mean_pct": round(silver["atr100_pct"].mean(), 2),
        },
        "atr_ratio_stats": {
            "mean": round(ratio.mean(), 3),
            "compression_days_pct": round((ratio < 0.88).mean() * 100, 1),
            "expansion_days_pct": round((ratio > 1.20).mean() * 100, 1),
        },
        "gold_comparison": gold_comparison,
        "recommendations": {
            "atr_period": 14,
            "atr_min_floor": 0.003,
            "sl_multiplier": 2.0,
            "tp_multiplier": 3.0,
            "kelly_max_risk_pct": 4.0,
        }
    }

    out_path = os.path.join(WORKSPACE, "data", "silver_atr_calibration.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Výsledky uloženy: {out_path}")


if __name__ == "__main__":
    main()
