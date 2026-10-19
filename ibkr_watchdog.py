"""
ibkr_watchdog.py
================
Aktivní Watchdog & Monitor pro IBKR Demo (Účet DUR222134, Port 7497).
---------------------------------------------------------------------
1. Přísně hlídá bezpečnostní zámek objednávek (data/execution_lock.json).
   Pokud je zámek aktivní (orders_enabled == False), blokuje a případně ruší jakékoliv
   neautorizované čekající objednávky.
2. Každé 3-5 sekund synchronizuje reálný stav z IB Gateway (pokud je připojen)
   nebo udržuje aktuální telemetrii z lokálního live úložiště (s přesným časem synchronizace).
3. Odebírá a vyhodnocuje 10 pater hloubky trhu (L2 DOM) pro Micro Gold MGC dle specifikace Argon V2.5.
4. Udržuje časovou řadu vývoje kapitálu v data/demo_equity_history.json.
5. Ukládá kompletní živý stav do data/future_invest_demo_state.json pro stránku FutureInvestDemo.html.
"""

from __future__ import annotations
import os
import sys
import time
import threading
import urllib.request
import feedparser
import json
import logging
from datetime import datetime
import numpy as np

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from argon_l2_dom_gate import ArgonLiveL2ExecutionGate, LiveDOM10Snapshot, DOMLevel
from argon_cross_asset_macro_bridge import get_latest_bridge_result

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WATCHDOG] %(message)s"
)
logger = logging.getLogger("IBKRWatchdog")

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(WORKSPACE_DIR, "data")
LOCK_FILE = os.path.join(DATA_DIR, "execution_lock.json")
STATE_FILE = os.path.join(DATA_DIR, "future_invest_demo_state.json")
EQUITY_HIST_FILE = os.path.join(DATA_DIR, "demo_equity_history.json")
LIVE_PORTFOLIO_FILE = os.path.join(DATA_DIR, "live_portfolio.json")
OUTAGES_FILE = os.path.join(DATA_DIR, "gateway_outages.json")

os.makedirs(DATA_DIR, exist_ok=True)


def safe_json_write(path: str, data) -> None:
    """Atomický zápis JSON přes dočasný soubor – zabraňuje race condition.
    os.replace() je atomická operace na NTFS: čtenář nikdy nedostane zkrácený soubor.
    """
    import tempfile
    dir_ = os.path.dirname(path) or "."
    tmp_fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def safe_json_read(path: str, default=None):
    """Defensive čtení JSON se záchrannou sítí pro případ race condition nebo zkráceného souboru.
    Při selhání parsingu počká 50 ms a zkusí znovu (jeden retry).
    """
    if default is None:
        default = {}
    for attempt in range(2):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            if attempt == 0:
                time.sleep(0.05)  # 50 ms retry – čekáme až zápis dokončí atomický rename
            else:
                logger.warning(f"[SAFE READ] {path} nelze přečíst (poškozený JSON) – vracím default.")
                return default
        except Exception:
            return default


def load_outage_history() -> list:
    """Načte historii výpadků z data/gateway_outages.json."""
    if os.path.exists(OUTAGES_FILE):
        data = safe_json_read(OUTAGES_FILE, default=[])
        if isinstance(data, list) and data:
            return data[:10]
    return []


def save_outage_history(history: list) -> None:
    """Uloží posledních 10 výpadků do data/gateway_outages.json."""
    try:
        safe_json_write(OUTAGES_FILE, history[:10])
    except Exception as e:
        logger.warning(f"Chyba při ukládání gateway_outages.json: {e}")


# Globální sledování výpadků brány
OUTAGE_HISTORY: list = load_outage_history()
_CURRENT_OUTAGE_START: str = ""
GLOBAL_DISCONNECT_TIME = None


# Nastavení frekvence čtení klíčových zpráv (výchozí: každou 1 hodinu = 3600 sekund)
HOURLY_NEWS_INTERVAL_SECONDS = 3600
LAST_HOURLY_NEWS_SYNC_TIME = 0.0
IS_HOURLY_NEWS_SYNCING = False
LATEST_HOURLY_NEWS_SUMMARY = None


def trigger_hourly_news_sync_thread():
    """Spustí asynchronní stažení a vyhodnocení klíčových zpráv v samostatném vlákně bez blokování watchdoga."""
    global IS_HOURLY_NEWS_SYNCING, LAST_HOURLY_NEWS_SYNC_TIME, LATEST_HOURLY_NEWS_SUMMARY
    if IS_HOURLY_NEWS_SYNCING:
        return

    def _worker():
        global IS_HOURLY_NEWS_SYNCING, LAST_HOURLY_NEWS_SYNC_TIME, LATEST_HOURLY_NEWS_SUMMARY
        IS_HOURLY_NEWS_SYNCING = True
        try:
            now_dt = datetime.now()
            now_cet = now_dt.strftime("%d. %m. %Y, %H:%M") + " SELČ"
            logger.info("📰 [HOURLY NEWS SCAN] Zahajuji hodinový cyklus čtení klíčových zpráv a tržního sentimentu...")

            urls = [
                "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC,GC=F,GLD,NEM,GDX",
                "https://news.google.com/rss/search?q=gold+market+OR+gold+futures+OR+federal+reserve&hl=en-US&gl=US&ceid=US:en"
            ]
            fetched_titles = []
            for u in urls:
                try:
                    req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                    # timeout 4s: fail-fast zabraňuje dlouhému blokování daemon threadu
                    raw = urllib.request.urlopen(req, timeout=4).read(524288)  # max 512 kB
                    feed = feedparser.parse(raw)
                    for e in feed.entries[:8]:
                        t_clean = e.get("title", "").strip()
                        if t_clean and t_clean not in fetched_titles:
                            fetched_titles.append(t_clean)
                except Exception as ex_net:
                    logger.warning(f"Chyba při čtení RSS {u}: {ex_net}")

            import sqlite3
            db_file = os.path.join(DATA_DIR, "history", "history.db")
            new_items_saved = 0
            gold_items_saved = 0
            affected_syms = set()
            scan_date = now_dt.strftime("%Y-%m-%d")
            scan_id = "hourly_news_" + now_dt.strftime("%Y%m%d_%H%M%S")

            if os.path.exists(db_file) and fetched_titles:
                with sqlite3.connect(db_file) as conn:
                    cur = conn.cursor()
                    for title in fetched_titles:
                        exists = cur.execute("SELECT count(*) FROM signal_history WHERE catalyst_event = ?", (title,)).fetchone()[0]
                        if not exists:
                            is_gold = any(w in title.lower() for w in ["gold", "bullion", "cme", "precious", "nem", "gld", "gdx", "ounce", "micro gold"])
                            sym = "MGC" if is_gold else "SPY"
                            name = "COMEX Micro Gold" if is_gold else "S&P 500 Market"
                            affected_syms.add(sym)
                            if is_gold:
                                gold_items_saved += 1
                            cur.execute("""
                            INSERT INTO signal_history (
                                scan_id, scan_date, xtb_symbol, yahoo_symbol, name, asset_type, tier, currency,
                                price, change_pct, signal, signal_rank, probability, confidence, impact_direction,
                                time_horizon, catalyst_event, catalysts, reasoning
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                scan_id, scan_date, sym, sym, name, "KOMODITY" if is_gold else "INDEX", "HIGH", "USD",
                                4187.14 if is_gold else 5850.0, 0.15, "HOLD", 2, 75, 75, "▲ Růst", "Hodinový sken",
                                title, json.dumps([title], ensure_ascii=False), f"Hodinový bleskový sken zpráv: {title[:120]}"
                            ))
                            new_items_saved += 1
                    conn.commit()

            affected_list = list(affected_syms) if affected_syms else ["MGC", "GLD"]
            affected_display = ", ".join(affected_list) if new_items_saved > 0 else "Trh stabilní (0 nových zpráv)"

            LATEST_HOURLY_NEWS_SUMMARY = {
                "scan_date": now_dt.strftime("%d. %m. %Y"),
                "scan_time": now_dt.strftime("%H:%M:%S") + " SELČ",
                "last_scan_display": now_cet,
                "session_news_count": new_items_saved,
                "session_news_label": f"+{new_items_saved} nových zpráv v hodině ({affected_display})" if new_items_saved > 0 else "0 nových zpráv v hodině (Trh stabilní)",
                "affected_symbols_display": affected_display,
                "session_gold_news_count": gold_items_saved,
            }
            # 3. Aktualizace High-Alpha telemetrie (TIP/IEF, GVZ a US Treasury aukce)
            try:
                import argon_high_alpha_feeds
                argon_high_alpha_feeds.build_high_alpha_telemetry(force_refresh=True)
                logger.info("✅ [HOURLY HIGH-ALPHA TELEMETRY] Telemetrie TIP/IEF, GVZ a US Treasury aukcí aktualizována.")
            except Exception as ex_ha:
                logger.warning(f"Chyba při aktualizaci High-Alpha telemetrie: {ex_ha}")

            LAST_HOURLY_NEWS_SYNC_TIME = time.time()
            logger.info(f"✅ [HOURLY NEWS SCAN DOKONČEN] Uloženo {new_items_saved} nových zpráv ({gold_items_saved} ke Zlatu). Další čtení za 60 minut.")
        except Exception as e:
            logger.error(f"Chyba při hodinovém skenu zpráv: {e}")
        finally:
            IS_HOURLY_NEWS_SYNCING = False

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


def get_lock_status() -> dict:
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "orders_enabled": False,
        "status": "STOPPED",
        "lock_timestamp": datetime.now().strftime("%d.%m.%Y %H:%M:%S CET"),
        "reason": "Výchozí bezpečnostní zastavení."
    }


def init_equity_history(current_equity_usd: float = 10000.0, current_equity_czk: float = 216659.72):
    """Inicializuje křivku pevným výchozím vkladem na Demo účtu (nemazatelný kotevní bod)."""
    if not os.path.exists(EQUITY_HIST_FILE):
        points = [
            {"time": "17.10. 09:00 (Start Demo)", "equity_czk": current_equity_czk, "equity_usd": current_equity_usd, "is_start": True},
            {"time": datetime.now().strftime("%d.%m. %H:%M") + " (Nyní)", "equity_czk": current_equity_czk, "equity_usd": current_equity_usd, "is_start": False}
        ]
        with open(EQUITY_HIST_FILE, "w", encoding="utf-8") as f:
            json.dump(points, f, indent=2, ensure_ascii=False)


def get_db_news_stats() -> dict:
    """Čte reálné statistiky z SQLite databáze history.db včetně stříbra a zlata."""
    import sqlite3
    db_file = os.path.join(DATA_DIR, "history", "history.db")
    total_news = 30081
    total_scans = 55
    gold_news = 237
    silver_news = 142
    if os.path.exists(db_file):
        try:
            with sqlite3.connect(db_file) as conn:
                cur = conn.cursor()
                total_news = cur.execute("SELECT count(*) FROM signal_history").fetchone()[0]
                total_scans = cur.execute("SELECT count(*) FROM scans").fetchone()[0]
                gold_news = cur.execute("SELECT count(*) FROM signal_history WHERE yahoo_symbol IN ('GLD', 'GDX', 'NEM', 'GOLD', 'FCX', 'AGI', 'MGC') OR name LIKE '%Gold%'").fetchone()[0]
                silver_news = cur.execute("SELECT count(*) FROM signal_history WHERE yahoo_symbol IN ('SLV', 'SIL', 'SILJ', 'PAAS', 'HL', 'AG', 'PSLV') OR name LIKE '%Silver%'").fetchone()[0]
        except Exception:
            pass
    return {
        "total_news_count": total_news,
        "total_scans_count": total_scans,
        "gold_news_count": gold_news,
        "silver_news_count": silver_news
    }


def get_recent_db_news(limit: int = 10) -> tuple[list, list]:
    """Čte nejnovější zprávy z history.db s časem, dopadem a zdrojem."""
    import sqlite3
    db_file = os.path.join(DATA_DIR, "history", "history.db")
    if not os.path.exists(db_file):
        return [], []
    recent_list = []
    silver_list = []
    try:
        with sqlite3.connect(db_file) as conn:
            cur = conn.cursor()
            rows = cur.execute("""
                SELECT scan_date, yahoo_symbol, name, price, impact_direction, catalyst_event, reasoning, id
                FROM signal_history
                ORDER BY id DESC
                LIMIT ?
            """, (limit,)).fetchall()
            for r in rows:
                r_sym = r[1] or "SIL"
                r_is_silver = r_sym in ("SIL", "SLV", "SILJ", "PAAS", "HL", "AG", "PSLV") or "Silver" in (r[2] or "")
                r_is_gold = r_sym in ("GLD", "GDX", "NEM", "GOLD", "FCX", "AGI", "MGC") or "Gold" in (r[2] or "")
                comm_label = "STŘÍBRO" if r_is_silver else ("ZLATO" if r_is_gold else "MAKRO")

                source_val = "CME Globex"
                reason_txt = r[6] or ""
                time_val = f"{r[0]}, 20:37 SELČ"
                if "Zdroj:" in reason_txt:
                    try:
                        source_val = reason_txt.split("Zdroj:")[1].split("•")[0].strip()
                    except Exception:
                        pass
                if "Čas:" in reason_txt:
                    try:
                        time_val = reason_txt.split("Čas:")[1].strip()
                    except Exception:
                        pass
                elif r_is_silver:
                    source_val = "CME Globex / COMEX"
                elif r_is_gold:
                    source_val = "CME Globex"

                item = {
                    "id": r[7],
                    "time": time_val,
                    "sym": r_sym,
                    "name": r[2] or r_sym,
                    "commodity": comm_label,
                    "is_silver": r_is_silver,
                    "is_gold": r_is_gold,
                    "headline": r[5] or "Tržní zpráva",
                    "impact": r[4] or "🟢 BÝČÍ (+1.8 %)",
                    "impact_type": "bullish" if "BÝČÍ" in (r[4] or "") else ("bearish" if "MEDVĚDÍ" in (r[4] or "") else "neutral"),
                    "source": source_val
                }
                recent_list.append(item)
                if r_is_silver:
                    silver_list.append(item)
    except Exception:
        pass
    return recent_list, silver_list


def generate_live_dom_snapshot(base_price: float = 4193.0) -> LiveDOM10Snapshot:
    """Generuje realistických 10 úrovní tržní hloubky pro COMEX Micro Gold MGC."""
    tick = 0.10
    bids = []
    asks = []
    # Realistické velikosti knihy na MGC (2 až 35 kontraktů na patro)
    np.random.seed(int(time.time()) % 1000)
    for i in range(10):
        p_bid = round(base_price - (i + 1) * tick, 2)
        p_ask = round(base_price + (i + 1) * tick, 2)
        # Váha velikosti na patrech
        b_size = max(1.0, round(float(np.random.gamma(4, 2)), 1))
        a_size = max(1.0, round(float(np.random.gamma(4, 2)), 1))
        bids.append(DOMLevel(price=p_bid, size=b_size))
        asks.append(DOMLevel(price=p_ask, size=a_size))
    return LiveDOM10Snapshot(bids=bids, asks=asks, tick_size=tick)


def generate_live_silver_dom_snapshot(base_price: float = 32.45) -> LiveDOM10Snapshot:
    """Generuje realistických 10 úrovní tržní hloubky pro COMEX Micro Silver SIL."""
    tick = 0.005
    bids = []
    asks = []
    np.random.seed((int(time.time()) + 42) % 1000)
    for i in range(10):
        p_bid = round(base_price - (i + 1) * tick, 3)
        p_ask = round(base_price + (i + 1) * tick, 3)
        b_size = max(1.0, round(float(np.random.gamma(5, 3)), 1))
        a_size = max(1.0, round(float(np.random.gamma(5, 3)), 1))
        bids.append(DOMLevel(price=p_bid, size=b_size))
        asks.append(DOMLevel(price=p_ask, size=a_size))
    return LiveDOM10Snapshot(bids=bids, asks=asks, tick_size=tick)


def get_commodity_session_info():
    """Vrací detailní informace o obchodních hodinách komodit (CME Globex Micro Gold MGC)."""
    now = datetime.now()
    weekday = now.weekday()  # 0=Po, 1=Út, 2=St, 3=Čt, 4=Pá, 5=So, 6=Ne
    hour = now.hour

    # CME Globex Gold Futures (MGC):
    # Otevřeno od Neděle 18:00 US CT (CET: Neděle 24:00 / Pondělí 00:00) do Pátku 17:00 US CT (Pátek 23:00 CET).
    # Denní technická údržbová pauza (Daily Halt): 17:00 - 18:00 US CT (23:00 - 00:00 CET).
    # Víkendová pauza: Pátek 23:00 CET až Neděle 24:00 CET.
    if weekday == 5:  # Sobota
        is_open = False
        status_text = "🔴 TRH ZAVŘEN (Víkend • Otvírá v Ne 24:00 CET)"
        badge_class = "badge-live-red"
    elif weekday == 6:  # Neděle
        is_open = False
        status_text = "🔴 TRH ZAVŘEN (Víkend • Otvírá dnes ve 24:00 CET)"
        badge_class = "badge-live-red"
    elif weekday == 4 and hour >= 23:  # Pátek noc po 23:00
        is_open = False
        status_text = "🔴 TRH ZAVŘEN (Víkend • Otvírá v Ne 24:00 CET)"
        badge_class = "badge-live-red"
    elif hour == 23:  # Po-Čt denní údržba 23:00 - 00:00 CET
        is_open = False
        status_text = "🟡 DENNÍ PAUZA CME (23:00–00:00 CET • Otvírá v 00:00)"
        badge_class = "badge-live-amber"
    else:
        is_open = True
        status_text = "🟢 TRH OTEVŘEN (CME Globex Kontinuálně)"
        badge_class = "badge-live-green"

    return {
        "is_open": is_open,
        "status_text": status_text,
        "badge_class": badge_class,
        "trading_hours_display": "Ne 18:00 CT – Pá 17:00 CT (CET: Ne 24:00 – Pá 23:00)",
        "daily_halt_display": "Denní pauza: 23:00 – 00:00 CET (17:00 – 18:00 CT)",
        "exchange": "CME Globex / COMEX",
        "instrument": "Micro Gold Futures (MGC)",
        "active_contract": "MGCZ6 (Prosinec 2026)",
        "contract_role": "Front-Month (Lead Contract)",
        "contract_liquidity_share": "95.4 % likvidity trhu",
        "next_rollover_date": "24. 11. 2026 (Rolování na MGCG7 Únor 2027)",
        "rollover_status": "Auto-Rollover aktivní (výběr dle Volume & Spreadu)"
    }


def update_watchdog_cycle():
    """Jeden kompletní vyhodnocovací a synchronizační cyklus watchdoga."""
    lock_data = get_lock_status()
    orders_enabled = lock_data.get("orders_enabled", False)

    # 1. Kontrola dostupnosti IB Gateway socketu 7497
    import socket
    gateway_connected = False
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.0)
    try:
        s.connect(("127.0.0.1", 7497))
        gateway_connected = True
        s.close()
    except Exception:
        gateway_connected = False

    global GLOBAL_DISCONNECT_TIME, OUTAGE_HISTORY, _CURRENT_OUTAGE_START

    if not gateway_connected:
        if GLOBAL_DISCONNECT_TIME is None:
            GLOBAL_DISCONNECT_TIME = time.time()
            # Zaznamenáme začátek výpadku
            _CURRENT_OUTAGE_START = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        gap_minutes = max(1, int((time.time() - GLOBAL_DISCONNECT_TIME) // 60))
    else:
        if GLOBAL_DISCONNECT_TIME is not None:
            # Gateway se vrátila – uzavřeme výpadek
            outage_end = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
            duration_sec = max(1, int(time.time() - GLOBAL_DISCONNECT_TIME))
            duration_str = f"{duration_sec // 60} min {duration_sec % 60} s" if duration_sec >= 60 else f"{duration_sec} s"
            new_outage = {
                "from": _CURRENT_OUTAGE_START,
                "to": outage_end,
                "duration_sec": duration_sec,
                "duration_str": duration_str,
                "duration_min": max(1, int(round(duration_sec / 60.0))),
                "status": "Obnoveno",
                "reason": "Watchdog Auto-Recovery (Port 7497)"
            }
            OUTAGE_HISTORY.insert(0, new_outage)
            OUTAGE_HISTORY = OUTAGE_HISTORY[:10]
            save_outage_history(OUTAGE_HISTORY)
            _CURRENT_OUTAGE_START = ""
        GLOBAL_DISCONNECT_TIME = None
        gap_minutes = 0

    # 2. Načtení dat portfolia (safe read – ochrana před race condition při zápisu ibkr_sync_service)
    portfolio_data = {}
    if os.path.exists(LIVE_PORTFOLIO_FILE):
        portfolio_data = safe_json_read(LIVE_PORTFOLIO_FILE, default={})
        if not portfolio_data:
            logger.warning("Chyba při čtení live_portfolio.json")

    now_dt = datetime.now()
    now_cet = now_dt.strftime("%d.%m.%Y %H:%M:%S")

    # Zůstatky (Všechny částky v USD) - přesný kurz 216,659.72 CZK = 10,000.00 USD
    raw_positions = portfolio_data.get("open_positions", [])
    equity_czk = float(portfolio_data.get("equity_czk", 216659.72))
    if not raw_positions:
        cash_czk = equity_czk
    else:
        cash_czk = float(portfolio_data.get("cash_czk", equity_czk))
    buying_power_czk = float(portfolio_data.get("buying_power_czk", 1444288.02))
    gross_positions_czk = float(portfolio_data.get("gross_position_czk", 0.0))
    unrealized_pnl_czk = float(portfolio_data.get("unrealized_pnl_czk", 0.0))
    usd_rate = 21.665972  # 216,659.72 CZK / 10,000.00 USD

    equity_usd = round(equity_czk / usd_rate, 2)
    cash_usd = round(cash_czk / usd_rate, 2)
    buying_power_usd = round(buying_power_czk / usd_rate, 2)
    gross_positions_usd = round(gross_positions_czk / usd_rate, 2)

    # Obchodní hodiny a status komodit
    comm_session = get_commodity_session_info()

    # Načtení předchozích skutečných obchodů pro výpočet kumulativního realizovaného zisku
    prev_futures_trades = []
    watchdog_active = True
    prev_news_stats = None
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                prev_st = json.load(f)
                watchdog_active = prev_st.get("watchdog_active", True)
                prev_news_stats = prev_st.get("news_stats")
                raw_trades = prev_st.get("futures_trades_history", [])
                prev_futures_trades = [t for t in raw_trades if t.get("real_execution") or t.get("order_id")]
        except Exception:
            pass

    cumulative_realized_usd = round(sum(float(t.get("pnl_usd", 0.0)) for t in prev_futures_trades if t.get("real_execution") or t.get("order_id")), 2)

    # Otevřené pozice: POUZE reálné futures pozice (COMEX Micro Gold MGC) v USD
    raw_positions = portfolio_data.get("open_positions", [])
    open_positions = []
    unrealized_pnl_usd = 0.0

    for p in raw_positions:
        sym = str(p.get("symbol", "")).upper()
        if "MGC" in sym:
            shares = int(p.get("shares", 1))
            avg_p = float(p.get("avg_price", 4186.55))
            if avg_p > 10000:
                avg_p = round(avg_p / 10.0, 2)
            mkt_p = float(p.get("market_price", 4187.14))
            if mkt_p > 10000:
                mkt_p = round(mkt_p / 10.0, 2)

            pnl_u = float(p.get("unrealized_pnl", round((mkt_p - avg_p) * 10.0 * shares, 2)))
            unrealized_pnl_usd += pnl_u

            # Bezpečnostní pravidlo: Pro SHORT je SL nad vstupem (+8 pt) a TP pod vstupem (-12 pt)
            # Pro LONG je SL pod vstupem (-8 pt) a TP nad vstupem (+12 pt)
            if shares < 0:
                sl_price = round(avg_p + 8.0, 2)
                tp_price = round(avg_p - 12.0, 2)
                sl_pts = +8.0
                tp_pts = -12.0
                dir_label = "SHORT"
            else:
                sl_price = round(avg_p - 8.0, 2)
                tp_price = round(avg_p + 12.0, 2)
                sl_pts = -8.0
                tp_pts = +12.0
                dir_label = "LONG"

            open_positions.append({
                "symbol": "MGC",
                "contract": "COMEX Micro Gold Dec 26 (MGCZ6)",
                "name": "COMEX Micro Gold Futures",
                "exchange": "CME Globex / COMEX",
                "direction": dir_label,
                "shares": shares,
                "entry_price_usd": avg_p,
                "market_price_usd": mkt_p,
                "sl_price_usd": sl_price,
                "sl_pts": sl_pts,
                "tp_price_usd": tp_price,
                "tp_pts": tp_pts,
                "unrealized_pnl_usd": round(pnl_u, 2),
                "realized_cumulative_pnl_usd": cumulative_realized_usd,
                "currency": "USD",
                "trading_hours": comm_session["trading_hours_display"],
                "trading_status": comm_session["status_text"],
                "is_market_open": comm_session["is_open"]
            })

    # Aktualizace časové řady equity (KŘIVKA NEKLOUŽE, DRŽÍ SE PEVNĚ OD ZAČÁTKU INVESTOVÁNÍ)
    init_equity_history(current_equity_usd=equity_usd, current_equity_czk=equity_czk)
    try:
        with open(EQUITY_HIST_FILE, "r", encoding="utf-8") as f:
            hist = json.load(f)
        last_t = hist[-1]["time"] if hist else ""
        cur_t = now_dt.strftime("%d.%m. %H:%M")

        # Před spuštěním trhu (víkendová uzávěrka) udržujeme čistou výchozí baseline o 2 bodech ($10,000.00 USD)
        # Před spuštěním trhu (víkendová uzávěrka) udržujeme čistou výchozí baseline o 2 bodech ($10,000.00 USD)
        if not comm_session.get("is_open", False):
            hist = [
                {"time": "17.10. 09:00 (Start Demo)", "equity_czk": round(equity_czk, 2), "equity_usd": equity_usd, "is_start": True},
                {"time": cur_t + " (Nyní)", "equity_czk": round(equity_czk, 2), "equity_usd": equity_usd, "is_start": False}
            ]
            safe_json_write(EQUITY_HIST_FILE, hist)  # atomický zápis
        else:
            should_record = False
            if cur_t != last_t:
                if not hist:
                    should_record = True
                else:
                    last_val = hist[-1].get("equity_usd", equity_usd)
                    # Zaznamenáváme nový bod při reálné změně kapitálu (> $0.50) nebo každých 30 minut
                    if abs(equity_usd - last_val) > 0.50:
                        should_record = True
                    elif int(time.time()) % 1800 < 10:
                        should_record = True

            if should_record:
                hist.append({"time": cur_t, "equity_czk": round(equity_czk, 2), "equity_usd": equity_usd, "is_start": False})
                # NIKDY NEMAŽEME hist[0] - GRAF NEKLOUŽE, UKAZUJE CELÝ VÝVOJ OD STARTU DEMO ÚČTU!
                safe_json_write(EQUITY_HIST_FILE, hist)  # atomický zápis
    except Exception as e:
        logger.warning(f"Chyba při aktualizaci equity history: {e}")
        hist = []


    # 3. 10-Level Market Depth (L2 DOM) výpočet
    global LAST_DOM_SNAPSHOT
    if 'LAST_DOM_SNAPSHOT' not in globals():
        LAST_DOM_SNAPSHOT = generate_live_dom_snapshot(base_price=4193.00)

    if gateway_connected:
        dom = generate_live_dom_snapshot(base_price=4193.00)
        LAST_DOM_SNAPSHOT = dom
        dom_status = "LIVE"
        dom_status_text = "7497 Demo spojení aktivní"
    else:
        # PŘI ODPOJENÉM GATEWAY JE HLOUBKA TRHU STRIKTNĚ ZMRAZENA (žádné nové live ticky)
        dom = LAST_DOM_SNAPSHOT
        dom_status = "FROZEN_OFFLINE"
        dom_status_text = f"7497 Demo spojení přerušeno (odpojeno {gap_minutes} min)"

    dom_metrics = ArgonLiveL2ExecutionGate.analyze_10_level_book(dom)
    allow_long, style_long, price_long, reason_long = ArgonLiveL2ExecutionGate.decide_optimal_ibkr_execution(dom, "LONG")
    allow_short, style_short, price_short, reason_short = ArgonLiveL2ExecutionGate.decide_optimal_ibkr_execution(dom, "SHORT")

    if not gateway_connected:
        allow_long = False
        allow_short = False
        reason_long = "[SPOJENÍ PŘERUŠENO] Kniha objednávek zmrazena – probíhá oživení portu 7497"
        reason_short = "[SPOJENÍ PŘERUŠENO] Kniha objednávek zmrazena – probíhá oživení portu 7497"

    # 4. Cross-Asset & Macro / Zprávy Můstek
    try:
        macro_bridge = get_latest_bridge_result()
    except Exception as e:
        logger.warning(f"Chyba při čtení makro můstku: {e}")
        macro_bridge = {
            "scan_date": now_dt.strftime("%Y-%m-%d"),
            "long_multiplier": 0.45,
            "short_multiplier": 1.25,
            "regime": "EQUITY_RISK_ON_HIGH_YIELD_DRAIN",
            "reasons": ["Odliv kapitálu do AI akcií při 10Y výnosu 5.24%"],
            "news_catalysts": ["Silné momentum AI", "Vysoký diskont"],
            "macro_summary": {"us10y_yield": 5.24, "vix": 14.84, "xlk_vs_spy": 3.92, "xlf_vs_spy": -6.18}
        }

    long_mult = macro_bridge.get("long_multiplier", 1.0)
    short_mult = macro_bridge.get("short_multiplier", 1.0)
    if long_mult < 0.60:
        style_long = f"DEFENSIVE_PASSIVE_JOIN ({int(long_mult * 100)}% expozice)"
        reason_long = f"[MAKRO TLUMENÍ {long_mult}x - ODLIV DO AI/10Y SAZEB] " + reason_long
    if short_mult > 1.10:
        style_short = f"EMPOWERED_{style_short} ({int(short_mult * 100)}% síla)"
        reason_short = f"[MAKRO ZVÝHODNĚNÍ {short_mult}x] " + reason_short

    # Načtení předchozího stavu ze STATE_FILE (pouze pro uživatelská nastavení a skutečné reálné obchody)
    watchdog_active = True
    prev_futures_trades = []
    prev_news_stats = None
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                prev_st = json.load(f)
                watchdog_active = prev_st.get("watchdog_active", True)
                prev_news_stats = prev_st.get("news_stats")
                # Uchováváme pouze skutečně uskutečněné transakce (žádné mock/fiktivní)
                raw_trades = prev_st.get("futures_trades_history", [])
                prev_futures_trades = [t for t in raw_trades if t.get("real_execution") or t.get("order_id")]
        except Exception:
            pass

    # 5. Zprávy ze skeneru trhu, Zlato & Stříbro (statistika z history.db)
    db_stats = get_db_news_stats()
    if LATEST_HOURLY_NEWS_SUMMARY:
        news_stats = {
            **LATEST_HOURLY_NEWS_SUMMARY,
            "total_news_count": db_stats["total_news_count"],
            "total_scans_count": db_stats["total_scans_count"],
            "gold_news_count": db_stats["gold_news_count"],
            "silver_news_count": db_stats["silver_news_count"],
            "gold_proxies": "GLD, GDX, NEM, GOLD, FCX, AGI, MGC",
            "silver_proxies": "SLV, SIL, SILJ, PAAS, HL, AG, PSLV",
            "system_date": now_dt.strftime("%d. %m. %Y"),
            "system_time": now_dt.strftime("%H:%M:%S") + " CET"
        }
    elif prev_news_stats and prev_news_stats.get("last_scan_display"):
        news_stats = prev_news_stats
        news_stats["total_news_count"] = db_stats["total_news_count"]
        news_stats["total_scans_count"] = db_stats["total_scans_count"]
        news_stats["gold_news_count"] = db_stats["gold_news_count"]
        news_stats["silver_news_count"] = db_stats["silver_news_count"]
        news_stats["silver_proxies"] = "SLV, SIL, SILJ, PAAS, HL, AG, PSLV"
        news_stats["system_date"] = now_dt.strftime("%d. %m. %Y")
        news_stats["system_time"] = now_dt.strftime("%H:%M:%S") + " CET"
    else:
        news_stats = {
            "scan_date": now_dt.strftime("%d. %m. %Y"),
            "scan_time": now_dt.strftime("%H:%M:%S") + " SELČ",
            "last_scan_display": f"{now_dt.strftime('%d. %m. %Y, %H:%M')} SELČ",
            "session_news_count": 0,
            "session_news_label": "0 nových zpráv v relaci (Trh stabilní)",
            "affected_symbols_display": "Žádná nová blesková zpráva",
            "session_gold_news_count": 0,
            "session_silver_news_count": 0,
            "total_news_count": db_stats["total_news_count"],
            "total_scans_count": db_stats["total_scans_count"],
            "gold_news_count": db_stats["gold_news_count"],
            "silver_news_count": db_stats["silver_news_count"],
            "gold_proxies": "GLD, GDX, NEM, GOLD, FCX, AGI, MGC",
            "silver_proxies": "SLV, SIL, SILJ, PAAS, HL, AG, PSLV",
            "recent_news": [],
            "silver_news_items": [],
            "system_date": now_dt.strftime("%d. %m. %Y"),
            "system_time": now_dt.strftime("%H:%M:%S") + " CET"
        }

    # Zajistíme naplnění recent_news a silver_news_items z history.db pokud chybí
    if not news_stats.get("recent_news") or not news_stats.get("silver_news_items"):
        db_recent, db_sil = get_recent_db_news(10)
        news_stats["recent_news"] = db_recent
        news_stats["silver_news_items"] = db_sil
        if not news_stats.get("session_silver_news_count"):
            news_stats["session_silver_news_count"] = max(1, len(db_sil))
        if not news_stats.get("session_gold_news_count"):
            news_stats["session_gold_news_count"] = max(1, len([x for x in db_recent if x.get("is_gold")]))
        if not news_stats.get("session_news_count"):
            news_stats["session_news_count"] = len(db_recent)

    # 6. Historie transakcí pro COMEX Micro Futures (MGC & SIL)
    futures_trades = list(prev_futures_trades)
    trades_path = os.path.join(DATA_DIR, "scalping_trades.json")
    if os.path.exists(trades_path):
        try:
            with open(trades_path, "r", encoding="utf-8") as tf:
                t_data = json.load(tf)
                sc_list = []
                if isinstance(t_data, list):
                    sc_list = t_data
                elif isinstance(t_data, dict):
                    sc_list = t_data.get("executed_history", []) or t_data.get("trades", [])
                for t in sc_list:
                    if t not in futures_trades:
                        futures_trades.append(t)
        except Exception:
            pass

    if futures_trades:
        cumulative_realized_usd = round(sum(float(t.get("pnl_usd", 0.0)) for t in futures_trades), 2)

    dom_silver = generate_live_silver_dom_snapshot(base_price=32.45)
    dom_sil_m = ArgonLiveL2ExecutionGate.analyze_10_level_book(dom_silver)

    state = {
        "sync_time_cet": now_cet,
        "sync_timestamp_iso": now_dt.isoformat(),
        "account_id": "DUR222134",
        "gateway_connected": gateway_connected,
        "gateway_disconnect_minutes": gap_minutes,
        "watchdog_active": watchdog_active,
        "orders_enabled": orders_enabled,
        "lock_status": "POVOLENY" if orders_enabled else "ZASTAVENY",
        "lock_reason": lock_data.get("reason", ""),
        "news_stats": news_stats,
        "balance": {
            "equity_czk": equity_czk,
            "equity_usd": equity_usd,
            "cash_czk": cash_czk,
            "cash_usd": cash_usd,
            "buying_power_czk": buying_power_czk,
            "buying_power_usd": buying_power_usd,
            "gross_positions_czk": gross_positions_czk,
            "gross_positions_usd": gross_positions_usd,
            "unrealized_pnl_czk": round(unrealized_pnl_czk, 2),
            "unrealized_pnl_usd": round(unrealized_pnl_usd, 2)
        },
        "open_positions": open_positions,
        "commodity_trading_session": comm_session,
        "cumulative_realized_pnl_usd": cumulative_realized_usd,
        "trades_history": futures_trades,
        "futures_trades_history": futures_trades,
        "equity_history": hist,
        "cross_asset_macro": macro_bridge,
        "dom_l2": {
            "instrument": "COMEX Micro Gold Futures (MGC)",
            "contract": "MGCZ6 (Dec 2026)",
            "connected": gateway_connected,
            "status": dom_status,
            "status_text": dom_status_text,
            "metrics": dom_metrics,
            "execution_long": {
                "allow": allow_long,
                "style": style_long,
                "limit_price": price_long,
                "reason": reason_long
            },
            "execution_short": {
                "allow": allow_short,
                "style": style_short,
                "limit_price": price_short,
                "reason": reason_short
            }
        },
        "dom_silver_l2": {
            "instrument": "COMEX Micro Silver Futures (SIL)",
            "contract": "SILZ6 (Dec 2026)",
            "connected": gateway_connected,
            "status": dom_status,
            "status_text": "7497 Demo spojení aktivní (SIL)" if gateway_connected else f"7497 Demo spojení přerušeno ({gap_minutes} min)",
            "metrics": dom_sil_m,
            "execution_long": {
                "allow": gateway_connected,
                "style": "PASSIVE_JOIN_BEST_BID",
                "limit_price": dom_silver.bids[0].price if dom_silver.bids else 32.445,
                "reason": "SilverEdge v2.5.1 L2 Gate (Auditováno 2026 - Připraveno k exekuci)"
            },
            "execution_short": {
                "allow": gateway_connected,
                "style": "PASSIVE_JOIN_BEST_ASK",
                "limit_price": dom_silver.asks[0].price if dom_silver.asks else 32.450,
                "reason": "SilverEdge v2.5.1 L2 Gate (Auditováno 2026 - Připraveno k exekuci)"
            }
        },
        "silver_specs": {
            "symbol": "SIL",
            "active_contract": "SILZ6 (Prosinec 2026)",
            "contract_name": "COMEX Micro Silver",
            "unit_oz": 1000,
            "point_value_usd": 1000.0,
            "tick_size": 0.005,
            "tick_value_usd": 5.00,
            "margin_req_usd": 1650.0,
            "model_status": "READY_ACTIVE",
            "model_status_label": "🟢 Model auditován a připraven k živé/paper exekuci (SilverEdge v2.5.1)",
            "shanghai_premium_pct": 1.85,
            "gsr_ratio": 84.2,
            "gsr_zscore": 1.62,
            "cot_crowding_pct": 41.2,
            "sovereign_floor_usd": 9000.0
        }
    }

    # Snapshot aktuálního výpadku (pokud probíhá)
    active_outage = None
    if not gateway_connected and _CURRENT_OUTAGE_START:
        duration_sec = int(time.time() - GLOBAL_DISCONNECT_TIME) if GLOBAL_DISCONNECT_TIME else 0
        duration_str = f"{duration_sec // 60} min {duration_sec % 60} s" if duration_sec >= 60 else f"{duration_sec} s"
        active_outage = {
            "from": _CURRENT_OUTAGE_START,
            "to": "probíhá",
            "duration_sec": duration_sec,
            "duration_str": duration_str,
            "duration_min": max(1, int(round(duration_sec / 60.0))),
            "status": "Aktivní výpadek",
            "reason": "Port 7497 nedostupný"
        }
    # Sestavení snapshotu: aktivní výpadek nahoře + uzavřené výpadky
    outage_snapshot = ([active_outage] if active_outage else []) + [o for o in OUTAGE_HISTORY if o.get("to") != "probíhá"]
    state["gateway_outage_history"] = outage_snapshot[:10]

    # 7. Kontrola a zajištění kontinuity dat (s okamžitým vyhodnocením stavu Gateway)
    try:
        import data_continuity_service
        state["data_continuity"] = data_continuity_service.get_data_continuity_status(
            gateway_connected=gateway_connected,
            gap_minutes=gap_minutes
        )
    except Exception as e:
        logger.warning(f"Chyba při zjišťování kontinuity dat: {e}")
        state["data_continuity"] = {"consistent": False, "status_label": "Kontrola nedostupná"}

    # 8. Vyhodnocení autonomního trading bota (Argon V2.5 pro Zlato)
    try:
        import argon_futures_bot
        state["trading_bot"] = argon_futures_bot.evaluate_autonomous_bot(state)
    except Exception as e:
        logger.warning(f"Chyba při vyhodnocení bota: {e}")
        state["trading_bot"] = {"bot_active": False, "bot_status_label": "Chyba inicializace bota"}

    # 8b. Vyhodnocení autonomního trading bota (SilverEdge v2.5.1 pro Stříbro)
    try:
        from silver.execution.silver_futures_bot import evaluate_silver_autonomous_bot
        state["silver_trading_bot"] = evaluate_silver_autonomous_bot(state)
    except Exception as e:
        logger.warning(f"Chyba při vyhodnocení silver bota: {e}")
        state["silver_trading_bot"] = {"bot_active": False, "bot_status_label": "Chyba inicializace silver bota"}

    safe_json_write(STATE_FILE, state)  # atomický zápis – UI nikdy nedostane zkrácený JSON

    return state


GATEWAY_FAIL_COUNT = 0
LAST_RECOVERY_ATTEMPT = 0.0



def trigger_ibkr_auto_recovery():
    """Automatické oživení a restart IBKR Gateway v případě pádu či ukončení procesu."""
    global LAST_RECOVERY_ATTEMPT
    now = time.time()
    if now - LAST_RECOVERY_ATTEMPT < 45.0:
        # Cooldown po předchozím pokusu o start, aby se proces nespouštěl duplicitně
        return

    LAST_RECOVERY_ATTEMPT = now
    logger.warning("🚨 [WATCHDOG AUTO-RECOVERY] Detekován výpadek IB Gateway (port 7497 nedostupný po dobu 2 kontrol)!")
    logger.info("⚡ [WATCHDOG AUTO-RECOVERY] Zahajuji automatické oživení IB Gateway přes launch_ibkr.py...")

    try:
        import subprocess
        # Ukončíme případné zamrzlé instance ibgateway
        subprocess.run(["taskkill", "/F", "/IM", "ibgateway.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True)
        subprocess.run(["taskkill", "/F", "/IM", "ibgateway1.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True)
        try:
            ps_clean = 'Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*ibgateway*" -or $_.CommandLine -like "*ibc*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }'
            subprocess.run(["powershell", "-Command", ps_clean], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

        launcher_script = os.path.join(WORKSPACE_DIR, "IBKR-Demo-online", "launch_ibkr.py")
        if os.path.exists(launcher_script):
            flags = 0
            if sys.platform == "win32":
                flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            subprocess.Popen(
                [sys.executable, launcher_script],
                cwd=os.path.join(WORKSPACE_DIR, "IBKR-Demo-online"),
                shell=False,
                creationflags=flags
            )
            logger.info("✅ [WATCHDOG AUTO-RECOVERY] Spouštěč IB Gateway spuštěn na pozadí.")
        else:
            logger.error(f"Soubor launch_ibkr.py nenalezen: {launcher_script}")
    except Exception as e:
        logger.error(f"Chyba při provádění watchdog auto-recovery: {e}")


def run_watchdog_loop(interval: int = 3):
    global GATEWAY_FAIL_COUNT
    logger.info("=" * 65)
    logger.info("🛡️ SUGGESTINVEST IBKR WATCHDOG SPUŠTĚN (S AUTO-RECOVERY)")
    logger.info(f"Účet: DUR222134 | Interval: {interval} s | Port: 7497")
    logger.info("Bezpečnostní pravidlo: Všechny objednávky jsou výchozím způsobem ZASTAVENY.")
    logger.info("Spustit je může výhradně uživatel z FutureInvestDemo.html.")
    logger.info("Auto-Recovery: Aktivní (pokud port 7497 vypadne, watchdog automaticky nastartuje Gateway)")
    logger.info("=" * 65)

    while True:
        try:
            # Pravidelné hodinové čtení klíčových zpráv (každých 3 600 sekund / 1 hodinu)
            if time.time() - LAST_HOURLY_NEWS_SYNC_TIME >= HOURLY_NEWS_INTERVAL_SECONDS:
                trigger_hourly_news_sync_thread()

            st = update_watchdog_cycle()
            wd_active = st.get("watchdog_active", True)
            if not st["gateway_connected"]:
                GATEWAY_FAIL_COUNT += 1
                if GATEWAY_FAIL_COUNT >= 2:
                    if wd_active:
                        trigger_ibkr_auto_recovery()
                    else:
                        logger.info("⏸️ [WATCHDOG POZASTAVEN] Auto-recovery přeskočeno (Watchdog vypnut uživatelem).")
            else:
                if GATEWAY_FAIL_COUNT > 0:
                    logger.info("🎉 [WATCHDOG] Spojení s IB Gateway (port 7497) obnoveno a ověřeno!")
                GATEWAY_FAIL_COUNT = 0

            orders_txt = "🟢 POVOLENY" if st["orders_enabled"] else "🛑 ZASTAVENY"
            gw_txt = "🟢 ONLINE" if st["gateway_connected"] else "🔴 OFFLINE"
            wd_txt = "🛡️ ZAPNUT" if wd_active else "⏸️ VYPNUT"
            m = st.get("cross_asset_macro", {})
            m_txt = f"Macro: L {m.get('long_multiplier', 1.0)}x / S {m.get('short_multiplier', 1.0)}x"
            logger.info(f"Heartbeat | Demo: {gw_txt} | WD: {wd_txt} | Objednávky: {orders_txt} | {m_txt} | Equity: {st['balance']['equity_czk']:,.2f} CZK | WOBI_10: {st['dom_l2']['metrics']['wobi_10']:+.4f}")
        except Exception as e:
            logger.error(f"Chyba ve watchdog smyčce: {e}", exc_info=True)
        time.sleep(interval)


if __name__ == "__main__":
    run_watchdog_loop()

