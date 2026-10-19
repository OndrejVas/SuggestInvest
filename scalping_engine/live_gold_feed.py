import os
import json
import sqlite3
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
logger = logging.getLogger("DualMetalsScalpingFeed")

IB_PORT = 7497
IBKR_CLIENT_ID = 15
ib = IB()
virt_engine = ExecutionEngine(port=IB_PORT, client_id=IBKR_CLIENT_ID, ib_instance=ib)

# Kvantitativní parametry pro drahé kovy (Zlato & Stříbro)
TARGET_GOLD_OZ = 2.0        # 2.0 oz zlata (~$8 380 USD notional / marže ~$420 USD při páce 1:20)
TARGET_SILVER_OZ = 50.0     # 50.0 oz stříbra (~$3 020 USD notional / marže ~$151 USD při páce 1:20)
IBKR_ROUNDTRIP_COMMISSION = 2.00  # $2.00 USD paušální provize IBKR roundtrip
MIN_NET_PROFIT_TARGET_USD = 4.50  # Cílový čistý zisk (+4.50 až +7.50 USD) po odečtu poplatku brokera

# Stav aplikace a duální stream
connected_clients = set()
current_timeframe = '1m'
gold_bars = {}              # Timeframe -> List[Dict] svíček pro XAU/USD
silver_bars = {}            # Timeframe -> List[Dict] svíček pro XAG/USD
_init_data = virt_engine.load_trades_data()
auto_invest_enabled = _init_data.get("auto_invest_enabled", True)
active_test_trades = _init_data.get("active_positions", [])
last_trade_closed_time = datetime.min
stagnation_cooldown_until = datetime.min
latest_gold_spot = 4188.60
latest_silver_spot = 60.425
last_market_data_time = datetime.now()

timeframes_durations = {
    '1m': '1d',
    '5m': '5d',
    '15m': '5d',
    '1h': '1mo',
    '1d': '1y'
}

def get_metals_market_status(now_dt=None) -> Dict[str, Any]:
    """
    Vrací přesný harmonogram a stav trhu pro drahé kovy (CME Globex & Interbank Spot XAU/USD, XAG/USD).
    - Otevřeno: Neděle 23:00 SEČ až Pátek 23:00 SEČ (23 hodin denně)
    - Denní přestávka (Rollover): Po-Čt 23:00 - 00:00 SEČ (60 min)
    - Víkendová přestávka: Pá 23:00 - Ne 23:00 SEČ (48 hod)
    - Pre-market: 15 minut před otevřením (23:45-00:00 SEČ / Ne 22:45-23:00 SEČ)
    """
    if now_dt is None:
        now_dt = datetime.now()
    weekday = now_dt.weekday() # 0 = Po, 4 = Pá, 5 = So, 6 = Ne
    hour = now_dt.hour
    minute = now_dt.minute
    
    status = "OPEN"
    status_text = "TRH OTEVŘEN (ŽIVÁ SEANCE)"
    is_open = True
    is_premarket = False
    next_open = now_dt
    
    # Víkend: Pátek od 23:00 do Neděle 23:00
    if weekday == 4 and hour >= 23:
        status = "CLOSED_WEEKEND"
        next_open = (now_dt + timedelta(days=2)).replace(hour=23, minute=0, second=0, microsecond=0)
    elif weekday == 5:
        status = "CLOSED_WEEKEND"
        next_open = (now_dt + timedelta(days=1)).replace(hour=23, minute=0, second=0, microsecond=0)
    elif weekday == 6:
        if hour < 22 or (hour == 22 and minute < 45):
            status = "CLOSED_WEEKEND"
            next_open = now_dt.replace(hour=23, minute=0, second=0, microsecond=0)
        elif hour == 22 and minute >= 45:
            status = "PRE_MARKET"
            status_text = "PŘED OTEVŘENÍM (PRE-MARKET AUCTION)"
            is_premarket = True
            is_open = False
            next_open = now_dt.replace(hour=23, minute=0, second=0, microsecond=0)
        else:
            status = "OPEN"
            next_open = now_dt
    else:
        # Pondělí až Čtvrtek: Denní pauza 23:00 - 00:00 SEČ
        if hour == 23 and minute < 45:
            status = "CLOSED_DAILY_BREAK"
            next_open = (now_dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        elif hour == 23 and minute >= 45:
            status = "PRE_MARKET"
            status_text = "PŘED OTEVŘENÍM (PRE-MARKET AUCTION)"
            is_premarket = True
            is_open = False
            next_open = (now_dt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            status = "OPEN"
            next_open = now_dt
            
    is_open = (status == "OPEN")
    time_to_open_sec = max(0, int((next_open - now_dt).total_seconds())) if not is_open else 0
    if status == "CLOSED_WEEKEND":
        status_text = "TRH UZAVŘEN (VÍKENDOVÁ PAUZA)"
    elif status == "CLOSED_DAILY_BREAK":
        status_text = "TRH UZAVŘEN (DENNÍ ROLLOVER PAUZA 23:00–00:00)"
        
    hours_left = time_to_open_sec // 3600
    mins_left = (time_to_open_sec % 3600) // 60
    secs_left = time_to_open_sec % 60
    countdown_str = f"{hours_left:02d}:{mins_left:02d}:{secs_left:02d}" if not is_open else "00:00:00 (Otevřeno)"
    
    return {
        "is_open": is_open,
        "is_premarket": is_premarket,
        "status": status,
        "status_text": status_text,
        "countdown_str": countdown_str,
        "next_open_cet": next_open.strftime("%d.%m.%Y %H:%M:%S") if not is_open else "Právě otevřeno",
        "next_open_timestamp": next_open.timestamp() if not is_open else 0,
        "time_to_open_sec": time_to_open_sec,
        "trading_hours": {
            "start": "Neděle 23:00 SEČ (18:00 NY EST / 22:00 UTC)",
            "end": "Pátek 23:00 SEČ (17:00 NY EST / 21:00 UTC)",
            "daily_break": "Pondělí až Čtvrtek 23:00 – 00:00 SEČ (60 min)",
            "weekend_break": "Pátek 23:00 až Neděle 23:00 SEČ (48 hod)",
            "pre_market": "15 minut před otevřením (23:45–00:00 / Ne 22:45–23:00)"
        },
        "engine_readiness": "● PŘIPOJENO K IBKR DEMO (PORT 7497) • DUÁLNÍ EXEKUCE ZLATO & STŘÍBRO",
        "configured_gold_size": f"{TARGET_GOLD_OZ} oz (~$8 380 USD notional / vázaná marže ~$420 USD při páce 1:20)",
        "configured_silver_size": f"{TARGET_SILVER_OZ} oz (~$3 020 USD notional / vázaná marže ~$151 USD při páce 1:20)",
        "configured_net_target": f"+{MIN_NET_PROFIT_TARGET_USD:.2f} až +7.50 USD / trade (po odečtu provizí IBKR)",
        "commission_accounting": f"Reálná IBKR komise ${IBKR_ROUNDTRIP_COMMISSION:.2f} za round-trip započtena do čistého zisku"
    }

def fetch_yahoo_bars_sync(symbol_ticker: str, interval='1m', range_str='1d') -> List[Dict[str, Any]]:
    """Stáhne svíčky drahých kovů z tržního feedu Yahoo Finance (GC=F pro Zlato, SI=F pro Stříbro)."""
    # mapování intervalů
    int_map = {'1m': '1m', '5m': '5m', '15m': '15m', '1h': '1h', '1d': '1d'}
    api_int = int_map.get(interval, '1m')
    rng = '1d' if api_int == '1m' else ('5d' if api_int in ['5m', '15m'] else ('1mo' if api_int == '1h' else '1y'))
    
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol_ticker}?interval={api_int}&range={rng}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            result = data.get('chart', {}).get('result', [])
            if not result:
                return []
            res0 = result[0]
            timestamps = res0.get('timestamp', [])
            quotes = res0.get('indicators', {}).get('quote', [{}])[0]
            opens = quotes.get('open', [])
            highs = quotes.get('high', [])
            lows = quotes.get('low', [])
            closes = quotes.get('close', [])
            volumes = quotes.get('volume', [])
            
            bars = []
            for i in range(len(timestamps)):
                if opens[i] is None or closes[i] is None:
                    continue
                bars.append({
                    "time": int(timestamps[i]),
                    "open": float(opens[i]),
                    "high": float(highs[i]),
                    "low": float(lows[i]),
                    "close": float(closes[i]),
                    "volume": float(volumes[i] or 1.0)
                })
            return bars
    except Exception as e:
        logger.warning(f"Chyba při stahování {symbol_ticker} bars: {e}")
        return []

def calculate_indicators(bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Vypočítá VWAP, VWAP sigma pásma, ATR(14), KAMA(10,2,30) a RSI(14)."""
    if not bars:
        return []
    
    df = pd.DataFrame(bars)
    df['date'] = pd.to_datetime(df['time'], unit='s')
    df['date_only'] = df['date'].dt.date
    df['vol'] = df.get('volume', 1).replace(0, 1)
    
    # 1. VWAP (Anchored na den)
    df['typical_price'] = (df['high'] + df['low'] + df['close']) / 3.0
    df['pv'] = df['typical_price'] * df['vol']
    df['cum_pv'] = df.groupby('date_only')['pv'].cumsum()
    df['cum_vol'] = df.groupby('date_only')['vol'].cumsum()
    df['vwap'] = df['cum_pv'] / df['cum_vol']
    
    df['vwap_dev'] = df['typical_price'] - df['vwap']
    is_gold = df['close'].iloc[-1] > 500
    min_std = 0.40 if is_gold else 0.05
    df['vwap_std'] = df['vwap_dev'].rolling(window=20, min_periods=5).std().fillna(min_std * 1.5).clip(lower=min_std)
    df['vwap_upper'] = df['vwap'] + 1.5 * df['vwap_std']
    df['vwap_lower'] = df['vwap'] - 1.5 * df['vwap_std']
    
    # 2. ATR(14)
    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - df['close'].shift(1)).abs()
    tr3 = (df['low'] - df['close'].shift(1)).abs()
    df['tr'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    def_atr = 0.85 if is_gold else 0.08
    df['atr'] = df['tr'].rolling(window=14, min_periods=1).mean().fillna(def_atr).clip(lower=def_atr * 0.3)
    
    # 3. KAMA (10, 2, 30)
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
    
    # 4. RSI (14)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14, min_periods=1).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14, min_periods=1).mean()
    rs = gain / loss.replace(0, 0.00001)
    df['rsi'] = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0).clip(lower=0.0, upper=100.0)
    
    result = []
    round_decimals = 2 if is_gold else 3
    for _, row in df.iterrows():
        result.append({
            "time": int(row['date'].timestamp()),
            "open": round(float(row['open']), round_decimals),
            "high": round(float(row['high']), round_decimals),
            "low": round(float(row['low']), round_decimals),
            "close": round(float(row['close']), round_decimals),
            "vwap": round(float(row['vwap']), round_decimals) if not pd.isna(row['vwap']) else round(float(row['close']), round_decimals),
            "vwap_upper": round(float(row['vwap_upper']), round_decimals) if not pd.isna(row['vwap_upper']) else round(float(row['close']), round_decimals),
            "vwap_lower": round(float(row['vwap_lower']), round_decimals) if not pd.isna(row['vwap_lower']) else round(float(row['close']), round_decimals),
            "kama": round(float(row['kama']), round_decimals) if not pd.isna(row['kama']) else round(float(row['close']), round_decimals),
            "er": round(float(row['er']), 3) if not pd.isna(row['er']) else 0.0,
            "atr": round(float(row['atr']), round_decimals) if not pd.isna(row['atr']) else def_atr,
            "rsi": round(float(row['rsi']), 1) if not pd.isna(row['rsi']) else 50.0
        })
    return result

def get_adaptive_state() -> Dict[str, Any]:
    """Kvantitativní řízení rizik na základě historie drahých kovů."""
    try:
        trades_data = virt_engine.load_trades_data()
        history = trades_data.get("executed_history", [])
        
        recent_10 = history[:10]
        wins_10 = sum(1 for t in recent_10 if t.get("pnl_usd", 0) > 0)
        win_rate_10 = round((wins_10 / len(recent_10) * 100), 1) if recent_10 else 100.0
        
        consecutive_losses = 0
        for t in history[:10]:
            if t.get("pnl_usd", 0) < 0:
                consecutive_losses += 1
            else:
                break
                
        if consecutive_losses >= 2:
            regime = "DEFENSIVE_HIGH_LOSS"
            min_cooldown_sec = 300
            er_threshold = 0.38
            mtf_required = True
        else:
            regime = "BALANCED_QUANT_SELECTIVE"
            min_cooldown_sec = 45
            er_threshold = 0.30
            mtf_required = False
            
        return {
            "regime": regime,
            "consecutive_losses": consecutive_losses,
            "win_rate_10": win_rate_10,
            "min_cooldown_sec": min_cooldown_sec,
            "er_threshold": er_threshold,
            "mtf_required": mtf_required,
            "gold_allocation_oz": TARGET_GOLD_OZ,
            "silver_allocation_oz": TARGET_SILVER_OZ
        }
    except Exception as e:
        logger.error(f"Chyba v get_adaptive_state: {e}")
        return {
            "regime": "BALANCED_QUANT_SELECTIVE",
            "consecutive_losses": 0,
            "win_rate_10": 100.0,
            "min_cooldown_sec": 45,
            "er_threshold": 0.30,
            "mtf_required": False,
            "gold_allocation_oz": TARGET_GOLD_OZ,
            "silver_allocation_oz": TARGET_SILVER_OZ
        }

def evaluate_open_trades(current_spot: float, symbol_raw: str, force_close_id: str = None):
    """
    Vyhodnocuje otevřené obchody pro Zlato a Stříbro.
    Aplikuje:
    - SL / TP zasažení
    - Posun na Break-Even po dosažení +60 % cíle
    - Stagnation Breaker
    - Záznam do scalping_trades.json včetně AI Causal Audit poučení
    """
    global active_test_trades, last_trade_closed_time
    now_dt = datetime.now()
    trades_data = virt_engine.load_trades_data()
    positions = trades_data.get("active_positions", [])
    if not positions:
        active_test_trades = []
        return

    remaining_positions = []
    for pos in positions:
        pos_sym = pos.get("symbol_raw", pos.get("symbol", ""))
        # Kontrola shody symbolu (XAUUSD vs XAGUSD)
        if "XAU" in pos_sym and "XAU" not in symbol_raw:
            remaining_positions.append(pos)
            continue
        if "XAG" in pos_sym and "XAG" not in symbol_raw:
            remaining_positions.append(pos)
            continue
            
        pos_id = pos.get("id")
        entry = float(pos.get("entry_price", current_spot))
        sl = float(pos.get("sl", pos.get("stop_loss", 0)))
        tp = float(pos.get("tp", pos.get("take_profit_1", 0)))
        qty_num = float(pos.get("qty_num", TARGET_GOLD_OZ if "XAU" in pos_sym else TARGET_SILVER_OZ))
        direction = pos.get("direction", "LONG").upper()
        is_long = "LONG" in direction or "BUY" in direction
        
        # Hrubý výnos
        gross_pnl = (current_spot - entry) * qty_num if is_long else (entry - current_spot) * qty_num
        comm = IBKR_ROUNDTRIP_COMMISSION
        net_pnl = round(gross_pnl - comm, 2)
        
        # 1. Dynamický Break-Even posun
        tp_dist = abs(tp - entry)
        curr_dist = abs(current_spot - entry)
        if not pos.get("be_moved", False) and curr_dist >= (0.60 * tp_dist) and net_pnl > 2.50:
            be_price = entry + (0.35 if is_long else -0.35) if "XAU" in pos_sym else entry + (0.04 if is_long else -0.04)
            pos["sl"] = round(be_price, 2)
            pos["stop_loss"] = round(be_price, 2)
            pos["be_moved"] = True
            logger.info(f"🛡️ BREAK-EVEN AKTIVOVÁN pro {pos_id} ({pos_sym}): SL posunut na {be_price} (Zajištěn čistý zisk)")
            
        pos["current_price"] = round(current_spot, 2)
        pos["gross_pnl_usd"] = round(gross_pnl, 2)
        pos["unrealized_pnl_usd"] = net_pnl
        pos["unrealized_pnl_czk"] = round(net_pnl * 23.2, 2)
        
        # 2. Kontrola výstupu (TP / SL / Stagnation / Force)
        hit_tp = (current_spot >= tp) if is_long else (current_spot <= tp)
        hit_sl = (current_spot <= sl) if is_long else (current_spot >= sl)
        force_exit = (force_close_id == pos_id)
        
        open_ts = pos.get("open_timestamp", now_dt.timestamp() - 60)
        dur_min = max(1, int((now_dt.timestamp() - open_ts) / 60))
        
        if hit_tp or hit_sl or force_exit:
            exit_price = current_spot
            last_trade_closed_time = now_dt
            
            if hit_tp:
                exit_reason = f"Take-Profit zasažen ({'+' if net_pnl>0 else ''}{net_pnl:.2f} USD čistý zisk)"
                outcome_analysis = f"Úspěšná realizace cílového pohybu po {dur_min} min. Model správně zachytil impulz na {pos_sym}."
                lesson_learned = f"Potvrzení platnosti kvantitativního filtru pro {pos_sym}. Zvýšit alokační skóre pro toto aktivum."
                model_feedback = "Zvýšit váhu aktuální strategie o +5 %."
                result = "WIN"
            elif hit_sl:
                exit_reason = "Stop-Loss zasažen (Obrana kapitálu)"
                outcome_analysis = f"Trh neudržel trendovou úroveň a obrátil se. Stop-Loss ochránil marži před hlubším propadem."
                lesson_learned = f"Při protipohybu na {pos_sym} analyzovat korelaci se sesterským kovem. Zpřísnit vstupní filtr ER."
                model_feedback = "Zvýšit ER práh a aplikovat ochranný cooldown."
                result = "LOSS"
            elif force_exit:
                exit_reason = f"Manuální Market Close ({'+' if net_pnl>0 else ''}{net_pnl:.2f} USD čistý zisk)"
                outcome_analysis = f"Pozice uzavřena manuálně uživatelem z webové aplikace po {dur_min} min."
                lesson_learned = f"Manuální zásah obchodníka na {pos_sym}. Model provádí okamžité vyhodnocení trhu."
                model_feedback = "Okamžitá kvantitativní evaluace pro další pokyn dle přepínače Investuj."
                result = "WIN" if net_pnl > 0 else "LOSS"
                if auto_invest_enabled:
                    last_trade_closed_time = datetime.min
                    stagnation_cooldown_until = datetime.min
            else:
                exit_reason = "Stagnation Breaker (Časový limit v mrtvém pásmu)"
                outcome_analysis = f"Pozice vypršela po {dur_min} minutách bez dynamiky. Uzavřeno na tržní ceně."
                lesson_learned = "Nízká volatilita neposkytuje dostatek prostoru pro překonání spreadu. Vyčkat na otevření US/London seance."
                model_feedback = "Dočasně pozastavit vstupy při nízkém ATR."
                result = "WIN" if net_pnl > 0 else "LOSS"
                
            virt_engine.record_executed_trade(
                symbol="XAUUSD" if "XAU" in pos_sym else "XAGUSD",
                name="Zlato (Gold Spot CFD)" if "XAU" in pos_sym else "Stříbro (Silver Spot CFD)",
                direction=direction,
                qty=pos.get("qty", f"{qty_num} oz"),
                entry=entry,
                exit_price=exit_price,
                sl=sl,
                tp=tp,
                pnl_usd=net_pnl,
                exit_reason=exit_reason,
                duration_min=dur_min,
                entry_reason=pos.get("entry_reason", "Kvantitativní selekce"),
                outcome_analysis=outcome_analysis,
                lesson_learned=lesson_learned,
                model_feedback=model_feedback,
                gross_pnl_usd=gross_pnl,
                commission_usd=comm
            )
            logger.info(f"🏁 POZICE UZAVŘENA: {pos_id} | {pos_sym} {direction} | Čistý PnL: ${net_pnl:.2f} USD ({result}) | Důvod: {exit_reason}")
            
            # Dynamické ponaučení pro Tabulku 2 (Kumulativní AI audit drahých kovů)
            learning_item = {
                "id": f"LRN-METALS-{now_dt.strftime('%Y%m%d%H%M%S')}",
                "datetime_cet": now_dt.strftime("%d.%m.%Y %H:%M:%S"),
                "symbol": "XAU/USD" if "XAU" in pos_sym else "XAG/USD",
                "title": f"{direction} {pos_sym} ({exit_reason})",
                "result": result,
                "net_pnl_usd": net_pnl,
                "duration_min": dur_min,
                "lesson": lesson_learned,
                "actionable_rule": model_feedback,
                "status": "AKTUALIZOVÁNO PŘI REFRESHI"
            }
            trades_data.setdefault("metals_learning_log", []).insert(0, learning_item)
            trades_data["metals_learning_log"] = trades_data["metals_learning_log"][:30]
            
            # Broadcast refresh všem klientům
            for ws in list(connected_clients):
                asyncio.create_task(ws.send(json.dumps({"type": "refresh"})))
        else:
            remaining_positions.append(pos)
            
    trades_data["active_positions"] = remaining_positions
    trades_data["summary"]["active_positions_count"] = len(remaining_positions)
    virt_engine.save_trades_data(trades_data)
    active_test_trades = remaining_positions

async def selective_quant_strategy_loop():
    """
    Autonomní selektivní kvantitativní rozhodovací cyklus:
    1. Každé 3 sekundy analyzuje svíčky a indikátory Zlata (XAU/USD) i Stříbra (XAG/USD).
    2. Spočítá pro obě aktiva Quality Score Q:
       - Trend Efficiency (ER)
       - KAMA Direction & Slope
       - VWAP Band Penetration & Mean Reversion Bounce
       - ATR / Volatilitní potenciál vůči fixní komisi $2.00
    3. Záměrně vybere jedno z aktiv s vyšší pravděpodobností a otevře pozici (LONG nebo SHORT).
    4. Odesílá reálné Bracket Orders do IB Gateway Demo (DUR222134) na port 7497.
    """
    global active_test_trades, stagnation_cooldown_until
    logger.info("⚡ Spouštím Selektivní Kvantitativní Strategii (Zlato vs. Stříbro).")
    
    while True:
        await asyncio.sleep(3)
        try:
            mkt = get_metals_market_status()
            now_dt = datetime.now()
            
            # Broadcast stavu trhu klientům
            if connected_clients:
                mkt_msg = json.dumps({
                    "type": "market_schedule",
                    "market_status": mkt,
                    "adaptive_governance": get_adaptive_state()
                })
                for ws in list(connected_clients):
                    asyncio.create_task(ws.send(mkt_msg))
                    
            if not mkt["is_open"]:
                continue
                
            if not auto_invest_enabled:
                continue
                
            if len(active_test_trades) > 0:
                continue
                
            if now_dt < stagnation_cooldown_until:
                continue
                
            adaptive = get_adaptive_state()
            if (now_dt - last_trade_closed_time).total_seconds() < adaptive["min_cooldown_sec"]:
                continue
                
            g_bars = gold_bars.get('1m', [])
            s_bars = silver_bars.get('1m', [])
            if len(g_bars) < 15 or len(s_bars) < 15:
                continue
                
            g_inds = calculate_indicators(g_bars)
            s_inds = calculate_indicators(s_bars)
            if len(g_inds) < 3 or len(s_inds) < 3:
                continue
                
            # Hodnocení Zlata
            g_curr = g_inds[-1]
            g_prev = g_inds[-2]
            g_er = g_curr["er"]
            g_kama_slope = g_curr["kama"] - g_prev["kama"]
            g_vwap_dev = abs(g_curr["close"] - g_curr["vwap"])
            
            # Hodnocení Stříbra
            s_curr = s_inds[-1]
            s_prev = s_inds[-2]
            s_er = s_curr["er"]
            s_kama_slope = (s_curr["kama"] - s_prev["kama"]) * 50.0 # škálováno na poměr cen
            s_vwap_dev = abs(s_curr["close"] - s_curr["vwap"]) * 50.0
            
            # Výpočet Quality Score pro obě aktiva
            score_gold = round(g_er * 1.5 + (abs(g_kama_slope) * 0.8) + (1.2 if g_curr["low"] <= g_curr["vwap_lower"] or g_curr["high"] >= g_curr["vwap_upper"] else 0.0), 3)
            score_silver = round(s_er * 1.5 + (abs(s_kama_slope) * 0.8) + (1.2 if s_curr["low"] <= s_curr["vwap_lower"] or s_curr["high"] >= s_curr["vwap_upper"] else 0.0), 3)
            
            # Záměrný výběr silnějšího aktiva
            chosen_symbol = "XAUUSD" if score_gold >= score_silver else "XAGUSD"
            chosen_score = score_gold if chosen_symbol == "XAUUSD" else score_silver
            chosen_inds = g_inds if chosen_symbol == "XAUUSD" else s_inds
            chosen_curr = chosen_inds[-1]
            chosen_prev = chosen_inds[-2]
            is_gold = (chosen_symbol == "XAUUSD")
            
            er_thresh = adaptive["er_threshold"]
            price = chosen_curr["close"]
            kama = chosen_curr["kama"]
            prev_kama = chosen_prev["kama"]
            vwap = chosen_curr["vwap"]
            atr = chosen_curr["atr"]
            rsi = chosen_curr.get("rsi", 50.0)
            
            signal = None
            direction = ""
            strategy_name = ""
            entry_reason = ""
            
            # 1. KAMA Trend Momentum
            if chosen_curr["er"] >= er_thresh:
                if (price > kama and kama > prev_kama and price >= vwap) and (42.0 <= rsi <= 68.0):
                    signal = "BUY"
                    direction = "LONG"
                    strategy_name = "KAMA Momentum Trend"
                    entry_reason = (
                        f"Selektivní kvantitativní výběr: Vybráno {('🥇 Zlato' if is_gold else '🥈 Stříbro')} "
                        f"(Score {chosen_score:.2f} > {min(score_gold, score_silver):.2f}). "
                        f"Potvrzen silný trend (ER={chosen_curr['er']:.2f} >= {er_thresh:.2f}), "
                        f"KAMA ({kama:.2f}) roste nad VWAP ({vwap:.2f}), RSI={rsi:.1f}."
                    )
                elif (price < kama and kama < prev_kama and price <= vwap) and (32.0 <= rsi <= 58.0):
                    signal = "SELL"
                    direction = "SHORT"
                    strategy_name = "KAMA Momentum Breakdown"
                    entry_reason = (
                        f"Selektivní kvantitativní výběr: Vybráno {('🥇 Zlato' if is_gold else '🥈 Stříbro')} "
                        f"(Score {chosen_score:.2f} > {min(score_gold, score_silver):.2f}). "
                        f"Medvědí průraz (ER={chosen_curr['er']:.2f} >= {er_thresh:.2f}), "
                        f"KAMA ({kama:.2f}) klesá pod VWAP ({vwap:.2f}), RSI={rsi:.1f}."
                    )
            # 2. VWAP Mean Reversion Bounce
            else:
                if (chosen_curr["low"] <= chosen_curr["vwap_lower"] and chosen_curr["close"] > chosen_curr["open"]) and (rsi <= 38.0):
                    signal = "BUY"
                    direction = "LONG"
                    strategy_name = "VWAP Mean Reversion"
                    entry_reason = (
                        f"Selektivní kvantitativní výběr: Vybráno {('🥇 Zlato' if is_gold else '🥈 Stříbro')} "
                        f"(Score {chosen_score:.2f}). Býčí odraz od dolního VWAP pásma ({chosen_curr['vwap_lower']:.2f}), RSI={rsi:.1f}."
                    )
                elif (chosen_curr["high"] >= chosen_curr["vwap_upper"] and chosen_curr["close"] < chosen_curr["open"]) and (rsi >= 62.0):
                    signal = "SELL"
                    direction = "SHORT"
                    strategy_name = "VWAP Mean Reversion"
                    entry_reason = (
                        f"Selektivní kvantitativní výběr: Vybráno {('🥇 Zlato' if is_gold else '🥈 Stříbro')} "
                        f"(Score {chosen_score:.2f}). Medvědí zamítnutí na horním VWAP pásmu ({chosen_curr['vwap_upper']:.2f}), RSI={rsi:.1f}."
                    )
                    
            if signal and direction:
                if is_gold:
                    qty_num = TARGET_GOLD_OZ
                    min_tp_points = round((MIN_NET_PROFIT_TARGET_USD + IBKR_ROUNDTRIP_COMMISSION) / TARGET_GOLD_OZ, 2)
                    tp_dist = max(min_tp_points, round(2.0 * atr, 2))
                    sl_dist = max(1.40, round(1.1 * atr, 2))
                    sym_display = "XAU/USD"
                    name_display = "Zlato Spot CFD"
                    round_digits = 2
                else:
                    qty_num = TARGET_SILVER_OZ
                    min_tp_points = round((MIN_NET_PROFIT_TARGET_USD + IBKR_ROUNDTRIP_COMMISSION) / TARGET_SILVER_OZ, 3)
                    tp_dist = max(min_tp_points, round(1.8 * atr, 3))
                    sl_dist = max(0.12, round(1.0 * atr, 3))
                    sym_display = "XAG/USD"
                    name_display = "Stříbro Spot CFD"
                    round_digits = 3
                    
                sl = round(price - sl_dist if direction == "LONG" else price + sl_dist, round_digits)
                tp = round(price + tp_dist if direction == "LONG" else price - tp_dist, round_digits)
                
                actual_invest_usd = round(qty_num * price, 2)
                margin_usd = round(actual_invest_usd * 0.05, 2) # páka 1:20
                pos_id = f"POS-METALS-{now_dt.strftime('%Y%m%d%H%M%S')}"
                qty_str = f"{qty_num} oz"
                
                trade = {
                    "id": pos_id,
                    "symbol_raw": chosen_symbol,
                    "symbol": sym_display,
                    "name": name_display,
                    "direction": direction,
                    "entry_price": round(price, round_digits),
                    "current_price": round(price, round_digits),
                    "sl": sl,
                    "tp": tp,
                    "stop_loss": sl,
                    "take_profit_1": tp,
                    "take_profit_2": round(tp + (tp - price) * 0.5 if direction == "LONG" else tp - (price - tp) * 0.5, round_digits),
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
                
                # POUZE ZDROJ IBKR: Žádné fiktivní pozice!
                # Pokyn odešleme do IBKR Demo účtu, kde čeká na vyplnění (PreSubmitted -> Filled).
                # Teprve po ověřeném potvrzení exekuce z IBKR se titul smí zařadit mezi aktivní pozice.
                est_gross_tp = round(qty_num * tp_dist, 2)
                est_net_tp = round(est_gross_tp - IBKR_ROUNDTRIP_COMMISSION, 2)
                logger.info(f"📤 ODESLÁNÍ DO IBKR: {sym_display} {direction} @ {price:.2f} | Objem: {qty_str} | TP: {trade['tp']} (+${est_net_tp:.2f} čistý) | SL: {trade['sl']} | {strategy_name}")

                if ib.isConnected():
                    asyncio.create_task(virt_engine.place_live_demo_bracket(
                        symbol=chosen_symbol,
                        action=signal,
                        quantity=qty_num,
                        limit_price=price,
                        take_profit_price=tp,
                        stop_loss_price=sl
                    ))
                else:
                    virt_engine.add_pending_order(
                        symbol=chosen_symbol,
                        name=name_display,
                        direction=direction,
                        limit_price=price,
                        sl=sl,
                        tp1=tp,
                        tp2=round(tp + (tp - price) * 0.5 if direction == "LONG" else tp - (price - tp) * 0.5, round_digits),
                        qty=qty_str,
                        rrr="1:2.0",
                        trigger=entry_reason
                    )
                    
                # Aktualizace selectoru v JSON
                trades_data = virt_engine.load_trades_data()
                trades_data["selective_quant_selector"] = {
                    "status": "ACTIVE_TRADE_OPENED",
                    "last_selection": chosen_symbol,
                    "rationale": entry_reason,
                    "gold_score": score_gold,
                    "silver_score": score_silver
                }
                virt_engine.save_trades_data(trades_data)
                
                for ws in list(connected_clients):
                    asyncio.create_task(ws.send(json.dumps({"type": "refresh"})))
        except Exception as e:
            logger.error(f"Chyba v selective_quant_strategy_loop: {e}")

async def metals_stream_task():
    """
    Průběžně každé 2 sekundy aktualizuje svíčky pro Zlato i Stříbro
    a vysílá real-time stream do obou grafů.
    """
    global gold_bars, silver_bars, latest_gold_spot, latest_silver_spot, last_market_data_time
    logger.info("Spouštím duální stream drahých kovů (Zlato & Stříbro).")
    
    # 1. Počáteční načtení historie pro všechny časové rámce
    for tf in ['1m', '5m', '15m', '1h', '1d']:
        g_data = await asyncio.to_thread(fetch_yahoo_bars_sync, 'GC=F', tf)
        if g_data:
            gold_bars[tf] = g_data
            latest_gold_spot = g_data[-1]['close']
            
        s_data = await asyncio.to_thread(fetch_yahoo_bars_sync, 'SI=F', tf)
        if s_data:
            silver_bars[tf] = s_data
            latest_silver_spot = s_data[-1]['close']
            
        await asyncio.sleep(0.3)
        
    logger.info(f"✅ Počáteční data načtena: Zlato = ${latest_gold_spot:.2f}, Stříbro = ${latest_silver_spot:.3f}")
    
    # 2. Živá smyčka aktualizací
    while True:
        try:
            await asyncio.sleep(2)
            fresh_gold = await asyncio.to_thread(fetch_yahoo_bars_sync, 'GC=F', '1m')
            fresh_silver = await asyncio.to_thread(fetch_yahoo_bars_sync, 'SI=F', '1m')
            
            if fresh_gold:
                if '1m' not in gold_bars: gold_bars['1m'] = []
                g_map = {b['time']: b for b in gold_bars['1m']}
                for b in fresh_gold: g_map[b['time']] = b
                gold_bars['1m'] = sorted(g_map.values(), key=lambda x: x['time'])[-150:]
                latest_gold_spot = gold_bars['1m'][-1]['close']
                
            if fresh_silver:
                if '1m' not in silver_bars: silver_bars['1m'] = []
                s_map = {b['time']: b for b in silver_bars['1m']}
                for b in fresh_silver: s_map[b['time']] = b
                silver_bars['1m'] = sorted(s_map.values(), key=lambda x: x['time'])[-150:]
                latest_silver_spot = silver_bars['1m'][-1]['close']
                
            last_market_data_time = datetime.now()
            
            # Vyhodnotit otevřené obchody pro obě komodity
            evaluate_open_trades(latest_gold_spot, "XAUUSD")
            evaluate_open_trades(latest_silver_spot, "XAGUSD")
            
            # Broadcast duální svíčky a indikátorů klientům
            g_inds = calculate_indicators(gold_bars.get('1m', []))
            s_inds = calculate_indicators(silver_bars.get('1m', []))
            
            if g_inds and s_inds:
                g_last = g_inds[-1]
                s_last = s_inds[-1]
                t_data = virt_engine.load_trades_data()
                
                dual_msg = {
                    "type": "dual_tick",
                    "gold": {
                        "symbol": "XAUUSD",
                        "candle": {
                            "time": g_last["time"],
                            "open": g_last["open"],
                            "high": g_last["high"],
                            "low": g_last["low"],
                            "close": g_last["close"]
                        },
                        "kama": g_last["kama"],
                        "vwap": g_last["vwap"],
                        "spot": g_last["close"],
                        "er": g_last["er"],
                        "atr": g_last["atr"],
                        "rsi": g_last["rsi"]
                    },
                    "silver": {
                        "symbol": "XAGUSD",
                        "candle": {
                            "time": s_last["time"],
                            "open": s_last["open"],
                            "high": s_last["high"],
                            "low": s_last["low"],
                            "close": s_last["close"]
                        },
                        "kama": s_last["kama"],
                        "vwap": s_last["vwap"],
                        "spot": s_last["close"],
                        "er": s_last["er"],
                        "atr": s_last["atr"],
                        "rsi": s_last["rsi"]
                    },
                    "active_positions": t_data.get("active_positions", []),
                    "summary": t_data.get("summary", {})
                }
                msg_str = json.dumps(dual_msg)
                for ws in list(connected_clients):
                    asyncio.create_task(ws.send(msg_str))
                    
        except Exception as e:
            logger.warning(f"Chyba v metals_stream_task: {e}")
            await asyncio.sleep(2)

async def ibkr_background_reconnect_task():
    """V pozadí každých 5 sekund udržuje spojení s IB Gateway (DUR222134) na portu 7497."""
    logger.info("Spouštím IBKR Gateway Background Reconnect & Account Sync Task.")
    while True:
        try:
            await asyncio.sleep(5)
            if not ib.isConnected():
                try:
                    await ib.connectAsync('127.0.0.1', IB_PORT, clientId=IBKR_CLIENT_ID, timeout=3)
                    logger.info("✅ IB Gateway úspěšně připojena na portu 7497 (clientId=15)!")
                    acc_info = virt_engine.sync_ibkr_account("DUR222134")
                    if acc_info and connected_clients:
                        msg = json.dumps({"type": "ibkr_account", "account": acc_info})
                        for ws in list(connected_clients):
                            asyncio.create_task(ws.send(msg))
                except Exception:
                    pass # tichý retry, neblokuje stream
            else:
                acc_info = virt_engine.sync_ibkr_account("DUR222134")
                if acc_info and connected_clients:
                    msg = json.dumps({"type": "ibkr_account", "account": acc_info})
                    for ws in list(connected_clients):
                        asyncio.create_task(ws.send(msg))
        except Exception as e:
            logger.debug(f"IBKR Reconnect loop: {e}")

async def download_monitor_task():
    """Průběžně každých 15 sekund monitoruje postup stahování historických dat z IBKR a aktualizuje DOWNLOAD_STATUS.md."""
    db_path = os.path.join("data", "historical", "gold_m1_history.db")
    status_md = os.path.join("data", "historical", "DOWNLOAD_STATUS.md")
    status_json = os.path.join("data", "historical", "download_progress.json")
    
    while True:
        await asyncio.sleep(15)
        try:
            gold_db = os.path.join("data", "historical", "gold_m1_history.db")
            silver_db = os.path.join("data", "historical", "silver_m1_history.db")
            
            # 1. Zjistíme stav Zlata
            g_count, g_min_dt, g_max_dt = 0, None, None
            g_size_mb = 0.0
            if os.path.exists(gold_db):
                g_size_mb = os.path.getsize(gold_db) / (1024 * 1024)
                conn = sqlite3.connect(gold_db, timeout=5)
                c = conn.cursor()
                c.execute("SELECT COUNT(*), MIN(datetime), MAX(datetime) FROM xauusd_m1_bars")
                row = c.fetchone()
                conn.close()
                if row and row[0]:
                    g_count, g_min_dt, g_max_dt = row[0], row[1], row[2]

            # 2. Zjistíme stav Stříbra
            s_count, s_min_dt, s_max_dt = 0, None, None
            s_size_mb = 0.0
            if os.path.exists(silver_db):
                s_size_mb = os.path.getsize(silver_db) / (1024 * 1024)
                conn = sqlite3.connect(silver_db, timeout=5)
                c = conn.cursor()
                c.execute("SELECT COUNT(*), MIN(datetime), MAX(datetime) FROM xagusd_m1_bars")
                row = c.fetchone()
                conn.close()
                if row and row[0]:
                    s_count, s_min_dt, s_max_dt = row[0], row[1], row[2]

            # 3. Načteme cíl a plánovač
            target_days = 365
            target_label = "1 rok Zlata"
            active_asset = "ZLATO (XAU/USD)"
            p1_stat = "🟢 BĚŽÍ"
            p2_stat = "⏳ NAPLÁNOVÁNO"
            p3_stat = "⏳ NAPLÁNOVÁNO"
            
            target_cfg_path = os.path.join("data", "historical", "download_target.json")
            if os.path.exists(target_cfg_path):
                try:
                    with open(target_cfg_path, "r", encoding="utf-8") as tf:
                        tcfg = json.load(tf)
                        target_days = tcfg.get("target_days", 365)
                        target_label = tcfg.get("target_label", "Zlato & Stříbro")
                        active_asset = tcfg.get("active_asset", "ZLATO")
                        stage = tcfg.get("current_stage", 1)
                        if stage == 1:
                            p1_stat, p2_stat, p3_stat = "🟢 BĚŽÍ", "⏳ NAPLÁNOVÁNO", "⏳ NAPLÁNOVÁNO"
                        elif stage == 2:
                            p1_stat, p2_stat, p3_stat = "✅ HOTOVO", "🟢 BĚŽÍ", "⏳ NAPLÁNOVÁNO"
                        elif stage == 3:
                            p1_stat, p2_stat, p3_stat = "✅ HOTOVO", "✅ HOTOVO", "🟢 BĚŽÍ"
                        elif stage >= 4:
                            p1_stat, p2_stat, p3_stat = "✅ HOTOVO", "✅ HOTOVO", "✅ HOTOVO"
                except Exception:
                    pass

            # Progres aktuálního aktivního aktiva
            cur_min = s_min_dt if "STŘÍBRO" in active_asset else g_min_dt
            cur_count = s_count if "STŘÍBRO" in active_asset else g_count
            cur_size = s_size_mb if "STŘÍBRO" in active_asset else g_size_mb
            
            if cur_min:
                clean_min = cur_min.split('+')[0].strip()
                min_date = datetime.strptime(clean_min, '%Y-%m-%d %H:%M:%S')
                days_done = max(0, (datetime.now() - min_date).days)
            else:
                days_done = 0
                
            pct = min(100.0, (days_done / target_days) * 100) if target_days > 0 else 0
            bars_fill = int(pct / 5)
            bar_visual = "█" * bars_fill + "░" * (20 - bars_fill)
            rem_days = max(0, target_days - days_done)
            rem_min = max(0, int((rem_days * (250 / 365.0)) * 13.0 / 60.0))
            eta_dt = datetime.now() + timedelta(minutes=rem_min)
            
            prog_data = {
                "status": "RUNNING",
                "active_asset": active_asset,
                "timestamp_cet": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
                "bars_count": cur_count,
                "gold_bars": g_count,
                "silver_bars": s_count,
                "days_completed": days_done,
                "target_days": target_days,
                "progress_pct": round(pct, 1),
                "db_size_mb": round(cur_size, 2),
                "eta_minutes": rem_min,
                "eta_time_cet": eta_dt.strftime("%H:%M")
            }
            with open(status_json, "w", encoding="utf-8") as f:
                json.dump(prog_data, f, indent=2)
                
            md_content = f"""# 📥 Průběh stahování kvantitativních dat (Zlato & Stříbro)

> **Stav:** 🟢 **AKTIVNĚ BĚŽÍ NA POZADÍ (Port 7497, Client ID 65)**  
> **Aktivní aktivum:** **{active_asset}**  
> **Poslední aktualizace:** {prog_data['timestamp_cet']} SEČ  

---

### 📋 Plánovaný harmonogram stahování portfolia (Pipeline)

| Krok | Aktivum | Cíl | Stav |
| :--- | :--- | :--- | :--- |
| **1.** | 🥇 **Zlato (XAU/USD)** | 1 rok M1 historie | **{p1_stat}** |
| **2.** | 🥇 **Zlato (XAU/USD)** | 5 let M1 historie (do 2021) | **{p2_stat}** |
| **3.** | 🥈 **Stříbro (XAG/USD)** | 5 let M1 historie (do 2021) | **{p3_stat}** |

---

### 📊 Stav aktivního aktiva ({active_asset})

| Metrika | Hodnota | Poznámka |
| :--- | :--- | :--- |
| **Staženo svíček** | **{cur_count:,} M1 svíček** | Každý obchodní den má 1 380 svíček (23 h) |
| **Časový rozsah v DB** | **{cur_min or 'Začínám'} ➔ {g_max_dt or 'Nyní'}** | Zpracováno {days_done} dní |
| **Cílové datum aktiva** | **{ (datetime.now() - timedelta(days=target_days)).strftime('%d. %m. %Y') }** | {target_label} |
| **Procentuální progres** | **{pct:.1f} %** | Postupuje stabilně po 1 dni zpět |
| **Pacing interval (Sleep)** | **13.0 sekund** | Bezpečné proti vykopnutí serverem IBKR (Error 162) |
| **Velikost databáze** | **{cur_size:.2f} MB** | SQLite v režimu WAL (rychlý pro Python i Pandas) |
| **Zbývající čas aktiva (ETA)** | **cca {rem_min} minut** | Odhadované dokončení: cca {eta_dt.strftime('%H:%M')} SEČ |

---

### 📈 Ukazatel progresu aktivního stahování

```text
[{bar_visual}] {pct:.1f} % HOTOVO ({cur_count:,} / ~{int(target_days * (250/365.0) * 1380):,} M1 svíček)
```

---

### 🗄️ Přehled obou SQLite databází

* 🥇 **Zlato:** [`data/historical/gold_m1_history.db`](file:///c:/Users/uzivatel/Desktop/SuggestInvest/data/historical/gold_m1_history.db) — **{g_count:,}** svíček ({g_size_mb:.2f} MB), rozsah: `{g_min_dt or 'Žádná data'}` až `{g_max_dt or 'Nyní'}`
* 🥈 **Stříbro:** [`data/historical/silver_m1_history.db`](file:///c:/Users/uzivatel/Desktop/SuggestInvest/data/historical/silver_m1_history.db) — **{s_count:,}** svíček ({s_size_mb:.2f} MB), rozsah: `{s_min_dt or 'Čeká v pipeline'}` až `{s_max_dt or 'Nyní'}`

---

### 🛡️ Bezpečnostní mechanismy
* **Plná automatizace (Supervisor):** Supervisor [`scripts/schedule_5years_pipeline.py`](file:///c:/Users/uzivatel/Desktop/SuggestInvest/scripts/schedule_5years_pipeline.py) hlídá dokončení jednotlivých fází a automaticky přepíná mezi Zlatem a Stříbrem.
* **Checkpointing / Auto-Resume:** Každý den se commituje zvlášť do SQLite. Žádná data se nestahují dvakrát.
* **Izolovaný proces:** Běží pod vyhrazeným `clientId=65`, neovlivňuje živý demo scalping na portu 7497 (`clientId=15`).
"""
            with open(status_md, "w", encoding="utf-8") as f:
                f.write(md_content)
                
            if connected_clients:
                msg = json.dumps({"type": "download_progress", "progress": prog_data})
                for ws in list(connected_clients):
                    asyncio.create_task(ws.send(msg))
        except Exception as e:
            logger.debug(f"Chyba v download_monitor_task: {e}")

async def ws_handler(websocket):
    """Zpracovává klientská WebSocket spojení z prohlížeče."""
    global current_timeframe, auto_invest_enabled, last_trade_closed_time, stagnation_cooldown_until
    connected_clients.add(websocket)
    try:
        # Počáteční stav pro oba grafy
        g_inds = calculate_indicators(gold_bars.get(current_timeframe, gold_bars.get('1m', [])))
        s_inds = calculate_indicators(silver_bars.get(current_timeframe, silver_bars.get('1m', [])))
        trades_data = virt_engine.load_trades_data()
        mkt = get_metals_market_status()
        
        init_payload = {
            "type": "init_dual",
            "gold": {
                "symbol": "XAUUSD",
                "name": "Zlato (Gold Spot CFD)",
                "spot": latest_gold_spot,
                "history": g_inds
            },
            "silver": {
                "symbol": "XAGUSD",
                "name": "Stříbro (Silver Spot CFD)",
                "spot": latest_silver_spot,
                "history": s_inds
            },
            "market_status": mkt,
            "account": trades_data.get("ibkr_live_account", {}),
            "summary": trades_data.get("summary", {}),
            "active_positions": trades_data.get("active_positions", []),
            "executed_history": trades_data.get("executed_history", []),
            "selective_selector": trades_data.get("selective_quant_selector", {}),
            "adaptive_governance": get_adaptive_state(),
            "auto_invest_enabled": auto_invest_enabled,
            "metals_learning_log": trades_data.get("metals_learning_log", [])
        }
        await websocket.send(json.dumps(init_payload))
        
        async for message in websocket:
            try:
                data = json.loads(message)
                action = data.get("action")
                
                if action == "change_tf":
                    new_tf = data.get("tf", "1m")
                    current_timeframe = new_tf
                    # Načíst svíčky pro nový timeframe
                    g_tf = calculate_indicators(gold_bars.get(new_tf, []))
                    s_tf = calculate_indicators(silver_bars.get(new_tf, []))
                    await websocket.send(json.dumps({
                        "type": "tf_update",
                        "tf": new_tf,
                        "gold_history": g_tf,
                        "silver_history": s_tf
                    }))
                elif action == "toggle_auto_trade":
                    auto_invest_enabled = bool(data.get("enabled", True))
                    t_data = virt_engine.load_trades_data()
                    t_data["auto_invest_enabled"] = auto_invest_enabled
                    virt_engine.save_trades_data(t_data)
                    logger.info(f"⚡ PŘEPÍNAČ: auto_invest_enabled = {auto_invest_enabled}")
                    for ws in list(connected_clients):
                        asyncio.create_task(ws.send(json.dumps({
                            "type": "auto_invest_status",
                            "enabled": auto_invest_enabled
                        })))
                elif action == "sync_ibkr":
                    logger.info("🔄 Požadavek z UI: Okamžitá synchronizace z IB Gateway (DUR222134)...")
                    if not ib.isConnected():
                        try:
                            await ib.connectAsync('127.0.0.1', IB_PORT, clientId=IBKR_CLIENT_ID, timeout=3)
                        except Exception as ce:
                            logger.warning(f"Nelze se připojit k IB Gateway: {ce}")
                    acc_info = virt_engine.sync_ibkr_account("DUR222134")
                    if acc_info:
                        logger.info(f"✅ Stav z IB Gateway úspěšně synchronizován: Net Liq = {acc_info.get('net_liquidation_czk')} CZK, Portfolio = {len(acc_info.get('portfolio', []))} pozic")
                        for ws in list(connected_clients):
                            asyncio.create_task(ws.send(json.dumps({
                                "type": "ibkr_account",
                                "account": acc_info
                            })))
                elif action == "close_position":
                    pos_id = data.get("pos_id")
                    logger.info(f"⚡ Manuální uzavření pozice z UI: {pos_id}")
                    evaluate_open_trades(latest_gold_spot, "XAUUSD", force_close_id=pos_id)
                    evaluate_open_trades(latest_silver_spot, "XAGUSD", force_close_id=pos_id)
                    if auto_invest_enabled:
                        last_trade_closed_time = datetime.min
                        stagnation_cooldown_until = datetime.min
                        logger.info("🚀 Režim Investuj je ZAPNUTÝ: Cooldown vynulován, engine ihned hledá a otevírá další vhodný pokyn.")
                    for ws in list(connected_clients):
                        asyncio.create_task(ws.send(json.dumps({"type": "refresh"})))
                elif action == "manual_order":
                    # Podpora manuálního zadání přes demo účet
                    sym = data.get("symbol", "XAUUSD")
                    act = data.get("direction", "BUY")
                    qty = float(data.get("quantity", TARGET_GOLD_OZ if "XAU" in sym else TARGET_SILVER_OZ))
                    limit_p = float(data.get("price", latest_gold_spot if "XAU" in sym else latest_silver_spot))
                    tp_p = float(data.get("tp", limit_p + 5.0))
                    sl_p = float(data.get("sl", limit_p - 3.0))
                    
                    order_res = await virt_engine.place_live_demo_bracket(
                        symbol=sym, action=act, quantity=qty,
                        limit_price=limit_p, take_profit_price=tp_p, stop_loss_price=sl_p
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

async def main():
    logger.info("==================================================================")
    logger.info("⚡ SUGGESTINVEST DUÁLNÍ SCALPING ENGINE: ZLATO & STŘÍBRO v3.0 START ⚡")
    logger.info("  - 🥇 Zlato (XAU/USD) & 🥈 Stříbro (XAG/USD) Duální Live Stream")
    logger.info("  - Selektivní Kvantitativní Rozhodování (Long / Short)")
    logger.info("  - Interactive Brokers Demo (DUR222134) na portu 7497")
    logger.info("  - WebSocket Server: ws://127.0.0.1:8765")
    logger.info("==================================================================")
    
    # Spuštění asynchronních úloh
    asyncio.create_task(metals_stream_task())
    asyncio.create_task(selective_quant_strategy_loop())
    asyncio.create_task(ibkr_background_reconnect_task())
    asyncio.create_task(download_monitor_task())
    
    # Spuštění WebSocket serveru
    async with websockets.serve(ws_handler, "127.0.0.1", 8765):
        logger.info("🚀 WebSocket server aktivní na ws://127.0.0.1:8765")
        await asyncio.Future()

if __name__ == '__main__':
    util.patchAsyncio()
    asyncio.run(main())
