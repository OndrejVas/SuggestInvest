import os
import json
import time
import logging
from datetime import datetime, date, timezone
from typing import Dict, Any, List, Optional
import concurrent.futures
import yfinance as yf

logger = logging.getLogger("FundamentalsFetcher")

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache_fundamentals.json")
CACHE_TTL_SECONDS = 24 * 3600  # 24 hodin


def load_fundamentals_cache() -> Dict[str, Any]:
    """Načte diskovou mezipaměť fundamentálních dat a kalendářů."""
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Chyba při čtení {CACHE_FILE}: {e}")
        return {}


def save_fundamentals_cache(cache: Dict[str, Any]) -> None:
    """Uloží mezipaměť fundamentálních dat do JSON souboru."""
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Chyba při zápisu do {CACHE_FILE}: {e}")


def _parse_date(val: Any) -> Optional[date]:
    """Převede různé formáty data z yfinance na standardní datetime.date."""
    if val is None:
        return None
    if isinstance(val, (datetime, date)):
        return val.date() if isinstance(val, datetime) else val
    if isinstance(val, list) and len(val) > 0:
        return _parse_date(val[0])
    if isinstance(val, (int, float)):
        # UNIX timestamp v sekundách
        try:
            return datetime.fromtimestamp(val, timezone.utc).date()
        except Exception:
            return None
    if isinstance(val, str):
        try:
            return datetime.strptime(val.strip(), "%Y-%m-%d").date()
        except Exception:
            pass
    return None


def fetch_single_ticker_fundamentals(yahoo_sym: str, asset_type: str = "AKCIE") -> Dict[str, Any]:
    """
    Získá cílové ceny analytiků a kalendářní události (výsledky, dividendy) pro daný ticker.
    Pro ETF a KRYPTO okamžitě vrací prázdnou strukturu bez zbytečných dotazů.
    """
    empty_result = {
        "target_mean": None,
        "target_high": None,
        "target_low": None,
        "target_median": None,
        "analysts_count": None,
        "recommendation_key": None,
        "next_earnings_date": None,
        "days_to_earnings": None,
        "ex_dividend_date": None,
        "days_to_ex_dividend": None,
        "timestamp": time.time(),
    }

    if asset_type.upper() in ["ETF", "KRYPTO"]:
        return empty_result

    today = date.today()
    try:
        t = yf.Ticker(yahoo_sym)

        # 1. Cílové ceny analytiků
        target_mean = None
        target_high = None
        target_low = None
        target_median = None
        analysts_count = None
        rec_key = None

        targets = getattr(t, "analyst_price_targets", None)
        if isinstance(targets, dict) and targets:
            target_mean = targets.get("mean")
            target_high = targets.get("high")
            target_low = targets.get("low")
            target_median = targets.get("median")

        # 2. Kalendář událostí (Earnings & Ex-Dividend)
        next_earnings_str = None
        days_to_earnings = None
        earnings_time = None
        ex_div_str = None
        days_to_ex_div = None

        cal = getattr(t, "calendar", None)
        if isinstance(cal, dict) and cal:
            # Earnings Date & Time
            ed_raw = cal.get("Earnings Date")
            ed = _parse_date(ed_raw)
            if ed:
                delta = (ed - today).days
                # Povolíme budoucí události nebo dnešní (delta >= 0)
                if delta >= 0:
                    next_earnings_str = ed.strftime("%d. %m. %Y")
                    days_to_earnings = delta
                    earnings_time = cal.get("Earnings Call Time") or cal.get("Earnings Time") or "BMO"

            # Ex-Dividend Date
            exd_raw = cal.get("Ex-Dividend Date")
            exd = _parse_date(exd_raw)
            if exd:
                delta_ex = (exd - today).days
                if delta_ex >= 0:
                    ex_div_str = exd.strftime("%d. %m. %Y")
                    days_to_ex_div = delta_ex

        # 3. Doplňková data z fast_info / info (pokud chybí počet analytiků)
        if target_mean is not None and analysts_count is None:
            try:
                info = getattr(t, "info", None)
                if isinstance(info, dict):
                    analysts_count = info.get("numberOfAnalystOpinions")
                    rec_key = info.get("recommendationKey")
            except Exception:
                pass

        return {
            "target_mean": float(target_mean) if target_mean is not None else None,
            "target_high": float(target_high) if target_high is not None else None,
            "target_low": float(target_low) if target_low is not None else None,
            "target_median": float(target_median) if target_median is not None else None,
            "analysts_count": int(analysts_count) if analysts_count is not None else None,
            "recommendation_key": rec_key,
            "next_earnings_date": next_earnings_str,
            "days_to_earnings": days_to_earnings,
            "earnings_time": earnings_time,
            "ex_dividend_date": ex_div_str,
            "days_to_ex_dividend": days_to_ex_div,
            "timestamp": time.time(),
        }
    except Exception as e:
        logger.debug(f"Chyba při stahování fundamentů pro {yahoo_sym}: {e}")
        return empty_result


def get_universe_fundamentals(universe_items: List[Dict[str, Any]], max_workers: int = 20) -> Dict[str, Dict[str, Any]]:
    """
    Získá fundamentální data a kalendář pro celé univerzum s využitím diskové mezipaměti.
    Dotazuje se pouze na chybějící nebo zastaralé záznamy (> 24 hodin).
    """
    cache = load_fundamentals_cache()
    now = time.time()
    results: Dict[str, Dict[str, Any]] = {}
    to_fetch: List[Dict[str, Any]] = []

    for item in universe_items:
        sym = item["yahoo_symbol"]
        atype = item.get("asset_type", "AKCIE")
        cached = cache.get(sym)

        # Kontrola platnosti cache
        if cached and (now - cached.get("timestamp", 0) < CACHE_TTL_SECONDS):
            results[sym] = cached
        elif atype in ["ETF", "KRYPTO"]:
            # Pro ETF a krypto není potřeba volat API
            res = {
                "target_mean": None,
                "target_high": None,
                "target_low": None,
                "target_median": None,
                "analysts_count": None,
                "recommendation_key": None,
                "next_earnings_date": None,
                "days_to_earnings": None,
                "ex_dividend_date": None,
                "days_to_ex_dividend": None,
                "timestamp": now,
            }
            results[sym] = res
            cache[sym] = res
        else:
            to_fetch.append(item)

    if to_fetch:
        logger.info(f"Stahuji předstihová data pro {len(to_fetch)} akcií (cache pokryla {len(results)} aktiv)...")

        def _worker(it):
            sym = it["yahoo_symbol"]
            data = fetch_single_ticker_fundamentals(sym, it.get("asset_type", "AKCIE"))
            return sym, data

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            fetched_pairs = list(executor.map(_worker, to_fetch))

        for sym, data in fetched_pairs:
            results[sym] = data
            cache[sym] = data

        save_fundamentals_cache(cache)
        logger.info(f"Předstihová data úspěšně uložena do mezipaměti ({len(to_fetch)} nových záznamů).")
    else:
        logger.info(f"Všech {len(universe_items)} aktiv bylo bleskově načteno z lokální mezipaměti!")

    return results


import numpy as np


def fetch_momentum_deltas(universe_items: List[Dict[str, Any]], batch_size: int = 80) -> Dict[str, Dict[str, Optional[float]]]:
    """
    Vypočítá 1M/3M momentum, 21denní realizovanou volatilitu (RV21), 14denní ATR,
    objemový šok (LiMT Z-score) a kvantilová exekuční pásma pomocí efektivního dávkového yf.download.
    """
    all_symbols = [item["yahoo_symbol"] for item in universe_items]
    deltas: Dict[str, Dict[str, Optional[float]]] = {}

    # Inicializace výchozími hodnotami
    for sym in all_symbols:
        deltas[sym] = {
            "delta_1m": None,
            "delta_3m": None,
            "rv_21": None,
            "atr_14": None,
            "atr_pct": None,
            "volume_shock_z": None,
            "daily_turnover": None,
            "limit_buy_price": None,
            "quant_invalidation_price": None,
        }

    logger.info(f"Počítám momentum a kvantitativní metriky (RV21, ATR, Volume Shock) pro {len(all_symbols)} aktiv...")

    chunks = [all_symbols[i:i + batch_size] for i in range(0, len(all_symbols), batch_size)]

    for chunk in chunks:
        try:
            df = yf.download(chunk, period="3mo", interval="1d", progress=False, auto_adjust=True)
            if df.empty:
                continue

            closes = df.get("Close")
            highs = df.get("High")
            lows = df.get("Low")
            vols = df.get("Volume")
            if closes is None:
                continue

            for sym in chunk:
                try:
                    # Extrakce cenových řad pro ticker (podpora MultiIndex i SingleIndex)
                    if sym in closes.columns:
                        series = closes[sym].dropna()
                        h_series = highs[sym].dropna() if highs is not None and sym in highs.columns else None
                        l_series = lows[sym].dropna() if lows is not None and sym in lows.columns else None
                        v_series = vols[sym].dropna() if vols is not None and sym in vols.columns else None
                    elif len(chunk) == 1 and not closes.empty:
                        series = closes.dropna()
                        h_series = highs.dropna() if highs is not None else None
                        l_series = lows.dropna() if lows is not None else None
                        v_series = vols.dropna() if vols is not None else None
                    else:
                        continue

                    n = len(series)
                    if n < 5:
                        continue

                    curr_price = float(series.iloc[-1])
                    if curr_price <= 0:
                        continue

                    # 1. 1M delta (~21 obchodních dnů)
                    idx_1m = max(0, n - 22)
                    price_1m = float(series.iloc[idx_1m])
                    delta_1m = ((curr_price - price_1m) / price_1m) * 100 if price_1m > 0 else None

                    # 2. 3M delta (~63 obchodních dnů nebo první dostupný den v 3M periodě)
                    price_3m = float(series.iloc[0])
                    delta_3m = ((curr_price - price_3m) / price_3m) * 100 if price_3m > 0 else None

                    # 3. 21denní realizovaná volatilita (RV21) dle SRC-4
                    ret_21 = np.diff(np.log(series.iloc[-min(22, n):].values))
                    rv_21 = float(np.sqrt(np.sum(ret_21**2) * (252.0 / len(ret_21)))) if len(ret_21) > 2 else 0.25

                    # 4. 14denní Average True Range (ATR14)
                    if h_series is not None and l_series is not None and len(h_series) >= 15:
                        h = h_series.iloc[-14:].values
                        l = l_series.iloc[-14:].values
                        c_prev = series.iloc[-15:-1].values
                        tr = np.maximum(h - l, np.maximum(np.abs(h - c_prev), np.abs(l - c_prev)))
                        atr_14 = float(np.mean(tr))
                    else:
                        atr_14 = float(curr_price * (rv_21 / np.sqrt(252.0)))

                    atr_pct = float((atr_14 / curr_price) * 100) if curr_price > 0 else 2.0

                    # 5. Objemový šok Z-skóre (LiMT Model - SRC-2)
                    vol_z = 0.0
                    daily_turnover = 0.0
                    if v_series is not None and len(v_series) >= 6:
                        v_curr = float(v_series.iloc[-1])
                        v_hist = v_series.iloc[-6:-1].values
                        daily_turnover = float(curr_price * v_curr)
                        if v_curr > 0 and np.mean(v_hist) > 0:
                            vol_z = float(np.log(v_curr + 1) - np.mean(np.log(v_hist + 1)))

                    # 6. Dynamická hladina zneplatnění teze (Diffusion IVS VaR99% Stop-Loss - SRC-4)
                    inv_loss_pct = max(0.035, min(0.15, max(1.5 * (atr_14 / curr_price), 2.33 * rv_21 * np.sqrt(5.0 / 252.0))))
                    quant_invalidation_price = round(curr_price * (1.0 - inv_loss_pct), 2)

                    # 7. Kvantilové pásmo limitního nákupu Q0.1 (OrderFusion+ - SRC-3)
                    limit_buy_price = round(curr_price - 0.45 * atr_14, 2)
                    if limit_buy_price >= curr_price:
                        limit_buy_price = round(curr_price * 0.995, 2)

                    deltas[sym] = {
                        "delta_1m": round(delta_1m, 2) if delta_1m is not None else None,
                        "delta_3m": round(delta_3m, 2) if delta_3m is not None else None,
                        "rv_21": round(rv_21 * 100, 1),
                        "atr_14": round(atr_14, 2),
                        "atr_pct": round(atr_pct, 1),
                        "volume_shock_z": round(vol_z, 2),
                        "daily_turnover": round(daily_turnover, 0),
                        "limit_buy_price": limit_buy_price,
                        "quant_invalidation_price": quant_invalidation_price,
                    }
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"Chyba při dávkovém stažení historie: {e}")

    logger.info("Momentum delty a kvantitativní metriky úspěšně spočteny.")
    return deltas

