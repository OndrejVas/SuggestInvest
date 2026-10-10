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
    
    def __init__(self, host: str = '127.0.0.1', port: int = 7497, client_id: int = 2, ib_instance: Optional[IB] = None):
        """
        Používáme client_id=2, abychom nekolidovali s Data Ingestion (ten má výchozí 1).
        Lze předat i již připojenou instanci IB.
        """
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib = ib_instance or IB()

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
            "version": "2.0.0",
            "account_id": "IBKR: DUR222134 (Paper Trading Sandbox)",
            "last_updated_cet": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
            "summary": {"total_trades": 0, "wins": 0, "losses": 0, "win_rate_pct": 0.0, "total_pnl_usd": 0.0},
            "active_positions": [],
            "pending_orders": [],
            "executed_history": [],
            "ibkr_live_account": None
        }

    def sync_ibkr_account(self, account_id: str = "DUR222134") -> Optional[Dict[str, Any]]:
        """
        Stáhne reálná data o účtu přímo z běžícího IB Gateway (DUR222134)
        a uloží je do data/scalping_trades.json pod klíčem 'ibkr_live_account'.
        """
        if not self.ib.isConnected():
            return None
        try:
            summary = self.ib.accountSummary(account_id)
            sum_dict = {s.tag: s.value for s in summary}
            
            portfolio_items = []
            for p in self.ib.portfolio(account_id):
                # Filtrujeme pouze čistě scalping kontrakty (komodity, krypto, pákové futures)
                if p.contract.secType in ['CMDTY', 'FUT', 'CRYPTO'] or p.contract.symbol in ['XAUUSD', 'BTC', 'BTCUSD', 'MGC']:
                    portfolio_items.append({
                        "symbol": p.contract.symbol,
                        "secType": p.contract.secType,
                        "position": p.position,
                        "marketPrice": round(p.marketPrice, 2),
                        "marketValue": round(p.marketValue, 2),
                        "averageCost": round(p.averageCost, 2),
                        "unrealizedPNL": round(p.unrealizedPNL, 2),
                        "realizedPNL": round(p.realizedPNL, 2)
                    })
            
            # Celková provize z fills
            fills = self.ib.fills()
            total_comm = round(sum(f.commissionReport.commission for f in fills if f.commissionReport), 2)
            
            # Převedeme CZK na USD kurzem cca 23.2
            net_czk = float(sum_dict.get('NetLiquidation', 0.0))
            avail_czk = float(sum_dict.get('AvailableFunds', 0.0))
            cash_czk = float(sum_dict.get('TotalCashValue', 0.0))
            bp_czk = float(sum_dict.get('BuyingPower', 0.0))
            maint_czk = float(sum_dict.get('MaintMarginReq', 0.0))
            gross_czk = float(sum_dict.get('GrossPositionValue', 0.0))
            
            acc_info = {
                "account_id": account_id,
                "status": "PŘIPOJENO K IBKR DEMO (PORT 7497)",
                "last_synced_cet": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
                "net_liquidation_czk": net_czk,
                "net_liquidation_usd": round(net_czk / 23.2, 2),
                "available_funds_czk": avail_czk,
                "available_funds_usd": round(avail_czk / 23.2, 2),
                "total_cash_czk": cash_czk,
                "total_cash_usd": round(cash_czk / 23.2, 2),
                "buying_power_czk": bp_czk,
                "buying_power_usd": round(bp_czk / 23.2, 2),
                "maint_margin_czk": maint_czk,
                "gross_position_czk": gross_czk,
                "total_commissions_usd": total_comm if total_comm > 0 else round(sum(t.get("commission_usd", 2.0) for t in self.load_trades_data().get("executed_history", [])), 2),
                "portfolio": portfolio_items
            }
            
            trades_data = self.load_trades_data()
            trades_data["ibkr_live_account"] = acc_info
            trades_data["version"] = "2.2.0"
            self.save_trades_data(trades_data)
            return acc_info
        except Exception as e:
            logger.error(f"Chyba při synchronizaci IBKR účtu: {e}")
            return None

    @staticmethod
    def save_trades_data(data: Dict[str, Any]):
        """Uloží aktualizovaný stav do data/scalping_trades.json s přepočtem souhrnů."""
        try:
            TRADES_FILE.parent.mkdir(parents=True, exist_ok=True)
            data["last_updated_cet"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
            data["version"] = "2.2.0"
            history = data.get("executed_history", [])
            wins = [t for t in history if t.get("result") == "WIN" or t.get("pnl_usd", 0) > 0]
            losses = [t for t in history if t.get("result") == "LOSS" or t.get("pnl_usd", 0) < 0]
            total_trades = len(history)
            win_rate = round((len(wins) / total_trades * 100), 1) if total_trades > 0 else 0.0
            total_pnl = round(sum(t.get("pnl_usd", 0) for t in history), 2)
            
            gross_win = sum(t.get("pnl_usd", 0) for t in wins)
            gross_loss = abs(sum(t.get("pnl_usd", 0) for t in losses))
            profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else (round(gross_win, 2) if gross_win > 0 else 1.0)
            
            total_commissions = round(sum(t.get("commission_usd", 2.0) for t in history), 2)
            total_gross_pnl = round(sum(t.get("gross_pnl_usd", t.get("pnl_usd", 0) + 2.0) for t in history), 2)
            
            data["summary"] = {
                "total_trades": total_trades,
                "wins": len(wins),
                "losses": len(losses),
                "win_rate_pct": win_rate,
                "total_gross_pnl_usd": total_gross_pnl,
                "total_commissions_usd": total_commissions,
                "total_pnl_usd": total_pnl,
                "total_net_pnl_usd": total_pnl,
                "total_pnl_czk": round(total_pnl * 23.2, 2),
                "profit_factor": profit_factor,
                "active_positions_count": len(data.get("active_positions", [])),
                "pending_orders_count": len(data.get("pending_orders", [])),
                "avg_trade_pnl_usd": round(total_pnl / total_trades, 2) if total_trades > 0 else 0.0,
                "target_capital_allocation": "2.0 oz (~$8 390 notional / marže ~$420 USD)",
                "target_net_profit_per_win": "+3.50 až +7.50 USD (po odečtu provizí)"
            }
            if "ibkr_live_account" in data and isinstance(data["ibkr_live_account"], dict):
                data["ibkr_live_account"]["total_commissions_usd"] = total_commissions

            temp_file = TRADES_FILE.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False, default=str)
            temp_file.replace(TRADES_FILE)
            logger.info(f"Data bezpečně uložena do {TRADES_FILE}")
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

    def add_active_position(self, pos: Dict[str, Any]):
        """Uloží nově otevřenou pozici do active_positions pro okamžité zobrazení na frontendu."""
        data = self.load_trades_data()
        data.setdefault("active_positions", [])
        # Odstranit duplicity pokud existují
        data["active_positions"] = [p for p in data["active_positions"] if p.get("id") != pos.get("id")]
        data["active_positions"].append(pos)
        self.save_trades_data(data)

    def update_active_position_spot(self, pos_id: str, current_price: float, be_moved: bool = False):
        """Aktualizuje tržní cenu a plovoucí PnL aktivní pozice podle reálného objemu."""
        data = self.load_trades_data()
        changed = False
        for pos in data.get("active_positions", []):
            if pos.get("id") == pos_id:
                pos["current_price"] = round(current_price, 2)
                entry = float(pos.get("entry_price", current_price))
                qty_mult = float(pos.get("qty_num", 0.25))
                is_long = "LONG" in pos.get("direction", "").upper() or "BUY" in pos.get("direction", "").upper()
                pnl = (current_price - entry) * qty_mult if is_long else (entry - current_price) * qty_mult
                pos["unrealized_pnl_usd"] = round(pnl, 2)
                pos["unrealized_pnl_czk"] = round(pnl * 23.2, 2)
                if be_moved:
                    pos["be_moved"] = True
                changed = True
        if changed:
            self.save_trades_data(data)

    def remove_active_position(self, pos_id: str):
        """Odebere uzavřenou pozici z active_positions."""
        data = self.load_trades_data()
        data["active_positions"] = [p for p in data.get("active_positions", []) if p.get("id") != pos_id]
        self.save_trades_data(data)

    def record_executed_trade(self, symbol: str, name: str, direction: str, qty: str,
                              entry: float, exit_price: float, sl: float, tp: float,
                              pnl_usd: float, exit_reason: str, duration_min: int = 15,
                              entry_reason: str = "", outcome_analysis: str = "",
                              lesson_learned: str = "", model_feedback: str = "",
                              gross_pnl_usd: float = None, commission_usd: float = 2.0) -> Dict[str, Any]:
        """Zaznamená uskutečněný obchod do historie včetně důvodu spekulace, provizí brokera a poučení pro model."""
        data = self.load_trades_data()
        trade_id = f"TRD-{datetime.now().strftime('%Y%m%d')}-{len(data.get('executed_history', [])) + 1:03d}"
        is_win = pnl_usd >= 0
        actual_gross = round(gross_pnl_usd if gross_pnl_usd is not None else (pnl_usd + commission_usd), 2)
        actual_comm = round(commission_usd, 2)
        actual_net = round(pnl_usd, 2)
        
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
            "entry_reason": entry_reason or ("Býčí impuls s proražením KAMA průměru" if "LONG" in direction.upper() else "Medvědí impuls pod KAMA průměrem"),
            "outcome_analysis": outcome_analysis or ("Take-Profit úspěšně zasažen" if is_win else "Stop-Loss zasažen kvůli obratu trhu"),
            "lesson_learned": lesson_learned or ("Potvrzení platnosti signálu pro posílení vah modelu." if is_win else "Zpřísnit filtry volatility a sklonu KAMA před vstupem."),
            "model_feedback": model_feedback or ("Zvýšit koeficient spolehlivosti" if is_win else "Zvýšit práh filtru ATR"),
            "gross_pnl_usd": actual_gross,
            "commission_usd": actual_comm,
            "net_pnl_usd": actual_net,
            "pnl_usd": actual_net,
            "pnl_czk": round(actual_net * 23.2, 2),
            "pnl_pct": round(((exit_price - entry) / entry * 100) if direction.upper().startswith("BUY") or direction.upper().startswith("LONG") else ((entry - exit_price) / entry * 100), 2),
            "duration_min": duration_min,
            "result": "WIN" if is_win else "LOSS",
            "ibkr_exec_id": f"IB-EX-{datetime.now().strftime('%H%M%S')}",
            "status": "USKUTEČNĚNO (ČISTÝ ZISK)" if is_win else "USKUTEČNĚNO (ČISTÁ ZTRÁTA)"
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

    async def place_live_demo_bracket(
        self,
        symbol: str,
        action: str,
        quantity: float,
        limit_price: float,
        take_profit_price: float,
        stop_loss_price: float
    ) -> Optional[Dict[str, Any]]:
        """
        Přímo odešle pokyn do IB Gateway Demo účtu (DUR222134) a zaregistruje jej do systému.
        """
        if not self.ib.isConnected():
            logger.warning("IB Gateway není připojena. Pokyn bude evidován virtuálně.")
            return None

        # Výběr typu kontraktu podle symbolu
        sym_clean = symbol.upper().replace('/', '').replace(' ', '')
        if 'XAU' in sym_clean or 'GOLD' in sym_clean:
            contract = Commodity('XAUUSD', 'SMART', 'USD')
        elif 'EUR' in sym_clean or 'USD' in sym_clean and 'BTC' not in sym_clean:
            contract = Forex('EURUSD', 'IDEALPRO')
        else:
            contract = Stock('AAPL', 'SMART', 'USD')

        try:
            bracket = await self.place_bracket_order(
                contract=contract,
                action=action,
                quantity=quantity,
                limit_price=limit_price,
                take_profit_price=take_profit_price,
                stop_loss_price=stop_loss_price
            )
            if bracket:
                order_id = f"IB-DEMO-{bracket[0].orderId}"
                now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
                order_rec = {
                    "id": order_id,
                    "ibkr_order_id": bracket[0].orderId,
                    "symbol": symbol,
                    "contract": contract.symbol,
                    "action": action.upper(),
                    "direction": "LONG" if action.upper() == "BUY" else "SHORT",
                    "quantity": quantity,
                    "limit_price": limit_price,
                    "stop_loss": stop_loss_price,
                    "take_profit": take_profit_price,
                    "status": "ODESLÁNO DO IBKR DEMO (PreSubmitted)",
                    "created_at_cet": now_str
                }
                # Zaznamenat do pending_orders
                data = self.load_trades_data()
                data.setdefault("pending_orders", []).insert(0, order_rec)
                self.save_trades_data(data)
                logger.info(f"Pokyn {order_id} úspěšně zaregistrován do IBKR Demo.")
                return order_rec
        except Exception as e:
            logger.error(f"Chyba při odesílání pokynu do IBKR Demo: {e}")
        return None

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
