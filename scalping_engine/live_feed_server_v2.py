import asyncio
import json
import logging
import time
from ib_insync import IB, util, Forex
import websockets
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("LiveFeedServerV2")

class LiveFeedServer:
    def __init__(self, host='127.0.0.1', ib_port=7497, ws_port=8765):
        self.ib_port = ib_port
        self.ws_port = ws_port
        self.ib = IB()
        self.clients = set()
        
        self.contract = Forex('EURUSD')
        self.current_timeframe = '1 min'
        self.is_streaming = False

    async def fetch_history(self, websocket, timeframe):
        # Nastavení parametrů podle timeframe
        if timeframe == '1 min':
            duration = '2 D'
            bar_size = '1 min'
        elif timeframe == '1 hour':
            duration = '1 M'
            bar_size = '1 hour'
        elif timeframe == '1 day':
            duration = '1 Y'
            bar_size = '1 day'
        else:
            return

        logger.info(f"Stahuji historii pro {timeframe}...")
        bars = await self.ib.reqHistoricalDataAsync(
            self.contract,
            endDateTime='',
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow='MIDPOINT',
            useRTH=False,
            formatDate=1
        )
        
        history_data = []
        for bar in bars:
            history_data.append({
                "time": int(bar.date.timestamp()) if hasattr(bar.date, 'timestamp') else int(time.mktime(bar.date.timetuple())),
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close
            })
            
        await websocket.send(json.dumps({
            "type": "history",
            "timeframe": timeframe,
            "data": history_data
        }))
        logger.info(f"Odesláno {len(history_data)} historických svíček klientovi.")

    async def handler(self, websocket):
        self.clients.add(websocket)
        logger.info(f"Nové připojení. Klientů: {len(self.clients)}")
        
        # Defaultně pošleme 1 min historii při připojení
        await self.fetch_history(websocket, '1 min')
        
        try:
            async for message in websocket:
                data = json.loads(message)
                if data.get('action') == 'set_timeframe':
                    self.current_timeframe = data['timeframe']
                    await self.fetch_history(websocket, self.current_timeframe)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.clients.remove(websocket)
            logger.info("Klient odpojen.")

    def on_pending_tickers(self, tickers):
        for ticker in tickers:
            if ticker.contract.symbol != self.contract.symbol:
                continue
                
            if ticker.bid and ticker.ask:
                mid_price = (ticker.bid + ticker.ask) / 2.0
            else:
                mid_price = ticker.marketPrice()
                
            if str(mid_price) == "nan":
                continue
                
            # Pro real-time streamování odesíláme ticky.
            # Frontend Lightweight Charts si z toho sám updatne poslední svíčku
            now = int(time.time())
            
            data = {
                "type": "live_tick",
                "time": now,
                "price": mid_price
            }
            msg = json.dumps(data)
            
            websockets.broadcast(self.clients, msg)

    async def run(self):
        try:
            logger.info(f"Připojování k IBKR na portu {self.ib_port}...")
            # Povolíme asyncio pro ib_insync (pokud už není)
            util.patchAsyncio()
            await self.ib.connectAsync('127.0.0.1', self.ib_port, clientId=5)
            logger.info("Připojeno k IBKR.")
        except Exception as e:
            logger.error(f"Chyba připojení k IBKR: {e}")
            return
            
        await self.ib.qualifyContractsAsync(self.contract)
        
        self.ib.reqMktData(self.contract, "", False, False)
        self.ib.pendingTickersEvent += self.on_pending_tickers
        
        logger.info(f"Startuji WebSocket server na portu {self.ws_port}")
        async with websockets.serve(self.handler, "localhost", self.ws_port):
            while self.ib.isConnected():
                await asyncio.sleep(1)

if __name__ == "__main__":
    server = LiveFeedServer()
    asyncio.run(server.run())
