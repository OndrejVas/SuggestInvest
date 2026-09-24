"""
dividend_analyzer.py
====================
Modul pro kvantitativní analýzu dividendového chování akcie (Dividend Capture & Post-Ex-Date Price Recovery).
Analyzuje historické Ex-Dividend dny u daného titulu a vyhodnocuje:
1. Dividend Drop-Off Ratio (DDR) – jak efektivně kurz absorboval dividendu
2. Pre-Ex Run-up Momentum – průměrný růst kurzu 20 dní před Ex-Date
3. Recovery Velocity (T_rec) – za kolik obchodních dní kurz smazal dividendový gap a vrátil se na cum-dividend cenu
4. Doporučenou strategii:
   - 🟢 DRŽET PŘES EX-DIV (CAPTURE) – vysoká pravděpodobnost rychlého zotavení kurzu
   - 🟡 PRODAT PŘED EX-DIV (HARVEST) – silný předexový růst a dlouhá povolební/povýsledková kocovina
   - ⚪ NEUTRÁLNÍ (BĚŽNÝ PRŮBĚH) – běžná fluktuace bez asymetrické výhody
"""

import os
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List
import pandas as pd
import numpy as np
import yfinance as yf

logger = logging.getLogger(__name__)

CACHE_FILE = os.path.join(os.path.dirname(__file__), "data", "dividend_cache.json")
CACHE_TTL_DAYS = 7


def _load_cache() -> Dict[str, Any]:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Chyba při čtení dividend_cache.json: %s", e)
    return {}


def _save_cache(cache: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("Chyba při zápisu dividend_cache.json: %s", e)


def analyze_ticker_dividend_history(symbol: str, max_events: int = 6) -> Optional[Dict[str, Any]]:
    """
    Analyzuje posledních max_events historických Ex-Dates pro daný Yahoo symbol.
    Vrací slovník s metrikami a doporučením, nebo None, pokud titul nemá dividendovou historii.
    """
    cache = _load_cache()
    now_ts = datetime.now(timezone.utc).timestamp()

    if symbol in cache:
        item = cache[symbol]
        if now_ts - item.get("cached_at", 0) < CACHE_TTL_DAYS * 86400:
            return item.get("data")

    try:
        ticker = yf.Ticker(symbol)
        divs = ticker.dividends
        if divs is None or len(divs) == 0:
            cache[symbol] = {"cached_at": now_ts, "data": None}
            _save_cache(cache)
            return None

        # Odstranění nulových dividend a seřazení od nejnovějších
        divs = divs[divs > 0].sort_index(ascending=False)
        if len(divs) == 0:
            cache[symbol] = {"cached_at": now_ts, "data": None}
            _save_cache(cache)
            return None

        # Vybereme posledních max_events dividend (vynecháme budoucí/dnešní, pokud ještě nemají historii)
        now_dt = pd.Timestamp.now(tz=divs.index.tz if divs.index.tz is not None else None)
        past_divs = divs[divs.index < now_dt]
        if len(past_divs) == 0:
            cache[symbol] = {"cached_at": now_ts, "data": None}
            _save_cache(cache)
            return None

        target_divs = past_divs.head(max_events)
        earliest_ex = target_divs.index.min() - pd.Timedelta(days=45)
        latest_ex = target_divs.index.max() + pd.Timedelta(days=50)

        # Stáhneme neupravené historické ceny
        hist = ticker.history(start=earliest_ex.strftime("%Y-%m-%d"), 
                              end=latest_ex.strftime("%Y-%m-%d"), 
                              auto_adjust=False)
        if hist is None or hist.empty or len(hist) < 30:
            cache[symbol] = {"cached_at": now_ts, "data": None}
            _save_cache(cache)
            return None

        # Normalizujeme časové zóny na prostá data (bez tz) pro snadné porovnávání indexů
        hist.index = pd.to_datetime(hist.index).tz_localize(None)

        events_data: List[Dict[str, Any]] = []

        for ex_dt_orig, div_amt in target_divs.items():
            ex_dt = pd.to_datetime(ex_dt_orig).tz_localize(None)
            div_val = float(div_amt)

            # Najdeme index dne Ex-Date nebo nejbližšího následujícího obchodního dne
            ex_matches = hist.index[hist.index >= ex_dt]
            if len(ex_matches) == 0:
                continue
            ex_date_actual = ex_matches[0]
            ex_idx = hist.index.get_loc(ex_date_actual)

            # Den před Ex-Date (cum-dividend)
            if ex_idx < 1:
                continue
            cum_idx = ex_idx - 1
            cum_close = float(hist["Close"].iloc[cum_idx])
            if cum_close <= 0:
                continue

            ex_open = float(hist["Open"].iloc[ex_idx])
            ex_close = float(hist["Close"].iloc[ex_idx])

            # 1. Dividend yield na Ex-Date
            div_yield_pct = round((div_val / cum_close) * 100, 2)

            # 2. Drop-off ratio
            drop_amount = cum_close - ex_close
            drop_off_ratio = round(drop_amount / div_val, 2) if div_val > 0 else 1.0

            # 3. Pre-ex run-up (20 obchodních dní před ex-date)
            pre_20_idx = max(0, cum_idx - 20)
            pre_20_close = float(hist["Close"].iloc[pre_20_idx])
            runup_pct = round(((cum_close - pre_20_close) / pre_20_close) * 100, 2) if pre_20_close > 0 else 0.0

            # 4. Post-ex recovery (zkoumáme následujících až 30 obchodních dní)
            post_window = hist["Close"].iloc[ex_idx:ex_idx + 31]
            # Zjišťujeme, zda a kdy kurz dosáhl cum_close
            recovered = False
            recovery_days = None

            for day_offset, close_p in enumerate(post_window):
                if float(close_p) >= cum_close:
                    recovered = True
                    recovery_days = day_offset # 0 znamená hned v den Ex-Date, 1 další den atd.
                    break

            events_data.append({
                "ex_date": ex_dt.strftime("%Y-%m-%d"),
                "dividend": div_val,
                "cum_close": round(cum_close, 2),
                "ex_close": round(ex_close, 2),
                "div_yield_pct": div_yield_pct,
                "drop_off_ratio": drop_off_ratio,
                "runup_20d_pct": runup_pct,
                "recovered_in_30d": recovered,
                "recovered_in_15d": recovered and (recovery_days is not None and recovery_days <= 15),
                "recovery_days": recovery_days
            })

        if not events_data:
            cache[symbol] = {"cached_at": now_ts, "data": None}
            _save_cache(cache)
            return None

        # Agregace statistik
        total_events = len(events_data)
        recovered_15d_count = sum(1 for e in events_data if e["recovered_in_15d"])
        recovered_30d_count = sum(1 for e in events_data if e["recovered_in_30d"])
        recovery_rate_15d = round((recovered_15d_count / total_events) * 100, 1)
        recovery_rate_30d = round((recovered_30d_count / total_events) * 100, 1)

        valid_days = [e["recovery_days"] for e in events_data if e["recovery_days"] is not None]
        median_days = int(np.median(valid_days)) if valid_days else None

        avg_runup = round(float(np.mean([e["runup_20d_pct"] for e in events_data])), 1)
        avg_yield = round(float(np.mean([e["div_yield_pct"] for e in events_data])), 2)
        avg_drop_ratio = round(float(np.mean([e["drop_off_ratio"] for e in events_data])), 2)

        # Rozhodovací matice (Decision Strategy)
        is_capture = (
            recovery_rate_15d >= 65.0 
            and (median_days is not None and median_days <= 15)
        )
        is_harvest = (
            avg_runup >= 1.5 
            and avg_runup >= (avg_yield * 0.7) 
            and recovery_rate_15d <= 40.0
        )

        if is_capture:
            rec_code = "CAPTURE"
            rec_badge = "🟢 Držet přes Ex-Div (Rychlé zotavení)"
            rec_color = "success"
            rec_summary = (
                f"V {recovery_rate_15d:.0f} % případů titul smazal dividendový gap do 15 dní "
                f"(medián zotavení: {median_days or '—'} dní). Kurz vykazuje silný nákupní polštář "
                f"a historicky se vyplatí pozici držet přes Ex-Date a inkasovat dividendu."
            )
        elif is_harvest:
            rec_code = "HARVEST"
            rec_badge = "🟡 Prodat před Ex-Div (Vybrat zisk)"
            rec_color = "warning"
            rec_summary = (
                f"Před Ex-Date titul průměrně posiluje o {avg_runup:+.1f} % (předexový run-up), ale po Ex-Date "
                f"je zotavení pomalé (pouze v {recovery_rate_15d:.0f} % případů smazáno do 15 dní). "
                f"Historická data favorizují realizaci kapitálového zisku před Ex-Date bez srážkové daně."
            )
        else:
            rec_code = "NEUTRAL"
            rec_badge = "⚪ Běžný průběh (Neutrální)"
            rec_color = "neutral"
            rec_summary = (
                f"Zotavení do 15 dní nastalo v {recovery_rate_15d:.0f} % případů (medián: {median_days or '—'} dní). "
                f"Průměrný run-up před Ex-Date činil {avg_runup:+.1f} %. Chování nevykazuje jednoznačnou statistickou anomálii."
            )

        res = {
            "events_count": total_events,
            "avg_div_yield_pct": avg_yield,
            "avg_pre_ex_runup_pct": avg_runup,
            "avg_drop_off_ratio": avg_drop_ratio,
            "recovery_rate_15d_pct": recovery_rate_15d,
            "recovery_rate_30d_pct": recovery_rate_30d,
            "median_recovery_days": median_days,
            "recommendation_code": rec_code,
            "recommendation_badge": rec_badge,
            "recommendation_color": rec_color,
            "recommendation_summary": rec_summary,
            "recent_events": events_data[:4]
        }

        cache[symbol] = {"cached_at": now_ts, "data": res}
        _save_cache(cache)
        return res

    except Exception as e:
        logger.error("Chyba při dividendové analýze symbolu %s: %s", symbol, e)
        cache[symbol] = {"cached_at": now_ts, "data": None}
        _save_cache(cache)
        return None
