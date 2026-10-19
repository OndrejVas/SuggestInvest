"""
silver_walkforward_manager.py
=============================
Správce rozdělení historických dat Stříbra (XAG / Micro Silver) pro trénování a walk-forward OOS validaci.

Pravidlo:
1. Období 2021–2025 je IN-SAMPLE (odemčená historie pro natrénování základního HMM & Kellyho modelu).
2. Rok 2026 je OUT-OF-SAMPLE a je striktně UZAMČENÝ.
   Postupně se odkrývají jednotlivé měsíce (2026-01 až 2026-10), na kterých se testuje slepá predikce
   a následně se na nich model inkrementálně dotrénovává.
"""

import os
import sys
import json
import sqlite3
import argparse
from datetime import datetime
from typing import Dict, Any, List, Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
HIST_DIR = os.path.join(WORKSPACE_DIR, "data", "historical")
DB_PATH = os.path.join(HIST_DIR, "silver_m1_history.db")
MANIFEST_PATH = os.path.join(HIST_DIR, "silver_2026_walkforward_manifest.json")


def safe_json_write(path: str, data: Any) -> None:
    import tempfile
    dir_ = os.path.dirname(path) or "."
    tmp_fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)


def build_or_refresh_manifest(force_relock: bool = False) -> Dict[str, Any]:
    """Sestaví nebo zaktualizuje manifest měsíčních bloků roku 2026 ze SQLite databáze."""
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"Databáze nenalezena: {DB_PATH}")

    existing_locks = {}
    if os.path.exists(MANIFEST_PATH) and not force_relock:
        try:
            with open(MANIFEST_PATH, "r", encoding="utf-8") as f:
                old_m = json.load(f)
                for tr in old_m.get("out_of_sample_2026", {}).get("months", []):
                    existing_locks[tr["month"]] = tr.get("status", "LOCKED")
        except Exception:
            pass

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 1. In-Sample statistika (2021-10-13 až 2025-12-31)
    in_cnt, in_min, in_max = c.execute(
        "SELECT count(*), min(datetime), max(datetime) FROM xagusd_m1_bars WHERE datetime < '2026-01-01'"
    ).fetchone()

    # 2. Rok 2026 po měsících
    months_query = c.execute("""
        SELECT 
            substr(datetime, 1, 7) as ym,
            count(*),
            min(datetime),
            max(datetime),
            min(low),
            max(high)
        FROM xagusd_m1_bars 
        WHERE datetime >= '2026-01-01'
        GROUP BY ym
        ORDER BY ym
    """).fetchall()

    conn.close()

    months_list = []
    month_names_cz = {
        "01": "Leden", "02": "Únor", "03": "Březen", "04": "Duben",
        "05": "Květen", "06": "Červen", "07": "Červenec", "08": "Srpen",
        "09": "Září", "10": "Říjen", "11": "Listopad", "12": "Prosinec"
    }

    total_2026_bars = 0
    unlocked_bars = 0

    for ym, cnt, d_min, d_max, p_low, p_high in months_query:
        m_code = ym.split("-")[1]
        m_name = f"{month_names_cz.get(m_code, m_code)} 2026"
        status = existing_locks.get(ym, "LOCKED")
        total_2026_bars += cnt
        if status == "UNLOCKED":
            unlocked_bars += cnt

        months_list.append({
            "month": ym,
            "title": m_name,
            "status": status,
            "bars_count": cnt,
            "start_datetime": d_min,
            "end_datetime": d_max,
            "price_range": {
                "low": round(p_low, 3) if p_low else None,
                "high": round(p_high, 3) if p_high else None
            },
            "unlocked_at": None if status == "LOCKED" else datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        })

    manifest = {
        "asset": "Silver (XAG/USD Spot CFD / Micro Silver SIL)",
        "database_file": DB_PATH,
        "last_updated": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        "in_sample_baseline": {
            "period": "2021-10-13 až 2025-12-31 (4 roky a 3 měsíce)",
            "status": "UNLOCKED_BASELINE_TRAINING",
            "start_datetime": in_min,
            "end_datetime": in_max,
            "bars_count": in_cnt,
            "role": "Základní trénování parametrů modelu (HMM režimy, ATR, Kelly koeficienty)"
        },
        "out_of_sample_2026": {
            "policy": "LOCKED_SEQUENTIAL_WALKFORWARD",
            "description": "Rok 2026 je uzamčený. Odkrývá se po měsících pro out-of-sample evaluaci a inkrementální dotrénování.",
            "total_bars_2026": total_2026_bars,
            "total_unlocked_bars": unlocked_bars,
            "months_count": len(months_list),
            "unlocked_months_count": sum(1 for m in months_list if m["status"] == "UNLOCKED"),
            "months": months_list
        }
    }

    safe_json_write(MANIFEST_PATH, manifest)
    return manifest


def unlock_month(ym: str) -> bool:
    """Odemkne zvolený měsíc roku 2026 pro walk-forward evaluaci a dotrénování."""
    manifest = build_or_refresh_manifest(force_relock=False)
    months = manifest["out_of_sample_2026"]["months"]
    found = False

    for m in months:
        if m["month"] == ym:
            m["status"] = "UNLOCKED"
            m["unlocked_at"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
            found = True
            break

    if found:
        manifest["out_of_sample_2026"]["unlocked_months_count"] = sum(1 for m in months if m["status"] == "UNLOCKED")
        manifest["out_of_sample_2026"]["total_unlocked_bars"] = sum(m["bars_count"] for m in months if m["status"] == "UNLOCKED")
        safe_json_write(MANIFEST_PATH, manifest)
        return True
    return False


def lock_month(ym: str) -> bool:
    """Znovu uzamkne zvolený měsíc."""
    manifest = build_or_refresh_manifest(force_relock=False)
    months = manifest["out_of_sample_2026"]["months"]
    found = False

    for m in months:
        if m["month"] == ym:
            m["status"] = "LOCKED"
            m["unlocked_at"] = None
            found = True
            break

    if found:
        manifest["out_of_sample_2026"]["unlocked_months_count"] = sum(1 for m in months if m["status"] == "UNLOCKED")
        manifest["out_of_sample_2026"]["total_unlocked_bars"] = sum(m["bars_count"] for m in months if m["status"] == "UNLOCKED")
        safe_json_write(MANIFEST_PATH, manifest)
        return True
    return False


def lock_all_months() -> None:
    """Uzamkne všechny měsíce roku 2026 zpět do výchozího stavu."""
    build_or_refresh_manifest(force_relock=True)


def print_manifest_dashboard(manifest: Dict[str, Any]):
    """Vytiskne přehledný stav rozdělení dat In-Sample a uzamčených měsíců 2026."""
    ins = manifest["in_sample_baseline"]
    oos = manifest["out_of_sample_2026"]

    print("\n" + "=" * 78)
    print("🥈 MANIFEST ROZDĚLENÍ HISTORIE STŘÍBRA (IN-SAMPLE vs UZAMČENÝ ROK 2026)")
    print("=" * 78)
    print(f"📦 Aktivum:            {manifest['asset']}")
    print(f"📁 Databáze:           {manifest['database_file']}")
    print(f"🕒 Poslední revize:    {manifest['last_updated']}")
    print("-" * 78)
    print("🟢 [IN-SAMPLE BASELINE] (Odemčeno pro základní trénování):")
    print(f"   Rozsah:            {ins['start_datetime']}  ➔  {ins['end_datetime']}")
    print(f"   Počet svíček M1:   {ins['bars_count']:,} svíček (cca 4.25 roku)")
    print(f"   Použití:           {ins['role']}")
    print("-" * 78)
    print(f"🔒 [OUT-OF-SAMPLE 2026] ({oos['unlocked_months_count']} / {oos['months_count']} měsíců odemčeno | celkem {oos['total_bars_2026']:,} svíček):")
    print(f"   Pravidlo: Postupné odkrývání měsíc po měsíci pro walk-forward evaluaci a dotrénování.")
    print("")
    print(f"{'MĚSÍC':<10} | {'NÁZEV':<14} | {'STAV':<13} | {'SVÍČEK M1':>10} | {'ROZSAH DAT':<33} | {'CENA (L/H)':<13}")
    print("-" * 105)

    for m in oos["months"]:
        st_icon = "🟢 ODEMČENO" if m["status"] == "UNLOCKED" else "🔒 UZAMČENO"
        p = m["price_range"]
        pr_str = f"${p['low']:.2f} - ${p['high']:.2f}" if p.get('low') else "–"
        date_str = f"{m['start_datetime'][:16]} ➔ {m['end_datetime'][:16]}"
        print(f"{m['month']:<10} | {m['title']:<14} | {st_icon:<13} | {m['bars_count']:>10,} | {date_str:<33} | {pr_str:<13}")

    print("=" * 105)
    print("Příkazy pro správu:")
    print("  python silver_walkforward_manager.py --unlock 2026-01   (odemkne Leden 2026)")
    print("  python silver_walkforward_manager.py --lock 2026-01     (znovu uzamkne Leden 2026)")
    print("  python silver_walkforward_manager.py --lock-all         (uzamkne celý rok 2026)")
    print("=" * 105 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Správce rozdělení a uzamčení dat Stříbra 2026")
    parser.add_argument("--status", action="store_true", help="Zobrazí přehledový dashboard")
    parser.add_argument("--unlock", type=str, help="Odemkne zadaný měsíc (např. 2026-01)")
    parser.add_argument("--lock", type=str, help="Uzamkne zadaný měsíc (např. 2026-01)")
    parser.add_argument("--lock-all", action="store_true", help="Uzamkne všechny měsíce roku 2026")
    parser.add_argument("--refresh", action="store_true", help="Aktualizuje počty svíček z databáze")

    args = parser.parse_args()

    if args.unlock:
        ok = unlock_month(args.unlock)
        print(f"Odemčení {args.unlock}: {'ÚSPĚŠNÉ ✅' if ok else 'CHYBA (měsíc nenalezen) ❌'}")
    elif args.lock:
        ok = lock_month(args.lock)
        print(f"Uzamčení {args.lock}: {'ÚSPĚŠNÉ 🔒' if ok else 'CHYBA ❌'}")
    elif args.lock_all:
        lock_all_months()
        print("Všechny měsíce roku 2026 byly UZAMČENY 🔒.")
    
    manifest = build_or_refresh_manifest()
    print_manifest_dashboard(manifest)


if __name__ == "__main__":
    main()
