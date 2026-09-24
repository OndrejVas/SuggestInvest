from typing import Dict, Any, List, Optional


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

    # 2. Seznam aktivních triggerů
    triggers: List[Dict[str, str]] = []

    # A) Triggery cílových cen analytiků
    if target_upside_pct is not None:
        if target_upside_pct >= 25.0:
            triggers.append({
                "id": "ANALYST_STRONG_UPSIDE",
                "label": f"🎯 Cíl +{target_upside_pct:.1f} %",
                "css_class": "trig-upside-high",
                "priority": 10
            })
        elif target_upside_pct >= 15.0:
            triggers.append({
                "id": "ANALYST_MODERATE_UPSIDE",
                "label": f"🎯 Cíl +{target_upside_pct:.1f} %",
                "css_class": "trig-upside-med",
                "priority": 20
            })
        elif target_upside_pct <= -5.0:
            triggers.append({
                "id": "ANALYST_EXHAUSTED",
                "label": f"⚠️ Nad cílem ({target_upside_pct:.1f} %)",
                "css_class": "trig-exhausted",
                "priority": 30
            })

    # B) Kalendářní triggery (Hospodářské výsledky & Dividendy)
    if days_to_earnings is not None:
        if 0 <= days_to_earnings <= 7:
            day_text = "Dnes" if days_to_earnings == 0 else ("Zítra" if days_to_earnings == 1 else f"za {days_to_earnings} d")
            triggers.append({
                "id": "EARNINGS_IMMINENT",
                "label": f"⏳ Výsledky {day_text}",
                "css_class": "trig-earnings-hot",
                "priority": 5
            })
        elif 8 <= days_to_earnings <= 21:
            triggers.append({
                "id": "EARNINGS_SOON",
                "label": f"📅 Výsledky za {days_to_earnings} d",
                "css_class": "trig-earnings-warm",
                "priority": 25
            })

    if days_to_ex_dividend is not None and 0 <= days_to_ex_dividend <= 14:
        ex_text = "Dnes" if days_to_ex_dividend == 0 else f"za {days_to_ex_dividend} d"
        triggers.append({
            "id": "DIVIDEND_SOON",
            "label": f"💰 Ex-Div {ex_text}",
            "css_class": "trig-dividend",
            "priority": 35
        })

    # C) Technické & Momentum triggery
    if change_pct >= 3.0:
        triggers.append({
            "id": "DAILY_SPIKE",
            "label": "🚀 Silné momentum",
            "css_class": "trig-spike",
            "priority": 15
        })
    elif change_pct <= -3.0:
        triggers.append({
            "id": "DAILY_DIP",
            "label": "📉 Korekce / Dip",
            "css_class": "trig-dip",
            "priority": 18
        })

    if year_high and price and price >= year_high * 0.98:
        triggers.append({
            "id": "ATH_52W",
            "label": "🔥 Test 52w Maxima",
            "css_class": "trig-ath",
            "priority": 22
        })

    if delta_1m is not None and delta_1m >= 10.0:
        triggers.append({
            "id": "MOMENTUM_1M_STRONG",
            "label": f"📈 1M trend +{delta_1m:.1f} %",
            "css_class": "trig-trend-up",
            "priority": 28
        })

    # D) Specifické třídy aktiv
    if currency == "CZK":
        triggers.append({
            "id": "BCPP_PRAGUE",
            "label": "🇨🇿 Pražská burza",
            "css_class": "trig-bcpp",
            "priority": 50
        })
    elif asset_type == "ETF":
        triggers.append({
            "id": "ETF_THEMATIC",
            "label": "📊 Pasivní ETF",
            "css_class": "trig-etf",
            "priority": 60
        })
    elif asset_type == "KRYPTO":
        triggers.append({
            "id": "CRYPTO_BENCH",
            "label": "⚡ Krypto Volatilita",
            "css_class": "trig-crypto",
            "priority": 40
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

    if delta_1m is not None:
        ai_context_parts.append(f"1měsíční momentum: {delta_1m:+.2f} %")

    ai_forward_context = " • ".join(ai_context_parts) if ai_context_parts else "Standardní tržní vývoj bez bezprostředních kalendářních událostí."

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
        "triggers": triggers,
        "trigger_ids": [t["id"] for t in triggers],
        "primary_catalyst_tag": primary_catalyst_tag,
        "ai_forward_context": ai_forward_context,
    }
