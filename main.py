import os
import sys
import json
import re
import logging
import concurrent.futures
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Tuple, Optional, Literal

from dotenv import load_dotenv
import feedparser
from bs4 import BeautifulSoup
import yfinance as yf
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, Field

from universe import get_all_universe, TIER_1_TOP, TIER_2_MID, TIER_3_LOW
from fundamentals_fetcher import get_universe_fundamentals, fetch_momentum_deltas
from trigger_engine import evaluate_asset_triggers
from history_manager import (
    save_scan_history, 
    get_ticker_signal_history, 
    get_ticker_historical_context,
    compute_daily_changes
)

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


# Pydantic schémata pro zaručení striktního JSON kontraktu Senior Quant & Risk modelu
class TickerSignalItem(BaseModel):
    ticker: str = Field(description="Symbol aktiva (např. NVDA.US, AAPL.US, CEZ1.CZ)")
    signal: Literal["STRONG BUY", "BUY", "HOLD", "SELL", "STRONG SELL"] = Field(description="Kvantitativní signál")
    confidence: int = Field(description="Míra jistoty 0 až 100", ge=0, le=100)
    impact_direction: Literal["▲ Růst", "▼ Pokles"] = Field(description="Očekávaný směr")
    catalysts: List[str] = Field(description="1 až 4 relevantní štítky z přesné sady 9 schválených štítků")
    reasoning: str = Field(description="Přesně 1 až 2 věty v češtině se specifickými hodnotami (vztah kurzu, cíle a události)")
    invalidation_price: Optional[float] = Field(default=None, description="Invalidační cenová hladina (stop-loss úroveň)")


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
    """Zavolá Gemini API pro jednu dávku tickerů dle Senior Quant & Risk standardu."""
    from google.genai import types

    data_summary = []
    for item in batch_items:
        sym = item["yahoo_symbol"]
        curr_target = item.get("target_mean")
        hist_ctx = get_ticker_historical_context(sym, curr_target)

        # Sektor / makro kontext
        sector = item.get("sector") or ("BCPP Energetika/Finance" if item.get("currency") == "CZK" else ("Technologie/Růst" if item.get("asset_type") == "AKCIE" else item.get("asset_type")))
        macro_snippet = f"Tržní zprávy: {global_news[0][:80]}..." if global_news else "Stabilní tržní prostředí."
        if item.get("currency") == "CZK":
            macro_snippet = "ČNB drží sazby stabilní, tuzemský trh těží z vysokých dividend a stabilních utilit."

        data_summary.append({
            "ticker": item.get("xtb_symbol") or sym,
            "name": item["name"],
            "tier": f"TIER {item.get('tier', 'MID')}",
            "sector": sector,
            "price": {
                "current": round(float(item.get("price", 0.0)), 2),
                "currency": item.get("currency", "USD"),
                "change_1d_pct": round(float(item.get("change_pct", 0.0)), 2),
                "change_1m_pct": round(float(item.get("delta_1m", 0.0)), 2) if item.get("delta_1m") is not None else 0.0,
                "change_3m_pct": round(float(item.get("delta_3m", 0.0)), 2) if item.get("delta_3m") is not None else 0.0,
                "high_52w": round(float(item.get("year_high")), 2) if item.get("year_high") else None,
                "low_52w": round(float(item.get("year_low")), 2) if item.get("year_low") else None,
                "dist_to_52w_high_pct": round(float(item.get("dist_to_52w_high_pct", 100.0)), 1)
            },
            "consensus": {
                "target_mean": round(float(curr_target), 2) if curr_target else None,
                "target_high": round(float(item.get("target_high")), 2) if item.get("target_high") else None,
                "target_low": round(float(item.get("target_low")), 2) if item.get("target_low") else None,
                "analyst_count": item.get("analysts_count"),
                "target_upside_pct": round(float(item.get("target_upside_pct")), 2) if item.get("target_upside_pct") is not None else None,
                "delta_target_30d_pct": hist_ctx.get("delta_target_30d_pct", 0.0)
            },
            "calendar": {
                "days_to_earnings": item.get("days_to_earnings"),
                "earnings_time": item.get("earnings_time") or ("BMO" if item.get("days_to_earnings") is not None else None),
                "days_to_ex_dividend": item.get("days_to_ex_dividend"),
                "dividend_strategy": item.get("dividend_analysis")
            },
            "history": {
                "prev_signal": hist_ctx.get("prev_signal", "HOLD"),
                "prev_confidence": hist_ctx.get("prev_confidence", 50),
                "confidence_delta_7d": hist_ctx.get("confidence_delta_7d", 0)
            },
            "macro_context": macro_snippet
        })

    prompt_payload = {
        "assets_to_evaluate": data_summary,
        "global_market_news": global_news
    }

    system_instruction = (
        "Jsi Senior Quantitative Equity Analyst a Head of Portfolio Risk v investičním labu SuggestInvest. "
        "Tvým úkolem je vyhodnocovat tržní aktiva a převádět kvantitativní metriky, konsenzuální odhady analytiků z Wall Street "
        "a firemní kalendáře do racionálních investičních signálů.\n"
        "Tvým cílem není popisovat minulý vývoj kurzu, ale identifikovat asymetrické tržní příležitosti a rizika "
        "v horizontu 1 až 3 měsíců na základě nesouladu mezi tržní cenou, posunem konsenzu a časem do klíčových událostí.\n\n"
        "ROZHODOVACÍ MATICE A EVENT TRIGGERS:\n"
        "A. Triggery konsenzu a valuace:\n"
        "- Fundamentální diskont (Target Upside > +20 %): Pokud je počet analytiků >= 5 a delta_target_30d_pct >= 0, jde o silný růstový signál (BUY / STRONG BUY). Pokud cena klesá (change_1m_pct < 0), ale cílová cena roste (delta_target_30d_pct > 0), vzniká pozitivní divergence (institucionální akumulace).\n"
        "- Přepálená valuace (Tržní cena nad průměrným cílem): Pokud je target_upside_pct <= 0, růstový potenciál je vyčerpán. Signál nesmí být STRONG BUY ani BUY. Zvol HOLD nebo SELL.\n\n"
        "B. Událostní filtry kalendáře:\n"
        "- Kritické okno před výsledky (days_to_earnings <= 7): Implikovaná volatilita roste. Binární riziko. Confidence nesmí překročit 65 %, pokud nejde o defenzivní dividendový monopol s vysokou jistotou. Do štítků přidej '⏳ Výsledky do 7 dní'.\n"
        "- Předvýsledkový run-up (days_to_earnings mezi 8 a 21 dny): Pokud je change_1m_pct > 0 a delta_target_30d_pct > 0, aktivum je v akumulační fázi před kvartální zprávou. Přidej '📅 Výsledky do 21 dní'.\n"
        "- Dividendový trigger a Ex-Date Recovery (days_to_ex_dividend <= 14): Pokud má aktivum v calendar.dividend_strategy doporučení '🟢 Držet přes Ex-Div (Rychlé zotavení)', kurz historicky rychle maže dividendový gap (do 15 dní). To podporuje BUY a strategii Dividend Capture. Pokud má naopak '🟡 Prodat před Ex-Div', titul před Ex-Date posiluje, ale po Ex-Date padá a zotavení trvá dlouho, což favorizuje realizaci zisku předem.\n\n"
        "C. Filtry trendu a spolehlivosti:\n"
        "- Obrat vs. Padající nůž: Test 52w minima (dist_to_52w_high_pct < 70) s klesající cílovou cenou (delta_target_30d_pct < -5) značí strukturální problém -> SELL nebo STRONG SELL. Test 52w minima se stabilní cílovou cenou a rostoucím 1M momentem značí obratový potenciál -> BUY.\n"
        "- Kontrola šumu: Denní skok o více než +/- 3 % ignoruj, pokud není v souladu s 1M momentem nebo novou fundamentální zprávou.\n\n"
        "VÝSTUPNÍ STRUKTURA (STRICT JSON CONTRACT):\n"
        "1. 'ticker': Symbol přesně tak, jak je zadán.\n"
        "2. 'signal': Striktně jedna z hodnot: 'STRONG BUY', 'BUY', 'HOLD', 'SELL', 'STRONG SELL'.\n"
        "   - STRONG BUY: Shoda silného 1M/3M trendu, diskont k cíli > 20 % a pozitivní revize odhadů.\n"
        "   - BUY: Pozitivní poměr výnosu a rizika, zdravý diskont, žádné binární riziko do 7 dnů.\n"
        "   - HOLD: Vyčerpaný potenciál k cílové ceně, probíhající konsolidace nebo výsledky do 7 dnů.\n"
        "   - SELL: Cena nad cílem analytiků, zhoršující se momentum nebo negativní revize EPS.\n"
        "   - STRONG SELL: Ztráta fundamentu, masivní snižování cílových cen analytiky.\n"
        "3. 'confidence': Celé číslo od 0 do 100.\n"
        "4. 'impact_direction': Striktně buď '▲ Růst', nebo '▼ Pokles'.\n"
        "5. 'catalysts': Vyber 1 až 4 relevantní štítky z této přesné sady:\n"
        "   ['🚀 Silné momentum', '📉 Přeprodáno / Korekce', '🔥 Test 52w Maxima', '🎯 Vysoký diskont', '⚠️ Nad cílem analytiků', '⏳ Výsledky do 7 dní', '📅 Výsledky do 21 dní', '💰 Ex-Div za N dní', '🇨🇿 BCPP Dividendy']\n"
        "6. 'reasoning': Přesně 1 až 2 věty v češtině. Musí konkrétně zmínit vztah mezi tržním kurzem, cílovou cenou a blížící se událostí (výsledky, dividenda apod.). Zákaz obecných frází typu 'akcie má dobré vyhlídky'.\n"
        "7. 'invalidation_price': Konkrétní cenová hladina (float), při jejímž prolomení celá investiční teze přestává platit.\n\n"
        "PŘÍKLAD:\n"
        "Input: NVDA.US (price 128.5, target_mean 155.0 (+20.6%), delta_target_30d_pct +5.8%, days_to_earnings 19)\n"
        "Output: {\n"
        "  'ticker': 'NVDA.US',\n"
        "  'signal': 'STRONG BUY',\n"
        "  'confidence': 84,\n"
        "  'impact_direction': '▲ Růst',\n"
        "  'catalysts': ['🚀 Silné momentum', '🎯 Vysoký diskont', '📅 Výsledky do 21 dní'],\n"
        "  'reasoning': 'Konsenzuální cílová cena vzrostla za posledních 30 dní o 5,8 % na 155 USD, což při 20% diskontu a 19 dnech do výsledků podporuje pokračování předvýsledkového run-upu. Pozice těží ze stabilního zrychlování kapitálových výdajů v celém AI sektoru.',\n"
        "  'invalidation_price': 116.0\n"
        "}"
    )

    response = client.models.generate_content(
        model=model_name,
        contents=[
            "Vyhodnoť následující aktiva a vygeneruj signály dle Senior Quant & Risk standardu:\n" + json.dumps(prompt_payload, ensure_ascii=False, indent=2)
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
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API")
    if not api_key:
        logger.warning("[TIP] Pro ostré AI vyhodnocení nastavte GEMINI_API_KEY v .env. Používám demo signály.")
        return generate_mock_signals_for_universe(market_items), True

    from google import genai
    client = genai.Client(api_key=api_key)

    models_to_try = [GEMINI_MODEL]
    for m_cand in ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-flash-latest"]:
        if m_cand not in models_to_try:
            models_to_try.append(m_cand)

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
    """Vygeneruje deterministické signály dle rozhodovací matice Senior Quant & Risk modelu."""
    signals = []
    for item in items:
        sym = item.get("xtb_symbol") or item.get("yahoo_symbol", "")
        name = item.get("name", sym)
        price = float(item.get("price", 0.0))
        curr = item.get("currency", "USD")
        ch_1d = float(item.get("change_pct", 0.0))
        ch_1m = float(item.get("delta_1m", 0.0)) if item.get("delta_1m") is not None else 0.0
        ch_3m = float(item.get("delta_3m", 0.0)) if item.get("delta_3m") is not None else 0.0
        upside = item.get("target_upside_pct")
        target_mean = item.get("target_mean")
        analysts = item.get("analysts_count") or 0
        days_ed = item.get("days_to_earnings")
        days_ex = item.get("days_to_ex_dividend")
        dist_52w = float(item.get("dist_to_52w_high_pct", 100.0))

        # Zjištění historie a 30d delty
        hist_ctx = get_ticker_historical_context(item.get("yahoo_symbol", ""), target_mean)
        delta_target_30d = hist_ctx.get("delta_target_30d_pct", 0.0)

        # 1. Seznam schválených štítků katalyzátorů
        catalysts = []
        if ch_1d >= 3.0 or ch_1m >= 10.0:
            catalysts.append("🚀 Silné momentum")
        elif ch_1d <= -3.0 and ch_3m > 0:
            catalysts.append("📉 Přeprodáno / Korekce")

        if dist_52w >= 97.0:
            catalysts.append("🔥 Test 52w Maxima")

        if upside is not None:
            if upside >= 20.0 and analysts >= 5:
                catalysts.append("🎯 Vysoký diskont")
            elif upside <= 0.0:
                catalysts.append("⚠️ Nad cílem analytiků")

        if days_ed is not None:
            if 0 <= days_ed <= 7:
                catalysts.append("⏳ Výsledky do 7 dní")
            elif 8 <= days_ed <= 21:
                catalysts.append("📅 Výsledky do 21 dní")

        if days_ex is not None and 0 <= days_ex <= 14:
            catalysts.append(f"💰 Ex-Div za {days_ex} dní" if days_ex > 0 else "💰 Ex-Div dnes")

        if curr == "CZK" and item.get("asset_type") == "AKCIE":
            catalysts.append("🇨🇿 BCPP Dividendy")

        if not catalysts:
            catalysts = ["🚀 Silné momentum"] if ch_1d >= 0 else ["📉 Přeprodáno / Korekce"]
        catalysts = catalysts[:4]

        # 2. Vyhodnocení signálu a konfidence dle Rozhodovací matice A, B, C
        signal = "HOLD"
        confidence = 55
        impact_direction = "▲ Růst" if ch_1d >= 0 else "▼ Pokles"
        inv_price = round(price * 0.92, 2) if price > 0 else None

        # Pravidlo A: Fundamentální diskont (> 20 %)
        if upside is not None and upside >= 20.0 and analysts >= 5 and delta_target_30d >= 0:
            if ch_1m > 5.0 and ch_3m > 10.0 and (days_ed is None or days_ed > 7):
                signal = "STRONG BUY"
                confidence = min(92, int(78 + min(upside * 0.3, 14)))
                impact_direction = "▲ Růst"
                inv_price = round(price * 0.91, 2)
            else:
                signal = "BUY"
                confidence = min(85, int(70 + min(upside * 0.25, 12)))
                impact_direction = "▲ Růst"
                inv_price = round(price * 0.90, 2)

        # Pozitivní divergence (cena klesá, cíl roste)
        elif upside is not None and upside >= 15.0 and ch_1m < 0 and delta_target_30d > 0:
            signal = "BUY"
            confidence = 74
            impact_direction = "▲ Růst"
            inv_price = round(price * 0.89, 2)

        # Přepálená valuace (target upside <= 0)
        elif upside is not None and upside <= 0.0:
            if ch_1d <= -1.5 or ch_1m < -5.0 or delta_target_30d < -3.0:
                signal = "SELL"
                confidence = 72
                impact_direction = "▼ Pokles"
                inv_price = round(price * 1.08, 2)
            else:
                signal = "HOLD"
                confidence = 60
                impact_direction = "▼ Pokles"
                inv_price = round(price * 1.06, 2)

        # Padající nůž (test 52w minima dist < 70 a delta_target_30d < -5)
        elif dist_52w < 70.0 and delta_target_30d < -5.0:
            signal = "STRONG SELL" if ch_1m < -10.0 else "SELL"
            confidence = 82
            impact_direction = "▼ Pokles"
            inv_price = round(price * 1.09, 2)

        # Obrat u 52w minima
        elif dist_52w < 70.0 and delta_target_30d >= 0.0 and ch_1m > 2.0:
            signal = "BUY"
            confidence = 71
            impact_direction = "▲ Růst"
            inv_price = round(price * 0.88, 2)

        # Pravidlo B: Kritické okno před výsledky (days_to_earnings <= 7)
        if days_ed is not None and 0 <= days_ed <= 7:
            if signal == "STRONG BUY":
                signal = "HOLD"
            confidence = min(confidence, 64)

        # 3. Odůvodnění (Přesně 1 až 2 věty v češtině se specifickými hodnotami)
        if signal in ["STRONG BUY", "BUY"]:
            target_text = f"na {target_mean:.1f} {curr} (+{upside:.1f} %)" if (target_mean and upside) else "s vysokým diskontem"
            event_text = f" a blížícími se výsledky za {days_ed} dní" if (days_ed is not None and days_ed <= 21) else ""
            reasoning = f"Konsenzuální cílová cena {target_text} vytváří atraktivní asymetrii výnosu a rizika při 1M momentu {ch_1m:+.1f} %{event_text}. Teze zůstává v platnosti nad hranicí podpory {inv_price} {curr}."
        elif signal in ["SELL", "STRONG SELL"]:
            target_text = f"překročila průměrný cíl analytiků {target_mean:.1f} {curr}" if target_mean else "vykazuje zhoršující se konsenzus"
            reasoning = f"Tržní cena {target_text} a 3M momentum {ch_3m:+.1f} % indikuje vyčerpání nákupního tlaku. Zvýšené distribuční riziko signalizuje obrat s validační hladinou na {inv_price} {curr}."
        else:
            event_text = f" a trh vyčkává na kvartální report za {days_ed} dní" if days_ed is not None else ""
            reasoning = f"Titul prochází technickou konsolidací s 1M změnou {ch_1m:+.1f} %{event_text}. Doporučujeme vyčkat na jasný fundamentální katalyzátor nad hladinou {inv_price} {curr}."

        signals.append({
            "ticker": sym,
            "signal": signal,
            "confidence": confidence,
            "impact_direction": impact_direction,
            "catalysts": catalysts,
            "reasoning": reasoning,
            "invalidation_price": inv_price
        })
    return signals


def normalize_signal_class(signal: str) -> str:
    s = signal.strip().upper()
    if "STRONG BUY" in s:
        return "signal-strong-buy"
    elif "BUY" in s:
        return "signal-buy"
    elif "STRONG SELL" in s:
        return "signal-strong-sell"
    elif "SELL" in s:
        return "signal-sell"
    return "signal-hold"


def normalize_progress_class(signal: str) -> str:
    s = signal.strip().upper()
    if "STRONG BUY" in s:
        return "fill-strong-buy"
    elif "BUY" in s:
        return "fill-buy"
    elif "STRONG SELL" in s:
        return "fill-strong-sell"
    elif "SELL" in s:
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


def build_html_report(processed_cards: List[Dict[str, Any]], is_demo: bool = False, scan_duration: str = "45 s", data_sources: str = "", change_stats: Optional[Dict[str, Any]] = None) -> str:
    """Zkompiluje finální index.html přes Jinja2 šablonu."""
    now_utc = datetime.now(timezone.utc)
    cet_offset = timedelta(hours=2) # Letní čas SELČ
    now_cet = now_utc + cet_offset

    timestamp_cet_str = now_cet.strftime("%d. %m. %Y v %H:%M SELČ")
    timestamp_utc_str = now_utc.strftime("%Y-%m-%d %H:%M:%S")

    if not data_sources:
        data_sources = "XTB Market Catalog • Yahoo Finance Realtime • Yahoo Analyst Consensus & Calendars • Yahoo Financial News RSS • Google Gemini 3.5 AI"

    # Statistiky pro záhlaví dle 5úrovňového modelu
    counts = {
        "total": len(processed_cards),
        "top": len([c for c in processed_cards if c["tier"] == "TOP"]),
        "mid": len([c for c in processed_cards if c["tier"] == "MID"]),
        "low": len([c for c in processed_cards if c["tier"] == "LOW"]),
        "strong_buy": len([c for c in processed_cards if c["signal"] == "STRONG BUY"]),
        "buy": len([c for c in processed_cards if c["signal"] == "BUY"]),
        "hold": len([c for c in processed_cards if c["signal"] == "HOLD"]),
        "sell": len([c for c in processed_cards if c["signal"] == "SELL"]),
        "strong_sell": len([c for c in processed_cards if c["signal"] == "STRONG SELL"]),
    }

    # Obohacení o statistiky denních posunů
    if change_stats:
        counts["total_changed"] = change_stats.get("total_changed", 0)
        counts["upgrades"] = change_stats.get("upgrades", 0)
        counts["downgrades"] = change_stats.get("downgrades", 0)
        counts["conf_jumps"] = change_stats.get("conf_jumps", 0)
        counts["prev_scan_date"] = change_stats.get("prev_scan_date", "—")
        counts["prev_scan_time"] = change_stats.get("prev_scan_time", "—")
    else:
        counts["total_changed"] = len([c for c in processed_cards if c.get("daily_change", {}).get("is_changed")])
        counts["upgrades"] = len([c for c in processed_cards if c.get("daily_change", {}).get("change_type") == "UPGRADE"])
        counts["downgrades"] = len([c for c in processed_cards if c.get("daily_change", {}).get("change_type") == "DOWNGRADE"])
        counts["conf_jumps"] = len([c for c in processed_cards if c.get("daily_change", {}).get("change_type") in ("CONFIDENCE_JUMP", "CONFIDENCE_DROP")])
        counts["prev_scan_date"] = "—"
        counts["prev_scan_time"] = "—"

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
        ai_model=GEMINI_MODEL if not is_demo else f"{GEMINI_MODEL} (Záložní Quant Režim)",
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

    # 7. Dávková AI analýza s Gemini dle Senior Quant & Risk specifikace
    signals_ai, is_demo = analyze_universe_with_gemini(market_data, rss_news, batch_size=25)

    # 8. Spojení dat do jednotné struktury pro frontend
    ai_by_ticker = {}
    for item in signals_ai:
        t_key = str(item.get("ticker", "")).upper()
        ai_by_ticker[t_key] = item

    final_cards = []
    for mdata in market_data:
        sym = mdata["yahoo_symbol"]
        xtb_sym = mdata.get("xtb_symbol", sym)
        
        # Hledání signálu dle XTB i Yahoo symbolu
        ai_item = ai_by_ticker.get(xtb_sym.upper()) or ai_by_ticker.get(sym.upper()) or {}

        raw_sig = str(ai_item.get("signal", "HOLD")).strip().upper()
        if "STRONG BUY" in raw_sig:
            signal = "STRONG BUY"
            sig_rank = 5
        elif "STRONG SELL" in raw_sig:
            signal = "STRONG SELL"
            sig_rank = 1
        elif "BUY" in raw_sig:
            signal = "BUY"
            sig_rank = 4
        elif "SELL" in raw_sig:
            signal = "SELL"
            sig_rank = 2
        else:
            signal = "HOLD"
            sig_rank = 3

        conf_val = ai_item.get("confidence")
        if conf_val is None:
            conf_val = ai_item.get("probability", 55)
        confidence = max(0, min(100, int(conf_val)))

        impact_direction = ai_item.get("impact_direction")
        if impact_direction not in ["▲ Růst", "▼ Pokles"]:
            impact_direction = "▲ Růst" if mdata["change_pct"] >= 0 else "▼ Pokles"

        # Získání štítků katalyzátorů
        catalysts_raw = ai_item.get("catalysts")
        if isinstance(catalysts_raw, list) and catalysts_raw:
            catalysts = catalysts_raw
        elif mdata.get("triggers"):
            catalysts = [t["label"] for t in mdata["triggers"][:3]]
        else:
            catalysts = ["🚀 Silné momentum"] if mdata["change_pct"] >= 0 else ["📉 Přeprodáno / Korekce"]

        reasoning = ai_item.get("reasoning", "Tržní aktivum se nachází ve fázi rovnovážné konsolidace.")
        
        # Invalidation price & vzdálenost
        inv_price = ai_item.get("invalidation_price") or mdata.get("invalidation_price")
        inv_price_float = float(inv_price) if inv_price is not None and inv_price != "" else None
        
        inv_dist_pct = None
        if inv_price_float and mdata["price"] > 0:
            inv_dist_pct = round(((inv_price_float - mdata["price"]) / mdata["price"]) * 100, 1)

        change_pct_str = f"{mdata['change_pct']:+.2f} %"
        change_direction = "positive" if mdata["change_pct"] >= 0 else "negative"
        chart_url = f"https://finance.yahoo.com/quote/{mdata['yahoo_symbol']}"

        # Formátování cílových cen a potenciálu
        target_mean_val = mdata.get("target_mean")
        target_mean_str = f"{format_currency_value(target_mean_val, mdata['currency'])} {mdata['currency']}" if target_mean_val else "—"
        target_upside_val = mdata.get("target_upside_pct")
        target_upside_str = f"{target_upside_val:+.1f} %" if target_upside_val is not None else "—"
        
        target_upside_class = "upside-positive" if (target_upside_val is not None and target_upside_val > 0) else ("upside-negative" if (target_upside_val is not None and target_upside_val < 0) else "upside-neutral")

        # Historický kontext z DB
        hist_ctx = get_ticker_historical_context(sym, target_mean_val)

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
            "catalysts": catalysts,
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
            "earnings_time": mdata.get("earnings_time"),
            "ex_dividend_date": mdata.get("ex_dividend_date"),
            "days_to_ex_dividend": mdata.get("days_to_ex_dividend"),
            "dividend_analysis": mdata.get("dividend_analysis"),
            "delta_1m": mdata.get("delta_1m"),
            "delta_3m": mdata.get("delta_3m"),
            "delta_1m_str": f"{mdata['delta_1m']:+.1f} %" if mdata.get("delta_1m") is not None else "—",
            "delta_3m_str": f"{mdata['delta_3m']:+.1f} %" if mdata.get("delta_3m") is not None else "—",
            "dist_to_52w_high_pct": mdata.get("dist_to_52w_high_pct", 100.0),
            "delta_target_30d_pct": hist_ctx.get("delta_target_30d_pct", 0.0),
            "invalidation_price": inv_price_float,
            "invalidation_price_str": f"{format_currency_value(inv_price_float, mdata['currency'])} {mdata['currency']}" if inv_price_float else "—",
            "invalidation_dist_pct": inv_dist_pct,
            "history_minitrend": get_ticker_signal_history(sym, limit=3),
            "time_horizon": "1-3 měsíce",
            "signal": signal,
            "signal_rank": sig_rank,
            "signal_class": normalize_signal_class(signal),
            "progress_class": normalize_progress_class(signal),
            "probability": confidence,
            "confidence": confidence,
            "impact_direction": impact_direction,
            "reasoning": reasoning,
            "chart_url": chart_url,
        })

    # Automatické řazení od nejlepších výsledků po nejhorší (Strong Buy -> Buy -> Hold -> Sell -> Strong Sell)
    final_cards.sort(key=lambda c: (c["signal_rank"], c["confidence"], c["change_pct_raw"]), reverse=True)

    # 8.5. Výpočet denních posunů oproti předchozímu skenu
    current_date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    final_cards, change_stats = compute_daily_changes(final_cards, current_scan_date=current_date_str)
    logger.info(f"Denní posuny vyhodnoceny: {change_stats.get('total_changed', 0)} změn (⬆️ {change_stats.get('upgrades', 0)} upgradů, ⬇️ {change_stats.get('downgrades', 0)} downgradů).")

    # 9. Vygenerování a uložení index.html
    elapsed = time.time() - scan_start
    if elapsed >= 60:
        scan_duration_str = f"{int(elapsed // 60)} min {int(elapsed % 60)} s"
    else:
        scan_duration_str = f"{elapsed:.1f} s"

    data_sources_str = "XTB Market Catalog • Yahoo Finance Realtime • Yahoo Analyst Consensus & Calendars • Yahoo Financial News RSS • Google Gemini 3.5 AI"
    html_output = build_html_report(final_cards, is_demo=is_demo, scan_duration=scan_duration_str, data_sources=data_sources_str, change_stats=change_stats)

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
            "ai_model": GEMINI_MODEL if not is_demo else f"{GEMINI_MODEL} (Záložní Quant)",
            "counts": {
                "total": len(final_cards),
                "strong_buy": len([c for c in final_cards if c["signal"] == "STRONG BUY"]),
                "buy": len([c for c in final_cards if c["signal"] == "BUY"]),
                "hold": len([c for c in final_cards if c["signal"] == "HOLD"]),
                "sell": len([c for c in final_cards if c["signal"] == "SELL"]),
                "strong_sell": len([c for c in final_cards if c["signal"] == "STRONG SELL"]),
                "total_changed": change_stats.get("total_changed", 0),
                "upgrades": change_stats.get("upgrades", 0),
                "downgrades": change_stats.get("downgrades", 0),
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
