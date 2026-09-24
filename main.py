import os
import sys
import json
import re
import logging
import concurrent.futures
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Tuple, Optional

from dotenv import load_dotenv
import feedparser
from bs4 import BeautifulSoup
import yfinance as yf
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, Field

from universe import get_all_universe, TIER_1_TOP, TIER_2_MID, TIER_3_LOW
from fundamentals_fetcher import get_universe_fundamentals, fetch_momentum_deltas
from trigger_engine import evaluate_asset_triggers
from history_manager import save_scan_history, get_ticker_signal_history

# Automatické načtení proměnných z .env
load_dotenv()

# Zajištění UTF-8 na Windows konzoli
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Konfigurace logování
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("MarketScanner")

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
RSS_FEED_URL = "https://finance.yahoo.com/news/rssindex"


# Pydantic schémata pro zaručení validního JSONu z Gemini s předstihovými indikátory
class TickerSignalItem(BaseModel):
    ticker: str = Field(description="Symbol aktiva (např. NVDA, AAPL, CEZ.PR)")
    signal: str = Field(description="Signál: Strong Buy, Buy, Hold, Sell, nebo Strong Sell")
    probability: int = Field(description="Míra konfidence 0 až 100", ge=0, le=100)
    impact_direction: str = Field(description="Očekávaný směr: 'up' nebo 'down'")
    time_horizon: str = Field(default="1-3 měsíce", description="Doporučený horizont: '1-4 týdny' (před earnings) nebo '1-3 měsíce' nebo '6-12 měsíců'")
    catalyst_event: str = Field(default="Standardní tržní vývoj", description="Klíčová budoucí událost či katalyzátor, např. 'Kvartální výsledky', 'Analytický diskont', 'Ex-Dividenda' či 'Konsolidace'")
    reasoning: str = Field(description="Stručné a věcné odůvodnění v češtině, maximálně 3 věty. Zohledni technické, kalendářní a analytické faktory.")


class MarketSignalsContainer(BaseModel):
    signals: List[TickerSignalItem]


def fetch_rss_market_headlines(max_items: int = 6) -> List[str]:
    """Stáhne a vyčistí aktuální globální zprávy z RSS feedu."""
    headlines = []
    try:
        logger.info(f"Stahuji zprávy z RSS feedu: {RSS_FEED_URL}")
        feed = feedparser.parse(RSS_FEED_URL)
        for entry in feed.entries[:max_items]:
            title = entry.get("title", "").strip()
            summary_raw = entry.get("summary", "")
            summary_clean = BeautifulSoup(summary_raw, "html.parser").get_text().strip() if summary_raw else ""
            if title:
                item_text = f"{title}" + (f" - {summary_clean[:120]}..." if summary_clean else "")
                headlines.append(item_text)
        logger.info(f"Úspěšně staženo {len(headlines)} zpráv z RSS.")
    except Exception as e:
        logger.warning(f"Chyba při stahování RSS feedu: {e}")
    return headlines


def _fetch_single_ticker_data(item: Dict[str, Any]) -> Dict[str, Any]:
    """Stáhne tržní data pro jeden ticker (spouštěno paralelně ve vláknech)."""
    yahoo_sym = item["yahoo_symbol"]
    try:
        t = yf.Ticker(yahoo_sym)
        fast_info = getattr(t, "fast_info", None)
        
        price = getattr(fast_info, "last_price", None) if fast_info else None
        prev_close = getattr(fast_info, "previous_close", None) if fast_info else None
        year_high = getattr(fast_info, "year_high", None) if fast_info else None
        year_low = getattr(fast_info, "year_low", None) if fast_info else None
        fifty_day_average = getattr(fast_info, "fifty_day_average", None) if fast_info else None
        two_hundred_day_average = getattr(fast_info, "two_hundred_day_average", None) if fast_info else None

        # Fallback na 5denní historii, pokud fast_info selže
        if price is None:
            hist = t.history(period="5d")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
                if len(hist) > 1:
                    prev_close = float(hist["Close"].iloc[-2])

        if price is not None and prev_close is not None and prev_close != 0:
            change_pct = ((price - prev_close) / prev_close) * 100
            change_val = price - prev_close
        else:
            change_pct = 0.0
            change_val = 0.0

        res = dict(item)
        res["price"] = price if price is not None else 0.0
        res["prev_close"] = prev_close if prev_close is not None else 0.0
        res["change_pct"] = change_pct
        res["change_val"] = change_val
        res["year_high"] = year_high
        res["year_low"] = year_low
        res["fifty_day_average"] = fifty_day_average
        res["two_hundred_day_average"] = two_hundred_day_average
        return res
    except Exception as e:
        logger.debug(f"Chyba při stahování {yahoo_sym}: {e}")
        res = dict(item)
        res["price"] = 0.0
        res["prev_close"] = 0.0
        res["change_pct"] = 0.0
        res["change_val"] = 0.0
        res["year_high"] = None
        res["year_low"] = None
        res["fifty_day_average"] = None
        res["two_hundred_day_average"] = None
        return res


def fetch_universe_market_data(universe_items: List[Dict[str, Any]], max_workers: int = 20) -> List[Dict[str, Any]]:
    """Paralelně stáhne kurzy pro všechny tickery z univerza."""
    logger.info(f"Paralelně stahuji tržní data pro {len(universe_items)} aktiv ({max_workers} vláken)...")
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(_fetch_single_ticker_data, universe_items))
    logger.info(f"Tržní data úspěšně stažena ({len(results)} aktiv).")
    return results


def _call_gemini_batch(client, model_name: str, batch_items: List[Dict[str, Any]], global_news: List[str]) -> List[Dict[str, Any]]:
    """Zavolá Gemini API pro jednu dávku tickerů včetně předstihových indikátorů."""
    from google.genai import types

    data_summary = []
    for item in batch_items:
        data_summary.append({
            "ticker": item["yahoo_symbol"],
            "name": item["name"],
            "price": f"{item['price']:.2f} {item['currency']}",
            "day_change": f"{item['change_pct']:+.2f}%",
            "forward_indicators": item.get("ai_forward_context", "Standardní tržní vývoj"),
            "asset_type": item["asset_type"],
            "tier": item["tier"]
        })

    prompt_payload = {
        "assets_to_evaluate": data_summary,
        "global_market_news": global_news
    }

    system_instruction = (
        "Jsi špičkový Senior Kvantitativní Analytik a Portfolio Manažer. "
        "Tvým úkolem je na základě poskytnutých dat (ceny, denní změny, předstihové indikátory, typ aktiva a globální sentiment) "
        "vygenerovat přesné investiční signály pro KAŽDÝ zadaný ticker v seznamu.\n\n"
        "PRAVIDLA:\n"
        "1. 'ticker': Symbol aktiva přesně tak, jak je zadán v 'ticker'.\n"
        "2. 'signal': Striktně jedna z hodnot: 'Strong Buy', 'Buy', 'Hold', 'Sell', 'Strong Sell'.\n"
        "3. 'probability': Celé číslo od 0 do 100 vyjadřující míru jistoty/síly signálu.\n"
        "4. 'impact_direction': Striktně buď 'up' (očekávání růstu), nebo 'down' (očekávání poklesu).\n"
        "5. 'time_horizon': Doporučený investiční horizont (např. '1-3 týdny' před earnings, '1-3 měsíce' střednědobě, '6-12 měsíců' dlouhodobě).\n"
        "6. 'catalyst_event': Klíčová budoucí událost či katalyzátor (např. 'Výsledky za 12 dní', 'Vysoký analytický diskont', 'Ex-Dividenda za 5 dní', 'Technická konsolidace').\n"
        "7. 'reasoning': Stručné a profesionální odůvodnění v ČEŠTINĚ, maximálně na 3 věty. "
        "Zohledni vztah k cílové ceně analytiků (upside diskont), blížící se výsledky a trend.\n\n"
        "Výstup musí být striktně validní JSON objekt odpovídající schématu MarketSignalsContainer."
    )

    response = client.models.generate_content(
        model=model_name,
        contents=[
            "Vyhodnoť následující aktiva a vygeneruj signály:\n" + json.dumps(prompt_payload, ensure_ascii=False, indent=2)
        ],
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=MarketSignalsContainer,
            temperature=0.2,
        )
    )

    response_text = response.text.strip()
    if response_text.startswith("```"):
        response_text = re.sub(r"^```(?:json)?\s*", "", response_text, flags=re.IGNORECASE)
        response_text = re.sub(r"\s*```$", "", response_text)

    parsed = json.loads(response_text)
    if isinstance(parsed, dict) and "signals" in parsed:
        return parsed["signals"]
    elif isinstance(parsed, list):
        return parsed
    return []


def analyze_universe_with_gemini(market_items: List[Dict[str, Any]], global_news: List[str], batch_size: int = 25) -> Tuple[List[Dict[str, Any]], bool]:
    """Rozdělí aktiva do dávek a vyhodnotí je přes Gemini API (s automatickým fallbackem)."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("[TIP] Pro ostré AI vyhodnocení nastavte GEMINI_API_KEY v .env. Používám demo signály.")
        return generate_mock_signals_for_universe(market_items), True

    from google import genai
    client = genai.Client(api_key=api_key)

    models_to_try = [GEMINI_MODEL]
    if "gemini-3.5-flash-lite" not in models_to_try:
        models_to_try.append("gemini-3.5-flash-lite")
    if "gemini-flash-latest" not in models_to_try:
        models_to_try.append("gemini-flash-latest")

    batches = [market_items[i:i + batch_size] for i in range(0, len(market_items), batch_size)]
    logger.info(f"Odesílám {len(market_items)} aktiv do Gemini rozdělených do {len(batches)} dávek (po {batch_size} ks)...")

    all_signals = []
    
    for b_idx, batch in enumerate(batches, 1):
        logger.info(f"Zpracovávám AI dávku {b_idx}/{len(batches)} ({len(batch)} aktiv)...")
        batch_success = False
        
        for model_name in models_to_try:
            try:
                signals = _call_gemini_batch(client, model_name, batch, global_news)
                all_signals.extend(signals)
                logger.info(f"Dávka {b_idx} úspěšně zpracována modelem {model_name} ({len(signals)} signálů).")
                batch_success = True
                break
            except Exception as e:
                logger.warning(f"Chyba modelu {model_name} pro dávku {b_idx}: {e}. Zkouším další...")

        if not batch_success:
            logger.warning(f"Dávka {b_idx} selhala na všech modelech. Doplňuji demo signály pro tuto dávku.")
            fallback_signals = generate_mock_signals_for_universe(batch)
            all_signals.extend(fallback_signals)

    return all_signals, False


def generate_mock_signals_for_universe(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Vygeneruje realistické demo signály pro případ absence API klíče či výpadku."""
    signals = []
    for item in items:
        ch = item.get("change_pct", 0.0)
        sym = item.get("yahoo_symbol", "")
        upside = item.get("target_upside_pct")
        days_ed = item.get("days_to_earnings")
        cat_tag = item.get("primary_catalyst_tag") or "Standardní trh"
        
        if ch >= 1.5 or (upside and upside >= 25.0):
            sig = "Strong Buy" if (ch >= 3.0 or (upside and upside >= 35.0)) else "Buy"
            prob = min(94, int(68 + max(0, ch) * 3))
            imp = "up"
            time_h = "1-3 měsíce"
            cat_ev = f"Cíl +{upside:.1f} %" if upside else cat_tag
            reas = f"{item['name']} vykazuje silné nákupní momentum."
            if upside:
                reas += f" Konsenzus analytiků vidí potenciál růstu {upside:+.1f} %."
            if days_ed is not None and days_ed <= 14:
                reas += f" Pozor na zvýšenou volatilitu před kvartálními výsledky (za {days_ed} dní)."
        elif ch <= -1.5 or (upside and upside <= -5.0):
            sig = "Strong Sell" if ch <= -3.0 else "Sell"
            prob = min(88, int(60 + abs(ch) * 4))
            imp = "down"
            time_h = "1-4 týdny"
            cat_ev = "Korekční tlak"
            reas = f"Titul čelí prodejnímu tlaku s poklesem o {ch:+.2f} %."
            if upside and upside <= -5.0:
                reas += f" Aktuální cena se nachází nad průměrným cílem analytiků."
        else:
            sig = "Hold"
            prob = 55
            imp = "up" if ch >= 0 else "down"
            time_h = "3-6 měsíců"
            cat_ev = "Konsolidace"
            reas = f"{item['name']} konsoliduje v dosavadním pásmu."
            if days_ed is not None:
                reas += f" Trh vyčkává na kvartální výsledky (za {days_ed} dní)."

        signals.append({
            "ticker": sym,
            "signal": sig,
            "probability": prob,
            "impact_direction": imp,
            "time_horizon": time_h,
            "catalyst_event": cat_ev,
            "reasoning": reas
        })
    return signals


def normalize_signal_class(signal: str) -> str:
    s = signal.strip().lower()
    if "strong buy" in s:
        return "signal-strong-buy"
    elif "buy" in s:
        return "signal-buy"
    elif "strong sell" in s:
        return "signal-strong-sell"
    elif "sell" in s:
        return "signal-sell"
    return "signal-hold"


def normalize_progress_class(signal: str) -> str:
    s = signal.strip().lower()
    if "strong buy" in s:
        return "fill-strong-buy"
    elif "buy" in s:
        return "fill-buy"
    elif "strong sell" in s:
        return "fill-strong-sell"
    elif "sell" in s:
        return "fill-sell"
    return "fill-hold"


def format_currency_value(value: Optional[float], currency: str) -> str:
    if value is None:
        return "—"
    if currency == "CZK":
        return f"{value:,.2f}".replace(",", " ")
    elif value >= 1000:
        return f"{value:,.2f}"
    else:
        return f"{value:.2f}"


def build_html_report(processed_cards: List[Dict[str, Any]], is_demo: bool = False, scan_duration: str = "45 s", data_sources: str = "") -> str:
    """Zkompiluje finální index.html přes Jinja2 šablonu."""
    now_utc = datetime.now(timezone.utc)
    cet_offset = timedelta(hours=2) # Letní čas SELČ
    now_cet = now_utc + cet_offset

    timestamp_cet_str = now_cet.strftime("%d. %m. %Y v %H:%M SELČ")
    timestamp_utc_str = now_utc.strftime("%Y-%m-%d %H:%M:%S")

    if not data_sources:
        data_sources = "XTB Market Catalog • Yahoo Finance Realtime • Yahoo Financial News RSS • Google Gemini 3.5 AI"

    # Statistiky pro záhlaví
    counts = {
        "total": len(processed_cards),
        "top": len([c for c in processed_cards if c["tier"] == "TOP"]),
        "mid": len([c for c in processed_cards if c["tier"] == "MID"]),
        "low": len([c for c in processed_cards if c["tier"] == "LOW"]),
        "buy": len([c for c in processed_cards if "buy" in c["signal"].lower()]),
        "hold": len([c for c in processed_cards if "hold" in c["signal"].lower()]),
        "sell": len([c for c in processed_cards if "sell" in c["signal"].lower()]),
    }

    template_dir = os.path.dirname(os.path.abspath(__file__))
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("template.html")

    html_content = template.render(
        cards=processed_cards,
        counts=counts,
        timestamp_cet=timestamp_cet_str,
        timestamp_utc=timestamp_utc_str,
        scan_duration=scan_duration,
        data_sources=data_sources,
        ai_model=GEMINI_MODEL if not is_demo else f"{GEMINI_MODEL} (Záložní režim)",
        is_demo=is_demo,
    )
    return html_content


def run_scanner(tiers: List[str] = None, allow_mock_fallback: bool = True) -> str:
    """Kompletní cyklus: sestavení univerza, paralelní stažení dat, předstihové indikátory, dávková AI analýza a HTML export."""
    import time
    scan_start = time.time()
    logger.info("=== Spouštím Stupňovitý Market Scanner & AI Screener s Předstihovými Indikátory ===")
    
    # 1. Načtení aktiv pro požadované koše (výchozí: TOP + MID + LOW)
    universe_items = get_all_universe(tiers=tiers)
    logger.info(f"Aktivních položek v univerzu: {len(universe_items)}")

    # 2. Paralelní stažení tržních dat (aktuální ceny a 52w rozsah)
    market_data = fetch_universe_market_data(universe_items, max_workers=20)

    # 3. Stažení fundamentů a kalendářů (s lokální 24h mezipamětí)
    fundamentals_by_sym = get_universe_fundamentals(universe_items, max_workers=20)

    # 4. Výpočet 1M a 3M momentum delt (dávkově)
    deltas_by_sym = fetch_momentum_deltas(universe_items, batch_size=80)

    # 5. Vyhodnocení deterministických triggerů pro každé aktivum
    for mdata in market_data:
        sym = mdata["yahoo_symbol"]
        fdata = fundamentals_by_sym.get(sym, {})
        ddata = deltas_by_sym.get(sym, {})
        trig_res = evaluate_asset_triggers(mdata, fdata, ddata)
        mdata.update(trig_res)

    # 6. Globální zprávy z RSS
    rss_news = fetch_rss_market_headlines(max_items=6)

    # 7. Dávková AI analýza s Gemini (obohacená o předstihové indikátory)
    signals_ai, is_demo = analyze_universe_with_gemini(market_data, rss_news, batch_size=25)

    # 8. Spojení dat do jednotné struktury pro frontend
    ai_by_ticker = {item.get("ticker", "").upper(): item for item in signals_ai}
    
    final_cards = []
    for mdata in market_data:
        sym = mdata["yahoo_symbol"]
        ai_item = ai_by_ticker.get(sym.upper(), {})

        signal = ai_item.get("signal", "Hold")
        probability = int(ai_item.get("probability", 50))
        probability = max(0, min(100, probability))

        impact_direction = str(ai_item.get("impact_direction", "up")).lower().strip()
        if impact_direction not in ["up", "down"]:
            impact_direction = "up" if mdata["change_pct"] >= 0 else "down"

        reasoning = ai_item.get("reasoning", "Tržní data bez jednoznačného fundamentálního impulsu.")
        time_horizon = ai_item.get("time_horizon", "1-3 měsíce")
        catalyst_event = ai_item.get("catalyst_event", mdata.get("primary_catalyst_tag") or "Standardní trh")

        change_pct_str = f"{mdata['change_pct']:+.2f} %"
        change_direction = "positive" if mdata["change_pct"] >= 0 else "negative"
        chart_url = f"https://finance.yahoo.com/quote/{mdata['yahoo_symbol']}"

        # Výpočet číselné síly signálu pro přesné řazení (Strong Buy -> Buy -> Hold -> Sell -> Strong Sell)
        s_lower = signal.strip().lower()
        if "strong buy" in s_lower:
            sig_rank = 5
        elif "buy" in s_lower:
            sig_rank = 4
        elif "hold" in s_lower:
            sig_rank = 3
        elif "strong sell" in s_lower:
            sig_rank = 1
        elif "sell" in s_lower:
            sig_rank = 2
        else:
            sig_rank = 3

        # Formátování cílových cen a potenciálu
        target_mean_val = mdata.get("target_mean")
        target_mean_str = f"{format_currency_value(target_mean_val, mdata['currency'])} {mdata['currency']}" if target_mean_val else "—"
        target_upside_val = mdata.get("target_upside_pct")
        target_upside_str = f"{target_upside_val:+.1f} %" if target_upside_val is not None else "—"
        
        target_upside_class = "upside-positive" if (target_upside_val is not None and target_upside_val > 0) else ("upside-negative" if (target_upside_val is not None and target_upside_val < 0) else "upside-neutral")

        final_cards.append({
            "xtb_symbol": mdata["xtb_symbol"],
            "yahoo_symbol": mdata["yahoo_symbol"],
            "name": mdata["name"],
            "tier": mdata["tier"],
            "asset_type": mdata["asset_type"],
            "currency": mdata["currency"],
            "price": format_currency_value(mdata["price"], mdata["currency"]),
            "price_raw": mdata["price"],
            "change_pct": change_pct_str,
            "change_pct_raw": mdata["change_pct"],
            "change_direction": change_direction,
            "catalyst_tag": mdata.get("primary_catalyst_tag") or mdata.get("catalyst_tag"),
            "triggers": mdata.get("triggers", []),
            "trigger_ids": mdata.get("trigger_ids", []),
            "target_mean": target_mean_str,
            "target_mean_raw": target_mean_val if target_mean_val is not None else -9999.0,
            "target_upside": target_upside_str,
            "target_upside_raw": target_upside_val if target_upside_val is not None else -9999.0,
            "target_upside_class": target_upside_class,
            "target_high": format_currency_value(mdata.get("target_high"), mdata["currency"]),
            "target_low": format_currency_value(mdata.get("target_low"), mdata["currency"]),
            "analysts_count": mdata.get("analysts_count"),
            "next_earnings_date": mdata.get("next_earnings_date"),
            "days_to_earnings": mdata.get("days_to_earnings"),
            "ex_dividend_date": mdata.get("ex_dividend_date"),
            "days_to_ex_dividend": mdata.get("days_to_ex_dividend"),
            "delta_1m": mdata.get("delta_1m"),
            "delta_3m": mdata.get("delta_3m"),
            "delta_1m_str": f"{mdata['delta_1m']:+.1f} %" if mdata.get("delta_1m") is not None else "—",
            "delta_3m_str": f"{mdata['delta_3m']:+.1f} %" if mdata.get("delta_3m") is not None else "—",
            "history_minitrend": get_ticker_signal_history(sym, limit=3),
            "time_horizon": time_horizon,
            "catalyst_event": catalyst_event,
            "signal": signal,
            "signal_rank": sig_rank,
            "signal_class": normalize_signal_class(signal),
            "progress_class": normalize_progress_class(signal),
            "probability": probability,
            "impact_direction": impact_direction,
            "reasoning": reasoning,
            "chart_url": chart_url,
        })

    # Automatické řazení od nejlepších výsledků po nejhorší (Strong Buy -> Buy -> Hold -> Sell -> Strong Sell)
    final_cards.sort(key=lambda c: (c["signal_rank"], c["probability"], c["change_pct_raw"]), reverse=True)

    # 9. Vygenerování a uložení index.html
    elapsed = time.time() - scan_start
    if elapsed >= 60:
        scan_duration_str = f"{int(elapsed // 60)} min {int(elapsed % 60)} s"
    else:
        scan_duration_str = f"{elapsed:.1f} s"

    data_sources_str = "XTB Market Catalog • Yahoo Finance Realtime • Yahoo Analyst Consensus & Calendars • Yahoo Financial News RSS • Google Gemini 3.5 AI"
    html_output = build_html_report(final_cards, is_demo=is_demo, scan_duration=scan_duration_str, data_sources=data_sources_str)

    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_output)

    logger.info(f"Report pro {len(final_cards)} aktiv byl úspěšně vygenerován do: {output_path}")

    # 10. Uložení historického snapshotu (JSON Data Lake + SQLite history.db)
    try:
        now_utc = datetime.now(timezone.utc)
        now_cet = now_utc + timedelta(hours=2)
        scan_meta = {
            "timestamp_utc": now_utc.strftime("%Y-%m-%d %H:%M:%S"),
            "timestamp_cet": now_cet.strftime("%d. %m. %Y v %H:%M SELČ"),
            "scan_duration": scan_duration_str,
            "ai_model": GEMINI_MODEL if not is_demo else f"{GEMINI_MODEL} (Záložní)",
            "counts": {
                "total": len(final_cards),
                "buy": len([c for c in final_cards if "buy" in c["signal"].lower()]),
                "hold": len([c for c in final_cards if "hold" in c["signal"].lower()]),
                "sell": len([c for c in final_cards if "sell" in c["signal"].lower()]),
            }
        }
        save_scan_history(final_cards, scan_meta)
    except Exception as e:
        logger.warning(f"Chyba při ukládání do historie: {e}")

    logger.info("=== Běh skeneru úspěšně dokončen ===")
    return output_path


def main():
    run_scanner()


if __name__ == "__main__":
    main()
