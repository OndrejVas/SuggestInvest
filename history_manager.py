import os
import json
import sqlite3
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

logger = logging.getLogger("HistoryManager")

HISTORY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "history")
DB_FILE = os.path.join(HISTORY_DIR, "history.db")


def init_history_storage() -> None:
    """Zajistí existenci adresáře data/history a inicializuje tabulky v SQLite databázi."""
    os.makedirs(HISTORY_DIR, exist_ok=True)
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS scans (
                scan_id TEXT PRIMARY KEY,
                scan_date TEXT,
                timestamp_utc TEXT,
                timestamp_cet TEXT,
                scan_duration TEXT,
                model_name TEXT,
                total_assets INTEGER,
                buy_count INTEGER,
                hold_count INTEGER,
                sell_count INTEGER
            );
            """)

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS signal_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_id TEXT,
                scan_date TEXT,
                xtb_symbol TEXT,
                yahoo_symbol TEXT,
                name TEXT,
                asset_type TEXT,
                tier TEXT,
                currency TEXT,
                price REAL,
                change_pct REAL,
                target_mean REAL,
                target_upside_pct REAL,
                days_to_earnings INTEGER,
                days_to_ex_dividend INTEGER,
                delta_1m REAL,
                delta_3m REAL,
                signal TEXT,
                signal_rank INTEGER,
                probability INTEGER,
                impact_direction TEXT,
                time_horizon TEXT,
                catalyst_event TEXT,
                reasoning TEXT,
                FOREIGN KEY (scan_id) REFERENCES scans(scan_id)
            );
            """)

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sig_sym ON signal_history(yahoo_symbol, scan_date);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_scan_date ON scans(scan_date);")
            conn.commit()
    except Exception as e:
        logger.warning(f"Chyba při inicializaci SQLite databáze {DB_FILE}: {e}")


def save_scan_history(cards: List[Dict[str, Any]], scan_meta: Dict[str, Any]) -> str:
    """
    Uloží denní snapshot:
    1. Do neměnného JSON souboru data/history/YYYY-MM-DD.json (Data Lake)
    2. Do relační časové řady history.db (SQLite)
    """
    init_history_storage()

    now_utc = datetime.now(timezone.utc)
    scan_date = now_utc.strftime("%Y-%m-%d")
    scan_id = scan_meta.get("scan_id") or f"scan_{now_utc.strftime('%Y%m%d_%H%M%S')}"

    # 1. Uložení JSON snapshotu
    json_path = os.path.join(HISTORY_DIR, f"{scan_date}.json")
    snapshot_payload = {
        "metadata": {
            "scan_id": scan_id,
            "scan_date": scan_date,
            "timestamp_utc": scan_meta.get("timestamp_utc", now_utc.strftime("%Y-%m-%d %H:%M:%S")),
            "timestamp_cet": scan_meta.get("timestamp_cet", ""),
            "scan_duration": scan_meta.get("scan_duration", ""),
            "ai_model": scan_meta.get("ai_model", ""),
            "total_assets": len(cards),
            "counts": scan_meta.get("counts", {}),
        },
        "cards": cards,
    }

    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(snapshot_payload, f, indent=2, ensure_ascii=False)
        logger.info(f"Denní JSON snapshot byl úspěšně uložen do: {json_path}")
    except Exception as e:
        logger.warning(f"Chyba při ukládání JSON snapshotu {json_path}: {e}")

    # 2. Uložení do SQLite
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            counts = scan_meta.get("counts", {})
            cursor.execute("""
            INSERT OR REPLACE INTO scans 
            (scan_id, scan_date, timestamp_utc, timestamp_cet, scan_duration, model_name, total_assets, buy_count, hold_count, sell_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                scan_id,
                scan_date,
                scan_meta.get("timestamp_utc", now_utc.strftime("%Y-%m-%d %H:%M:%S")),
                scan_meta.get("timestamp_cet", ""),
                scan_meta.get("scan_duration", ""),
                scan_meta.get("ai_model", ""),
                len(cards),
                counts.get("buy", 0),
                counts.get("hold", 0),
                counts.get("sell", 0)
            ))

            # Vymazání případného staršího záznamu se stejným scan_id před vložením
            cursor.execute("DELETE FROM signal_history WHERE scan_id = ?", (scan_id,))

            rows_to_insert = []
            for c in cards:
                rows_to_insert.append((
                    scan_id,
                    scan_date,
                    c.get("xtb_symbol", ""),
                    c.get("yahoo_symbol", ""),
                    c.get("name", ""),
                    c.get("asset_type", "AKCIE"),
                    c.get("tier", "MID"),
                    c.get("currency", "USD"),
                    float(c.get("price_raw", 0.0)),
                    float(c.get("change_pct_raw", 0.0)),
                    float(c.get("target_mean_raw", -9999.0)) if c.get("target_mean_raw") != -9999.0 else None,
                    float(c.get("target_upside_raw", -9999.0)) if c.get("target_upside_raw") != -9999.0 else None,
                    c.get("days_to_earnings"),
                    c.get("days_to_ex_dividend"),
                    c.get("delta_1m"),
                    c.get("delta_3m"),
                    c.get("signal", "Hold"),
                    int(c.get("signal_rank", 3)),
                    int(c.get("probability", 50)),
                    c.get("impact_direction", "up"),
                    c.get("time_horizon", "1-3 měsíce"),
                    c.get("catalyst_event", ""),
                    c.get("reasoning", "")
                ))

            cursor.executemany("""
            INSERT INTO signal_history (
                scan_id, scan_date, xtb_symbol, yahoo_symbol, name, asset_type, tier, currency,
                price, change_pct, target_mean, target_upside_pct, days_to_earnings, days_to_ex_dividend,
                delta_1m, delta_3m, signal, signal_rank, probability, impact_direction,
                time_horizon, catalyst_event, reasoning
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows_to_insert)

            conn.commit()
            logger.info(f"Do SQLite databáze {DB_FILE} bylo uloženo {len(rows_to_insert)} záznamů signálů.")
    except Exception as e:
        logger.warning(f"Chyba při zápisu do SQLite {DB_FILE}: {e}")

    return json_path


def get_ticker_signal_history(yahoo_symbol: str, limit: int = 4) -> List[Dict[str, Any]]:
    """Vrátí chronologickou historii signálů pro daný ticker (pro minitrend v tooltipu)."""
    if not os.path.exists(DB_FILE):
        return []
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT scan_date, signal, probability, price, impact_direction
            FROM signal_history
            WHERE UPPER(yahoo_symbol) = UPPER(?)
            ORDER BY scan_date DESC, id DESC
            LIMIT ?
            """, (yahoo_symbol, limit))
            rows = cursor.fetchall()
            # Obrátíme chronologicky od nejstaršího po nejnovější pro vizuální šipku
            history = []
            for r in reversed(rows):
                history.append({
                    "date": r[0],
                    "signal": r[1],
                    "probability": r[2],
                    "price": r[3],
                    "impact_direction": r[4]
                })
            return history
    except Exception as e:
        logger.debug(f"Chyba při dotazu na historii pro {yahoo_symbol}: {e}")
        return []


def get_available_scan_dates() -> List[str]:
    """Vrátí seznam všech dostupných dat skenů pro přepínač archivu v záhlaví."""
    if not os.path.exists(DB_FILE):
        return []
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT scan_date FROM scans ORDER BY scan_date DESC;")
            return [row[0] for row in cursor.fetchall()]
    except Exception as e:
        logger.debug(f"Chyba při zjišťování dostupných dat skenů: {e}")
        return []
