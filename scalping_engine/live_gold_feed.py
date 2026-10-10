import os
import json
import logging
import asyncio
import urllib.request
import websockets
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from ib_insync import IB, util, Commodity, Contract, Stock, Forex

from execution import ExecutionEngine

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("MultiAssetScalpingFeed")

IB_PORT = 7497
ib = IB()
virt_engine = ExecutionEngine(port=IB_PORT, client_id=99, ib_instance=ib)

# Kvantitativní parametry
TARGET_GOLD_OZ = 2.0        # 2.0 oz zlata (~$8 390 USD notional / marže ~$420 USD)
TARGET_BTC_QTY = 0.02       # 0.02 BTC (~$1 655 USD notional / marže ~$82 USD při páce 1:20)
IBKR_ROUNDTRIP_COMMISSION = 2.00  # $2.00 USD paušální provize IBKR
MIN_NET_PROFIT_TARGET_USD = 3.50  # Cílový čistý zisk v jednotkách dolarů (+3.50 až +7.50 USD)

# Stav aplikace
connected_clients = set()
current_symbol = 'BTCUSD'   # Výchozí je BTC pro 24/7 non-stop obchodování i o víkendech
current_timeframe = '1m'
gold_bars = {}              # Timeframe -> BarDataList z IBKR
btc_bars = {}               # Timeframe -> List[Dict] svíček z 24/7 streamu
active_test_trades = []
last_trade_closed_time = datetime.min
latest_btc_spot = 82750.0
latest_gold_spot = 4195.86

timeframes_durations = {
    '1m': '1 D',
    '5m': '5 D',
    '15m': '10 D',
    '1h': '1 M',
    '1d': '1 Y'
}

tf_to_ib_bar = {
    '1m': '1 min',
    '5m': '5 mins',
    '15m': '15 mins',
    '1h': '1 hour',
    '1d': '1 day'
}

def get_gold_market_status(now_dt=None):
    """Vrací harmonogram trhu se zlatem (XAU/USD / CME GC)."""
    if now_dt is None:
        now_dt = datetime.now()
    weekday = now_dt.weekday() # 0 = Po, 4 = Pá, 5 = So, 6 = Ne
    hour = now_dt.hour
    
    if weekday == 4 and hour >= 23:
        status = "CLOSED_WEEKEND"
        next_open = (now_dt + timedelta(days=2)).replace(hour=23, minute=0, second=0, microsecond=0)
    elif weekday == 5:
        status = "CLOSED_WEEKEND"
        next_open = (now_dt + timedelta(days=1)).replace(hour=23, minute=0, second=0, microsecond=0)
    elif weekday == 6:
        if hour < 23:
            status = "CLOSED_WEEKEND"
            next_open = now_dt.replace(hour=23, minute=0, second=0, microsecond=0)
        else:
            status = "OPEN"
            next_open = now_dt
    else:
        if hour == 23:
            status = "CLOSED_DAILY_BREAK"
            next_open = (now_dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            status = "OPEN"
            next_open = now_dt
            
    is_open = (status == "OPEN")
    time_to_open_sec = max(0, int((next_open - now_dt).total_seconds())) if not is_open else 0
    status_text = "TRH OTEVŘEN (ŽIVÁ SEANCE)" if is_open else (
        "TRH UZAVŘEN (VÍKENDOVÁ PAUZA)" if status == "CLOSED_WEEKEND" else "TRH UZAVŘEN (DENNÍ ROLLOVER PAUZA 23:00–00:00)"
    )
    
    return {
        "is_open": is_open,
        "status": status,
        "status_text": status_text,
        "next_open_cet": next_open.strftime("%d.%m.%Y %H:%M:%S") if not is_open else "Právě otevřeno",
        "next_open_timestamp": next_open.timestamp() if not is_open else 0,
        "time_to_open_sec": time_to_open_sec,
        "trading_hours": {
            "start": "Neděle 23:00 SEČ (17:00 NY EST / 22:00 UTC)",
            "end": "Pátek 23:00 SEČ (17:00 NY EST / 21:00 UTC)",
            "daily_break": "Pondělí až Čtvrtek 23:00 – 00:00 SEČ (60 min)",
            "weekend_break": "Pátek 23:00 až Neděle 23:00 SEČ (48 hod)"
        },
        "engine_readiness": "PŘIPRAVEN K AUTOMATICKÉ EXEKUCI PŘI OTEVŘENÍ TRHU",
        "configured_position_size": f"{TARGET_GOLD_OZ} oz (~$8 390 USD notional / vázaná marže ~$420 USD při páce 1:20)",
        "configured_net_target": f"+{MIN_NET_PROFIT_TARGET_USD:.2f} až +7.50 USD / trade (po odečtu provizí IBKR)",
        "commission_accounting": f"Reálná IBKR komise ${IBKR_ROUNDTRIP_COMMISSION:.2f} za round-trip započtena do čistého zisku"
    }

def fetch_btc_klines_sync(interval='1m', limit=120) -> List[Dict[str, Any]]:
    """Stáhne 24/7 živé svíčky Bitcoinu z Binance API (neomezený veřejný endpoint)."""
    # mapování intervalů
    int_map = {'1m': '1m', '5m': '5m', '15m': '15m', '1h': '1h', '1d': '1d'}
    api_int = int_map.get(interval, '1m')
    url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval={api_int}&limit={limit}"
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            bars = []
            for row in data:
                bars.append({
                    "time": int(row[0] / 1000),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5])
                })
            return bars
    except Exception as e:
        logger.warning(f"Chyba při stahování BTC klines: {e}")
        return []

def calculate_indicators(bars):
    """Vypočítá VWAP, VWAP sigma pásma, ATR(14) a KAMA(10,2,30) z libovolných svíček."""
    if not bars: return []
    
    if isinstance(bars, list) and len(bars) > 0 and isinstance(bars[0], dict):
        df = pd.DataFrame(bars)
        df['date'] = pd.to_datetime(df['time'], unit='s')
    else:
        df = util.df(bars)
        df['date'] = pd.to_datetime(df['date'])
        
    df['date_only'] = df['date'].dt.date
    df['vol'] = df.get('volume', 1).replace(0, 1)
    
    # 1. VWAP
    df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3.0
    df['pv'] = df['typical_price'] * df['vol']
    df['cum_pv'] = df.groupby('date_only')['pv'].cumsum()
    df['cum_vol'] = df.groupby('date_only')['vol'].cumsum()
    df['vwap'] = df['cum_pv'] / df['cum_vol']
    
    df['vwap_dev'] = df['typical_price'] - df['vwap']
    min_std = 5.0 if df['close'].iloc[-1] > 10000 else 0.40
    df['vwap_std'] = df['vwap_dev'].rolling(window=20, min_periods=5).std().fillna(min_std * 1.5).clip(lower=min_std)
    df['vwap_upper'] = df['vwap'] + 1.5 * df['vwap_std']
    df['vwap_lower'] = df['vwap'] - 1.5 * df['vwap_std']
    
    # 2. ATR
    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - df['close'].shift(1)).abs()
    tr3 = (df['low'] - df['close'].shift(1)).abs()
    df['tr'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    def_atr = 25.0 if df['close'].iloc[-1] > 10000 else 0.80
    df['atr'] = df['tr'].rolling(window=14, min_periods=1).mean().fillna(def_atr).clip(lower=def_atr * 0.3)
    
    # 3. KAMA
    period = 10
    df['change'] = (df['close'] - df['close'].shift(period)).abs()
    df['volatility'] = df['close'].diff().abs().rolling(window=period).sum()
    df['er'] = (df['change'] / df['volatility']).fillna(0).clip(lower=0.0, upper=1.0)
    
    fast_c = 2.0 / (2.0 + 1.0)
    slow_c = 2.0 / (30.0 + 1.0)
    df['sc'] = (df['er'] * (fast_c - slow_c) + slow_c) ** 2
    
    kama = np.zeros(len(df))
    kama[0] = df['close'].iloc[0]
    sc_vals = df['sc'].values
    close_vals = df['close'].values
    for i in range(1, len(df)):
        if np.isnan(sc_vals[i]):
            kama[i] = kama[i-1]
        else:
            kama[i] = kama[i-1] + sc_vals[i] * (close_vals[i] - kama[i-1])
            
    df['kama'] = kama
    
    result = []
    for _, row in df.iterrows():
        result.append({
            "time": int(row['date'].timestamp()),
            "open": float(row['open']), "high": float(row['high']), "low": float(row['low']), "close": float(row['close']),
            "vwap": round(float(row['vwap']), 2) if not pd.isna(row['vwap']) else float(row['close']),
            "vwap_upper": round(float(row['vwap_upper']), 2) if not pd.isna(row['vwap_upper']) else float(row['close']),
            "vwap_lower": round(float(row['vwap_lower']), 2) if not pd.isna(row['vwap_lower']) else float(row['close']),
            "kama": round(float(row['kama']), 2) if not pd.isna(row['kama']) else float(row['close']),
            "er": round(float(row['er']), 3) if not pd.isna(row['er']) else 0.0,
            "atr": round(float(row['atr']), 2) if not pd.isna(row['atr']) else def_atr
        })
    return result

def evaluate_trades(current_price: float, symbol: str = "BTCUSD"):
    """Průběžná aktualizace otevřených pozic, trailing / BE a kontrola SL/TP s odečtem reálných provizí."""
    global active_test_trades, last_trade_closed_time
    remaining = []
    
    for t in active_test_trades:
        # Pouze pro shodný symbol
        if t.get("symbol_raw") != symbol:
            remaining.append(t)
            continue
            
        closed = False
        reason = ""
        exit_price = 0.0
        
        entry_p = t["entry_price"]
        qty_num = float(t.get("qty_num", 0.02 if "BTC" in symbol else TARGET_GOLD_OZ))
        is_long = t["direction"] == "LONG"
        gross_float_pnl = (current_price - entry_p) * qty_num if is_long else (entry_p - current_price) * qty_num
        
        # Break-Even ochrana kryjící provize
        atr = t.get("atr", 25.0 if "BTC" in symbol else 0.8)
        be_offset = round((IBKR_ROUNDTRIP_COMMISSION / qty_num) + (2.0 if "BTC" in symbol else 0.15), 2)
        if not t.get("be_moved", False):
            if is_long and current_price >= entry_p + (1.2 * atr):
                t["sl"] = round(entry_p + be_offset, 2)
                t["be_moved"] = True
                logger.info(f"Pozice {t['id']}: Dosažen profit +1.2x ATR -> SL posunut na BE + komise ({t['sl']:.2f})!")
            elif not is_long and current_price <= entry_p - (1.2 * atr):
                t["sl"] = round(entry_p - be_offset, 2)
                t["be_moved"] = True
                logger.info(f"Pozice {t['id']}: Dosažen profit +1.2x ATR -> SL posunut na BE - komise ({t['sl']:.2f})!")
                
        virt_engine.update_active_position_spot(t["id"], current_price, t.get("be_moved", False))
        
        # Kontrola exekuce SL a TP
        if is_long:
            if current_price >= t["tp"]:
                closed = True; reason = "Take-Profit Zasažen"; exit_price = t["tp"]
            elif current_price <= t["sl"]:
                closed = True; reason = "Stop-Loss Zasažen"; exit_price = t["sl"]
        else:
            if current_price <= t["tp"]:
                closed = True; reason = "Take-Profit Zasažen"; exit_price = t["tp"]
            elif current_price >= t["sl"]:
                closed = True; reason = "Stop-Loss Zasažen"; exit_price = t["sl"]
                
        if closed:
            last_trade_closed_time = datetime.now()
            open_ts = t.get("open_timestamp", datetime.now().timestamp() - 60)
            duration = max(1, round((datetime.now().timestamp() - open_ts) / 60.0))
            
            gross_pnl = (exit_price - entry_p) * qty_num if is_long else (entry_p - exit_price) * qty_num
            commission = IBKR_ROUNDTRIP_COMMISSION
            net_pnl = round(gross_pnl - commission, 2)
            is_win = net_pnl >= 0
            
            entry_rsn = t.get("entry_reason", f"Kvantitativní spekulace {t['direction']}")
            strategy_name = t.get("strategy_name", "Kvantitativní model")
            invested_str = f"${t.get('invested_usd', round(entry_p * qty_num, 2)):.0f}"
            
            if is_win:
                outcome_analysis = f"Cíl TP ({exit_price:.2f} USD) úspěšně zasažen. Čistý zisk v jednotkách dolarů +${net_pnl:.2f} USD (Hrubý: +${gross_pnl:.2f} USD, provize: -${commission:.2f} USD) při alokaci {invested_str}."
                lesson_learned = f"Potvrzení platnosti strategie [{strategy_name}]: Dosažen zisk v jednotkách dolarů po odečtu poplatků."
                model_feedback = "Zvýšit váhu této signálové třídy o +3.5 %; zachovat poměr RRR 1:2.0."
            else:
                outcome_analysis = f"Zasažen Stop-Loss na {exit_price:.2f} USD. Čistá ztráta -${abs(net_pnl):.2f} USD (Hrubá ztráta: -${abs(gross_pnl):.2f} USD, provize: -${commission:.2f} USD)."
                lesson_learned = f"Poučení pro model [{strategy_name}]: Lokální šum prorazil ochranný SL."
                model_feedback = "Zvýšit ATR bezpečnostní násobek na 1.35x."

            virt_engine.remove_active_position(t["id"])
            virt_engine.record_executed_trade(
                symbol=t["symbol"], name=t["name"], direction=t["direction"],
                qty=t["qty"], entry=t["entry_price"], exit_price=exit_price, sl=t["sl"], tp=t["tp"],
                pnl_usd=net_pnl, exit_reason=f"{reason} (REAL-NET)", duration_min=duration,
                entry_reason=entry_rsn, outcome_analysis=outcome_analysis,
                lesson_learned=lesson_learned, model_feedback=model_feedback,
                gross_pnl_usd=round(gross_pnl, 2), commission_usd=commission
            )
            logger.info(f"Obchod {t['id']} uzavřen: {reason} | Čistý PnL: ${net_pnl:.2f} USD")
            
            for ws in list(connected_clients):
                asyncio.create_task(ws.send(json.dumps({"type": "refresh"})))
        else:
            remaining.append(t)
            
    active_test_trades = remaining

async def quant_strategy_loop():
    """
    Autonomní kvantitativní rozhodovací modul pro 24/7 Bitcoin a Zlato:
    - Bitcoin běží 24/7 non-stop bez pauzy!
    - Zlato běží po-pá dle harmonogramu.
    - Cílový čistý zisk: +3.50 až +7.50 USD na ziskový obchod.
    """
    logger.info("Spouštím aktivní kvantitativní engine s podporou 24/7 Bitcoinu.")
    global active_test_trades, last_trade_closed_time
    last_mkt_log_time = datetime.min
    
    while True:
        await asyncio.sleep(2)
        
        # Broadcast stavu trhu každých 10 s
        if (datetime.now() - last_mkt_log_time).total_seconds() >= 10:
            mkt = get_gold_market_status()
            trades_data = virt_engine.load_trades_data()
            trades_data["market_status"] = mkt
            trades_data["current_symbol"] = current_symbol
            trades_data["btc_spot"] = latest_btc_spot
            trades_data["gold_spot"] = latest_gold_spot
            virt_engine.save_trades_data(trades_data)
            last_mkt_log_time = datetime.now()
            
            mkt_msg = json.dumps({"type": "market_status", "market_status": mkt, "current_symbol": current_symbol})
            for ws in list(connected_clients):
                asyncio.create_task(ws.send(mkt_msg))
                
        # Kontrola, zda je dané aktivum otevřeno
        is_btc = (current_symbol == 'BTCUSD')
        if not is_btc:
            mkt = get_gold_market_status()
            if not mkt["is_open"]:
                continue
                
        if len(active_test_trades) > 0:
            continue
            
        if (datetime.now() - last_trade_closed_time).total_seconds() < 15:
            continue
            
        # Získat svíčky pro hodnocení
        if is_btc:
            bars = btc_bars.get('1m', [])
        else:
            bars = gold_bars.get('1m', [])
            
        if not bars or len(bars) < 10:
            continue
            
        inds = calculate_indicators(bars)
        if len(inds) < 2:
            continue
            
        curr = inds[-1]
        prev = inds[-2]
        price = curr["close"]
        open_p = curr["open"]
        er = curr["er"]
        kama = curr["kama"]
        prev_kama = prev["kama"]
        vwap = curr["vwap"]
        atr = curr["atr"]
        
        signal = None
        direction = ""
        strategy_name = ""
        entry_reason = ""
        
        if is_btc:
            # Bitcoin parametry: 0.02 BTC
            qty_num = TARGET_BTC_QTY
            # Pohyb o $250 přinese 0.02 * 250 = $5.00 gross - $1.50 comm = +$3.50 net
            tp_dist = max(250.0, round(2.0 * atr, 1))
            sl_dist = max(150.0, round(1.0 * atr, 1))
            sym_display = "BTC/USD"
            name_display = "Bitcoin Spot 24/7"
        else:
            # Zlato parametry: 2.0 oz
            qty_num = TARGET_GOLD_OZ
            min_tp_points = round((MIN_NET_PROFIT_TARGET_USD + IBKR_ROUNDTRIP_COMMISSION) / TARGET_GOLD_OZ, 2)
            tp_dist = max(min_tp_points, round(2.0 * atr, 2))
            sl_dist = max(1.20, round(0.9 * atr, 2))
            sym_display = "XAU/USD"
            name_display = "Zlato Spot CFD"
            
        # 1. KAMA Trend Momentum (ER >= 0.28)
        if er >= 0.28:
            if (price > kama and (kama >= prev_kama or price >= vwap)) or (price > kama and price > open_p):
                signal = "BUY"
                direction = "LONG"
                strategy_name = "KAMA Momentum Trend"
                entry_reason = f"Kvantitativní LONG signál [{strategy_name}]: Trendový cyklus (ER={er:.2f} >= 0.28), cena ({price:.2f}) vykazuje nákupní tlak nad KAMA ({kama:.2f}) a nad VWAP ({vwap:.2f})."
            elif (price < kama and (kama <= prev_kama or price <= vwap)) or (price < kama and price < open_p):
                signal = "SELL"
                direction = "SHORT"
                strategy_name = "KAMA Momentum Breakdown"
                entry_reason = f"Kvantitativní SHORT signál [{strategy_name}]: Trendový cyklus (ER={er:.2f} >= 0.28), cena ({price:.2f}) vykazuje prodejní tlak pod KAMA ({kama:.2f}) a pod VWAP ({vwap:.2f})."
        # 2. VWAP Mean Reversion (ER < 0.28)
        else:
            if curr["low"] <= curr["vwap_lower"] or (price < vwap and price > curr["low"]):
                signal = "BUY"
                direction = "LONG"
                strategy_name = "VWAP Mean Reversion"
                entry_reason = f"Kvantitativní LONG signál [{strategy_name}]: Pásmová rovnováha (ER={er:.2f} < 0.28), cena pod VWAP ({price:.2f} < {vwap:.2f}) s absorpčním odrazem."
            elif curr["high"] >= curr["vwap_upper"] or (price > vwap and price < curr["high"]):
                signal = "SELL"
                direction = "SHORT"
                strategy_name = "VWAP Mean Reversion"
                entry_reason = f"Kvantitativní SHORT signál [{strategy_name}]: Pásmová rovnováha (ER={er:.2f} < 0.28), cena nad VWAP ({price:.2f} > {vwap:.2f}) s prodejním zamítnutím."

        if signal and direction:
            sl = price - sl_dist if direction == "LONG" else price + sl_dist
            tp = price + tp_dist if direction == "LONG" else price - tp_dist
            
            actual_invest_usd = round(qty_num * price, 2)
            margin_usd = round(actual_invest_usd * 0.05, 2)
            now_dt = datetime.now()
            pos_id = f"POS-{now_dt.strftime('%Y%m%d')}-{int(now_dt.timestamp()) % 1000:03d}"
            
            qty_str = f"{qty_num} BTC" if is_btc else f"{qty_num} oz"
            trade = {
                "id": pos_id,
                "symbol_raw": current_symbol,
                "symbol": sym_display,
                "name": name_display,
                "direction": direction,
                "entry_price": round(price, 2),
                "current_price": round(price, 2),
                "sl": round(sl, 2),
                "tp": round(tp, 2),
                "stop_loss": round(sl, 2),
                "take_profit_1": round(tp, 2),
                "take_profit_2": round(tp + (tp - price) * 0.5 if direction == "LONG" else tp - (price - tp) * 0.5, 2),
                "qty": f"{qty_str} (${actual_invest_usd:.0f})",
                "size": f"{qty_str} (${actual_invest_usd:.0f} / marže ${margin_usd:.0f})",
                "qty_num": qty_num,
                "invested_usd": actual_invest_usd,
                "margin_usd": margin_usd,
                "open_time": now_dt.strftime("%d.%m.%Y %H:%M:%S"),
                "open_timestamp": now_dt.timestamp(),
                "entry_reason": entry_reason,
                "strategy_name": strategy_name,
                "strategy_trigger": entry_reason,
                "unrealized_pnl_usd": 0.0,
                "unrealized_pnl_czk": 0.0,
                "be_moved": False,
                "atr": atr
            }
            
            active_test_trades.append(trade)
            virt_engine.add_active_position(trade)
            
            est_gross_tp = round(qty_num * tp_dist, 2)
            est_net_tp = round(est_gross_tp - IBKR_ROUNDTRIP_COMMISSION, 2)
            logger.info(f"🚀 EXEKUCE: {sym_display} {direction} @ {price:.2f} | Objem: {qty_str} | TP: {trade['tp']} (+${est_net_tp:.2f} čistý) | SL: {trade['sl']} | {strategy_name}")
            
            # Pokud je IBKR připojeno a není víkend, odeslat reálný bracket do IBKR Demo
            if not is_btc and ib.isConnected():
                asyncio.create_task(virt_engine.place_live_demo_bracket(
                    symbol="XAUUSD", action=signal, quantity=qty_num,
                    limit_price=price, take_profit_price=tp, stop_loss_price=sl
                ))
                
            for ws in list(connected_clients):
                asyncio.create_task(ws.send(json.dumps({"type": "refresh"})))

async def btc_stream_task():
    """Průběžně každé 2 sekundy stahuje nejnovější BTC 1m svíčky a streamuje klientům."""
    global btc_bars, latest_btc_spot
    logger.info("Spouštím 24/7 Bitcoin klines stream task.")
    
    # První naplnění historie
    for tf in ['1m', '5m', '15m', '1h', '1d']:
        bars = await asyncio.to_thread(fetch_btc_klines_sync, tf, 100)
        if bars:
            btc_bars[tf] = bars
        await asyncio.sleep(0.3)
        
    while True:
        try:
            await asyncio.sleep(2)
            fresh_1m = await asyncio.to_thread(fetch_btc_klines_sync, '1m', 15)
            if fresh_1m:
                if '1m' not in btc_bars:
                    btc_bars['1m'] = []
                # Sloučit svíčky podle timestampu
                existing_map = {b['time']: b for b in btc_bars['1m']}
                for b in fresh_1m:
                    existing_map[b['time']] = b
                btc_bars['1m'] = sorted(existing_map.values(), key=lambda x: x['time'])[-150:]
                
                latest_btc_spot = btc_bars['1m'][-1]['close']
                
                # Pokud klient sleduje BTC a 1m, poslat update svíčky
                if current_symbol == 'BTCUSD' and current_timeframe == '1m':
                    inds = calculate_indicators(btc_bars['1m'])
                    if inds:
                        last_ind = inds[-1]
                        candle_msg = {
                            "type": "candle",
                            "symbol": "BTCUSD",
                            "candle": {
                                "time": last_ind["time"],
                                "open": last_ind["open"],
                                "high": last_ind["high"],
                                "low": last_ind["low"],
                                "close": last_ind["close"]
                            },
                            "kama": last_ind["kama"],
                            "vwap": last_ind["vwap"],
                            "spot": last_ind["close"]
                        }
                        msg_str = json.dumps(candle_msg)
                        for ws in list(connected_clients):
                            asyncio.create_task(ws.send(msg_str))
                            
                        evaluate_trades(last_ind["close"], "BTCUSD")
        except Exception as e:
            logger.warning(f"Chyba v btc_stream_task: {e}")
            await asyncio.sleep(3)

async def ibkr_account_sync_task():
    """Pravidelně každých 5 sekund synchronizuje live data o účtu z IB Gateway Demo (DUR222134)."""
    logger.info("Spouštím IBKR Demo Account Sync Task (DUR222134).")
    while True:
        try:
            await asyncio.sleep(5)
            if ib.isConnected():
                acc_info = virt_engine.sync_ibkr_account("DUR222134")
                if acc_info:
                    msg = json.dumps({"type": "ibkr_account", "account": acc_info})
                    for ws in list(connected_clients):
                        asyncio.create_task(ws.send(msg))
        except Exception as e:
            logger.debug(f"Chyba v account sync: {e}")
            await asyncio.sleep(5)

async def push_history_to_client(websocket, symbol: str, timeframe: str):
    """Odešle historická data a indikátory klientovi pro zvolený symbol a timeframe."""
    if symbol == 'BTCUSD':
        bars = btc_bars.get(timeframe, [])
        if not bars:
            bars = await asyncio.to_thread(fetch_btc_klines_sync, timeframe, 100)
            btc_bars[timeframe] = bars
    else:
        # Zlato
        ib_tf = tf_to_ib_bar.get(timeframe, '1 min')
        bars = gold_bars.get(ib_tf, [])
        
    if not bars:
        return
        
    indicators = calculate_indicators(bars)
    msg = json.dumps({
        "type": "history",
        "symbol": symbol,
        "timeframe": timeframe,
        "candles": [{"time": d["time"], "open": d["open"], "high": d["high"], "low": d["low"], "close": d["close"]} for d in indicators],
        "kama": [{"time": d["time"], "value": d["kama"]} for d in indicators],
        "vwap": [{"time": d["time"], "value": d["vwap"]} for d in indicators],
        "spot": indicators[-1]["close"]
    })
    await websocket.send(msg)

async def ws_handler(websocket):
    global current_symbol, current_timeframe
    connected_clients.add(websocket)
    try:
        # 1. Odeslat IBKR Demo Account stav
        trades_data = virt_engine.load_trades_data()
        acc = trades_data.get("ibkr_live_account")
        if acc:
            await websocket.send(json.dumps({"type": "ibkr_account", "account": acc}))
            
        # 2. Odeslat Market status a aktivní symbol
        mkt = get_gold_market_status()
        await websocket.send(json.dumps({
            "type": "market_status",
            "market_status": mkt,
            "current_symbol": current_symbol,
            "btc_spot": latest_btc_spot,
            "gold_spot": latest_gold_spot
        }))
        
        # 3. Odeslat historii grafu
        await push_history_to_client(websocket, current_symbol, current_timeframe)
        
        async for message in websocket:
            try:
                data = json.loads(message)
                action = data.get("action")
                
                if action == "change_symbol":
                    new_sym = data.get("symbol", "BTCUSD")
                    logger.info(f"Klient přepíná instrument na: {new_sym}")
                    current_symbol = new_sym
                    await push_history_to_client(websocket, current_symbol, current_timeframe)
                    # Broadcast nového symbolu
                    for ws in list(connected_clients):
                        asyncio.create_task(ws.send(json.dumps({
                            "type": "symbol_changed",
                            "symbol": current_symbol
                        })))
                        
                elif action == "change_tf":
                    new_tf = data.get("tf", "1m")
                    logger.info(f"Klient přepíná timeframe na: {new_tf}")
                    current_timeframe = new_tf
                    await push_history_to_client(websocket, current_symbol, current_timeframe)
                    
                elif action == "place_demo_order":
                    # Manuální pokus odeslání do IBKR Demo
                    sym = data.get("symbol", "XAUUSD")
                    direction = data.get("direction", "BUY")
                    qty = float(data.get("qty", 1.0))
                    price = float(data.get("price", 4195.0))
                    sl = float(data.get("sl", 4190.0))
                    tp = float(data.get("tp", 4205.0))
                    
                    logger.info(f"Manuální požadavek z webu: Odeslat pokyn do IBKR Demo: {direction} {qty} {sym} @ {price}")
                    order_res = await virt_engine.place_live_demo_bracket(
                        symbol=sym, action=direction, quantity=qty,
                        limit_price=price, take_profit_price=tp, stop_loss_price=sl
                    )
                    await websocket.send(json.dumps({
                        "type": "order_confirmed",
                        "order": order_res or {"status": "Virtuálně zaevidováno v systému"}
                    }))
                    for ws in list(connected_clients):
                        asyncio.create_task(ws.send(json.dumps({"type": "refresh"})))
            except Exception as e:
                logger.error(f"Chyba při zpracování WS zprávy: {e}")
    finally:
        connected_clients.remove(websocket)

def on_gold_bar_update(bars, has_new_bar, ib_tf):
    global latest_gold_spot
    if not bars: return
    
    inds = calculate_indicators(bars)
    if not inds: return
    last_ind = inds[-1]
    latest_gold_spot = last_ind["close"]
    
    # Broadcast pouze pokud klient sleduje Zlato
    tf_short = {v: k for k, v in tf_to_ib_bar.items()}.get(ib_tf, '1m')
    if current_symbol == 'XAUUSD' and current_timeframe == tf_short:
        candle_msg = {
            "type": "candle",
            "symbol": "XAUUSD",
            "candle": {
                "time": last_ind["time"],
                "open": last_ind["open"],
                "high": last_ind["high"],
                "low": last_ind["low"],
                "close": last_ind["close"]
            },
            "kama": last_ind["kama"],
            "vwap": last_ind["vwap"],
            "spot": last_ind["close"]
        }
        msg_str = json.dumps(candle_msg)
        for ws in list(connected_clients):
            asyncio.create_task(ws.send(msg_str))
            
        evaluate_trades(last_ind["close"], "XAUUSD")

async def subscribe_gold_timeframes():
    logger.info("Odebírám data pro zlato z IBKR...")
    gold_contract = Commodity('XAUUSD', 'SMART', 'USD')
    try:
        await ib.qualifyContractsAsync(gold_contract)
        for tf_short, ib_tf in tf_to_ib_bar.items():
            dur = timeframes_durations.get(tf_short, '1 D')
            bars = ib.reqHistoricalData(
                gold_contract, endDateTime='', durationStr=dur,
                barSizeSetting=ib_tf, whatToShow='MIDPOINT', useRTH=False, keepUpToDate=True
            )
            bars.updateEvent += lambda b, h, timeframe=ib_tf: on_gold_bar_update(b, h, timeframe)
            gold_bars[ib_tf] = bars
            await asyncio.sleep(0.4)
    except Exception as e:
        logger.warning(f"IBKR Gold subscription upozornění: {e}")

async def main():
    logger.info("================================================================")
    logger.info("⚡ SUGGESTINVEST PROFI MULTI-ASSET SCALPING ENGINE v2.0.0 START ⚡")
    logger.info("  - 24/7 Bitcoin (BTC/USD) Non-stop Live Trading")
    logger.info("  - Interactive Brokers Paper Trading Demo (DUR222134) Live Sync")
    logger.info("  - Port: 8765 WebSocket | IB Gateway Port: 7497")
    logger.info("================================================================")
    
    # 1. Připojení k IBKR Gateway Demo (DUR222134)
    try:
        await ib.connectAsync('127.0.0.1', IB_PORT, clientId=3)
        logger.info("✅ Úspěšně připojeno k IB Gateway (Port 7497)!")
        # První synchronizace účtu
        acc = virt_engine.sync_ibkr_account("DUR222134")
        if acc:
            logger.info(f"✅ IBKR Demo Účet {acc['account_id']} synchronizován: Net Liq = {acc['net_liquidation_czk']} CZK (~${acc['net_liquidation_usd']} USD), Volný margin = {acc['available_funds_czk']} CZK")
    except Exception as e:
        logger.warning(f"IB Gateway connect upozornění (bude se opakovat): {e}")
        
    # 2. Odběr zlata z IBKR
    await subscribe_gold_timeframes()
    
    # 3. Spuštění asynchronních úloh
    asyncio.create_task(btc_stream_task())
    asyncio.create_task(ibkr_account_sync_task())
    asyncio.create_task(quant_strategy_loop())
    
    # 4. Spuštění WebSocket serveru na portu 8765
    async with websockets.serve(ws_handler, "127.0.0.1", 8765):
        logger.info("🚀 WebSocket server aktivní na ws://127.0.0.1:8765")
        await asyncio.Future()

if __name__ == '__main__':
    util.patchAsyncio()
    asyncio.run(main())
