import asyncio
import json
import logging
import time
from ib_insync import IB, util, Forex
import websockets

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("LiveFeedServer")

class LiveFeedServer:
    def __init__(self, host='127.0.0.1', ib_port=7497, ws_port=8765):
        self.ib_port = ib_port
        self.ws_port = ws_port
        self.ib = IB()
        self.clients = set()
        
        # Uchováváme data pro tvorbu svíček
        self.current_candle = None
        self.last_candle_time = 0
        
    async def register(self, websocket):
        self.clients.add(websocket)
        logger.info(f"Nové websocket připojení (Celkem klientů: {len(self.clients)})")
        try:
            await websocket.wait_closed()
        finally:
            self.clients.remove(websocket)
            logger.info("Klient se odpojil.")

    def on_pending_tickers(self, tickers):
        for ticker in tickers:
            if ticker.bid and ticker.ask:
                mid_price = (ticker.bid + ticker.ask) / 2.0
            else:
                mid_price = ticker.marketPrice()
                
            if str(mid_price) == "nan":
                continue
                
            now = time.time()
            
            # Svíčková logika (1-sekundové svíčky pro TradingView Lightweight Charts)
            # Čas zaokrouhlený na sekundy dolů
            candle_timestamp = int(now) 
            
            if self.current_candle is None or candle_timestamp > self.last_candle_time:
                # Odeslání uzavřené svíčky (pokud existovala) by se dělalo tady, 
                # ale pro real-time posíláme update pokaždé.
                
                self.current_candle = {
                    "time": candle_timestamp,
                    "open": mid_price,
                    "high": mid_price,
                    "low": mid_price,
                    "close": mid_price
                }
                self.last_candle_time = candle_timestamp
            else:
                # Aktualizace existující sekundy
                self.current_candle["high"] = max(self.current_candle["high"], mid_price)
                self.current_candle["low"] = min(self.current_candle["low"], mid_price)
                self.current_candle["close"] = mid_price

            # Přidáme SMA simulaci k odeslání (jednoduchý průměr High/Low, v reálu SMA array)
            sma = (self.current_candle["high"] + self.current_candle["low"]) / 2.0

            data = {
                "type": "candle",
                "symbol": ticker.contract.symbol,
                "candle": self.current_candle,
                "sma": sma
            }
            msg = json.dumps(data)
            
            # Broadcast všem klientům
            websockets.broadcast(self.clients, msg)

    async def run(self):
        # 1. Připojení k IBKR
        try:
            logger.info(f"Připojování k IBKR na portu {self.ib_port}...")
            await self.ib.connectAsync('127.0.0.1', self.ib_port, clientId=5)
            logger.info("Připojeno k IBKR.")
        except Exception as e:
            logger.error(f"Chyba připojení k IBKR: {e}")
            return
            
        contract = Forex('EURUSD')
        await self.ib.qualifyContractsAsync(contract)
        
        self.ib.reqMktData(contract, "", False, False)
        self.ib.pendingTickersEvent += self.on_pending_tickers
        
        # 2. Spuštění WS serveru
        logger.info(f"Startuji WebSocket server na ws://localhost:{self.ws_port}")
        async with websockets.serve(self.register, "localhost", self.ws_port):
            logger.info("Server běží a čeká na klienty (např. scalping.html).")
            while self.ib.isConnected():
                await asyncio.sleep(1)

if __name__ == "__main__":
    util.patchAsyncio()
    server = LiveFeedServer()
    asyncio.run(server.run())
