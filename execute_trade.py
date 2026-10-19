"""
execute_trade.py
----------------
Exekuční most pro Interactive Brokers (port 7497 Socket API).
Umožňuje reálné odeslání prodejních (Take-Profit / Stop-Loss / Close), nákupních
a rotačních pokynů na účet DUR222134 s okamžitou synchronizací dat.
"""

import os
import sys
import argparse
import logging
from typing import Dict, Any, Optional

try:
    from ib_insync import IB, Stock, MarketOrder, LimitOrder, util
except ImportError:
    print("CHYBA: ib_insync není nainstalován!")
    sys.exit(1)

import json
from typing import Dict, Any, Optional, Tuple

from ibkr_sync_service import sync_ibkr, COMPANY_NAMES, WORKSPACE_DIR

def is_orders_execution_allowed() -> Tuple[bool, str]:
    """Zkontroluje, zda jsou objednávky povoleny uživatelem z FutureInvestDemo."""
    lock_file = os.path.join(WORKSPACE_DIR, "data", "execution_lock.json")
    if os.path.exists(lock_file):
        try:
            with open(lock_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not data.get("orders_enabled", False):
                return False, data.get("reason", "Všechny objednávky jsou zastaveny. Spustit je lze výhradně z FutureInvestDemo.")
            return True, "POVOLENO"
        except Exception as e:
            return False, f"Chyba při čtení bezpečnostního zámku: {e}"
    return False, "Bezpečnostní zámek nebyl nalezen (výchozí stav: STOP)."


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("IBKR-Executor")


def get_contract_for_symbol(ib: IB, symbol: str) -> Stock:
    """Vrátí kvalifikovaný IBKR kontrakt pro daný symbol."""
    sym = symbol.upper().strip()
    if sym in ("RHM", "SAP"):
        contract = Stock(sym, "IBIS", "EUR")
    elif sym in ("SAN",):
        contract = Stock(sym, "BM", "EUR")
    elif sym in ("ASML", "ADYEN"):
        contract = Stock(sym, "AEB", "EUR")
    else:
        contract = Stock(sym, "SMART", "USD")
    
    qualified = ib.qualifyContracts(contract)
    if qualified:
        return qualified[0]
    return contract


def _ensure_event_loop():
    import asyncio
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def check_account_status(host: str = "127.0.0.1", port: int = 7497, client_id: int = 993, account: str = "DUR222134") -> Dict[str, Any]:
    _ensure_event_loop()
    ib = IB()
    res = {"positions": [], "orders": [], "account": account}
    try:
        ib.connect(host, port, clientId=client_id, timeout=6)
        positions = [p for p in ib.positions(account) if abs(p.position) > 0.0001]
        orders = ib.openOrders()

        for p in positions:
            name = COMPANY_NAMES.get(p.contract.symbol, p.contract.symbol)
            res["positions"].append({
                "symbol": p.contract.symbol,
                "name": name,
                "shares": int(p.position),
                "avg_price": round(p.avgCost, 2),
                "currency": p.contract.currency
            })

        for o in orders:
            res["orders"].append({
                "order_id": o.orderId,
                "action": o.action,
                "shares": o.totalQuantity,
                "type": o.orderType,
                "status": getattr(o, "status", "Submitted")
            })

        print(f"\n=== IBKR ÚČET {account} (Port {port}) ===")
        print(f"Otevřené pozice ({len(positions)}):")
        for p in res["positions"]:
            print(f"  • {p['symbol']} ({p['name']}): {p['shares']} ks @ {p['avg_price']} {p['currency']}")

        print(f"\nAktivní příkazy na burze ({len(orders)}):")
        if not orders:
            print("  (Žádné čekající příkazy)")
        for o in res["orders"]:
            print(f"  • {o['action']} {o['shares']} ks {o['type']} (Status: {o['status']})")
        print("=========================================\n")
        return res
    finally:
        ib.disconnect()


def execute_sell(
    symbol: str, 
    shares: int = 0, 
    order_type: str = "MKT", 
    limit_price: float = 0.0,
    outside_rth: bool = True,
    reason: str = "MANUAL_SELL",
    host: str = "127.0.0.1", 
    port: int = 7497, 
    client_id: int = 994, 
    account: str = "DUR222134"
) -> Dict[str, Any]:
    """Odešle reálný prodejní příkaz na IBKR a provede okamžitou resynchronizaci."""
    allowed, lock_reason = is_orders_execution_allowed()
    if not allowed:
        logger.warning(f"ZABLOKOVÁNO: {lock_reason}")
        return {"ok": False, "error": f"Objednávky jsou zastaveny: {lock_reason}", "orders_locked": True}

    _ensure_event_loop()
    ib = IB()
    sym = symbol.upper().strip()
    try:
        logger.info(f"Připojuji se k IB Gateway na {host}:{port} pro SELL {sym}...")
        ib.connect(host, port, clientId=client_id, timeout=6)

        # 1. Zjištění otevřené pozice
        positions = {p.contract.symbol: p for p in ib.positions(account) if abs(p.position) > 0.0001}

        if sym not in positions:
            msg = f"Pozice {sym} nebyla nalezena na účtu {account}! Dostupné: {list(positions.keys())}"
            logger.error(msg)
            return {"ok": False, "error": msg}

        current_pos = positions[sym]
        pos_qty = float(current_pos.position)
        if abs(pos_qty) < 0.0001:
            return {"ok": False, "error": f"Pozice {sym} je již nulová."}

        # Určení směru pro uzavření (pro LONG prodáváme, pro SHORT dokupujeme)
        order_action = "SELL" if pos_qty > 0 else "BUY"
        total_shares = int(abs(pos_qty))
        close_shares = shares if (shares > 0 and shares <= total_shares) else total_shares

        # 2. Vytvoření kontraktu
        contract = current_pos.contract
        ib.qualifyContracts(contract)

        # 3. Vytvoření objednávky
        if order_type.upper() == "LMT" and limit_price > 0:
            order = LimitOrder(order_action, close_shares, limit_price, tif="GTC", outsideRth=outside_rth)
            logger.info(f"Zadávám LIMIT {order_action} {close_shares} ks {sym} @ {limit_price} (outsideRth={outside_rth})")
        else:
            order = MarketOrder(order_action, close_shares, tif="DAY", outsideRth=outside_rth)
            logger.info(f"Zadávám MARKET {order_action} {close_shares} ks {sym} (outsideRth={outside_rth})")

        order.account = account

        # 4. Odeslání pokynu
        trade = ib.placeOrder(contract, order)
        ib.sleep(2)  # Čekání na potvrzení od IBKR

        status = trade.orderStatus.status
        filled = trade.orderStatus.filled
        avg_price = trade.orderStatus.avgFillPrice

        logger.info(f"Stav pokynu u brokera: {status} (Vyplněno: {filled}/{close_shares} ks @ {avg_price})")

        return {
            "ok": True,
            "action": order_action,
            "symbol": sym,
            "shares": close_shares,
            "order_id": trade.order.orderId,
            "status": status,
            "filled": filled,
            "avg_fill_price": avg_price,
            "reason": reason,
            "message": f"Pokyn {order_action} {close_shares} ks {sym} odeslán na IBKR. Stav: {status}."
        }

    except Exception as e:
        logger.error(f"Chyba při exekuci prodeje {sym}: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}
    finally:
        ib.disconnect()
        # Vždy okamžitě resynchronizovat portfolio
        sync_ibkr(host=host, port=port, account_id=account)


def execute_buy(
    symbol: str, 
    shares: int, 
    order_type: str = "MKT", 
    limit_price: float = 0.0,
    outside_rth: bool = True,
    host: str = "127.0.0.1", 
    port: int = 7497, 
    client_id: int = 995, 
    account: str = "DUR222134"
) -> Dict[str, Any]:
    """Odešle reálný nákupní příkaz na IBKR a provede okamžitou resynchronizaci."""
    allowed, lock_reason = is_orders_execution_allowed()
    if not allowed:
        logger.warning(f"ZABLOKOVÁNO: {lock_reason}")
        return {"ok": False, "error": f"Objednávky jsou zastaveny: {lock_reason}", "orders_locked": True}

    if shares <= 0:
        return {"ok": False, "error": "Počet akcií pro nákup musí být větší než 0!"}

    _ensure_event_loop()
    ib = IB()
    sym = symbol.upper().strip()
    try:
        logger.info(f"Připojuji se k IB Gateway na {host}:{port} pro BUY {sym}...")
        ib.connect(host, port, clientId=client_id, timeout=6)

        contract = get_contract_for_symbol(ib, sym)

        if order_type.upper() == "LMT" and limit_price > 0:
            order = LimitOrder("BUY", shares, limit_price, tif="GTC", outsideRth=outside_rth)
            logger.info(f"Zadávám LIMIT BUY {shares} ks {sym} @ {limit_price} (outsideRth={outside_rth})")
        else:
            order = MarketOrder("BUY", shares, tif="DAY", outsideRth=outside_rth)
            logger.info(f"Zadávám MARKET BUY {shares} ks {sym} (outsideRth={outside_rth})")

        order.account = account

        trade = ib.placeOrder(contract, order)
        ib.sleep(2)

        status = trade.orderStatus.status
        filled = trade.orderStatus.filled
        avg_price = trade.orderStatus.avgFillPrice

        logger.info(f"Stav pokynu BUY u brokera: {status} (Vyplněno: {filled}/{shares} ks)")

        return {
            "ok": True,
            "action": "BUY",
            "symbol": sym,
            "shares": shares,
            "order_id": trade.order.orderId,
            "status": status,
            "filled": filled,
            "avg_fill_price": avg_price,
            "message": f"Pokyn BUY {shares} ks {sym} odeslán na IBKR. Stav: {status}."
        }

    except Exception as e:
        logger.error(f"Chyba při exekuci nákupu {sym}: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}
    finally:
        ib.disconnect()
        sync_ibkr(host=host, port=port, account_id=account)


def execute_rotate(
    sell_symbol: str, 
    buy_symbol: str, 
    buy_shares: int = 0,
    outside_rth: bool = True,
    host: str = "127.0.0.1", 
    port: int = 7497, 
    account: str = "DUR222134"
) -> Dict[str, Any]:
    """Provede reálnou rotaci: prodá sell_symbol a nakoupí buy_symbol."""
    allowed, lock_reason = is_orders_execution_allowed()
    if not allowed:
        logger.warning(f"ZABLOKOVÁNO: {lock_reason}")
        return {"ok": False, "error": f"Objednávky jsou zastaveny: {lock_reason}", "orders_locked": True}

    sell_res = execute_sell(symbol=sell_symbol, shares=0, outside_rth=outside_rth, reason="ROTATION_SELL", host=host, port=port, account=account)
    if not sell_res.get("ok"):
        return {"ok": False, "error": f"Rotace selhala při prodeji {sell_symbol}: {sell_res.get('error')}"}

    # Výpočet počtu kusů pro nákup, pokud nebyl zadán
    final_buy_shares = buy_shares
    if final_buy_shares <= 0:
        # Odhad dle standardních vah kandidátů
        default_shares = {"NVDA": 14, "MSFT": 4, "ASML": 2, "AMZN": 9, "SAP": 8}
        final_buy_shares = default_shares.get(buy_symbol.upper(), 5)

    buy_res = execute_buy(symbol=buy_symbol, shares=final_buy_shares, outside_rth=outside_rth, host=host, port=port, account=account)
    
    return {
        "ok": True,
        "action": "ROTATION",
        "sell": sell_res,
        "buy": buy_res,
        "message": f"Rotace z {sell_symbol} do {buy_symbol} byla odeslána na IBKR."
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SuggestInvest IBKR Trade Executor")
    parser.add_argument("--status", action="store_true", help="Zobrazit reálný stav pozic a objednávek na účtu")
    parser.add_argument("--close", type=str, help="Uzavřít celou pozici pro daný ticker (např. --close ORCL)")
    parser.add_argument("--sell", type=str, help="Prodat ticker (např. --sell ORCL)")
    parser.add_argument("--buy", type=str, help="Koupit ticker (např. --buy NVDA)")
    parser.add_argument("--rotate", nargs=2, metavar=("SELL", "BUY"), help="Rotovat pozici (např. --rotate ORCL NVDA)")
    parser.add_argument("--shares", type=int, default=0, help="Počet akcií")
    parser.add_argument("--limit", type=float, default=0.0, help="Limitní cena")
    args = parser.parse_args()

    if args.status:
        check_account_status()
    elif args.close:
        execute_sell(symbol=args.close, shares=0)
    elif args.sell:
        execute_sell(symbol=args.sell, shares=args.shares, limit_price=args.limit, order_type="LMT" if args.limit > 0 else "MKT")
    elif args.buy:
        execute_buy(symbol=args.buy, shares=args.shares if args.shares > 0 else 5, limit_price=args.limit, order_type="LMT" if args.limit > 0 else "MKT")
    elif args.rotate:
        execute_rotate(sell_symbol=args.rotate[0], buy_symbol=args.rotate[1], buy_shares=args.shares)
    else:
        check_account_status()
