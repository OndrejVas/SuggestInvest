import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
from ib_insync import IB, util, Contract, Stock, Forex, Order, BracketOrder

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("ExecutionEngine")

TRADES_FILE = Path(__file__).resolve().parent.parent / "data" / "scalping_trades.json"

class ExecutionEngine:
    """
    Modul pro asynchronní odesílání a správu objednávek přes Interactive Brokers.
    Implementuje Fázi 2 (Nervové Centrum a Obrana) s perzistencí do data/scalping_trades.json.
    """
    
    def __init__(self, host: str = '127.0.0.1', port: int = 7497, client_id: int = 2):
        """
        Používáme client_id=2, abychom nekolidovali s Data Ingestion (ten má výchozí 1),
        pokud by běžely ve stejný čas jako oddělené skripty.
        """
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib = IB()

    @staticmethod
    def load_trades_data() -> Dict[str, Any]:
        """Načte stav z data/scalping_trades.json nebo vrátí výchozí strukturu."""
        if TRADES_FILE.exists():
            try:
                with open(TRADES_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Chyba při čtení {TRADES_FILE}: {e}")
        return {
            "version": "1.0.0",
            "account_id": "IBKR: DUR222134 (Paper Trading Sandbox)",
            "last_updated_cet": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            "summary": {"total_trades": 0, "wins": 0, "losses": 0, "win_rate_pct": 0.0, "total_pnl_usd": 0.0},
            "active_positions": [],
            "pending_orders": [],
            "executed_history": []
        }

    @staticmethod
    def save_trades_data(data: Dict[str, Any]):
        """Uloží aktualizovaný stav do data/scalping_trades.json s přepočtem souhrnů."""
        try:
            TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)
            data["last_updated_cet"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
            history = data.get("executed_history", [])
            wins = [t for t in history if t.get("result") == "WIN" or t.get("pnl_usd", 0) > 0]
            losses = [t for t in history if t.get("result") == "LOSS" or t.get("pnl_usd", 0) < 0]
            total_trades = len(history)
            win_rate = round((len(wins) / total_trades * 100), 1) if total_trades > 0 else 0.0
            total_pnl = round(sum(t.get("pnl_usd", 0) for t in history), 2)
            
            gross_win = sum(t.get("pnl_usd", 0) for t in wins)
            gross_loss = abs(sum(t.get("pnl_usd", 0) for t in losses))
            profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else (round(gross_win, 2) if gross_win > 0 else 1.0)
            
            data["summary"] = {
                "total_trades": total_trades,
                "wins": len(wins),
                "losses": len(losses),
                "win_rate_pct": win_rate,
                "total_pnl_usd": total_pnl,
                "total_pnl_czk": round(total_pnl * 23.2, 2),
                "profit_factor": profit_factor,
                "active_positions_count": len(data.get("active_positions", [])),
                "pending_orders_count": len(data.get("pending_orders", [])),
                "avg_trade_pnl_usd": round(total_pnl / total_trades, 2) if total_trades > 0 else 0.0
            }
            with open(TRADES_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"Data úspěšně uložena do {TRADES_FILE}")
        except Exception as e:
            logger.error(f"Chyba při zápisu {TRADES_FILE}: {e}")

    def add_pending_order(self, symbol: str, name: str, direction: str, limit_price: float,
                          sl: float, tp1: float, tp2: float, qty: str, rrr: str, trigger: str) -> Dict[str, Any]:
        """Přidá nový připravený pokyn a uloží do souboru."""
        data = self.load_trades_data()
        order_id = f"ORD-{datetime.now().strftime('%Y%m%d')}-{len(data.get('pending_orders', [])) + 101}"
        new_order = {
            "id": order_id,
            "symbol": symbol,
            "name": name,
            "direction": direction,
            "order_type": "Bracket Limit (LMT)",
            "limit_price": limit_price,
            "stop_loss": sl,
            "take_profit_1": tp1,
            "take_profit_2": tp2,
            "quantity": qty,
            "rrr": rrr,
            "created_at_cet": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            "strategy_trigger": trigger,
            "status": "PŘIPRAVENO V ENGINE"
        }
        data.setdefault("pending_orders", []).insert(0, new_order)
        self.save_trades_data(data)
        return new_order

    def record_executed_trade(self, symbol: str, name: str, direction: str, qty: str,
                              entry: float, exit_price: float, sl: float, tp: float,
                              pnl_usd: float, exit_reason: str, duration_min: int = 15) -> Dict[str, Any]:
        """Zaznamená uskutečněný obchod do historie."""
        data = self.load_trades_data()
        trade_id = f"TRD-{datetime.now().strftime('%Y%m%d')}-{len(data.get('executed_history', [])) + 1:03d}"
        is_win = pnl_usd >= 0
        trade = {
            "id": trade_id,
            "datetime_cet": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            "symbol": symbol,
            "name": name,
            "direction": direction,
            "quantity": qty,
            "entry_price": entry,
            "exit_price": exit_price,
            "stop_loss": sl,
            "take_profit": tp,
            "exit_reason": exit_reason,
            "pnl_usd": round(pnl_usd, 2),
            "pnl_czk": round(pnl_usd * 23.2, 2),
            "pnl_pct": round(((exit_price - entry) / entry * 100) if direction.upper().startswith("BUY") or direction.upper().startswith("LONG") else ((entry - exit_price) / entry * 100), 2),
            "duration_min": duration_min,
            "result": "WIN" if is_win else "LOSS",
            "ibkr_exec_id": f"IB-EX-{datetime.now().strftime('%H%M%S')}",
            "status": "USKUTEČNĚNO (ZISK)" if is_win else "USKUTEČNĚNO (ZTRÁTA)"
        }
        data.setdefault("executed_history", []).insert(0, trade)
        self.save_trades_data(data)
        return trade

    async def connect(self):
        try:
            logger.info(f"Připojování Execution Enginu k IBKR na {self.host}:{self.port}...")
            await self.ib.connectAsync(self.host, self.port, clientId=self.client_id)
            logger.info("Execution Engine úspěšně připojen.")
        except Exception as e:
            logger.error(f"Chyba připojení enginu: {e}")
            raise

    def disconnect(self):
        if self.ib.isConnected():
            self.ib.disconnect()
            logger.info("Execution Engine odpojen.")

    async def check_margin_and_risk(self) -> bool:
        """
        Zkontroluje, zda máme dostatek prostředků (Obrana).
        Vrací True, pokud je účet v pořádku pro další obchodování.
        """
        if not self.ib.isConnected():
            return False
            
        account_summary = self.ib.accountSummary()
        # Najdeme hodnotu AvailableFunds
        available_funds = 0.0
        for item in account_summary:
            if item.tag == 'AvailableFunds':
                available_funds = float(item.value)
                break
                
        logger.info(f"Dostupný kapitál pro margin: {available_funds}")
        
        # Pojistka: Pokud je dostupný margin pod nějakou hranicí (např. 1000), blokujeme exekuci.
        if available_funds < 1000:
            logger.warning("Nízký margin! Obchodování zablokováno.")
            return False
            
        return True

    async def place_bracket_order(
        self, 
        contract: Contract, 
        action: str, 
        quantity: float, 
        limit_price: float, 
        take_profit_price: float, 
        stop_loss_price: float
    ) -> Optional[BracketOrder]:
        """
        Odešle bezpečný Bracket Order (Vstupní Limit příkaz ohraničený SL a TP).
        """
        if not self.ib.isConnected():
            logger.error("IBKR není připojeno. Příkaz zahozen.")
            return None

        # 1. Kvalifikace kontraktu (důležité pro IBKR k jednoznačné identifikaci)
        try:
            await self.ib.qualifyContractsAsync(contract)
        except Exception as e:
            logger.error(f"Nepodařilo se kvalifikovat kontrakt {contract.symbol}: {e}")
            return None

        # 2. Vytvoření Bracket Order
        bracket = self.ib.bracketOrder(
            action=action.upper(),
            quantity=quantity,
            limitPrice=round(limit_price, 5),
            takeProfitPrice=round(take_profit_price, 5),
            stopLossPrice=round(stop_loss_price, 5)
        )
        
        # 3. Odeslání všech 3 spojených příkazů (Parent, TP, SL)
        logger.info(f"Odesílám {action} {quantity} {contract.symbol} @ LMT {limit_price} | TP: {take_profit_price} | SL: {stop_loss_price}")
        
        placed_trades = []
        for order in bracket:
            trade = self.ib.placeOrder(contract, order)
            placed_trades.append(trade)
            
        return bracket

async def demo_execution():
    """Ukázkový běh exekuce z Fáze 3 (Test nanečisto)"""
    engine = ExecutionEngine(port=7497)
    
    try:
        await engine.connect()
        
        is_safe = await engine.check_margin_and_risk()
        if not is_safe:
            return
            
        # Příklad: Skalpový nákup EURUSD, kde RR je těsné
        # V reálu si contract, price a SL/TP přebíráme z trading_engine.py
        contract = Forex('EURUSD')
        
        # Testovací ceny:
        current_price_guess = 1.0950
        action = "BUY"
        qty = 100000  # 1 standard lot
        limit_price = current_price_guess - 0.0010  # Chytáme limit 10 pips pod aktuální cenou
        tp = limit_price + 0.0015  # 15 pips target
        sl = limit_price - 0.0005  # 5 pips stop loss (těsný skalp)
        
        bracket = await engine.place_bracket_order(
            contract=contract,
            action=action,
            quantity=qty,
            limit_price=limit_price,
            take_profit_price=tp,
            stop_loss_price=sl
        )
        
        if bracket:
            logger.info("Příkazy odeslány na trh. Čekáme sekundu pro potvrzení...")
            await asyncio.sleep(1)
            
            # Zrušení po odeslání pro čistý paper trading test
            logger.info("Ruším testovací příkazy (Clean-up)...")
            for order in bracket:
                engine.ib.cancelOrder(order)
                
    except Exception as e:
        logger.error(f"Demo exekuce selhala: {e}")
    finally:
        engine.disconnect()

if __name__ == "__main__":
    util.patchAsyncio()
    asyncio.run(demo_execution())
