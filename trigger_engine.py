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
    rv_21 = ddata.get("rv_21")
    atr_14 = ddata.get("atr_14")
    atr_pct = ddata.get("atr_pct")
    volume_shock_z = ddata.get("volume_shock_z")
    daily_turnover = ddata.get("daily_turnover")
    quant_invalidation_price = ddata.get("quant_invalidation_price")
    limit_buy_price = ddata.get("limit_buy_price")

    # 1. Výpočet Upside / Downside Gapu k cílové ceně
    target_upside_pct = None
    if target_mean is not None and price > 0:
        target_upside_pct = round(((target_mean - price) / price) * 100, 2)

    # Vzdálenost od 52w maxima v % (100 = na maximu)
    dist_to_52w_high_pct = 100.0
    if year_high and year_high > 0 and price > 0:
        dist_to_52w_high_pct = round((price / year_high) * 100, 1)

    # 2. Seznam aktivních triggerů z rozšířené výzkumné taxonomie
    triggers: List[Dict[str, str]] = []

    # A) Výzkumný katalyzátor 1: Objemový šok institucionální akumulace (LiMT Model - SRC-2)
    if volume_shock_z is not None and volume_shock_z >= 1.8 and price > 0:
        triggers.append({
            "id": "CAT_VOLUME_SHOCK",
            "label": "⚡ Objemový průraz (LiMT)",
            "css_class": "trig-volume-shock",
            "priority": 7
        })

    # B) Triggery konsenzu a valuace
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

    # C) Výzkumný katalyzátor 2: Pozitivní Sentiment Divergence (NLP Trading - SRC-5)
    # Cena konsoliduje nebo mírně vyklesává, ale fundamentální cíl a zájem prudce akceleruje
    if target_upside_pct is not None and target_upside_pct >= 15.0 and delta_1m is not None and -6.0 <= delta_1m <= 2.0:
        triggers.append({
            "id": "CAT_SENTIMENT_DIVERGENCE",
            "label": "🧠 Sentiment Divergence",
            "css_class": "trig-sentiment-divergence",
            "priority": 11
        })

    # D) Výzkumný katalyzátor 3: Sektorový diskont a relativní valuace (Pairs Trading - SRC-6)
    # Titul zaostává za svým 52w maximem více než sektor, ačkoliv má vysoký diskont
    if target_upside_pct is not None and target_upside_pct >= 22.0 and dist_to_52w_high_pct <= 82.0:
        triggers.append({
            "id": "CAT_PAIRS_DISCOUNT",
            "label": "⚖️ Sektorový diskont (Pairs)",
            "css_class": "trig-pairs-discount",
            "priority": 13
        })

    # D2) Výzkumný katalyzátor 4: Bankovní úrokový cyklus a expanze marží (Sadasivan - SRC-8)
    # Finanční instituce se stabilní volatilitou a ziskovostí v prostředí stabilních/vyšších sazeb
    is_financial = any(k in mdata.get("name", "").lower() or k in mdata.get("xtb_symbol", "").lower() for k in ["bank", "banco", "group", "finan", "reinsurance", "insurance", "pko", "pekao", "erste", "komb", "monet", "rbi", "raw"])
    if is_financial and target_upside_pct is not None and target_upside_pct >= 8.0 and (rv_21 is not None and rv_21 <= 38.0):
        triggers.append({
            "id": "CAT_FINANCIAL_CYCLE",
            "label": "🏛️ Úrokový cyklus (NIM)",
            "css_class": "trig-financial-cycle",
            "priority": 12
        })

    # E) Kalendářní triggery událostí (Hospodářské výsledky & Dividendy)
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

    # F) Technické & Momentum triggery
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

    # G) České dividendové tituly BCPP
    if currency == "CZK" and asset_type == "AKCIE":
        triggers.append({
            "id": "CAT_BCPP_DIV",
            "label": "🇨🇿 BCPP Dividendy",
            "css_class": "trig-bcpp",
            "priority": 45
        })

    # H) Kvantitativní analýza Ex-Date historie (Dividend Capture & Recovery)
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

    if volume_shock_z is not None and volume_shock_z >= 1.5:
        ai_context_parts.append(f"Institucionální objemový šok: Z={volume_shock_z:+.2f} (akumulační průraz)")

    if rv_21 is not None:
        ai_context_parts.append(f"Realizovaná volatilita 21d: {rv_21:.1f} % (ATR: {atr_pct or 0:.1f} %)")

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

    # 3. Výpočet vědecké dynamické invalidace (Stop-Loss dle Diffusion IVS / VaR99% - SRC-4)
    if quant_invalidation_price and quant_invalidation_price > 0:
        default_invalidation_price = quant_invalidation_price
    elif price > 0:
        default_invalidation_price = round(price * 0.92, 2)
    else:
        default_invalidation_price = None

    # 4. Kvantilové exekuční pásmo vstupu (OrderFusion+ - SRC-3)
    if limit_buy_price is None and price > 0:
        limit_buy_price = round(price * 0.99, 2)
    limit_buy_range = f"{limit_buy_price:.2f} – {price:.2f} {currency}" if (limit_buy_price and price > 0) else None

    # 5. Maximální bezpečná kapacita alokace dle 2% obratu (LiMT-APO - SRC-2)
    max_position_turnover_cap = round(0.02 * daily_turnover, 0) if daily_turnover else None

    # 6. Masuda Conviction Score (poměr růstu k volatilitě očištěný o katalyzátory - SRC-9)
    conviction_score = 0.0
    if target_upside_pct and target_upside_pct > 0 and rv_21 and rv_21 > 0:
        base_sharpe_proxy = target_upside_pct / max(rv_21, 10.0)
        catalyst_mult = 1.0 + (0.12 * len(triggers))
        conviction_score = round(base_sharpe_proxy * catalyst_mult, 3)

    # 7. Volatilitně adaptivní citlivost na sentiment (Ahmad - SRC-11)
    if rv_21 is not None:
        if rv_21 >= 25.0:
            sentiment_regime = "HIGH_VOLATILITY_FAST_NEWS"
        elif rv_21 <= 18.0:
            sentiment_regime = "DEFENSIVE_FUNDAMENTAL_DOMINANT"
        else:
            sentiment_regime = "BALANCED"
    else:
        sentiment_regime = "BALANCED"

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
        "rv_21": rv_21,
        "atr_14": atr_14,
        "atr_pct": atr_pct,
        "volume_shock_z": volume_shock_z,
        "daily_turnover": daily_turnover,
        "dist_to_52w_high_pct": dist_to_52w_high_pct,
        "invalidation_price": default_invalidation_price,
        "limit_buy_price": limit_buy_price,
        "limit_buy_range": limit_buy_range,
        "max_position_turnover_cap": max_position_turnover_cap,
        "conviction_score": conviction_score,
        "sentiment_regime": sentiment_regime,
        "triggers": triggers,
        "trigger_ids": [t["id"] for t in triggers],
        "primary_catalyst_tag": primary_catalyst_tag,
        "ai_forward_context": ai_forward_context,
        "dividend_analysis": dividend_analysis,
    }


def compute_top_5_conviction_basket(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Vybere denní TOP 5 aktiv s nejvyšším Masuda Sharpe Conviction skóre
    s diverzifikačním omezením (max 2 aktiva ze stejné měny/regionu).
    Váhy portfolia odpovídají Mean-Variance rozptylu: 25%, 25%, 20%, 15%, 15%.
    """
    eligible = [
        c for c in cards 
        if c.get("signal") in ["STRONG BUY", "BUY"] 
        and (c.get("conviction_score") or 0.0) > 0.0
    ]
    if not eligible:
        # Fallback na jakákoliv aktiva s nejvyšším conviction score
        eligible = [c for c in cards if (c.get("conviction_score") or 0.0) > 0.0]

    # Seřadit sestupně dle conviction_score
    eligible.sort(key=lambda x: x.get("conviction_score", 0.0), reverse=True)

    weights = ["25 %", "25 %", "20 %", "15 %", "15 %"]
    selected = []
    curr_counts = {}

    for c in eligible:
        curr = c.get("currency", "USD")
        if curr_counts.get(curr, 0) >= 2:
            continue
        
        idx = len(selected)
        w = weights[idx]
        curr_counts[curr] = curr_counts.get(curr, 0) + 1

        selected.append({
            "rank": idx + 1,
            "xtb_symbol": c.get("xtb_symbol"),
            "name": c.get("name"),
            "currency": curr,
            "target_upside": c.get("target_upside", "N/A"),
            "rv_21_str": c.get("rv_21_str", "N/A"),
            "conviction_score": f"{c.get('conviction_score', 0.0):.2f}",
            "portfolio_weight": w,
            "tactical_note": c.get("reasoning", "Vysoký poměr očekávaného růstu k volatilitě."),
            "catalysts": c.get("catalysts", [])[:2],
            "sentiment_regime": c.get("sentiment_regime", "BALANCED"),
        })

        if len(selected) == 5:
            break

    return selected


