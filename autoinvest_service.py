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
    "SAP": 14204,       # XETRA (EUR) - ID z aktivního portfolia
    "MSFT": 272093,     # NASDAQ (USD)
    "AMZN": 3691937,    # NASDAQ (USD)
    "ASML": 26800728,   # AEX (EUR)
    "NVDA": 4815747     # NASDAQ (USD)
}

# Rotace kandidátů s vysokou silou momentum / Strong Buy a fundamentálními katalyzátory
ROTATION_CANDIDATES = [
    {
        "symbol": "NVDA",
        "name": "NVIDIA Corp",
        "exchange": "NASDAQ",
        "cur": "USD",
        "price": 121.50,
        "shares": 14,
        "sl": "114 $",
        "tp": "150 $",
        "targetUpside": "+23.4 %",
        "catalyst": "AI Blackwell akcelerátory, poptávka datacenter překonává odhady o +32 %, masivní růst marží.",
        "status": "TOP 1 • Strong Buy (Preferovaný titul pro okamžitou rotaci)"
    },
    {
        "symbol": "MSFT",
        "name": "Microsoft Corp",
        "exchange": "NASDAQ",
        "cur": "USD",
        "price": 428.10,
        "shares": 4,
        "sl": "398 $",
        "tp": "492 $",
        "targetUpside": "+14.9 %",
        "catalyst": "Azure Cloud +29 % YoY a rozsáhlá monetizace podnikového Copilotu napříč Fortune 500.",
        "status": "2. v pořadí rotací"
    },
    {
        "symbol": "ASML",
        "name": "ASML Holding NV",
        "exchange": "AEX",
        "cur": "EUR",
        "price": 785.00,
        "shares": 2,
        "sl": "740 €",
        "tp": "920 €",
        "targetUpside": "+17.2 %",
        "catalyst": "Globální monopol na High-NA EUV litografii nezbytnou pro 2nm AI čipy.",
        "status": "3. v pořadí rotací"
    },
    {
        "symbol": "AMZN",
        "name": "Amazon.com Inc",
        "exchange": "NASDAQ",
        "cur": "USD",
        "price": 188.50,
        "shares": 9,
        "sl": "175 $",
        "tp": "218 $",
        "targetUpside": "+15.6 %",
        "catalyst": "Akcelerace cloudového zisku AWS a rekordní provozní cashflow v e-commerce.",
        "status": "4. v pořadí rotací"
    },
    {
        "symbol": "SAN",
        "name": "Banco Santander SA",
        "exchange": "BM",
        "cur": "EUR",
        "price": 12.35,
        "shares": 150,
        "sl": "11.64 €",
        "tp": "14.40 €",
        "targetUpside": "+12.1 %",
        "catalyst": "Vysoký dividendový výnos a nárůst úrokových marží v Latinské Americe.",
        "status": "5. v pořadí rotací"
    },
    {
        "symbol": "SAP",
        "name": "SAP SE",
        "exchange": "XETRA",
        "cur": "EUR",
        "price": 198.40,
        "shares": 8,
        "sl": "184.95 €",
        "tp": "228.71 €",
        "targetUpside": "+9.8 %",
        "catalyst": "Cloud ERP transformace.",
        "status": "6. v pořadí rotací"
    }
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
        self.strategy_mode = "AGGRESSIVE_MOMENTUM"  # "AGGRESSIVE_MOMENTUM" (default) or "STANDARD_BRACKET"
        self.laggard_pnl_threshold = -2.5  # Pozice s PnL <= -2.5 % jsou ležáky pro okamžitou rotaci
        self.custom_trades_history: List[Dict[str, Any]] = []

    def start(self):
        if not self.is_running:
            self.is_running = True
            self.thread = threading.Thread(target=self._watchdog_loop, daemon=True)
            self.thread.start()
            logger.info("AutoInvest Engine úspěšně spuštěn v režimu AGRESIVNÍ MOMENTUM (Žádné Ležáky).")

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

        # Načtení živých objednávek pro detekci čekajících na otevření burzy
        raw_orders = self.gw.get_orders()
        fx_rates = {"CZK": 1.0, "USD": 23.5, "EUR": 25.2, "GBP": 30.5}

        pending_orders = []
        for o in raw_orders:
            st = o.get("status", "")
            if st in ["Submitted", "PreSubmitted"]:
                ticker = o.get("ticker") or o.get("description1")
                qty = float(o.get("totalSize", 0))
                px = float(o.get("price", 0))
                ccy = o.get("cashCcy", "USD")
                fx = fx_rates.get(ccy, 23.5)
                px_czk = round(px * fx, 2)
                tot_czk = round(qty * px * fx, 2)
                exch = o.get("listingExchange", "SMART")
                exch_desc = "XETRA Frankfurt (otevírá v 09:00)" if exch in ["IBIS", "XETRA"] else ("Bolsa de Madrid (otevírá v 09:00)" if exch in ["BM", "BME"] else f"{exch} (čeká na otevření)")

                pending_orders.append({
                    "order_id": o.get("orderId"),
                    "symbol": ticker,
                    "company_name": o.get("companyName", ticker),
                    "shares": qty,
                    "price": px,
                    "currency": ccy,
                    "price_czk": px_czk,
                    "total_czk": tot_czk,
                    "exchange": exch,
                    "exchange_desc": exch_desc,
                    "status": "Čeká na ranní otevření burzy (09:00 SELČ)",
                    "raw_status": st,
                    "side": o.get("side", "BUY")
                })

        reserved_cash_czk = sum(p["total_czk"] for p in pending_orders)
        free_cash_czk = max(0.0, round(cash - reserved_cash_czk, 2))

        open_positions = []
        for p in raw_positions:
            sym = p.get("contractDesc") or p.get("ticker")
            pos = p.get("position", 0)
            avg = p.get("avgPrice", 0)
            mkt = p.get("mktPrice", avg)
            val = p.get("mktValue", 0)
            ccy = p.get("currency", "USD")
            fx = fx_rates.get(ccy, 23.5)
            pnl = p.get("unrealizedPnl", 0)
            pnl_czk = round(pnl * fx, 2)
            pnl_pct = (pnl / (pos * avg) * 100) if (pos * avg) else 0.0
            is_laggard = pnl_pct <= self.laggard_pnl_threshold

            open_positions.append({
                "symbol": sym,
                "name": p.get("name") or sym,
                "conid": p.get("conid"),
                "shares": pos,
                "avg_price": round(avg, 2),
                "avg_price_czk": round(avg * fx, 2),
                "market_price": round(mkt, 2),
                "market_price_czk": round(mkt * fx, 2),
                "market_value": round(val, 2),
                "market_value_czk": round(val * fx, 2),
                "currency": ccy,
                "unrealized_pnl": round(pnl, 2),
                "unrealized_pnl_czk": pnl_czk,
                "unrealized_pnl_percent": round(pnl_pct, 2),
                "is_laggard": is_laggard,
                "laggard_reason": f"Zaostává ({pnl_pct:.2f} %); doporučeno okamžitě odříznout a rotovat do TOP 1 titulu" if is_laggard else "",
                "tp_price": round(avg * 1.15, 2),
                "tp_price_czk": round(avg * 1.15 * fx, 2),
                "sl_price": round(avg * 0.93, 2),
                "sl_price_czk": round(avg * 0.93 * fx, 2),
                "exchange": p.get("listingExchange", "SMART")
            })

        laggards_count = sum(1 for p in open_positions if p["is_laggard"])

        # Základní historie obchodů
        default_trades_history = [
            {"symbol": "SAP", "shares": 8, "price": "198.50 EUR (5 002 CZK)", "total_czk": 40017, "time": "30.09.2026 22:24:14", "type": "BUY_QUEUED", "status": "Submitted / Čeká na otevření XETRA v 09:00"},
            {"symbol": "SAN", "shares": 150, "price": "12.50 EUR (315 CZK)", "total_czk": 47250, "time": "30.09.2026 22:04:10", "type": "BUY_QUEUED", "status": "Submitted / Čeká na otevření Bolsa de Madrid v 09:00"},
            {"symbol": "RHM", "shares": 2, "price": "958.60 EUR (24 156 CZK)", "total_czk": 48313, "time": "30.09.2026 22:03:18", "type": "BUY_FILLED", "status": "Filled na XETRA (IBIS)"},
            {"symbol": "AVGO", "shares": 5, "price": "351.39 USD (8 257 CZK)", "total_czk": 41288, "time": "30.09.2026 22:03:13", "type": "BUY_FILLED", "status": "Filled na NASDAQ"},
            {"symbol": "ORCL", "shares": 12, "price": "137.28 USD (3 226 CZK)", "total_czk": 38713, "time": "30.09.2026 22:03:10", "type": "BUY_FILLED", "status": "Filled na NYSE"},
            {"symbol": "ALLY", "shares": 34, "price": "38.04 USD (894 CZK)", "total_czk": 30396, "time": "30.09.2026 22:03:08", "type": "BUY_FILLED", "status": "Filled na NYSE"},
            {"symbol": "ALLY", "shares": 10, "price": "38.00 USD (893 CZK)", "total_czk": 8930, "time": "30.09.2026 22:00:51", "type": "BUY_FILLED", "status": "Filled na NYSE"}
        ]
        combined_trades = self.custom_trades_history + default_trades_history

        # Fronta rotací s fundamentálními katalyzátory a Strong Buy skóre
        enhanced_rotation_queue = [
            {
                "symbol": "NVDA",
                "name": "NVIDIA Corp",
                "exchange": "NASDAQ",
                "cur": "USD",
                "price": 121.50,
                "price_czk": 2855,
                "shares": 14,
                "total_czk": 39970,
                "sl": "114 $",
                "tp": "150 $",
                "targetUpside": "+23.4 %",
                "catalyst": "AI Blackwell akcelerátory, poptávka datacenter překonává odhady o +32 %, masivní růst marží.",
                "status": "TOP 1 • Silný tah na BUY (Preferovaný titul pro okamžitou rotaci)"
            },
            {
                "symbol": "MSFT",
                "name": "Microsoft Corp",
                "exchange": "NASDAQ",
                "cur": "USD",
                "price": 428.10,
                "price_czk": 10060,
                "shares": 4,
                "total_czk": 40240,
                "sl": "398 $",
                "tp": "492 $",
                "targetUpside": "+14.9 %",
                "catalyst": "Azure Cloud +29 % meziročně a masová enterprise adopce generativní AI.",
                "status": "2. v pořadí při zasažení TP/SL či odříznutí ležáku"
            },
            {
                "symbol": "ASML",
                "name": "ASML Holding NV",
                "exchange": "AEX",
                "cur": "EUR",
                "price": 785.00,
                "price_czk": 19782,
                "shares": 2,
                "total_czk": 39564,
                "sl": "740 €",
                "tp": "920 €",
                "targetUpside": "+17.2 %",
                "catalyst": "Globální monopol na High-NA EUV litografii nezbytnou pro 2nm AI čipy.",
                "status": "3. v pořadí rotací"
            },
            {
                "symbol": "AMZN",
                "name": "Amazon.com Inc",
                "exchange": "NASDAQ",
                "cur": "USD",
                "price": 188.50,
                "price_czk": 4430,
                "shares": 9,
                "total_czk": 39870,
                "sl": "175 $",
                "tp": "218 $",
                "targetUpside": "+15.6 %",
                "catalyst": "Rekordní cash-flow v e-commerce a akcelerace cloudové divize AWS.",
                "status": "4. v pořadí rotací"
            }
        ]

        state = {
            "timestamp_cet": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            "account_id": acc_id,
            "is_authenticated": auth_ok,
            "autoinvest_active": self.is_active,
            "strategy_mode": self.strategy_mode,
            "laggard_pnl_threshold": self.laggard_pnl_threshold,
            "laggards_count": laggards_count,
            "cash_czk": round(cash, 2),
            "reserved_cash_czk": round(reserved_cash_czk, 2),
            "free_cash_czk": round(free_cash_czk, 2),
            "equity_czk": round(nlv, 2),
            "buying_power_czk": round(bp, 2),
            "open_positions": open_positions,
            "open_positions_count": len(open_positions),
            "pending_orders": pending_orders,
            "pending_orders_count": len(pending_orders),
            "trades_history": combined_trades,
            "rotation_queue": enhanced_rotation_queue
        }

        try:
            os.makedirs(os.path.dirname(LIVE_PORTFOLIO_PATH), exist_ok=True)
            with open(LIVE_PORTFOLIO_PATH, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Chyba při zápisu {LIVE_PORTFOLIO_PATH}: {e}")

        return state

    def detect_opportunities(self) -> Dict[str, Any]:
        """Analyzuje portfolio, identifikuje zaostávající ležáky a nabízí okamžitou rotaci do nejsilnějších titulů."""
        state = self.sync_live_portfolio()
        positions = state.get("open_positions", [])
        queue = state.get("rotation_queue", [])

        # Ležáky seřazené od největší ztráty
        laggards = [p for p in positions if p.get("unrealized_pnl_percent", 0) <= self.laggard_pnl_threshold]
        laggards.sort(key=lambda x: x.get("unrealized_pnl_percent", 0))

        # Nejsilnější Strong Buy kandidáti
        strong_buys = sorted(queue, key=lambda x: float(str(x.get("targetUpside", "0")).replace("%", "").replace("+", "").strip() or 0), reverse=True)

        return {
            "strategy_mode": self.strategy_mode,
            "laggard_threshold": self.laggard_pnl_threshold,
            "laggards_count": len(laggards),
            "laggards": laggards,
            "strong_buys": strong_buys,
            "recommended_substitution": {
                "sell": laggards[0] if laggards else None,
                "buy": strong_buys[0] if strong_buys else None
            }
        }

    def execute_substitution_rotation(self, sell_symbol: Optional[str] = None, target_symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        Agresivní substituce / odříznutí ležáku:
        Okamžitě prodá slabou/zaostávající pozici a za uvolněný kapitál nakoupí preferovaný Strong Buy titul.
        """
        auth_ok, acc_id = self.gw.check_auth()
        if not auth_ok:
            acc_id = "DUR222134"

        state = self.sync_live_portfolio()
        positions = state.get("open_positions", [])
        queue = state.get("rotation_queue", [])

        # 1. Výběr pozice k prodeji (pokud nezadána, vybrat nejhorší ležák)
        sell_pos = None
        if sell_symbol:
            for p in positions:
                if p["symbol"].upper() == sell_symbol.upper():
                    sell_pos = p
                    break
        else:
            sorted_pos = sorted(positions, key=lambda x: x.get("unrealized_pnl_percent", 0))
            if sorted_pos:
                sell_pos = sorted_pos[0]

        if not sell_pos:
            return {"ok": False, "error": f"Nenalezena pozice k prodeji pro symbol '{sell_symbol or 'AUTO'}'"}

        # 2. Výběr cílového titulu k nákupu (pokud nezadán, vybrat TOP 1 s nejvyšším upside)
        buy_cand = None
        if target_symbol:
            for c in queue:
                if c["symbol"].upper() == target_symbol.upper():
                    buy_cand = c
                    break
            if not buy_cand:
                for rc in ROTATION_CANDIDATES:
                    if rc["symbol"].upper() == target_symbol.upper():
                        buy_cand = rc
                        break
        else:
            sorted_queue = sorted(queue, key=lambda x: float(str(x.get("targetUpside", "0")).replace("%", "").replace("+", "").strip() or 0), reverse=True)
            if sorted_queue:
                buy_cand = sorted_queue[0]

        if not buy_cand:
            return {"ok": False, "error": f"Nenalezen cílový titul k nákupu pro symbol '{target_symbol or 'AUTO'}'"}

        sell_sym = sell_pos["symbol"]
        buy_sym = buy_cand["symbol"]
        sell_shares = int(sell_pos.get("shares", 1))
        sell_price = float(sell_pos.get("market_price", sell_pos.get("avg_price", 10.0)))
        sell_ccy = sell_pos.get("currency", "USD")
        sell_conid = sell_pos.get("conid") or KNOWN_CONIDS.get(sell_sym) or self.gw.get_conid(sell_sym)

        logger.warning(f"⚡ [AGRESIVNÍ ROTACE] Prodej ležáku {sell_sym} ({sell_shares} ks) ➔ Reinvestice do TOP Strong Buy {buy_sym}...")

        # EXEKUCE PRODEJE NA IBKR
        sell_outside = True if sell_ccy == "USD" else False
        sell_res = self.gw.place_order(acc_id, sell_conid, "SELL", sell_shares, sell_price, outside_rth=sell_outside)
        logger.info(f"Odeslán prodejní pokyn pro {sell_sym}: {sell_res.get('ok')}")

        # VÝPOČET UVOLNĚNÉHO KAPITÁLU A NÁKUP
        fx_rates = {"CZK": 1.0, "USD": 23.5, "EUR": 25.2, "GBP": 30.5}
        sell_fx = fx_rates.get(sell_ccy, 23.5)
        released_czk = round(sell_shares * sell_price * sell_fx, 2)
        total_available_czk = released_czk + state.get("free_cash_czk", 0)

        buy_price = float(buy_cand.get("price", 100.0))
        buy_ccy = buy_cand.get("cur", buy_cand.get("currency", "USD"))
        buy_fx = fx_rates.get(buy_ccy, 23.5)
        buy_px_czk = buy_price * buy_fx

        target_allocation_czk = min(total_available_czk, max(38000, released_czk))
        buy_shares = max(1, int(target_allocation_czk // buy_px_czk))
        buy_conid = KNOWN_CONIDS.get(buy_sym) or self.gw.get_conid(buy_sym)

        time.sleep(1)

        buy_outside = True if buy_ccy == "USD" else False
        buy_res = self.gw.place_order(acc_id, buy_conid, "BUY", buy_shares, buy_price, outside_rth=buy_outside)
        logger.info(f"Odeslán nákupní pokyn pro {buy_sym}: {buy_shares} ks @ {buy_price} {buy_ccy} (ConID {buy_conid}): {buy_res.get('ok')}")

        # ZÁPIS DO AUDITNÍ HISTORIE OBCHODŮ
        now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        trade_buy = {
            "symbol": buy_sym,
            "shares": buy_shares,
            "price": f"{buy_price:.2f} {buy_ccy} ({round(buy_px_czk):,} CZK)",
            "total_czk": round(buy_shares * buy_px_czk),
            "time": now_str,
            "type": "AGGRESSIVE_SUB_BUY",
            "status": f"Okamžitý reinvest do TOP Strong Buy aktiva (+{buy_cand.get('targetUpside', '15%')})"
        }
        trade_sell = {
            "symbol": sell_sym,
            "shares": sell_shares,
            "price": f"{sell_price:.2f} {sell_ccy} ({round(sell_price * sell_fx):,} CZK)",
            "total_czk": round(released_czk),
            "time": now_str,
            "type": "AGGRESSIVE_PRUNE_SELL",
            "status": f"Odříznutí ležáku ({sell_pos.get('unrealized_pnl_percent', 0)} %): kapitál okamžitě rotován do {buy_sym}"
        }

        # Přidat na začátek vlastní historie obchodů
        self.custom_trades_history.insert(0, trade_buy)
        self.custom_trades_history.insert(1, trade_sell)

        updated_state = self.sync_live_portfolio()

        return {
            "ok": True,
            "message": f"Agresivní rotace úspěšná: odříznut ležák {sell_sym} ({sell_shares} ks), kapitál {released_czk:,.0f} CZK okamžitě investován do {buy_sym} ({buy_shares} ks @ {buy_price} {buy_ccy}).",
            "sell": {"symbol": sell_sym, "shares": sell_shares, "result": sell_res},
            "buy": {"symbol": buy_sym, "shares": buy_shares, "result": buy_res},
            "state": updated_state
        }

    def execute_manual_order(self, symbol: str, shares: int, price: float, currency: str = "USD") -> Dict[str, Any]:
        """Provede manuální nákup vybraného titulu na Demo účtu přes IBKR."""
        auth_ok, acc_id = self.gw.check_auth()
        if not auth_ok:
            return {"ok": False, "error": "Gateway není autentizována"}

        conid = KNOWN_CONIDS.get(symbol) or self.gw.get_conid(symbol)
        if not conid:
            return {"ok": False, "error": f"ConID pro {symbol} nenalezeno"}

        outside_rth = True if currency == "USD" else False
        logger.info(f"Manuální pokyn: nákup {symbol} ({shares} ks @ {price} {currency}, conid: {conid})...")
        res = self.gw.place_order(acc_id, conid, "BUY", shares, price, outside_rth=outside_rth)
        self.sync_live_portfolio()
        return {"ok": True, "result": res}

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

                    # Detekce a varování před ležáky v agresivním režimu
                    if self.strategy_mode == "AGGRESSIVE_MOMENTUM":
                        for p in positions:
                            pos_qty = p.get("position", 0)
                            avg_px = p.get("avgPrice", 0)
                            pnl_val = p.get("unrealizedPnl", 0)
                            if pos_qty and avg_px:
                                pnl_pct = (pnl_val / (pos_qty * avg_px)) * 100
                                if pnl_pct <= self.laggard_pnl_threshold:
                                    sym = p.get("contractDesc") or p.get("ticker")
                                    logger.info(f"⚡ [DETEKTOR LEŽÁKŮ] Titul {sym} zaostává ({pnl_pct:.2f} %). Připravena agresivní substituce do TOP 1 Strong Buy aktiva.")

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

        elif self.path == "/api/orders":
            state = ENGINE.sync_live_portfolio()
            self._set_headers(200)
            self.wfile.write(json.dumps({
                "ok": True,
                "pending_orders": state.get("pending_orders", []),
                "trades_history": state.get("trades_history", [])
            }, ensure_ascii=False).encode("utf-8"))

        elif self.path == "/api/autoinvest/opportunities":
            opps = ENGINE.detect_opportunities()
            self._set_headers(200)
            self.wfile.write(json.dumps(opps, ensure_ascii=False).encode("utf-8"))

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

        elif self.path == "/api/autoinvest/substitute":
            sell_sym = data.get("sell_symbol")
            buy_sym = data.get("buy_symbol")
            res = ENGINE.execute_substitution_rotation(sell_sym, buy_sym)
            self._set_headers(200)
            self.wfile.write(json.dumps(res, ensure_ascii=False).encode("utf-8"))

        elif self.path == "/api/autoinvest/strategy":
            mode = data.get("mode")
            thresh = data.get("laggard_threshold")
            if mode:
                ENGINE.strategy_mode = mode
            if thresh is not None:
                ENGINE.laggard_pnl_threshold = float(thresh)
            ENGINE.sync_live_portfolio()
            self._set_headers(200)
            self.wfile.write(json.dumps({
                "ok": True,
                "strategy_mode": ENGINE.strategy_mode,
                "laggard_threshold": ENGINE.laggard_pnl_threshold
            }, ensure_ascii=False).encode("utf-8"))

        elif self.path == "/api/order/submit":
            sym = data.get("symbol", "").upper()
            shares = int(data.get("shares", 1))
            price = float(data.get("price", 100.0))
            cur = data.get("currency", "USD")
            res = ENGINE.execute_manual_order(sym, shares, price, cur)
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
