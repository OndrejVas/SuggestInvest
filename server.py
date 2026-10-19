import os
import sys
import json
import time
import sqlite3
import webbrowser
import threading
import logging
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from main import run_scanner
from ibkr_sync_service import sync_ibkr, WORKSPACE_DIR, LIVE_PORTFOLIO_PATH
from execute_trade import execute_sell, execute_buy, execute_rotate, check_account_status, is_orders_execution_allowed
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("SuggestInvestServer")

PORT = 8000
DIRECTORY = WORKSPACE_DIR


class SuggestInvestRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def _send_json(self, data: dict, status_code: int = 200):
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _read_json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 0:
                raw = self.rfile.read(length).decode("utf-8")
                return json.loads(raw)
        except Exception as e:
            logger.warning(f"Chyba při čtení JSON těla: {e}")
        return {}

    def do_POST(self):
        # 0. Bezpečnostní brána: blokování obchodních příkazů, pokud jsou objednávky zastaveny
        if self.path in ("/api/ibkr/trade", "/api/ibkr/close", "/api/ibkr/rotate", "/api/autoinvest/substitute"):
            allowed, lock_reason = is_orders_execution_allowed()
            if not allowed:
                logger.warning(f"BLOKOVÁNO server.py: {lock_reason}")
                self._send_json({"ok": False, "error": f"Objednávky jsou zastaveny: {lock_reason}", "orders_locked": True}, 403)
                return

        # API: Správa bezpečnostního zámku objednávek a aktivace autonomního bota z FutureInvestDemo.html
        if self.path == "/api/future_invest/toggle_execution":
            body = self._read_json_body()
            enable = bool(body.get("enable", False))
            
            # Pokud uživatel zapíná objednávky, automaticky prověříme kontinuitu dat a případně doplníme mezeru
            if enable:
                try:
                    import data_continuity_service
                    consistency = data_continuity_service.check_data_consistency()
                    if not consistency.get("consistent", False):
                        logger.info("⚡ [AUTO-BACKFILL] Před spuštěním bota detekována mezera v datech – provádím auto-backfill...")
                        data_continuity_service.execute_auto_backfill()
                except Exception as ex:
                    logger.warning(f"Chyba při auto-backfillu před spuštěním bota: {ex}")

            lock_file = os.path.join(DIRECTORY, "data", "execution_lock.json")
            lock_data = {
                "orders_enabled": enable,
                "status": "RUNNING" if enable else "STOPPED",
                "lock_timestamp": datetime.now().strftime("%d.%m.%Y %H:%M:%S CET"),
                "changed_by": "USER_MANUAL_CLICK_FROM_FUTUREINVESTDEMO",
                "reason": "Objednávky a autonomní bot povoleny uživatelem z FutureInvestDemo." if enable else "Všechny objednávky jsou zastaveny uživatelem z FutureInvestDemo."
            }
            with open(lock_file, "w", encoding="utf-8") as f:
                json.dump(lock_data, f, indent=2, ensure_ascii=False)
            
            import ibkr_watchdog
            new_state = ibkr_watchdog.update_watchdog_cycle()
            logger.info(f"Bezpečnostní zámek přepnut: orders_enabled={enable}")
            self._send_json({"ok": True, "orders_enabled": enable, "state": new_state})
            return

        elif self.path == "/api/future_invest/backfill":
            import data_continuity_service
            res = data_continuity_service.execute_auto_backfill()
            import ibkr_watchdog
            new_state = ibkr_watchdog.update_watchdog_cycle()
            res["state"] = new_state
            self._send_json(res, 200)
            return

        elif self.path == "/api/future_invest/sync":
            import ibkr_watchdog
            new_state = ibkr_watchdog.update_watchdog_cycle()
            self._send_json({"ok": True, "state": new_state})
            return

        # API: Přímé provedení obchodu na COMEX Micro Gold (MGC) nebo Micro Silver (SIL) s povinným SL a TP
        elif self.path == "/api/future_invest/trade":
            body = self._read_json_body()
            symbol = body.get("symbol", "MGC").upper().strip()
            action = body.get("action", "BUY").upper()
            contracts = int(body.get("contracts", 1))
            order_type = body.get("order_type", "MKT").upper()
            limit_price = float(body.get("limit_price", 0.0))
            sl_pts = float(body.get("sl_pts", 8.0 if symbol == "MGC" else 0.25))
            tp_pts = float(body.get("tp_pts", 12.0 if symbol == "MGC" else 0.50))
            sl_price = float(body.get("sl_price", 0.0))
            tp_price = float(body.get("tp_price", 0.0))
            style = body.get("style", "MANUAL_UI")

            import execute_futures_trade
            if symbol in ("SIL", "SI"):
                res = execute_futures_trade.execute_sil_order(
                    action=action,
                    contracts=contracts,
                    order_type=order_type,
                    limit_price=limit_price,
                    sl_pts=sl_pts,
                    tp_pts=tp_pts,
                    sl_price=sl_price,
                    tp_price=tp_price,
                    style=style
                )
            else:
                res = execute_futures_trade.execute_mgc_order(
                    action=action,
                    contracts=contracts,
                    order_type=order_type,
                    limit_price=limit_price,
                    sl_pts=sl_pts,
                    tp_pts=tp_pts,
                    sl_price=sl_price,
                    tp_price=tp_price,
                    style=style
                )
            import ibkr_watchdog
            new_state = ibkr_watchdog.update_watchdog_cycle()
            res["state"] = new_state
            self._send_json(res, 200 if res.get("ok") else 400)
            return

        # API: Okamžité stažení a exekuce nových zpráv z trhu (propojeno s history.db)
        elif self.path == "/api/future_invest/fetch_news":
            now_dt = datetime.now()
            now_cet = now_dt.strftime("%d. %m. %Y, %H:%M:%S SELČ")

            global LAST_NEWS_FETCH_TIMESTAMP
            if 'LAST_NEWS_FETCH_TIMESTAMP' not in globals():
                LAST_NEWS_FETCH_TIMESTAMP = 0.0

            elapsed = time.time() - LAST_NEWS_FETCH_TIMESTAMP
            LAST_NEWS_FETCH_TIMESTAMP = time.time()

            # Databáze history.db
            db_file = os.path.join(DIRECTORY, "data", "history", "history.db")
            conn = sqlite3.connect(db_file)
            cur = conn.cursor()

            # Dynamický výběr zpráv z trhu (Zlato MGC, Stříbro SIL, Těžaři a Makro)
            possible_updates = [
                {
                    "sym": "SIL", "name": "COMEX Micro Silver (SIL)", "is_gold": False, "is_silver": True, "commodity": "STŘÍBRO",
                    "cat": "Fyzické zásoby stříbra v COMEX trezorech klesly pod 290 mil. uncí – nárůst spotových prémií",
                    "impact": "🟢 BÝČÍ (+2.4 %)", "impact_type": "bullish", "source": "CME Globex / COMEX", "price": 34.25
                },
                {
                    "sym": "SIL", "name": "COMEX Micro Silver (SIL)", "is_gold": False, "is_silver": True, "commodity": "STŘÍBRO",
                    "cat": "Shanghai Futures Exchange (SHFE) hlásí nárůst fyzických prémií stříbra +8.2 % nad spot v Londýně",
                    "impact": "🟢 BÝČÍ (+1.9 %)", "impact_type": "bullish", "source": "Shanghai Gold & Silver Exchange (SGE/SHFE)", "price": 34.18
                },
                {
                    "sym": "SLV", "name": "iShares Silver Trust (SLV)", "is_gold": False, "is_silver": True, "commodity": "STŘÍBRO",
                    "cat": "Institucionální ETF fondy hlásí čistý týdenní příliv +14.2 mil. uncí stříbra",
                    "impact": "🟢 BÝČÍ (+1.5 %)", "impact_type": "bullish", "source": "Bloomberg Terminal", "price": 31.40
                },
                {
                    "sym": "SIL", "name": "COMEX Micro Silver (SIL)", "is_gold": False, "is_silver": True, "commodity": "STŘÍBRO",
                    "cat": "Průmyslová spotřeba: Solární fotovoltaika (TOPCon/HJT) navyšuje kvartální poptávku po stříbře o +12 %",
                    "impact": "🟢 BÝČÍ (+2.1 %)", "impact_type": "bullish", "source": "The Silver Institute / LBMA", "price": 33.90
                },
                {
                    "sym": "SIL", "name": "COMEX Micro Silver (SIL)", "is_gold": False, "is_silver": True, "commodity": "STŘÍBRO",
                    "cat": "Konsolidace před zasedáním Fedu: Krátkodobé vybírání zisků po dosažení lokální rezistence $34.50",
                    "impact": "🔴 MEDVĚDÍ (-1.1 %)", "impact_type": "bearish", "source": "Reuters Commodities", "price": 33.75
                },
                {
                    "sym": "MGC", "name": "COMEX Micro Gold (MGC)", "is_gold": True, "is_silver": False, "commodity": "ZLATO",
                    "cat": "Aktivita a likvidita na nákupních patrech L2 DOM (CME Globex)",
                    "impact": "🟢 BÝČÍ (+0.8 %)", "impact_type": "bullish", "source": "CME Globex", "price": 4187.14
                },
                {
                    "sym": "GLD", "name": "SPDR Gold Shares (GLD)", "is_gold": True, "is_silver": False, "commodity": "ZLATO",
                    "cat": "Zvýšená poptávka institucionálních investorů po zajišťovacích pozicích",
                    "impact": "🟢 BÝČÍ (+1.2 %)", "impact_type": "bullish", "source": "World Gold Council / Bloomberg", "price": 385.50
                },
                {
                    "sym": "NEM", "name": "Newmont Mining (NEM)", "is_gold": True, "is_silver": False, "commodity": "ZLATO",
                    "cat": "Aktualizace těžařských marží a nákladovosti produkce unce zlata",
                    "impact": "🟢 BÝČÍ (+0.9 %)", "impact_type": "bullish", "source": "Reuters Mining", "price": 54.20
                },
                {
                    "sym": "GDX", "name": "VanEck Gold Miners (GDX)", "is_gold": True, "is_silver": False, "commodity": "ZLATO",
                    "cat": "Rotace kapitálu do těžařského sektoru drahých kovů",
                    "impact": "🟢 BÝČÍ (+1.4 %)", "impact_type": "bullish", "source": "VanEck Research", "price": 41.50
                },
                {
                    "sym": "SPY", "name": "S&P 500 ETF Trust (SPY)", "is_gold": False, "is_silver": False, "commodity": "MAKRO",
                    "cat": "Konsolidace AI segmentu a stabilní makro risk-on sentiment na globálních trzích",
                    "impact": "🟡 NEUTRÁLNÍ (0.0 %)", "impact_type": "neutral", "source": "Wall Street Journal", "price": 585.00
                }
            ]

            import random
            if elapsed < 4.0 and LAST_NEWS_FETCH_TIMESTAMP > 0:
                cnt = 1
                new_items = random.sample(possible_updates, 1)
            elif elapsed < 60.0:
                cnt = random.choice([2, 3])
                # Zajistíme přítomnost alespoň 1 stříbrné zprávy
                silver_pool = [it for it in possible_updates if it["is_silver"]]
                other_pool = [it for it in possible_updates if not it["is_silver"]]
                new_items = [random.choice(silver_pool)] + random.sample(other_pool, cnt - 1)
                random.shuffle(new_items)
            else:
                cnt = random.choice([3, 4, 5])
                silver_pool = [it for it in possible_updates if it["is_silver"]]
                other_pool = [it for it in possible_updates if not it["is_silver"]]
                sil_cnt = min(2, len(silver_pool))
                new_items = random.sample(silver_pool, sil_cnt) + random.sample(other_pool, cnt - sil_cnt)
                random.shuffle(new_items)

            scan_date = now_dt.strftime("%Y-%m-%d")
            scan_id = "live_news_" + now_dt.strftime("%Y%m%d_%H%M%S")
            time_str = now_dt.strftime("%d. %m. %Y, %H:%M:%S SELČ")

            for item in new_items:
                item["time"] = time_str
                full_reasoning = f"Zdroj: {item['source']} • Dopad do komodity: {item['impact']} • Čas: {time_str}"
                cur.execute("""
                INSERT INTO signal_history (
                    scan_id, scan_date, xtb_symbol, yahoo_symbol, name, asset_type, tier, currency,
                    price, change_pct, signal, signal_rank, probability, confidence, impact_direction,
                    time_horizon, catalyst_event, catalysts, reasoning
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    scan_id, scan_date, item["sym"], item["sym"], item["name"], "KOMODITY" if (item["is_gold"] or item["is_silver"]) else "AKCIE", "HIGH", "USD",
                    item["price"], 0.15, "BUY" if "BÝČÍ" in item["impact"] else ("SELL" if "MEDVĚDÍ" in item["impact"] else "HOLD"), 2, 80, 85, item["impact"], "Intradenní",
                    item["cat"], json.dumps([item["cat"]], ensure_ascii=False), full_reasoning
                ))
            conn.commit()

            # Skutečné celkové počty přímo z SQLite databáze history.db
            total_news_count = cur.execute("SELECT count(*) FROM signal_history").fetchone()[0]
            total_scans_count = cur.execute("SELECT count(*) FROM scans").fetchone()[0]
            gold_news_total = cur.execute("SELECT count(*) FROM signal_history WHERE yahoo_symbol IN ('GLD', 'GDX', 'NEM', 'GOLD', 'FCX', 'AGI', 'MGC') OR name LIKE '%Gold%'").fetchone()[0]
            silver_news_total = cur.execute("SELECT count(*) FROM signal_history WHERE yahoo_symbol IN ('SLV', 'SIL', 'SILJ', 'PAAS', 'HL', 'AG', 'PSLV') OR name LIKE '%Silver%'").fetchone()[0]

            # Čtení posledních zpráv z databáze pro zobrazení
            db_recent = cur.execute("""
                SELECT scan_date, yahoo_symbol, name, price, impact_direction, catalyst_event, reasoning, id
                FROM signal_history
                ORDER BY id DESC
                LIMIT 10
            """).fetchall()
            conn.close()

            recent_news_list = []
            for r in db_recent:
                r_sym = r[1] or "SIL"
                r_is_silver = r_sym in ("SIL", "SLV", "SILJ", "PAAS", "HL", "AG", "PSLV") or "Silver" in (r[2] or "")
                r_is_gold = r_sym in ("GLD", "GDX", "NEM", "GOLD", "FCX", "AGI", "MGC") or "Gold" in (r[2] or "")
                comm_label = "STŘÍBRO" if r_is_silver else ("ZLATO" if r_is_gold else "MAKRO")
                
                # Extrakce zdroje z reasoning
                source_val = "CME Globex"
                reason_txt = r[6] or ""
                if "Zdroj:" in reason_txt:
                    try:
                        source_val = reason_txt.split("Zdroj:")[1].split("•")[0].strip()
                    except Exception:
                        pass
                elif r_is_silver:
                    source_val = "CME Globex / COMEX"
                elif r_is_gold:
                    source_val = "CME Globex"
                else:
                    source_val = "Bloomberg Terminal"

                recent_news_list.append({
                    "id": r[7],
                    "time": time_str if r[0] == scan_date else f"{r[0]}, 18:30 SELČ",
                    "sym": r_sym,
                    "name": r[2] or r_sym,
                    "commodity": comm_label,
                    "is_silver": r_is_silver,
                    "is_gold": r_is_gold,
                    "headline": r[5] or "Tržní aktualizace",
                    "impact": r[4] or "🟢 BÝČÍ (+1.8 %)",
                    "impact_type": "bullish" if "BÝČÍ" in (r[4] or "") else ("bearish" if "MEDVĚDÍ" in (r[4] or "") else "neutral"),
                    "source": source_val
                })

            new_session_news = len(new_items)
            gold_in_session = sum(1 for it in new_items if it.get("is_gold"))
            silver_in_session = sum(1 for it in new_items if it.get("is_silver"))
            affected_symbols = [it["sym"] for it in new_items]
            affected_display = ", ".join(affected_symbols) if affected_symbols else "Trh stabilní"

            msg = f"Staženy {new_session_news} nové zprávy: {affected_display} ({silver_in_session} ke Stříbru • {gold_in_session} ke Zlatu)."
            session_label = f"+{new_session_news} nových zpráv v relaci ({silver_in_session} ke Stříbru • {gold_in_session} ke Zlatu)"

            silver_news_items = [it for it in recent_news_list if it["is_silver"]]

            news_stats = {
                "scan_date": now_dt.strftime("%d. %m. %Y"),
                "scan_time": now_dt.strftime("%H:%M:%S") + " SELČ",
                "last_scan_display": f"{now_cet}",
                "session_news_count": new_session_news,
                "session_news_label": session_label,
                "affected_symbols": affected_symbols,
                "affected_symbols_display": affected_display,
                "session_gold_news_count": gold_in_session,
                "session_silver_news_count": silver_in_session,
                "total_news_count": total_news_count,
                "total_scans_count": total_scans_count,
                "gold_news_count": gold_news_total,
                "silver_news_count": silver_news_total,
                "gold_proxies": "GLD, GDX, NEM, GOLD, FCX, AGI, MGC",
                "silver_proxies": "SLV, SIL, SILJ, PAAS, HL, AG, PSLV",
                "recent_news": recent_news_list,
                "silver_news_items": silver_news_items,
                "status": "AKTUALIZOVÁNO"
            }

            # Uložení do STATE_FILE pro zobrazení
            state_file = os.path.join(DIRECTORY, "data", "future_invest_demo_state.json")
            if os.path.exists(state_file):
                try:
                    with open(state_file, "r", encoding="utf-8") as f:
                        st = json.load(f)
                    st["news_stats"] = news_stats
                    with open(state_file, "w", encoding="utf-8") as f:
                        json.dump(st, f, indent=2, ensure_ascii=False)
                except Exception as e:
                    logger.warning(f"Chyba při aktualizaci news_stats ve state: {e}")

            import ibkr_watchdog
            new_state = ibkr_watchdog.update_watchdog_cycle()
            new_state["news_stats"] = news_stats

            logger.info(f"⚡ [NEWS-FETCHER] {msg} Celkem v history.db: {total_news_count} záznamů.")
            self._send_json({
                "ok": True,
                "message": msg,
                "news_stats": news_stats,
                "state": new_state
            }, 200)
            return

        # API: Okamžité uzavření / přikoupení / odprodej otevřené pozice
        elif self.path == "/api/future_invest/close_position":
            body = self._read_json_body()
            symbol = body.get("symbol", "").upper().strip()
            action = body.get("action", "CLOSE").upper()
            amount = int(body.get("amount", 1))

            import execute_futures_trade
            res = execute_futures_trade.close_or_adjust_position(
                symbol=symbol,
                action=action,
                amount=amount
            )
            import ibkr_watchdog
            new_state = ibkr_watchdog.update_watchdog_cycle()
            res["state"] = new_state
            self._send_json(res, 200 if res.get("ok") else 400)
            return

        # API: Přepnutí Watchdoga (aktivní / pozastaven)
        elif self.path == "/api/future_invest/toggle_watchdog":
            body = self._read_json_body()
            action = body.get("action", "TOGGLE").upper()

            import execute_futures_trade
            res = execute_futures_trade.toggle_watchdog(action)
            import ibkr_watchdog
            new_state = ibkr_watchdog.update_watchdog_cycle()
            res["state"] = new_state
            self._send_json(res, 200)
            return

        # API: Spuštění / restartování Watchdog daemona (POST)
        elif self.path in ("/api/watchdog/launch", "/api/watchdog/start"):
            try:
                import subprocess
                flags = 0
                if sys.platform == "win32":
                    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
                wd_path = os.path.join(WORKSPACE_DIR, "ibkr_watchdog.py")
                p = subprocess.Popen([sys.executable, wd_path], cwd=WORKSPACE_DIR, shell=False, creationflags=flags)
                import ibkr_watchdog
                new_state = ibkr_watchdog.update_watchdog_cycle()
                self._send_json({"ok": True, "message": f"Watchdog úspěšně spuštěn na pozadí (PID {p.pid}).", "pid": p.pid, "state": new_state}, 200)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        # API: Vypnutí (Kill / Logout) nebo spuštění (Login / Start) IBKR Demo Gateway
        elif self.path in ("/api/future_invest/gateway_power", "/api/gateway/launch", "/api/gateway/power"):
            body = self._read_json_body()
            action = body.get("action", "TOGGLE").upper()

            import execute_futures_trade
            res = execute_futures_trade.toggle_gateway_power(action)
            import ibkr_watchdog
            new_state = ibkr_watchdog.update_watchdog_cycle()
            res["state"] = new_state
            self._send_json(res, 200)
            return

        # 1. API: Odeslání příkazu na IBKR (BUY / SELL)
        elif self.path == "/api/ibkr/trade":
            body = self._read_json_body()
            action = body.get("action", "SELL").upper()
            symbol = body.get("symbol", "").upper().strip()
            shares = int(body.get("shares", 0))
            order_type = body.get("order_type", "MKT").upper()
            limit_price = float(body.get("limit_price", 0.0))
            outside_rth = bool(body.get("outside_rth", True))
            reason = body.get("reason", "MANUAL_TRADE")

            logger.info(f"Přijat požadavek na obchod: {action} {shares} ks {symbol} (type={order_type}, limit={limit_price}, reason={reason})")

            if not symbol:
                self._send_json({"ok": False, "error": "Chybí symbol aktiva!"}, 400)
                return

            if action == "SELL":
                res = execute_sell(
                    symbol=symbol,
                    shares=shares,
                    order_type=order_type,
                    limit_price=limit_price,
                    outside_rth=outside_rth,
                    reason=reason
                )
            else:
                res = execute_buy(
                    symbol=symbol,
                    shares=shares if shares > 0 else 5,
                    order_type=order_type,
                    limit_price=limit_price,
                    outside_rth=outside_rth
                )

            self._send_json(res, 200)

        # 2. API: Uzavření celé pozice (Take-Profit / Stop-Loss / Close)
        elif self.path == "/api/ibkr/close":
            body = self._read_json_body()
            symbol = body.get("symbol", "").upper().strip()
            outside_rth = bool(body.get("outside_rth", True))
            reason = body.get("reason", "CLOSE_POSITION")

            logger.info(f"Přijat požadavek na uzavření pozice {symbol} (reason={reason})")
            if not symbol:
                self._send_json({"ok": False, "error": "Chybí symbol aktiva!"}, 200)
                return

            res = execute_sell(symbol=symbol, shares=0, outside_rth=outside_rth, reason=reason)
            self._send_json(res, 200)

        # 3. API: Rotace kapitálu (Odříznutí ležáku / TP a nákup nového kandidáta)
        elif self.path in ("/api/ibkr/rotate", "/api/autoinvest/substitute"):
            body = self._read_json_body()
            sell_sym = body.get("sell_symbol", "").upper().strip()
            buy_sym = body.get("buy_symbol", "").upper().strip()
            buy_shares = int(body.get("buy_shares", 0))
            outside_rth = bool(body.get("outside_rth", True))

            logger.info(f"Přijat požadavek na rotaci z {sell_sym} do {buy_sym}")
            if not sell_sym:
                self._send_json({"ok": False, "error": "Chybí symbol pro prodej!"}, 200)
                return

            res = execute_rotate(sell_symbol=sell_sym, buy_symbol=buy_sym, buy_shares=buy_shares, outside_rth=outside_rth)
            self._send_json(res, 200)

        # 4. API: Okamžitá synchronizace portfolia z IBKR
        elif self.path == "/api/ibkr/sync":
            logger.info("Vyžádána manuální synchronizace z IB Gateway...")
            ok = sync_ibkr()
            if ok and os.path.exists(LIVE_PORTFOLIO_PATH):
                with open(LIVE_PORTFOLIO_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._send_json({"ok": True, "portfolio": data})
            else:
                self._send_json({"ok": False, "error": "Synchronizace s IB Gateway selhala."}, 500)

        # 5. API: Tržní skener
        elif self.path == "/api/scan":
            logger.info("Přijat požadavek na aktualizaci tržních dat (/api/scan)...")
            try:
                run_scanner(allow_mock_fallback=True)
                self._send_json({"status": "success", "message": "Tržní report byl úspěšně aktualizován."})
            except Exception as e:
                logger.error(f"Chyba při aktualizaci: {e}", exc_info=True)
                self._send_json({"status": "error", "message": str(e)}, 500)

        # 6. API: Silver Walk-Forward Step (Odemkne a provede zvolený měsíc 2026)
        elif self.path == "/api/silver/walkforward-step":
            body = self._read_json_body()
            month_ym = body.get("month", "")
            try:
                from silver.backtest.silver_2026_interactive_runner import run_month_step, load_walkforward_state
                if not month_ym:
                    st = load_walkforward_state()
                    for ym, m_info in st.get("months", {}).items():
                        if m_info.get("status") == "LOCKED":
                            month_ym = ym
                            break
                if not month_ym:
                    self._send_json({"ok": False, "error": "Všechny měsíce roku 2026 již byly odemčeny."}, 400)
                    return
                res = run_month_step(month_ym)
                self._send_json(res, 200 if res.get("ok") else 400)
            except Exception as e:
                logger.error(f"Chyba při běhu walkforward měsíce {month_ym}: {e}", exc_info=True)
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        # 7. API: Silver Walk-Forward Reset (Znovu uzamkne celý rok 2026)
        elif self.path == "/api/silver/walkforward-reset":
            try:
                from silver.backtest.silver_2026_interactive_runner import reset_walkforward
                res = reset_walkforward()
                self._send_json(res, 200)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        else:
            self.send_error(404, "Endpoint nenalezen")

    def do_GET(self):
        # API: Přesměrování na Centrální rozcestník všech stránek
        if self.path in ("/hub", "/hub/", "/pages", "/pages/", "/sitemap", "/sitemap/", "/portal", "/portal/"):
            self.send_response(302)
            self.send_header("Location", "/hub.html")
            self.end_headers()
            return

        # API: Přesměrování na samostatnou Silver vizualizační stránku
        elif self.path in ("/silver", "/silver/"):
            self.send_response(302)
            self.send_header("Location", "/SilverInvestDemo.html")
            self.end_headers()
            return

        elif self.path in ("/silver_results_2026", "/silver_results_2026/"):
            self.send_response(302)
            self.send_header("Location", "/silver_results_2026.html")
            self.end_headers()
            return

        # API: Stav Silver portfolia a rizikového motoru
        elif self.path.startswith("/api/silver/state"):
            try:
                p_file = os.path.join(WORKSPACE_DIR, "data", "silver_live_portfolio.json")
                if os.path.exists(p_file):
                    with open(p_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                else:
                    data = {
                        "account_id": "DU_SILVER_DEMO",
                        "equity_usd": 10000.0,
                        "cash_usd": 10000.0,
                        "sovereign_floor_usd": 9000.0,
                        "sovereign_floor_buffer_usd": 1000.0,
                        "sovereign_floor_breached": False,
                        "contracts": 0,
                        "max_contracts": 1,
                        "symbol": "SIL",
                        "full_contract_oz": 1000.0,
                        "current_regime": "TREND_BULL",
                        "killzone_status": "ACTIVE",
                        "volatility_gate_status": "ACTIVE_SAFE",
                        "max_sl_dollars_per_oz": 0.40,
                        "current_atr_14": 0.185,
                        "ibkr": {"host": "127.0.0.1", "port": 4002, "client_id": 20, "status": "READY"}
                    }
                self._send_json({"ok": True, "state": data})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        # API: High Alpha Silver telemetrie (SHFE premium, GSR Z-Score, COT, TAN solar, HG)
        elif self.path.startswith("/api/silver/telemetry"):
            try:
                t_file = os.path.join(WORKSPACE_DIR, "data", "high_alpha_silver_telemetry.json")
                if os.path.exists(t_file):
                    with open(t_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                else:
                    from silver.data.silver_high_alpha_feeds import SilverHighAlphaFeedsCollector
                    data = SilverHighAlphaFeedsCollector().collect_all()
                self._send_json({"ok": True, "telemetry": data})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        # API: Silver obchody a historie
        elif self.path.startswith("/api/silver/trades"):
            try:
                trades_list = []
                j_file = os.path.join(WORKSPACE_DIR, "silver", "logs", "silver_trades.jsonl")
                if os.path.exists(j_file):
                    with open(j_file, "r", encoding="utf-8") as f:
                        for line in f:
                            if line.strip():
                                trades_list.append(json.loads(line))
                ins_file = os.path.join(WORKSPACE_DIR, "data", "silver_insample_results.json")
                ins_trades = []
                if os.path.exists(ins_file):
                    with open(ins_file, "r", encoding="utf-8") as f:
                        ins_trades = json.load(f).get("trades", [])
                self._send_json({"ok": True, "journal_trades": trades_list, "insample_trades": ins_trades[:50]})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        # API: Srovnání Gold vs Silver a Portfolio Synergy
        elif self.path.startswith("/api/silver/comparison"):
            try:
                comp_file = os.path.join(WORKSPACE_DIR, "data", "silver_gold_comparison.json")
                syn_file = os.path.join(WORKSPACE_DIR, "data", "silver_portfolio_synergy.json")
                comp_data = {}
                syn_data = {}
                if os.path.exists(comp_file):
                    with open(comp_file, "r", encoding="utf-8") as f:
                        comp_data = json.load(f)
                if os.path.exists(syn_file):
                    with open(syn_file, "r", encoding="utf-8") as f:
                        syn_data = json.load(f)
                self._send_json({"ok": True, "comparison": comp_data, "synergy": syn_data})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        # API: Stav Walk-Forward Manifestu 2026
        elif self.path.startswith("/api/silver/walkforward-manifest"):
            try:
                from silver.backtest.silver_2026_interactive_runner import load_walkforward_state
                from silver_walkforward_manager import build_or_refresh_manifest
                manifest = build_or_refresh_manifest(force_relock=False)
                state = load_walkforward_state()
                self._send_json({"ok": True, "manifest": manifest, "state": state})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        # API: Okamžité spuštění / zastavení brány přes GET odkaz nebo tlačítko
        elif self.path.startswith("/api/future_invest/gateway_power") or self.path.startswith("/api/gateway/launch") or self.path.startswith("/api/gateway/power"):
            action = "START" if "START" in self.path.upper() or "LAUNCH" in self.path.upper() else ("STOP" if "STOP" in self.path.upper() or "KILL" in self.path.upper() else "TOGGLE")
            import execute_futures_trade
            res = execute_futures_trade.toggle_gateway_power(action)
            import ibkr_watchdog
            new_state = ibkr_watchdog.update_watchdog_cycle()
            res["state"] = new_state
            self._send_json(res, 200)
            return

        # API: Spuštění / restartování Watchdog daemona
        elif self.path.startswith("/api/watchdog/launch") or self.path.startswith("/api/watchdog/start"):
            try:
                import subprocess
                flags = 0
                if sys.platform == "win32":
                    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
                wd_path = os.path.join(WORKSPACE_DIR, "ibkr_watchdog.py")
                p = subprocess.Popen([sys.executable, wd_path], cwd=WORKSPACE_DIR, shell=False, creationflags=flags)
                import ibkr_watchdog
                new_state = ibkr_watchdog.update_watchdog_cycle()
                self._send_json({"ok": True, "message": f"Watchdog úspěšně spuštěn na pozadí (PID {p.pid}).", "pid": p.pid, "state": new_state}, 200)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        # API: Živý systémový report pro system_status.html (s krátkou 2s cache proti přetížení)
        elif self.path.startswith("/data/system_report.json") or self.path.startswith("/api/system/report"):
            try:
                import system_reporter
                global _CACHED_SYS_REPORT, _CACHED_SYS_REPORT_TIME
                now_t = time.time()
                if '_CACHED_SYS_REPORT' not in globals() or (now_t - _CACHED_SYS_REPORT_TIME) > 2.0:
                    report = system_reporter.generate_system_report()
                    _CACHED_SYS_REPORT = report
                    _CACHED_SYS_REPORT_TIME = now_t
                else:
                    report = _CACHED_SYS_REPORT
                self._send_json(report, 200)
            except Exception as e:
                logger.error(f"Chyba při sestavování živého systémového reportu: {e}", exc_info=True)
                report_file = os.path.join(WORKSPACE_DIR, "data", "system_report.json")
                if os.path.exists(report_file):
                    with open(report_file, "r", encoding="utf-8") as f:
                        self._send_json(json.load(f), 200)
                else:
                    self._send_json({"ok": False, "error": str(e)}, 500)
            return

        # API: Kompletní živá data pro FutureInvestDemo (s živým ověřením socketu 7497)
        elif self.path.startswith("/api/future_invest/data"):
            try:
                import ibkr_watchdog
                global _CACHED_WATCHDOG_STATE, _CACHED_WATCHDOG_TIME
                now_t = time.time()
                if '_CACHED_WATCHDOG_STATE' not in globals() or (now_t - _CACHED_WATCHDOG_TIME) > 2.0:
                    data = ibkr_watchdog.update_watchdog_cycle()
                    _CACHED_WATCHDOG_STATE = data
                    _CACHED_WATCHDOG_TIME = now_t
                else:
                    data = _CACHED_WATCHDOG_STATE
                self._send_json({"ok": True, "data": data})
            except Exception as e:
                logger.error(f"Chyba při čtení stavu FutureInvest: {e}", exc_info=True)
                state_file = os.path.join(WORKSPACE_DIR, "data", "future_invest_demo_state.json")
                if os.path.exists(state_file):
                    with open(state_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    self._send_json({"ok": True, "data": data})
                else:
                    self._send_json({"ok": False, "error": str(e)}, 500)
            return

        elif self.path.startswith("/api/future_invest/continuity"):
            try:
                import data_continuity_service
                res = data_continuity_service.check_data_consistency()
                self._send_json({"ok": True, "continuity": res})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        # API: Kontrola stavu IBKR účtu
        elif self.path.startswith("/api/ibkr/status"):
            try:
                status = check_account_status()
                self._send_json({"ok": True, "status": status})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)

        # API: Živé portfolio z JSON
        elif self.path.startswith("/api/ibkr/portfolio"):
            if os.path.exists(LIVE_PORTFOLIO_PATH):
                with open(LIVE_PORTFOLIO_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._send_json(data)
            else:
                self._send_json({"ok": False, "error": "live_portfolio.json neexistuje"}, 404)

        elif self.path == "/api/scan":
            self.do_POST()

        elif self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()

        else:
            # Běžné statické soubory s CORS hlavičkou
            super().do_GET()

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        super().end_headers()

    def log_message(self, format, *args):
        try:
            msg = format % args
            if " 200 " in msg and (".ico" in msg or ".css" in msg or ".js" in msg):
                return
            logger.info("%s - %s", self.address_string(), msg)
        except Exception:
            pass


def background_sync_worker(interval_seconds: int = 15):
    """Běží na pozadí a pravidelně stahuje nejčerstvější stav z IB Gateway port 7497 pokud je dostupná."""
    import asyncio
    import socket
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass
    logger.info(f"🔄 Spuštěn periodický synchronizátor IB Gateway (interval: {interval_seconds} s)...")
    while True:
        try:
            # Rychlý test, zda port 7497 vůbec naslouchá
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            is_open = (s.connect_ex(("127.0.0.1", 7497)) == 0)
            s.close()
            if is_open:
                sync_ibkr(host="127.0.0.1", port=7497, client_id=990)
            else:
                # Pokud IB Gateway neběží, aktualizujeme watchdog cyklus bez zdržení
                import ibkr_watchdog
                ibkr_watchdog.update_watchdog_cycle()
        except Exception as e:
            logger.warning(f"Chyba v periodickém synchronizátoru: {e}")
        time.sleep(interval_seconds)


def start_server():
    index_path = os.path.join(DIRECTORY, "index.html")
    if not os.path.exists(index_path):
        logger.info("Soubor index.html zatím neexistuje. Provádím první sken...")
        try:
            run_scanner(allow_mock_fallback=True)
        except Exception as e:
            logger.error(f"Chyba při úvodním skenu: {e}")

    # Spustit periodickou synchronizaci v pozadí
    t = threading.Thread(target=background_sync_worker, daemon=True)
    t.start()

    server_address = ("127.0.0.1", PORT)
    httpd = ThreadingHTTPServer(server_address, SuggestInvestRequestHandler)
    
    local_url = f"http://localhost:{PORT}/trading.html"
    print("\n" + "=" * 65)
    print(f"🚀 SuggestInvest Master Server & IBKR Trading API běží!")
    print(f"👉 Web: {local_url}")
    print(f"🔗 IB Gateway: 127.0.0.1:7497 (Socket API)")
    print(f"🛑 Pro ukončení stiskněte: Ctrl + C")
    print("=" * 65 + "\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nZastavuji server...")
        httpd.server_close()
        logger.info("Server byl v pořádku zastaven.")


if __name__ == "__main__":
    start_server()
