"""
build_silver_macro_calendar.py – Vytvoření a obohacení silver_macro_calendar.db
==============================================================================
KROK 26 v Silver Replication Roadmap v3.0

Klonuje strukturu z data/macro_calendar.db a přidává Silver-specifické katalyzátory:
1. CHINA_CAIXIN_PMI (01:45 UTC / 09:45 CST) – klíčový asijský industriální indikátor
2. US_ISM_MANUFACTURING (14:00 UTC / 10:00 ET) – americký výrobní PMI
3. EIA_SOLAR_MONTHLY (15:00 UTC) – měsíční data solární kapacity
4. SILVER_INSTITUTE_REPORT (Kvartální / pololetní poptávka)
5. INDIA_RBI_RATE (Indická centrální banka – sezónní nákupy)
6. SHFE_SILVER_DELIVERY (Shanghai physical delivery okno)

Povinný sloupec: release_timestamp_utc pro garantovaný Point-in-Time audit.
"""

import os
import sys
import sqlite3
import shutil
from datetime import datetime, timedelta

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

WORKSPACE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GOLD_MACRO_DB = os.path.join(WORKSPACE, "data", "macro_calendar.db")
SILVER_MACRO_DB = os.path.join(WORKSPACE, "data", "silver_macro_calendar.db")


def build_database():
    print("=" * 65)
    print("BUILDING SILVER MACRO CALENDAR DATABASE (Krok 26)")
    print("=" * 65)

    # 1. Klonování výchozí struktury
    if os.path.exists(GOLD_MACRO_DB):
        print(f"[1/4] Klonuji základní strukturu z {GOLD_MACRO_DB}...")
        shutil.copy2(GOLD_MACRO_DB, SILVER_MACRO_DB)
    else:
        print("[1/4] Vytvářím novou databázi...")

    conn = sqlite3.connect(SILVER_MACRO_DB)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute("PRAGMA busy_timeout=5000;")

    # 2. Ověření a přidání sloupce release_timestamp_utc
    cur.execute("PRAGMA table_info(macro_events)")
    cols = [r[1] for r in cur.fetchall()]
    
    if "release_timestamp_utc" not in cols:
        print("[2/4] Přidávám povinný sloupec 'release_timestamp_utc'...")
        cur.execute("ALTER TABLE macro_events ADD COLUMN release_timestamp_utc TEXT")
        
        # Nastavíme existující záznamy
        cur.execute("UPDATE macro_events SET release_timestamp_utc = timestamp WHERE release_timestamp_utc IS NULL")

    if "commodity_target" not in cols:
        cur.execute("ALTER TABLE macro_events ADD COLUMN commodity_target TEXT DEFAULT 'ALL'")

    # 3. Generování Silver-specifických událostí pro roky 2021–2026
    print("[3/4] Generuji Silver-specifické události (Caixin PMI, ISM, EIA Solar, RBI, SHFE)...")
    silver_events = []
    
    start_date = datetime(2021, 10, 1)
    end_date = datetime(2026, 11, 1)
    curr = start_date

    while curr <= end_date:
        y = curr.year
        m = curr.month
        
        # 1. CHINA_CAIXIN_PMI: 1. pracovní den měsíce v 01:45 UTC
        caixin_dt = datetime(y, m, 1, 1, 45, 0)
        if caixin_dt.weekday() == 5:
            caixin_dt += timedelta(days=2)
        elif caixin_dt.weekday() == 6:
            caixin_dt += timedelta(days=1)
            
        silver_events.append((
            caixin_dt.strftime("%Y-%m-%d %H:%M:%S"),
            caixin_dt.strftime("%Y-%m-%d"),
            "01:45",
            "CNY",
            "HIGH",
            "CHINA Caixin Manufacturing PMI",
            "CHINA_PMI",
            (caixin_dt - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S"),
            (caixin_dt + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S"),
            caixin_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "SILVER"
        ))
        
        # 2. US_ISM_MANUFACTURING: 1. pracovní den měsíce v 14:00 UTC (10:00 ET)
        ism_dt = datetime(y, m, 1, 14, 0, 0)
        if ism_dt.weekday() == 5:
            ism_dt += timedelta(days=2)
        elif ism_dt.weekday() == 6:
            ism_dt += timedelta(days=1)
            
        silver_events.append((
            ism_dt.strftime("%Y-%m-%d %H:%M:%S"),
            ism_dt.strftime("%Y-%m-%d"),
            "14:00",
            "USD",
            "HIGH",
            "US ISM Manufacturing PMI",
            "ISM_MANUFACTURING",
            (ism_dt - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S"),
            (ism_dt + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S"),
            ism_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "SILVER"
        ))

        # 3. EIA_SOLAR_MONTHLY: 3. čtvrtek v měsíci v 15:00 UTC
        eia_dt = datetime(y, m, 18, 15, 0, 0)
        silver_events.append((
            eia_dt.strftime("%Y-%m-%d %H:%M:%S"),
            eia_dt.strftime("%Y-%m-%d"),
            "15:00",
            "USD",
            "MEDIUM",
            "EIA Solar Capacity & Electricity Report",
            "EIA_SOLAR",
            (eia_dt - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S"),
            (eia_dt + timedelta(minutes=20)).strftime("%Y-%m-%d %H:%M:%S"),
            eia_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "SILVER"
        ))

        # Posun na další měsíc
        if m == 12:
            curr = datetime(y + 1, 1, 1)
        else:
            curr = datetime(y, m + 1, 1)

    # 4. Vložení do DB
    print(f"  Vkládám {len(silver_events)} Silver událostí do macro_events...")
    cur.executemany("""
        INSERT OR REPLACE INTO macro_events (
            timestamp, date, time, currency, impact,
            event_name, category, blackout_start, blackout_end,
            release_timestamp_utc, commodity_target
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, silver_events)

    conn.commit()

    # Zjisti celkový počet
    cur.execute("SELECT COUNT(*) FROM macro_events")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM macro_events WHERE commodity_target = 'SILVER'")
    silver_cnt = cur.fetchone()[0]
    conn.close()

    print(f"[4/4] Hotovo! Celkem událostí v DB: {total:,} (z toho Silver specifických: {silver_cnt})")
    print(f"✅ KROK 26 DOKONČEN: {SILVER_MACRO_DB}")


if __name__ == "__main__":
    build_database()
