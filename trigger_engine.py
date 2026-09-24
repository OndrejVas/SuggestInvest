from typing import Dict, Any, List, Optional
from dividend_analyzer import analyze_ticker_dividend_history


def evaluate_asset_triggers(
    mdata: Dict[str, Any],
    fdata: Dict[str, Any],
    ddata: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Vyhodnotí deterministické indikátory, cílové ceny a triggery pro jedno aktivum.
    """
    price = mdata.get("price", 0.0)
    change_pct = mdata.get("change_pct", 0.0)
    year_high = mdata.get("year_high")
    year_low = mdata.get("year_low")
    currency = mdata.get("currency", "USD")
    asset_type = mdata.get("asset_type", "AKCIE")

    target_mean = fdata.get("target_mean")
    target_high = fdata.get("target_high")
    target_low = fdata.get("target_low")
    analysts_count = fdata.get("analysts_count")
    next_earnings_date = fdata.get("next_earnings_date")
    days_to_earnings = fdata.get("days_to_earnings")
    ex_dividend_date = fdata.get("ex_dividend_date")
    days_to_ex_dividend = fdata.get("days_to_ex_dividend")

    delta_1m = ddata.get("delta_1m")
    delta_3m = ddata.get("delta_3m")

    # 1. Výpočet Upside / Downside Gapu k cílové ceně
    target_upside_pct = None
    if target_mean is not None and price > 0:
        target_upside_pct = round(((target_mean - price) / price) * 100, 2)

    # Vzdálenost od 52w maxima v % (100 = na maximu)
    dist_to_52w_high_pct = 100.0
    if year_high and year_high > 0 and price > 0:
        dist_to_52w_high_pct = round((price / year_high) * 100, 1)

    # 2. Seznam aktivních triggerů z přesné taxonomie 9 schválených štítků
    triggers: List[Dict[str, str]] = []

    # A) Triggery konsenzu a valuace
    if target_upside_pct is not None:
        if target_upside_pct >= 20.0 and (analysts_count is None or analysts_count >= 5):
            triggers.append({
                "id": "CAT_HIGH_DISCOUNT",
                "label": "🎯 Vysoký diskont",
                "css_class": "trig-upside-high",
                "priority": 10
            })
        elif target_upside_pct <= 0.0:
            triggers.append({
                "id": "CAT_OVER_TARGET",
                "label": "⚠️ Nad cílem analytiků",
                "css_class": "trig-exhausted",
                "priority": 30
            })

    # B) Kalendářní triggery událostí (Hospodářské výsledky & Dividendy)
    if days_to_earnings is not None:
        if 0 <= days_to_earnings <= 7:
            triggers.append({
                "id": "CAT_EARNINGS_7D",
                "label": "⏳ Výsledky do 7 dní",
                "css_class": "trig-earnings-hot",
                "priority": 5
            })
        elif 8 <= days_to_earnings <= 21:
            triggers.append({
                "id": "CAT_EARNINGS_21D",
                "label": "📅 Výsledky do 21 dní",
                "css_class": "trig-earnings-warm",
                "priority": 25
            })

    if days_to_ex_dividend is not None and 0 <= days_to_ex_dividend <= 14:
        ex_label = f"💰 Ex-Div za {days_to_ex_dividend} dní" if days_to_ex_dividend > 0 else "💰 Ex-Div dnes"
        triggers.append({
            "id": "CAT_DIVIDEND_SOON",
            "label": ex_label,
            "css_class": "trig-dividend",
            "priority": 35
        })

    # C) Technické & Momentum triggery
    if change_pct >= 3.0 or (delta_1m is not None and delta_1m >= 10.0):
        triggers.append({
            "id": "CAT_STRONG_MOMENTUM",
            "label": "🚀 Silné momentum",
            "css_class": "trig-spike",
            "priority": 15
        })
    elif change_pct <= -3.0 and delta_3m is not None and delta_3m > 0:
        triggers.append({
            "id": "CAT_OVERSOLD_DIP",
            "label": "📉 Přeprodáno / Korekce",
            "css_class": "trig-dip",
            "priority": 18
        })

    if dist_to_52w_high_pct >= 97.0:
        triggers.append({
            "id": "CAT_ATH_TEST",
            "label": "🔥 Test 52w Maxima",
            "css_class": "trig-ath",
            "priority": 22
        })

    # D) České dividendové tituly BCPP
    if currency == "CZK" and asset_type == "AKCIE":
        triggers.append({
            "id": "CAT_BCPP_DIV",
            "label": "🇨🇿 BCPP Dividendy",
            "css_class": "trig-bcpp",
            "priority": 45
        })

    # E) Kvantitativní analýza Ex-Date historie (Dividend Capture & Recovery)
    dividend_analysis = None
    symbol = mdata.get("yahoo_symbol", "")
    if symbol and ((days_to_ex_dividend is not None and days_to_ex_dividend <= 45) or (currency == "CZK" and asset_type == "AKCIE")):
        dividend_analysis = analyze_ticker_dividend_history(symbol)
        if dividend_analysis:
            rec_code = dividend_analysis.get("recommendation_code")
            if rec_code == "CAPTURE":
                triggers.append({
                    "id": "CAT_DIV_CAPTURE",
                    "label": "🟢 Ex-Div: Držet (Zotavení)",
                    "css_class": "trig-dividend",
                    "priority": 12
                })
            elif rec_code == "HARVEST":
                triggers.append({
                    "id": "CAT_DIV_HARVEST",
                    "label": "🟡 Ex-Div: Prodat předem",
                    "css_class": "trig-dip",
                    "priority": 14
                })

    # Seřazení triggerů dle priority
    triggers.sort(key=lambda x: x["priority"])

    primary_catalyst_tag = triggers[0]["label"] if triggers else None

    # Forward-looking souhrn pro AI prompt
    ai_context_parts = []
    if target_mean is not None:
        upside_str = f"{target_upside_pct:+.1f} %" if target_upside_pct is not None else "N/A"
        ac_str = f" ({analysts_count} analytiků)" if analysts_count else ""
        ai_context_parts.append(f"Cílová cena analytiků: {target_mean:.2f} {currency} (potenciál {upside_str}){ac_str}")

    if days_to_earnings is not None:
        ai_context_parts.append(f"Kvartální výsledky: {next_earnings_date} (za {days_to_earnings} dní)")

    if days_to_ex_dividend is not None:
        ai_context_parts.append(f"Ex-dividenda: {ex_dividend_date} (za {days_to_ex_dividend} dní)")

    if dividend_analysis:
        ai_context_parts.append(
            f"Ex-Div taktika: {dividend_analysis['recommendation_badge']} "
            f"(zotavení do 15d: {dividend_analysis['recovery_rate_15d_pct']:.0f} %, medián: {dividend_analysis['median_recovery_days'] or '—'} d, 20d runup: {dividend_analysis['avg_pre_ex_runup_pct']:+.1f} %)"
        )

    if delta_1m is not None:
        ai_context_parts.append(f"1měsíční momentum: {delta_1m:+.2f} %")

    ai_forward_context = " • ".join(ai_context_parts) if ai_context_parts else "Standardní tržní vývoj bez bezprostředních kalendářních událostí."

    # Výpočet výchozí technické invalidace (stop-loss hladiny)
    default_invalidation_price = None
    if price > 0:
        if target_upside_pct is not None and target_upside_pct > 0:
            default_invalidation_price = round(price * 0.91, 2)
        elif target_upside_pct is not None and target_upside_pct <= 0:
            default_invalidation_price = round(price * 1.08, 2)
        else:
            default_invalidation_price = round(price * 0.92, 2)

    return {
        "target_mean": target_mean,
        "target_high": target_high,
        "target_low": target_low,
        "target_upside_pct": target_upside_pct,
        "analysts_count": analysts_count,
        "next_earnings_date": next_earnings_date,
        "days_to_earnings": days_to_earnings,
        "ex_dividend_date": ex_dividend_date,
        "days_to_ex_dividend": days_to_ex_dividend,
        "delta_1m": delta_1m,
        "delta_3m": delta_3m,
        "dist_to_52w_high_pct": dist_to_52w_high_pct,
        "invalidation_price": default_invalidation_price,
        "triggers": triggers,
        "trigger_ids": [t["id"] for t in triggers],
        "primary_catalyst_tag": primary_catalyst_tag,
        "ai_forward_context": ai_forward_context,
        "dividend_analysis": dividend_analysis,
    }
