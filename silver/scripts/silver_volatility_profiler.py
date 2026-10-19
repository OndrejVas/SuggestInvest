"""
silver_volatility_profiler.py – Volatilita profiling per seance a Volatility Gate kalibrace
=========================================================================================
KROKY 15 a 16 v Silver Replication Roadmap v3.0

Počítá:
1. Rozdělení volatility podle seancí:
   - Shanghai (SHFE): 02:00 – 08:00 SEČ
   - London Open:     09:00 – 11:30 SEČ
   - New York Active: 14:00 – 20:30 SEČ
2. Pravděpodobnost aktivace Volatility Gate:
   - V kolika % času je 2.0 × ATR(14) × 1000 oz > $400 (tj. ATR14 > $0.20/oz)
   - Kolik obchodů musí bot vynechat (Skip Trade) pro ochranu $10k účtu
3. Výpočet adaptivních multiplikátorů pro jednotlivé seance a režimy.
"""

import os
import sys
import sqlite3
import json
import numpy as np
import pandas as pd
from datetime import datetime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

WORKSPACE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SILVER_DB = os.path.join(WORKSPACE, "data", "historical", "silver_m1_history.db")
GOLD_DB = os.path.join(WORKSPACE, "data", "historical", "gold_m1_history.db")


def load_sample_m1_sessions(db_path: str, max_bars: int = 250_000) -> pd.DataFrame:
    """Načte reprezentativní vzorek M1 svíček pro seancovou analýzu."""
    conn = sqlite3.connect(db_path)
    # Načteme posledních 250,000 barů (~6-8 měsíců trhu)
    df = pd.read_sql(f"""
        SELECT datetime, open, high, low, close 
        FROM xagusd_m1_bars 
        ORDER BY timestamp DESC 
        LIMIT {max_bars}
    """, conn)
    conn.close()
    
    df["dt"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("dt").reset_index(drop=True)
    df["hour"] = df["dt"].dt.hour
    df["minute"] = df["dt"].dt.minute
    df["time_min"] = df["hour"] * 60 + df["minute"]
    
    # Přiřazení seancí podle SEČ (CET)
    # SHFE: 02:00 - 08:00 (120 - 480 min)
    # London: 09:00 - 11:30 (540 - 690 min)
    # NY: 14:00 - 20:30 (840 - 1230 min)
    def assign_session(m):
        if 120 <= m < 480:
            return "SHANGHAI"
        elif 540 <= m < 690:
            return "LONDON"
        elif 840 <= m <= 1230:
            return "NEW_YORK"
        else:
            return "OFF_PEAK"
            
    df["session"] = df["time_min"].apply(assign_session)
    return df


def compute_true_range(df: pd.DataFrame) -> pd.Series:
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - df["close"].shift(1)).abs()
    tr3 = (df["low"] - df["close"].shift(1)).abs()
    return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)


def main():
    print("=" * 65)
    print("SILVER VOLATILITY PROFILING & VOLATILITY GATE CALIBRATION (KROKY 15 & 16)")
    print("=" * 65)
    
    print("\n[1/3] Načítám M1 data pro seancový rozpad...")
    df = load_sample_m1_sessions(SILVER_DB, max_bars=300_000)
    print(f"  Načteno {len(df):,} barů ({df['dt'].min()} → {df['dt'].max()}).")
    
    # 2. Výpočet TR a ATR(14) na M1
    tr = compute_true_range(df)
    df["tr"] = tr
    df["atr14"] = tr.ewm(alpha=1.0 / 14, min_periods=1, adjust=False).mean()
    df["atr_pct"] = (df["atr14"] / df["close"]) * 100.0
    
    # 3. Analýza per seance
    print("\n[2/3] Volatilita podle seancí (ATR v % a absolutně):")
    sessions = ["SHANGHAI", "LONDON", "NEW_YORK", "OFF_PEAK"]
    session_stats = {}
    
    for s in sessions:
        sub = df[df["session"] == s]
        if len(sub) == 0:
            continue
        mean_tr = sub["tr"].mean()
        mean_atr_pct = sub["atr_pct"].mean()
        max_atr_pct = sub["atr_pct"].max()
        p95_tr = sub["tr"].quantile(0.95)
        
        session_stats[s] = {
            "bars": len(sub),
            "mean_atr_pct": round(mean_atr_pct, 4),
            "max_atr_pct": round(max_atr_pct, 4),
            "mean_tr_usd": round(mean_tr, 4),
            "p95_tr_usd": round(p95_tr, 4)
        }
        print(f"  • {s:10s}: ATR = {mean_atr_pct:.3f}% (Mean TR: ${mean_tr:.4f}/oz, 95th pct: ${p95_tr:.4f}/oz)")
        
    # 4. Volatility Gate kalibrace (Krok 16)
    print("\n[3/3] Kalibrace Volatility Gate pro $10,000 účet (SIL = 1,000 oz):")
    # Pravidlo: 1 kontrakt SIL = 1,000 oz.
    # Max risk na $10k účtu = 4% = $400.
    # Pokud strategie používá Stop-Loss = 2.0 × ATR(14):
    # Dolarový risk na 1 kontrakt = (2.0 × ATR14) × 1,000.
    # Podmínka gate: pokud (2.0 × ATR14) > $0.40/oz (tj. ATR14 > $0.20/oz), obchod se MUSÍ PŘESKOČIT (Skip Trade).
    
    df["sl_distance_usd_per_oz"] = 2.0 * df["atr14"]
    df["dollar_risk_1contract"] = df["sl_distance_usd_per_oz"] * 1000.0
    
    gate_breaches = df["dollar_risk_1contract"] > 400.0
    breach_pct = gate_breaches.mean() * 100.0
    
    print(f"  • Max povolený Stop-Loss:  $0.40/oz (80 ticků) = $400 na 1 SIL kontrakt")
    print(f"  • Prahová hodnota ATR(14):  $0.20/oz")
    print(f"  • Podíl barů s ATR > $0.20: {breach_pct:.2f}%")
    print(f"  • Podíl povolených barů:    {100.0 - breach_pct:.2f}%")
    
    # Podle seancí
    print("\n  Aktivace Volatility Gate per seance:")
    for s in ["SHANGHAI", "LONDON", "NEW_YORK"]:
        sub = df[df["session"] == s]
        s_breaches = (sub["dollar_risk_1contract"] > 400.0).mean() * 100.0
        print(f"    - {s:10s}: {s_breaches:.2f}% barů vyžaduje Skip Trade")
        
    results = {
        "analysis_date": datetime.now().isoformat(),
        "bars_analyzed": len(df),
        "sessions": session_stats,
        "volatility_gate": {
            "contract_oz": 1000.0,
            "max_account_risk_usd": 400.0,
            "max_sl_dollars_per_oz": 0.40,
            "atr_threshold_for_skip": 0.20,
            "overall_skip_trade_pct": round(breach_pct, 2),
            "overall_allowed_trade_pct": round(100.0 - breach_pct, 2),
            "rule": "IF (strategy_sl_multiplier * atr14 * 1000) > $400 THEN SKIP_TRADE ELSE ALLOW_1_CONTRACT"
        }
    }
    
    out_file = os.path.join(WORKSPACE, "data", "silver_volatility_gate_calibration.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
        
    print(f"\n✅ Výsledky uloženy: {out_file}")
    print("✅ KROKY 15 a 16 DOKONČENY ÚSPĚŠNĚ!")


if __name__ == "__main__":
    main()
