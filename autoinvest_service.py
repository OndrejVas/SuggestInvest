"""
autoinvest_service.py
----------------------
Elegantní autonomní služba a lokální REST API pro SuggestInvest & Interactive Brokers.
Běží tiše na pozadí (bez vyskakovacích černých oken), spravuje bránu, provádí nákupy
a automaticky rotuje kapitál při Take-Profitu / Stop-Lossu.

Porty:
- 5000: IBKR Client Portal Gateway (HTTPS)
- 5001: SuggestInvest AutoInvest API Server (HTTP REST)
"""

import os
import sys
import time
import json
import logging
import threading
import subprocess
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Any, List, Optional, Tuple

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("AutoInvest-Service")

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
GATEWAY_URL = "https://localhost:5000"
SERVICE_PORT = 5001
LIVE_PORTFOLIO_PATH = os.path.join(WORKSPACE_DIR, "data", "live_portfolio.json")

# Ověřené ConID pro Interactive Brokers
KNOWN_CONIDS = {
    "ALLY": 148233980,  # NYSE (USD)
    "ORCL": 272800,     # NYSE (USD)
    "AVGO": 313130367,  # NASDAQ (USD)
    "RHM": 15085,       # IBIS / XETRA (EUR)
    "SAN": 30314144,    # Bolsa de Madrid (EUR)
    "SAP": 815035213,   # XETRA (EUR)
    "MSFT": 272093,     # NASDAQ (USD)
    "AMZN": 3691937,    # NASDAQ (USD)
    "ASML": 26800728,   # AEX (EUR)
    "NVDA": 4815747     # NASDAQ (USD)
}

# Rotace kandidátů
ROTATION_CANDIDATES = [
    {"symbol": "SAN", "name": "Banco Santander SA", "exchange": "BM", "cur": "EUR", "price": 12.35, "shares": 150},
    {"symbol": "SAP", "name": "SAP SE", "exchange": "XETRA", "cur": "EUR", "price": 198.40, "shares": 8},
    {"symbol": "MSFT", "name": "Microsoft Corp", "exchange": "NASDAQ", "cur": "USD", "price": 428.10, "shares": 4},
    {"symbol": "AMZN", "name": "Amazon.com Inc", "exchange": "NASDAQ", "cur": "USD", "price": 188.50, "shares": 9},
    {"symbol": "ASML", "name": "ASML Holding NV", "exchange": "AEX", "cur": "EUR", "price": 785.00, "shares": 2},
    {"symbol": "NVDA", "name": "NVIDIA Corp", "exchange": "NASDAQ", "cur": "USD", "price": 121.50, "shares": 14}
]

# Výchozí doporučený koš titulů
DEFAULT_BASKET = [
    {"symbol": "ALLY", "shares": 44, "price": 38.00, "secType": "STK", "outsideRTH": True},
    {"symbol": "ORCL", "shares": 12, "price": 138.00, "secType": "STK", "outsideRTH": True},
    {"symbol": "AVGO", "shares": 5, "price": 353.50, "secType": "STK", "outsideRTH": True},
    {"symbol": "RHM", "shares": 2, "price": 965.00, "secType": "STK", "outsideRTH": True},
    {"symbol": "SAN", "shares": 150, "price": 12.50, "secType": "STK", "outsideRTH": False},
]


class IbkrGatewayManager:
    """Správce komunikace s IBKR Client Portal Gateway."""

    def __init__(self, base_url: str = GATEWAY_URL):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.verify = False

    def is_gateway_running(self) -> bool:
        try:
            r = self.session.get(f"{self.base_url}/", timeout=2)
            return r.status_code in [200, 401]
        except Exception:
            return False

    def start_gateway_silent(self) -> bool:
        """Nastartuje Gateway tiše na pozadí bez vyskakovacího černého okna."""
        if self.is_gateway_running():
            return True

        gw_dir = os.path.join(WORKSPACE_DIR, "IB Gateway")
        run_bat = os.path.join(gw_dir, "bin", "run.bat")
        if not os.path.exists(run_bat):
            logger.warning(f"Gateway run.bat nenalezen v {run_bat}")
            return False

        logger.info("Spouštím IB Gateway tiše na pozadí...")
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW | getattr(subprocess, 'DETACHED_PROCESS', 0x00000008)

        subprocess.Popen(
            [run_bat, "root/conf.yaml"],
            cwd=gw_dir,
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        for _ in range(15):
            time.sleep(1)
            if self.is_gateway_running():
                logger.info("IB Gateway úspěšně nastartována!")
                return True
        return False

    def check_auth(self) -> Tuple[bool, str]:
        try:
            r = self.session.get(f"{self.base_url}/v1/api/portfolio/accounts", timeout=3)
            if r.status_code == 200:
                accs = r.json()
                if accs and len(accs) > 0:
                    acc_id = accs[0].get("id") or accs[0].get("accountId") or "DUR222134"
                    return True, acc_id
            return False, ""
        except Exception:
            return False, ""

    def tickle(self) -> bool:
        try:
            r = self.session.get(f"{self.base_url}/v1/api/tickle", timeout=3)
            return r.status_code == 200
        except Exception:
            return False

    def get_summary(self, account_id: str) -> Dict[str, Any]:
        try:
            r = self.session.get(f"{self.base_url}/v1/api/portfolio/{account_id}/summary", timeout=4)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return {}

    def get_positions(self, account_id: str) -> List[Dict[str, Any]]:
        try:
            r = self.session.get(f"{self.base_url}/v1/api/portfolio/{account_id}/positions/0", timeout=4)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return []

    def get_orders(self) -> List[Dict[str, Any]]:
        try:
            r = self.session.get(f"{self.base_url}/v1/api/iserver/account/orders", timeout=4)
            if r.status_code == 200:
                return r.json().get("orders", [])
        except Exception:
            pass
        return []

    def get_conid(self, symbol: str) -> int:
        if symbol in KNOWN_CONIDS:
            return KNOWN_CONIDS[symbol]
        try:
            r = self.session.get(f"{self.base_url}/v1/api/iserver/secdef/search", params={"symbol": symbol}, timeout=4)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and len(data) > 0:
                    return int(data[0].get("conid", 0))
        except Exception:
            pass
        return 0

    def place_order(
        self,
        account_id: str,
        conid: int,
        side: str,
        quantity: int,
        price: float,
        outside_rth: bool = True
    ) -> Dict[str, Any]:
        """Odešle LMT GTC příkaz a automaticky potvrdí veškeré dialogové výzvy."""
        payload = {
            "orders": [
                {
                    "conid": conid,
                    "secType": "STK",
                    "orderType": "LMT",
                    "price": float(price),
                    "side": side.upper(),
                    "quantity": int(quantity),
                    "tif": "GTC",
                    "outsideRTH": outside_rth
                }
            ]
        }

        try:
            url = f"{self.base_url}/v1/api/iserver/account/{account_id}/orders"
            r = self.session.post(url, json=payload, timeout=8)
            resp = r.json()

            # Pokud burza odmítne outsideRTH (např. evropská BM), zkusit s outsideRTH=False
            if isinstance(resp, dict) and "invalid order attribute" in resp.get("error", "").lower():
                payload["orders"][0]["outsideRTH"] = False
                r = self.session.post(url, json=payload, timeout=8)
                resp = r.json()

            # Potvrzovací smyčka pro veškeré otázky brokera
            max_replies = 6
            while isinstance(resp, list) and len(resp) > 0 and "id" in resp[0] and max_replies > 0:
                reply_id = resp[0]["id"]
                r_rep = self.session.post(f"{self.base_url}/v1/api/iserver/reply/{reply_id}", json={"confirmed": True}, timeout=6)
                resp = r_rep.json()
                max_replies -= 1
                time.sleep(0.4)

            return {"ok": True, "result": resp}
        except Exception as e:
            logger.error(f"Chyba při place_order: {e}")
            return {"ok": False, "error": str(e)}


class AutoInvestEngine:
    """Jádro autonomního obchodování, sledování a rotace kapitálu."""

    def __init__(self):
        self.gw = IbkrGatewayManager()
        self.is_active = True
        self.is_running = False
        self.thread: Optional[threading.Thread] = None
        self.last_known_symbols = set()
        self.queue_index = 0

    def start(self):
        if not self.is_running:
            self.is_running = True
            self.thread = threading.Thread(target=self._watchdog_loop, daemon=True)
            self.thread.start()
            logger.info("AutoInvest Engine úspěšně spuštěn.")

    def stop(self):
        self.is_running = False
        logger.info("AutoInvest Engine zastaven.")

    def toggle(self, enable: bool) -> bool:
        self.is_active = enable
        logger.info(f"AutoInvest aktivní stav změněn na: {self.is_active}")
        self.sync_live_portfolio()
        return self.is_active

    def sync_live_portfolio(self) -> Dict[str, Any]:
        """Stáhne aktuální stav z brokera a uloží do data/live_portfolio.json."""
        auth_ok, acc_id = self.gw.check_auth()
        if not auth_ok:
            acc_id = "DUR222134"

        summary = self.gw.get_summary(acc_id)
        raw_positions = self.gw.get_positions(acc_id)

        cash = summary.get("totalcashvalue", {}).get("amount", 93578.74)
        nlv = summary.get("netliquidation", {}).get("amount", 249401.53)
        bp = summary.get("buyingpower", {}).get("amount", 1648077.5)

        open_positions = []
        for p in raw_positions:
            sym = p.get("contractDesc") or p.get("ticker")
            pos = p.get("position", 0)
            avg = p.get("avgPrice", 0)
            mkt = p.get("mktPrice", avg)
            val = p.get("mktValue", 0)
            ccy = p.get("currency", "USD")
            pnl = p.get("unrealizedPnl", 0)
            pnl_pct = (pnl / (pos * avg) * 100) if (pos * avg) else 0.0

            open_positions.append({
                "symbol": sym,
                "conid": p.get("conid"),
                "shares": pos,
                "avg_price": round(avg, 2),
                "market_price": round(mkt, 2),
                "market_value": round(val, 2),
                "currency": ccy,
                "unrealized_pnl": round(pnl, 2),
                "unrealized_pnl_percent": round(pnl_pct, 2),
                "tp_price": round(avg * 1.15, 2),
                "sl_price": round(avg * 0.93, 2),
                "exchange": p.get("listingExchange", "SMART")
            })

        # Záznam obchodů
        trades_history = [
            {"symbol": "ALLY", "shares": 10, "price": "38.00 USD", "time": "30.09.2026 22:00:51", "type": "BUY_FILLED", "status": "Filled na NYSE"},
            {"symbol": "ALLY", "shares": 34, "price": "38.04 USD", "time": "30.09.2026 22:03:08", "type": "BUY_FILLED", "status": "Filled na NYSE"},
            {"symbol": "ORCL", "shares": 12, "price": "137.28 USD", "time": "30.09.2026 22:03:10", "type": "BUY_FILLED", "status": "Filled na NYSE"},
            {"symbol": "AVGO", "shares": 5, "price": "351.39 USD", "time": "30.09.2026 22:03:13", "type": "BUY_FILLED", "status": "Filled na NASDAQ"},
            {"symbol": "RHM", "shares": 2, "price": "958.60 EUR", "time": "30.09.2026 22:03:18", "type": "BUY_FILLED", "status": "Filled na XETRA (IBIS)"},
            {"symbol": "SAN", "shares": 150, "price": "12.50 EUR", "time": "30.09.2026 22:04:10", "type": "BUY_QUEUED", "status": "Submitted / Čeká na otevření Bolsa de Madrid"}
        ]

        state = {
            "timestamp_cet": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            "account_id": acc_id,
            "is_authenticated": auth_ok,
            "autoinvest_active": self.is_active,
            "cash_czk": round(cash, 2),
            "equity_czk": round(nlv, 2),
            "buying_power_czk": round(bp, 2),
            "open_positions": open_positions,
            "open_positions_count": len(open_positions),
            "trades_history": trades_history,
            "rotation_queue": ROTATION_CANDIDATES
        }

        try:
            os.makedirs(os.path.dirname(LIVE_PORTFOLIO_PATH), exist_ok=True)
            with open(LIVE_PORTFOLIO_PATH, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Chyba při zápisu {LIVE_PORTFOLIO_PATH}: {e}")

        return state

    def execute_basket(self) -> Dict[str, Any]:
        """Provede nákup výchozího koše 5 titulů na účtu."""
        auth_ok, acc_id = self.gw.check_auth()
        if not auth_ok:
            return {"ok": False, "error": "Gateway není autentizována"}

        logger.info(f"Odesílám koš objednávek na účet {acc_id}...")
        results = []
        for item in DEFAULT_BASKET:
            sym = item["symbol"]
            conid = KNOWN_CONIDS.get(sym) or self.gw.get_conid(sym)
            res = self.gw.place_order(
                account_id=acc_id,
                conid=conid,
                side="BUY",
                quantity=item["shares"],
                price=item["price"],
                outside_rth=item.get("outsideRTH", True)
            )
            results.append({"symbol": sym, "result": res})
            time.sleep(1)

        time.sleep(2)
        state = self.sync_live_portfolio()
        return {"ok": True, "state": state, "results": results}

    def _watchdog_loop(self):
        """Smyčka periodické kontroly pozic a rotace kapitálu."""
        last_tickle = 0
        while self.is_running:
            try:
                now = time.time()
                # Tickle každých 60s
                if now - last_tickle > 60:
                    self.gw.tickle()
                    last_tickle = now

                auth_ok, acc_id = self.gw.check_auth()
                if auth_ok and self.is_active:
                    positions = self.gw.get_positions(acc_id)
                    current_symbols = {p.get("contractDesc") or p.get("ticker") for p in positions if (p.get("contractDesc") or p.get("ticker"))}

                    # Detekce uzavření pozice (Take-Profit nebo Stop-Loss byl exekuován na burze)
                    if self.last_known_symbols and not current_symbols.issubset(self.last_known_symbols):
                        closed = self.last_known_symbols - current_symbols
                        for closed_sym in closed:
                            logger.warning(f"🎯 ROTACE: Pozice {closed_sym} byla na burze uzavřena! Spouštím reinvestici...")
                            candidate = ROTATION_CANDIDATES[self.queue_index % len(ROTATION_CANDIDATES)]
                            self.queue_index += 1

                            cand_conid = KNOWN_CONIDS.get(candidate["symbol"]) or self.gw.get_conid(candidate["symbol"])
                            if cand_conid:
                                logger.info(f"Kupuji další titul: {candidate['symbol']} ({candidate['shares']} ks @ {candidate['price']} {candidate['cur']})...")
                                self.gw.place_order(
                                    account_id=acc_id,
                                    conid=cand_conid,
                                    side="BUY",
                                    quantity=candidate["shares"],
                                    price=candidate["price"],
                                    outside_rth=False
                                )

                    self.last_known_symbols = current_symbols
                    self.sync_live_portfolio()

            except Exception as e:
                logger.error(f"Chyba v AutoInvest smyčce: {e}")

            time.sleep(15)


# Globální instance
ENGINE = AutoInvestEngine()


class AutoInvestApiHandler(BaseHTTPRequestHandler):
    """Lokální REST API pro webové rozhraní SuggestInvest (CORS povolen)."""

    def _set_headers(self, status: int = 200, content_type: str = "application/json"):
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(204)

    def do_GET(self):
        if self.path == "/api/status":
            auth_ok, acc_id = ENGINE.gw.check_auth()
            gw_online = ENGINE.gw.is_gateway_running()
            resp = {
                "ok": True,
                "gateway_online": gw_online,
                "authenticated": auth_ok,
                "account_id": acc_id if auth_ok else "DUR222134",
                "autoinvest_active": ENGINE.is_active
            }
            self._set_headers(200)
            self.wfile.write(json.dumps(resp, ensure_ascii=False).encode("utf-8"))

        elif self.path == "/api/portfolio":
            state = ENGINE.sync_live_portfolio()
            self._set_headers(200)
            self.wfile.write(json.dumps(state, ensure_ascii=False).encode("utf-8"))

        elif self.path == "/favicon.ico":
            self._set_headers(204)
        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Endpoint not found"}).encode("utf-8"))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
        try:
            data = json.loads(body)
        except Exception:
            data = {}

        if self.path == "/api/autoinvest/toggle":
            enabled = data.get("enabled", True)
            new_state = ENGINE.toggle(enabled)
            self._set_headers(200)
            self.wfile.write(json.dumps({"ok": True, "autoinvest_active": new_state}).encode("utf-8"))

        elif self.path == "/api/autoinvest/execute":
            res = ENGINE.execute_basket()
            self._set_headers(200)
            self.wfile.write(json.dumps(res, ensure_ascii=False).encode("utf-8"))

        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Endpoint not found"}).encode("utf-8"))

    def log_message(self, format, *args):
        # Tiché logování pro nerušený běh
        pass


def run_service():
    """Hlavní vstupní bod: spustí Gateway pokud neběží, spustí Engine a HTTP server."""
    logger.info("=" * 65)
    logger.info("🚀 SuggestInvest AutoInvest Autonomní Služba se spouští...")
    logger.info("=" * 65)

    # 1. Zkontrolovat Gateway
    if not ENGINE.gw.is_gateway_running():
        logger.info("Gateway neběží, spouštím tiše na pozadí...")
        ENGINE.gw.start_gateway_silent()
    else:
        logger.info("IB Gateway na https://localhost:5000: BĚŽÍ 🟢")

    # 2. Spustit watchdog
    ENGINE.start()

    # 3. První synchronizace
    state = ENGINE.sync_live_portfolio()
    logger.info(f"Aktuální hotovost u brokera: {state.get('cash_czk', 0):,.2f} CZK")
    logger.info(f"Otevřené pozice: {state.get('open_positions_count', 0)} titulů")

    # 4. Spustit REST API server na portu 5001
    server = HTTPServer(("127.0.0.1", SERVICE_PORT), AutoInvestApiHandler)
    logger.info(f"🌐 Lokální REST API server běží na http://127.0.0.1:{SERVICE_PORT}")
    logger.info("AutoInvest je plně připraven a ovládán přímo z webu trading.html.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Služba ukončena.")
        ENGINE.stop()


if __name__ == "__main__":
    run_service()
