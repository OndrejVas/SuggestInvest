import os
import sys
import json
import re
import logging
import concurrent.futures
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Tuple

from dotenv import load_dotenv
import feedparser
from bs4 import BeautifulSoup
import yfinance as yf
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, Field

from universe import get_all_universe, TIER_1_TOP, TIER_2_MID, TIER_3_LOW

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


# Pydantic schémata pro zaručení validního JSONu z Gemini
class TickerSignalItem(BaseModel):
    ticker: str = Field(description="Symbol aktiva (např. NVDA, AAPL, CEZ.PR)")
    signal: str = Field(description="Signál: Strong Buy, Buy, Hold, Sell, nebo Strong Sell")
    probability: int = Field(description="Míra konfidence 0 až 100", ge=0, le=100)
    impact_direction: str = Field(description="Očekávaný směr: 'up' nebo 'down'")
    reasoning: str = Field(description="Stručné a věcné odůvodnění v češtině, maximálně 3 věty.")


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

        # Automatické přiřazení technického štítku (Catalyst Tag)
        catalyst_tag = None
        if change_pct >= 3.0:
            catalyst_tag = "🚀 Silné momentum"
        elif change_pct <= -3.0:
            catalyst_tag = "📉 Přeprodáno / Korekce"
        elif year_high and price and price >= year_high * 0.97:
            catalyst_tag = "🔥 Test 52w Maxima"
        elif item["currency"] == "CZK":
            catalyst_tag = "🇨🇿 BCPP Dividendy"
        elif item["asset_type"] == "ETF":
            catalyst_tag = "📊 Pasivní ETF"
        elif item["asset_type"] == "KRYPTO":
            catalyst_tag = "⚡ Krypto Volatilita"

        res = dict(item)
        res["price"] = price if price is not None else 0.0
        res["prev_close"] = prev_close if prev_close is not None else 0.0
        res["change_pct"] = change_pct
        res["change_val"] = change_val
        res["catalyst_tag"] = catalyst_tag
        return res
    except Exception as e:
        logger.debug(f"Chyba při stahování {yahoo_sym}: {e}")
        res = dict(item)
        res["price"] = 0.0
        res["prev_close"] = 0.0
        res["change_pct"] = 0.0
        res["change_val"] = 0.0
        res["catalyst_tag"] = None
        return res


def fetch_universe_market_data(universe_items: List[Dict[str, Any]], max_workers: int = 15) -> List[Dict[str, Any]]:
    """Paralelně stáhne kurzy pro všechny tickery z univerza."""
    logger.info(f"Paralelně stahuji tržní data pro {len(universe_items)} aktiv ({max_workers} vláken)...")
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(_fetch_single_ticker_data, universe_items))
    logger.info(f"Tržní data úspěšně stažena ({len(results)} aktiv).")
    return results


def _call_gemini_batch(client, model_name: str, batch_items: List[Dict[str, Any]], global_news: List[str]) -> List[Dict[str, Any]]:
    """Zavolá Gemini API pro jednu dávku tickerů (max 15-20 ks)."""
    from google.genai import types

    data_summary = []
    for item in batch_items:
        data_summary.append({
            "ticker": item["yahoo_symbol"],
            "name": item["name"],
            "price": f"{item['price']:.2f} {item['currency']}",
            "day_change": f"{item['change_pct']:+.2f}%",
            "asset_type": item["asset_type"],
            "tier": item["tier"]
        })

    prompt_payload = {
        "assets_to_evaluate": data_summary,
        "global_market_news": global_news
    }

    system_instruction = (
        "Jsi špičkový Senior Kvantitativní Analytik a Portfolio Manažer. "
        "Tvým úkolem je na základě poskytnutých dat (ceny, denní změny, typ aktiva, kategorie a globální sentiment) "
        "vygenerovat přesné investiční signály pro KAŽDÝ zadaný ticker v seznamu.\n\n"
        "PRAVIDLA:\n"
        "1. 'ticker': Symbol aktiva přesně tak, jak je zadán v 'ticker'.\n"
        "2. 'signal': Striktně jedna z hodnot: 'Strong Buy', 'Buy', 'Hold', 'Sell', 'Strong Sell'.\n"
        "3. 'probability': Celé číslo od 0 do 100 vyjadřující míru jistoty/síly signálu.\n"
        "4. 'impact_direction': Striktně buď 'up' (očekávání růstu), nebo 'down' (očekávání poklesu).\n"
        "5. 'reasoning': Stručné a profesionální odůvodnění v ČEŠTINĚ, maximálně na 3 věty. "
        "Uveď klíčový technický nebo fundamentální faktor.\n\n"
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


def analyze_universe_with_gemini(market_items: List[Dict[str, Any]], global_news: List[str], batch_size: int = 15) -> Tuple[List[Dict[str, Any]], bool]:
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

    # Rozdělení na dávky
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
        
        if ch >= 1.5:
            sig = "Strong Buy" if ch >= 3.0 else "Buy"
            prob = min(92, int(65 + ch * 4))
            imp = "up"
            reas = f"{item['name']} vykazuje silné nákupní momentum s denním nárůstem {ch:+.2f} %. Růstový trend podporuje zájem institucionálních investorů."
        elif ch <= -1.5:
            sig = "Strong Sell" if ch <= -3.0 else "Sell"
            prob = min(88, int(60 + abs(ch) * 4))
            imp = "down"
            reas = f"Titul čelí zvýšenému prodejnímu tlaku s poklesem o {ch:+.2f} %. Doporučujeme opatrnost a vyčkání na potvrzení technického dna."
        else:
            sig = "Hold"
            prob = 55
            imp = "up" if ch >= 0 else "down"
            reas = f"{item['name']} se nachází v konsolidačním pásmu kolem stávajících úrovní. Trh čeká na další fundamentální katalyzátor."

        signals.append({
            "ticker": sym,
            "signal": sig,
            "probability": prob,
            "impact_direction": imp,
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


def format_currency_value(value: float, currency: str) -> str:
    if currency == "CZK":
        return f"{value:,.2f}".replace(",", " ")
    elif value >= 1000:
        return f"{value:,.2f}"
    else:
        return f"{value:.2f}"


def build_html_report(processed_cards: List[Dict[str, Any]], is_demo: bool = False) -> str:
    """Zkompiluje finální index.html přes Jinja2 šablonu."""
    now_utc = datetime.now(timezone.utc)
    cet_offset = timedelta(hours=2) # Letní čas SELČ
    now_cet = now_utc + cet_offset
    timestamp_cet_str = now_cet.strftime("%d. %m. %Y v %H:%M SELČ")
    timestamp_utc_str = now_utc.strftime("%Y-%m-%d %H:%M:%S")

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
        ai_model=f"{GEMINI_MODEL} (Lokální Demo)" if is_demo else GEMINI_MODEL,
        is_demo=is_demo,
    )
    return html_content


def run_scanner(tiers: List[str] = None, allow_mock_fallback: bool = True) -> str:
    """Kompletní cyklus: sestavení univerza, paralelní stažení dat, dávková AI analýza a HTML export."""
    logger.info("=== Spouštím Stupňovitý Market Scanner & AI Screener ===")
    
    # 1. Načtení aktiv pro požadované koše (výchozí: TOP + MID + LOW)
    universe_items = get_all_universe(tiers=tiers)
    logger.info(f"Aktivních položek v univerzu: {len(universe_items)}")

    # 2. Paralelní stažení tržních dat
    market_data = fetch_universe_market_data(universe_items, max_workers=20)

    # 3. Globální zprávy z RSS
    rss_news = fetch_rss_market_headlines(max_items=6)

    # 4. Dávková AI analýza s Gemini
    signals_ai, is_demo = analyze_universe_with_gemini(market_data, rss_news, batch_size=18)

    # 5. Spojení dat do jednotné struktury pro frontend
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
        change_pct_str = f"{mdata['change_pct']:+.2f} %"
        change_direction = "positive" if mdata["change_pct"] >= 0 else "negative"

        final_cards.append({
            "xtb_symbol": mdata["xtb_symbol"],
            "yahoo_symbol": mdata["yahoo_symbol"],
            "name": mdata["name"],
            "tier": mdata["tier"],
            "asset_type": mdata["asset_type"],
            "currency": mdata["currency"],
            "price": format_currency_value(mdata["price"], mdata["currency"]),
            "change_pct": change_pct_str,
            "change_direction": change_direction,
            "catalyst_tag": mdata.get("catalyst_tag"),
            "signal": signal,
            "signal_class": normalize_signal_class(signal),
            "progress_class": normalize_progress_class(signal),
            "probability": probability,
            "impact_direction": impact_direction,
            "reasoning": reasoning,
        })

    # 6. Vygenerování a uložení index.html
    html_output = build_html_report(final_cards, is_demo=is_demo)
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_output)

    logger.info(f"Report pro {len(final_cards)} aktiv byl úspěšně vygenerován do: {output_path}")
    logger.info("=== Běh skeneru úspěšně dokončen ===")
    return output_path


def main():
    run_scanner()


if __name__ == "__main__":
    main()
