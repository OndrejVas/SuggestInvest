import os
import json
import sqlite3
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple

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
                strong_buy_count INTEGER DEFAULT 0,
                buy_count INTEGER,
                hold_count INTEGER,
                sell_count INTEGER,
                strong_sell_count INTEGER DEFAULT 0
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
                confidence INTEGER,
                impact_direction TEXT,
                time_horizon TEXT,
                catalyst_event TEXT,
                catalysts TEXT,
                invalidation_price REAL,
                reasoning TEXT,
                FOREIGN KEY (scan_id) REFERENCES scans(scan_id)
            );
            """)

            # Migrace existující databáze, pokud sloupce chybí
            for col_sql in [
                "ALTER TABLE signal_history ADD COLUMN invalidation_price REAL;",
                "ALTER TABLE signal_history ADD COLUMN catalysts TEXT;",
                "ALTER TABLE signal_history ADD COLUMN confidence INTEGER;",
                "ALTER TABLE scans ADD COLUMN strong_buy_count INTEGER DEFAULT 0;",
                "ALTER TABLE scans ADD COLUMN strong_sell_count INTEGER DEFAULT 0;"
            ]:
                try:
                    cursor.execute(col_sql)
                except sqlite3.OperationalError:
                    pass

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
            (scan_id, scan_date, timestamp_utc, timestamp_cet, scan_duration, model_name, total_assets, strong_buy_count, buy_count, hold_count, sell_count, strong_sell_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                scan_id,
                scan_date,
                scan_meta.get("timestamp_utc", now_utc.strftime("%Y-%m-%d %H:%M:%S")),
                scan_meta.get("timestamp_cet", ""),
                scan_meta.get("scan_duration", ""),
                scan_meta.get("ai_model", ""),
                len(cards),
                counts.get("strong_buy", 0),
                counts.get("buy", 0),
                counts.get("hold", 0),
                counts.get("sell", 0),
                counts.get("strong_sell", 0)
            ))

            # Vymazání případného staršího záznamu se stejným scan_id před vložením
            cursor.execute("DELETE FROM signal_history WHERE scan_id = ?", (scan_id,))

            rows_to_insert = []
            for c in cards:
                conf_val = c.get("confidence")
                if conf_val is None:
                    conf_val = c.get("probability", 50)

                cat_list = c.get("catalysts")
                if isinstance(cat_list, list):
                    cat_str = json.dumps(cat_list, ensure_ascii=False)
                elif isinstance(cat_list, str):
                    cat_str = cat_list
                elif c.get("catalyst_event"):
                    cat_str = json.dumps([c["catalyst_event"]], ensure_ascii=False)
                else:
                    cat_str = "[]"

                inv_price = c.get("invalidation_price")
                inv_price_float = float(inv_price) if inv_price is not None and inv_price != "" else None

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
                    c.get("signal", "HOLD"),
                    int(c.get("signal_rank", 3)),
                    int(conf_val),
                    int(conf_val),
                    c.get("impact_direction", "▲ Růst"),
                    c.get("time_horizon", "1-3 měsíce"),
                    c.get("catalyst_event", ""),
                    cat_str,
                    inv_price_float,
                    c.get("reasoning", "")
                ))

            cursor.executemany("""
            INSERT INTO signal_history (
                scan_id, scan_date, xtb_symbol, yahoo_symbol, name, asset_type, tier, currency,
                price, change_pct, target_mean, target_upside_pct, days_to_earnings, days_to_ex_dividend,
                delta_1m, delta_3m, signal, signal_rank, probability, confidence, impact_direction,
                time_horizon, catalyst_event, catalysts, invalidation_price, reasoning
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows_to_insert)

            conn.commit()
            logger.info(f"Do SQLite databáze {DB_FILE} bylo uloženo {len(rows_to_insert)} záznamů signálů.")
    except Exception as e:
        logger.warning(f"Chyba při zápisu do SQLite {DB_FILE}: {e}")

    return json_path


def get_ticker_historical_context(yahoo_symbol: str, current_target_mean: Optional[float] = None) -> Dict[str, Any]:
    """
    Vrátí historický kontext pro obohacení AI promptu:
    - prev_signal: poslední signál (default: 'HOLD')
    - prev_confidence: poslední konfidence (default: 50)
    - confidence_delta_7d: posun konfidence za 7 dní
    - delta_target_30d_pct: procentuální změna konsenzuální cílové ceny za 30 dní
    """
    default_ctx = {
        "prev_signal": "HOLD",
        "prev_confidence": 50,
        "confidence_delta_7d": 0,
        "delta_target_30d_pct": 0.0
    }
    if not os.path.exists(DB_FILE):
        return default_ctx

    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("""
            SELECT signal, COALESCE(confidence, probability, 50), target_mean, scan_date
            FROM signal_history
            WHERE UPPER(yahoo_symbol) = UPPER(?)
            ORDER BY scan_date DESC, id DESC
            LIMIT 10
            """, (yahoo_symbol,))
            rows = cursor.fetchall()
            if not rows:
                return default_ctx

            prev_sig = rows[0][0] or "HOLD"
            prev_conf = rows[0][1] if rows[0][1] is not None else 50

            conf_7d_ago = prev_conf
            if len(rows) > 1:
                conf_7d_ago = rows[-1][1] if rows[-1][1] is not None else prev_conf
            confidence_delta_7d = prev_conf - conf_7d_ago

            delta_target_30d_pct = 0.0
            if current_target_mean is not None and current_target_mean > 0:
                for r in reversed(rows):
                    past_target = r[2]
                    if past_target is not None and past_target > 0:
                        delta_target_30d_pct = round(((current_target_mean - past_target) / past_target) * 100, 2)
                        break

            return {
                "prev_signal": prev_sig,
                "prev_confidence": int(prev_conf),
                "confidence_delta_7d": int(confidence_delta_7d),
                "delta_target_30d_pct": float(delta_target_30d_pct)
            }
    except Exception as e:
        logger.debug(f"Chyba při zjišťování historického kontextu pro {yahoo_symbol}: {e}")
        return default_ctx


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


SIGNAL_RANK_MAP = {
    "STRONG BUY": 5,
    "BUY": 4,
    "HOLD": 3,
    "SELL": 2,
    "STRONG SELL": 1
}


def compute_daily_changes(
    cards: List[Dict[str, Any]], 
    current_scan_id: Optional[str] = None,
    current_scan_date: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Porovná aktuální sadu karet s referenčním předchozím skenem (z předchozího dne, 
    popř. nejnovějším starším skenem v SQLite history.db).
    
    Pro každé aktivum spočítá strukturu 'daily_change':
    - is_changed: bool
    - change_type: 'UPGRADE' | 'DOWNGRADE' | 'CONFIDENCE_JUMP' | 'CONFIDENCE_DROP' | 'TARGET_SHIFT' | 'NEW_CATALYST' | 'NEW_ASSET' | 'UNCHANGED'
    - change_badge: string (např. '⬆️ UPGRADE', '⬇️ DOWNGRADE', '⚡ +12% CONF')
    - badge_class: CSS třída (např. 'badge-upgrade', 'badge-downgrade')
    - change_color: hex kód pro zvýraznění
    - prev_signal: původní signál
    - curr_signal: aktuální signál
    - rank_diff: posun v hodnocení (+1, -1, ...)
    - conf_diff: posun v konfidenci (+12, -8, ...)
    - change_desc: česky psaný srozumitelný popis do tooltipu
    - prev_date_str: datum/čas referenčního skenu
    
    Vrací: (obohacené karty, statistiky změn)
    """
    default_stats = {
        "total_changed": 0,
        "upgrades": 0,
        "downgrades": 0,
        "conf_jumps": 0,
        "prev_scan_date": "—",
        "prev_scan_time": "—"
    }

    if not os.path.exists(DB_FILE):
        for c in cards:
            c["daily_change"] = {
                "is_changed": False,
                "change_type": "UNCHANGED",
                "change_badge": "",
                "badge_class": "",
                "change_color": "#94a3b8",
                "prev_signal": c.get("signal", "HOLD"),
                "curr_signal": c.get("signal", "HOLD"),
                "rank_diff": 0,
                "conf_diff": 0,
                "prev_conf": c.get("confidence", 50),
                "curr_conf": c.get("confidence", 50),
                "change_desc": "První sken v historii.",
                "prev_date_str": "—"
            }
        return cards, default_stats

    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT scan_id, scan_date, timestamp_utc, timestamp_cet FROM scans ORDER BY timestamp_utc DESC")
            all_scans = cursor.fetchall()
            if not all_scans:
                return cards, default_stats

            # Vybereme referenční sken:
            # 1. Filtrujeme aktuální sken, pokud je zadán
            candidate_scans = [s for s in all_scans if s[0] != current_scan_id]
            
            # 2. Přednostně hledáme sken z dřívějšího data (včerejšek či starší)
            ref_scan = None
            if current_scan_date:
                prev_date_scans = [s for s in candidate_scans if s[1] < current_scan_date]
                if prev_date_scans:
                    ref_scan = prev_date_scans[0]

            # 3. Pokud není starší datum (např. testování v rámci jednoho dne), vezmeme nejnovější předcházející sken
            if ref_scan is None and candidate_scans:
                ref_scan = candidate_scans[0]

            if ref_scan is None:
                # Žádný starší sken k porovnání
                for c in cards:
                    c["daily_change"] = {
                        "is_changed": False,
                        "change_type": "UNCHANGED",
                        "change_badge": "",
                        "badge_class": "",
                        "change_color": "#94a3b8",
                        "prev_signal": c.get("signal", "HOLD"),
                        "curr_signal": c.get("signal", "HOLD"),
                        "rank_diff": 0,
                        "conf_diff": 0,
                        "prev_conf": c.get("confidence", 50),
                        "curr_conf": c.get("confidence", 50),
                        "change_desc": "Výchozí sken.",
                        "prev_date_str": "—"
                    }
                return cards, default_stats

            ref_scan_id, ref_scan_date, ref_scan_utc, ref_scan_cet = ref_scan
            ref_date_display = ref_scan_cet if ref_scan_cet else (ref_scan_date or ref_scan_utc)

            cursor.execute("""
            SELECT yahoo_symbol, signal, signal_rank, COALESCE(confidence, probability, 50),
                   target_mean, target_upside_pct, catalysts
            FROM signal_history
            WHERE scan_id = ?
            """, (ref_scan_id,))
            rows = cursor.fetchall()

            prev_data_by_sym = {}
            for r in rows:
                sym = (r[0] or "").upper().strip()
                cats = []
                if r[6]:
                    try:
                        cats = json.loads(r[6]) if r[6].startswith("[") else [r[6]]
                    except Exception:
                        cats = [r[6]]
                
                sig_raw = (r[1] or "HOLD").upper().strip()
                prev_data_by_sym[sym] = {
                    "signal": sig_raw,
                    "signal_rank": r[2] if r[2] is not None else SIGNAL_RANK_MAP.get(sig_raw, 3),
                    "confidence": int(r[3]) if r[3] is not None else 50,
                    "target_mean": r[4],
                    "target_upside_pct": r[5],
                    "catalysts": cats
                }

            total_changed = 0
            upgrades = 0
            downgrades = 0
            conf_jumps = 0

            for card in cards:
                sym = (card.get("yahoo_symbol") or "").upper().strip()
                curr_sig = (card.get("signal") or "HOLD").upper().strip()
                curr_rank = card.get("signal_rank") or SIGNAL_RANK_MAP.get(curr_sig, 3)
                curr_conf = card.get("confidence")
                if curr_conf is None:
                    curr_conf = card.get("probability", 50)
                curr_upside = card.get("target_upside_raw")
                curr_cats = set(card.get("catalysts") or [])

                if sym not in prev_data_by_sym:
                    # Titul nebyl v předchozím skenu
                    daily_change = {
                        "is_changed": True,
                        "change_type": "NEW_ASSET",
                        "change_badge": "✨ NOVÉ",
                        "badge_class": "badge-new-asset",
                        "change_color": "#60a5fa",
                        "prev_signal": None,
                        "curr_signal": curr_sig,
                        "rank_diff": 0,
                        "conf_diff": 0,
                        "prev_conf": None,
                        "curr_conf": curr_conf,
                        "change_desc": f"Titul nově zařazen do monitoringu se signálem {curr_sig} (konfidence {curr_conf} %).",
                        "prev_date_str": ref_date_display
                    }
                    total_changed += 1
                else:
                    prev = prev_data_by_sym[sym]
                    prev_sig = prev["signal"]
                    prev_rank = prev["signal_rank"]
                    prev_conf = prev["confidence"]
                    prev_upside = prev["target_upside_pct"]
                    prev_cats = set(prev["catalysts"] or [])
                    new_cats = curr_cats - prev_cats

                    rank_diff = curr_rank - prev_rank
                    conf_diff = curr_conf - prev_conf

                    is_changed = False
                    change_type = "UNCHANGED"
                    change_badge = ""
                    badge_class = ""
                    change_color = "#94a3b8"
                    desc = f"Signál {curr_sig} beze změny oproti předchozímu skenu ({ref_date_display})."

                    if rank_diff > 0:
                        is_changed = True
                        change_type = "UPGRADE"
                        change_badge = "⬆️ UPGRADE"
                        badge_class = "badge-upgrade"
                        change_color = "#34d399"
                        desc = f"Zvýšení doporučení z {prev_sig} na {curr_sig}."
                        if conf_diff != 0:
                            desc += f" Konfidence vzrostla na {curr_conf} % ({conf_diff:+d} b.p.)."
                        if new_cats:
                            desc += f" Nový katalyzátor: {', '.join(list(new_cats)[:2])}."
                        upgrades += 1
                    elif rank_diff < 0:
                        is_changed = True
                        change_type = "DOWNGRADE"
                        change_badge = "⬇️ DOWNGRADE"
                        badge_class = "badge-downgrade"
                        change_color = "#f87171"
                        desc = f"Snížení doporučení z {prev_sig} na {curr_sig}."
                        if conf_diff != 0:
                            desc += f" Konfidence se změnila na {curr_conf} % ({conf_diff:+d} b.p.)."
                        downgrades += 1
                    elif conf_diff >= 10:
                        is_changed = True
                        change_type = "CONFIDENCE_JUMP"
                        change_badge = f"⚡ +{conf_diff}% CONF"
                        badge_class = "badge-conf-up"
                        change_color = "#22d3ee"
                        desc = f"Výrazné posílení konfidence signálu {curr_sig} z {prev_conf} % na {curr_conf} % (+{conf_diff} b.p.)."
                        conf_jumps += 1
                    elif conf_diff <= -10:
                        is_changed = True
                        change_type = "CONFIDENCE_DROP"
                        change_badge = f"⚠️ {conf_diff}% CONF"
                        badge_class = "badge-conf-down"
                        change_color = "#fbbf24"
                        desc = f"Pokles konfidence signálu {curr_sig} z {prev_conf} % na {curr_conf} % ({conf_diff} b.p.)."
                        conf_jumps += 1
                    elif (prev_upside is not None and curr_upside not in (-9999.0, None) and abs(curr_upside - prev_upside) >= 8.0):
                        diff_upside = curr_upside - prev_upside
                        is_changed = True
                        change_type = "TARGET_SHIFT"
                        change_badge = f"🎯 {diff_upside:+.0f}% CÍL"
                        badge_class = "badge-target-shift"
                        change_color = "#c084fc"
                        desc = f"Posun konsenzuálního růstového potenciálu k cílové ceně analytiků z {prev_upside:+.1f} % na {curr_upside:+.1f} % ({diff_upside:+.1f} b.p.)."
                    elif new_cats:
                        is_changed = True
                        change_type = "NEW_CATALYST"
                        change_badge = "🔥 KATALYZÁTOR"
                        badge_class = "badge-new-catalyst"
                        change_color = "#f472b6"
                        desc = f"Aktivován nový předstihový katalyzátor: {', '.join(list(new_cats)[:2])}."
                    
                    if is_changed:
                        total_changed += 1

                    daily_change = {
                        "is_changed": is_changed,
                        "change_type": change_type,
                        "change_badge": change_badge,
                        "badge_class": badge_class,
                        "change_color": change_color,
                        "prev_signal": prev_sig,
                        "curr_signal": curr_sig,
                        "rank_diff": rank_diff,
                        "conf_diff": conf_diff,
                        "prev_conf": prev_conf,
                        "curr_conf": curr_conf,
                        "change_desc": desc,
                        "prev_date_str": ref_date_display
                    }

                card["daily_change"] = daily_change

            stats = {
                "total_changed": total_changed,
                "upgrades": upgrades,
                "downgrades": downgrades,
                "conf_jumps": conf_jumps,
                "prev_scan_date": ref_scan_date,
                "prev_scan_time": ref_date_display
            }
            return cards, stats

    except Exception as e:
        logger.warning(f"Chyba při výpočtu denních změn v history_manager: {e}")
        return cards, default_stats
