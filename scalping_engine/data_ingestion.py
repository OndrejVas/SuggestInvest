import asyncio
import time
import logging
from ib_insync import IB, util, Forex, Stock, ContFuture
from typing import Callable, Any

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DataIngestion")

class DataIngestionEngine:
    """
    Modul pro asynchronní sběr dat v reálném čase přes IBKR WebSocket.
    Zajišťuje Fázi 1 implementačního plánu pro Paper Trading s minimalizací latence.
    """
    def __init__(self, host: str = '127.0.0.1', port: int = 7497, client_id: int = 1):
        """
        port 7497 je výchozí pro TWS Paper Trading. 4002 pro IB Gateway Paper Trading.
        """
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib = IB()
        self.callbacks = []
        self._is_running = False

    async def connect(self):
        try:
            logger.info(f"Připojování k IBKR na {self.host}:{self.port} (Client ID: {self.client_id})...")
            # timeout lze nastavit dle potřeby
            await self.ib.connectAsync(self.host, self.port, clientId=self.client_id)
            logger.info("Úspěšně připojeno k IBKR (Paper Trading).")
        except Exception as e:
            logger.error(f"Chyba při připojení k IBKR: {e}")
            raise

    def disconnect(self):
        if self.ib.isConnected():
            self.ib.disconnect()
            logger.info("Odpojeno od IBKR.")

    def register_callback(self, callback: Callable[[Any, float], None]):
        """Registrace callback funkce pro příjem nových ticků a měření latence."""
        self.callbacks.append(callback)

    def _on_pending_tickers(self, tickers):
        """
        Interní callback volaný knihovnou ib_insync ihned, 
        když na WebSocketu přistanou nová market data.
        """
        receive_time = time.time()
        for ticker in tickers:
            for callback in self.callbacks:
                # Předáváme samotný ticker a lokální timestamp přijetí
                callback(ticker, receive_time)

    async def subscribe_market_data(self, contract):
        """
        Zahájí asynchronní odběr market dat pro daný kontrakt.
        """
        if not self.ib.isConnected():
            logger.error("Nelze odebírat data: Není připojeno k IBKR.")
            return

        # Kvalifikace kontraktu - doplňuje chybějící údaje (conId atd.) přímo od brokera
        await self.ib.qualifyContractsAsync(contract)
        
        logger.info(f"Odebírám live tick data pro: {contract.symbol}")
        
        # reqMktData pro standardní real-time ticky (případně reqTickByTickData pro tick-by-tick orderbook)
        self.ib.reqMktData(contract, "", False, False)
        
        # Připojení event handleru
        self.ib.pendingTickersEvent += self._on_pending_tickers

    async def run_forever(self):
        """Udržuje asynchronní event loop aktivní."""
        self._is_running = True
        logger.info("Data Ingestion Engine běží. Naslouchám... (Ctrl+C pro ukončení)")
        try:
            while self._is_running and self.ib.isConnected():
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            self.disconnect()

# =====================================================================
# TESTOVACÍ BLOK (Simulace a měření zpoždění - Fáze 3: Paper Trading)
# =====================================================================

async def latency_test_callback(ticker, receive_time: float):
    """
    Tato funkce reprezentuje napojení na náš budoucí Execution & Risk Engine.
    Měří reálnou latenci zpracování indikátoru a rozhodnutí.
    """
    # 1. Získání ceny (mid price jako příklad)
    if ticker.bid and ticker.ask:
        mid_price = (ticker.bid + ticker.ask) / 2.0
    else:
        mid_price = ticker.marketPrice()
        
    if str(mid_price) == "nan":
        return

    # 2. START MĚŘENÍ INTERNÍ LATENCE
    start_calc = time.perf_counter()
    
    # --> ZDE PROBÍHÁ SIMULACE VÝPOČTU STRATEGIE (SMA, ATR, atd.) <--
    _ = mid_price * 1.0001 # dummy výpočet
    
    # 3. KONEC MĚŘENÍ INTERNÍ LATENCE
    end_calc = time.perf_counter()
    calc_latency_ms = (end_calc - start_calc) * 1000

    # Pokud bychom měli tick-by-tick, porovnali bychom time serveru s receive_time.
    # U reqMktData logujeme naši schopnost reagovat na tick okamžitě.
    
    logger.info(
        f"[TICK] {ticker.contract.symbol} | Bid: {ticker.bid} Ask: {ticker.ask} "
        f"| Interní latence enginu: {calc_latency_ms:.5f} ms"
    )

async def main():
    # Inicializace engine s výchozím portem TWS Paper Trading (7497)
    engine = DataIngestionEngine(port=7497, client_id=1)
    
    try:
        await engine.connect()
        
        # Vybereme EURUSD z našeho instruments.py
        contract = Forex('EURUSD')
        
        # Zaregistrujeme měřící callback a spustíme odběr
        engine.register_callback(latency_test_callback)
        await engine.subscribe_market_data(contract)
        
        # Testovací běh (v produkci by bylo await engine.run_forever())
        logger.info("Spouštím 30s test datového streamu...")
        for _ in range(30):
            if not engine.ib.isConnected():
                break
            await asyncio.sleep(1)
            
    except Exception as e:
        logger.error(f"Kritická chyba: {e}")
    finally:
        engine.disconnect()

if __name__ == "__main__":
    # Util patch pro kompatibilitu ib_insync s běžným asyncio (hlavně v Jupyter/Windows)
    util.patchAsyncio()
    asyncio.run(main())
