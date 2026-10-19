"""
verify_silver_db.py – Ověření kompletnosti Silver M1 databáze
=============================================================
1. Celkový rozsah dat
2. Detekce gaps (mezery > 2h v obchodních hodinách)
3. Statistiky per rok
4. OHLCV integrity check
"""
import os, sys, sqlite3, json
from datetime import datetime, timedelta
from collections import defaultdict

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

WORKSPACE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
DB_PATH = os.path.join(WORKSPACE, "data", "historical", "silver_m1_history.db")

def main():
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] DB nenalezena: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # 1. Zjisti tabulky
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]
    print(f"=== SILVER M1 DB VERIFICATION ===")
    print(f"Tabulky: {tables}")

    table = tables[0] if tables else None
    if not table:
        print("[ERROR] Žádná tabulka!")
        return

    # 2. Sloupce
    cur.execute(f"PRAGMA table_info({table})")
    cols = [(r[1], r[2]) for r in cur.fetchall()]
    print(f"Sloupce: {cols}")

    # 3. Celkový count
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    total = cur.fetchone()[0]
    print(f"\nCelkem řádků: {total:,}")

    # 4. Rozsah
    cur.execute(f"SELECT MIN(timestamp), MAX(timestamp) FROM {table}")
    min_ts, max_ts = cur.fetchone()
    print(f"Min timestamp: {min_ts}")
    print(f"Max timestamp: {max_ts}")

    # Zkusíme parsovat timestamps
    try:
        if isinstance(min_ts, (int, float)):
            dt_min = datetime.utcfromtimestamp(min_ts)
            dt_max = datetime.utcfromtimestamp(max_ts)
            ts_is_epoch = True
        else:
            dt_min = datetime.fromisoformat(str(min_ts).replace("Z", "+00:00").replace("+00:00", ""))
            dt_max = datetime.fromisoformat(str(max_ts).replace("Z", "+00:00").replace("+00:00", ""))
            ts_is_epoch = False
        print(f"Rozsah: {dt_min} → {dt_max}")
        print(f"Délka: {(dt_max - dt_min).days} dní")
    except Exception as e:
        print(f"[WARN] Nelze parsovat timestamp: {e}")
        dt_min = dt_max = None
        ts_is_epoch = False

    # 5. Statistiky per rok
    print(f"\n=== STATISTIKY PER ROK ===")
    if ts_is_epoch:
        for year in range(2019, 2027):
            start = datetime(year, 1, 1).timestamp()
            end = datetime(year + 1, 1, 1).timestamp()
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE timestamp >= ? AND timestamp < ?", (start, end))
            cnt = cur.fetchone()[0]
            if cnt > 0:
                cur.execute(f"SELECT MIN(timestamp), MAX(timestamp) FROM {table} WHERE timestamp >= ? AND timestamp < ?", (start, end))
                y_min, y_max = cur.fetchone()
                print(f"  {year}: {cnt:>10,} barů | {datetime.utcfromtimestamp(y_min).strftime('%Y-%m-%d')} → {datetime.utcfromtimestamp(y_max).strftime('%Y-%m-%d')}")
            else:
                print(f"  {year}: {cnt:>10,} barů")
    else:
        for year in range(2019, 2027):
            start_str = f"{year}-01-01"
            end_str = f"{year+1}-01-01"
            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE timestamp >= ? AND timestamp < ?", (start_str, end_str))
            cnt = cur.fetchone()[0]
            if cnt > 0:
                cur.execute(f"SELECT MIN(timestamp), MAX(timestamp) FROM {table} WHERE timestamp >= ? AND timestamp < ?", (start_str, end_str))
                y_min, y_max = cur.fetchone()
                print(f"  {year}: {cnt:>10,} barů | {y_min} → {y_max}")
            else:
                print(f"  {year}: {cnt:>10,} barů")

    # 6. Gap detection (mezery > 2 hodiny v trading hours)
    print(f"\n=== GAP DETECTION (mezery > 2h) ===")
    cur.execute(f"SELECT timestamp FROM {table} ORDER BY timestamp ASC")
    timestamps = [r[0] for r in cur.fetchall()]

    gaps = []
    for i in range(1, len(timestamps)):
        if ts_is_epoch:
            diff_sec = timestamps[i] - timestamps[i-1]
            if diff_sec > 7200:  # 2 hodiny
                gap_start = datetime.utcfromtimestamp(timestamps[i-1])
                gap_end = datetime.utcfromtimestamp(timestamps[i])
                # Ignoruj víkendy (pá 22:00 → ne 23:00)
                if gap_start.weekday() == 4 and gap_end.weekday() == 6:
                    continue
                if gap_start.weekday() == 4 and gap_end.weekday() == 0:
                    continue
                gaps.append((gap_start, gap_end, diff_sec / 3600))
        else:
            try:
                t1 = datetime.fromisoformat(str(timestamps[i-1]).replace("Z","").replace("+00:00",""))
                t2 = datetime.fromisoformat(str(timestamps[i]).replace("Z","").replace("+00:00",""))
                diff_sec = (t2 - t1).total_seconds()
                if diff_sec > 7200:
                    if t1.weekday() == 4 and t2.weekday() in (0, 6):
                        continue
                    gaps.append((t1, t2, diff_sec / 3600))
            except:
                pass

    if gaps:
        print(f"Nalezeno {len(gaps)} mezer > 2h (mimo víkendy):")
        for g in gaps[:30]:
            print(f"  {g[0].strftime('%Y-%m-%d %H:%M')} → {g[1].strftime('%Y-%m-%d %H:%M')} ({g[2]:.1f}h)")
        if len(gaps) > 30:
            print(f"  ... a dalších {len(gaps)-30}")
    else:
        print("Žádné významné mezery nalezeny ✓")

    # 7. OHLCV integrity
    print(f"\n=== OHLCV INTEGRITY CHECK ===")
    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE high < low")
    bad_hl = cur.fetchone()[0]
    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE close > high OR close < low")
    bad_cl = cur.fetchone()[0]
    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE open > high OR open < low")
    bad_op = cur.fetchone()[0]
    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE volume < 0")
    bad_vol = cur.fetchone()[0]
    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE close IS NULL OR open IS NULL")
    nulls = cur.fetchone()[0]

    print(f"  High < Low: {bad_hl} {'✓' if bad_hl == 0 else '⚠️'}")
    print(f"  Close outside H/L: {bad_cl} {'✓' if bad_cl == 0 else '⚠️'}")
    print(f"  Open outside H/L: {bad_op} {'✓' if bad_op == 0 else '⚠️'}")
    print(f"  Negative volume: {bad_vol} {'✓' if bad_vol == 0 else '⚠️'}")
    print(f"  NULL close/open: {nulls} {'✓' if nulls == 0 else '⚠️'}")

    # 8. Ukázkové řádky
    print(f"\n=== UKÁZKA PRVNÍCH 5 ŘÁDKŮ ===")
    cur.execute(f"SELECT * FROM {table} ORDER BY timestamp ASC LIMIT 5")
    for r in cur.fetchall():
        print(f"  {r}")

    print(f"\n=== UKÁZKA POSLEDNÍCH 5 ŘÁDKŮ ===")
    cur.execute(f"SELECT * FROM {table} ORDER BY timestamp DESC LIMIT 5")
    for r in cur.fetchall():
        print(f"  {r}")

    # 9. Výstup JSON summary
    summary = {
        "table": table,
        "total_bars": total,
        "min_timestamp": str(min_ts),
        "max_timestamp": str(max_ts),
        "date_range_days": (dt_max - dt_min).days if dt_min and dt_max else None,
        "gaps_count": len(gaps),
        "integrity": {
            "high_lt_low": bad_hl,
            "close_outside_hl": bad_cl,
            "open_outside_hl": bad_op,
            "negative_volume": bad_vol,
            "null_values": nulls,
        },
        "status": "OK" if (bad_hl == 0 and nulls == 0 and len(gaps) < 50) else "NEEDS_ATTENTION",
    }
    out_path = os.path.join(os.path.dirname(DB_PATH), "silver_db_verification.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Summary uložen: {out_path}")

    conn.close()

if __name__ == "__main__":
    main()
