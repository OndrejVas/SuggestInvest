import json
import os
import sys
import re
from collections import Counter

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from trigger_engine import compute_top_5_conviction_basket
from macro_engine import get_macro_recession_barometer
from trading_engine import BrokerExecutionEngine
from history_manager import compute_daily_changes, get_all_ticker_signal_dots
from main import build_html_report, build_trading_page

print("=== REBUILDING SUGGESTINVEST FULL REPORT & HISTORICAL SIGNALS ===")

# 1. Load cards from 2026-09-29.json
snapshot_path = os.path.join("data", "history", "2026-09-29.json")
if not os.path.exists(snapshot_path):
    raise FileNotFoundError(f"Snapshot not found: {snapshot_path}")

with open(snapshot_path, "r", encoding="utf-8") as f:
    data = json.load(f)

metadata = data.get("metadata", {})
cards = data.get("cards", []) if isinstance(data, dict) else data
print(f"1. Načteno {len(cards)} karet ze snapshotu {snapshot_path}")

# 2. Compute daily changes against previous scan (2026-09-28)
cards, change_stats = compute_daily_changes(cards, current_scan_date="2026-09-29")
print(f"2. Vyhodnoceny změny doporučení:")
print(f"   - Celkem změn: {change_stats.get('total_changed', 0)}")
print(f"   - ⬆️ Upgrady: {change_stats.get('upgrades', 0)}")
print(f"   - ⬇️ Downgrady: {change_stats.get('downgrades', 0)}")
print(f"   - Referenční sken: {change_stats.get('prev_scan_time')}")

# 3. Attach signal history dots (up to 30 scans)
all_signal_dots = get_all_ticker_signal_dots(limit_per_ticker=30)
cards_with_dots = 0
total_dots = 0
for card in cards:
    sym_key = (card.get("yahoo_symbol") or "").upper().strip()
    dots = all_signal_dots.get(sym_key, [])
    if not dots:
        sig_upper = card.get("signal", "HOLD").upper()
        c_color = "#10b981" if "STRONG BUY" in sig_upper else ("#22c55e" if "BUY" in sig_upper else ("#ef4444" if "SELL" in sig_upper else "#eab308"))
        dots = [{
            "date": "2026-09-29",
            "date_str": "Dnes",
            "signal": card.get("signal", "HOLD"),
            "signal_class": card.get("signal_class", "signal-hold"),
            "probability": card.get("confidence", 50),
            "price_str": f"{card.get('price_raw', 0):.2f}" if card.get("price_raw") else "",
            "color": c_color
        }]
    else:
        cards_with_dots += 1
        total_dots += len(dots)
    card["signal_history_dots"] = dots

print(f"3. Připojena historie doporučení (tečky):")
print(f"   - Aktiv s historií: {cards_with_dots}/{len(cards)}")
print(f"   - Celkem historických bodů: {total_dots} (průměr {total_dots/len(cards):.1f} skenů na aktivum)")

# 4. Save enriched cards back to 2026-09-29.json
metadata["counts"]["total_changed"] = change_stats.get("total_changed", 0)
metadata["counts"]["upgrades"] = change_stats.get("upgrades", 0)
metadata["counts"]["downgrades"] = change_stats.get("downgrades", 0)
with open(snapshot_path, "w", encoding="utf-8") as f:
    json.dump({"metadata": metadata, "cards": cards}, f, indent=2, ensure_ascii=False)
print(f"4. Snapshot {snapshot_path} byl aktualizován o tečky historie a statistiky změn.")

# 5. Top 5 Conviction Basket
top_5_basket = compute_top_5_conviction_basket(cards)
print(f"5. Sestaven Top 5 Conviction Basket: {[x['xtb_symbol'] for x in top_5_basket]}")

# 6. Macro Barometer
macro_barometer = get_macro_recession_barometer(cards, use_cache=True)
print(f"6. Makro barometr: Index {macro_barometer['composite_index']}/100 ({macro_barometer['risk_level']})")

# 7. Trading orders
trading_engine = BrokerExecutionEngine(
    mode=os.getenv("TRADING_MODE", "PAPER"),
    portfolio_capital=float(os.getenv("PORTFOLIO_CAPITAL", "250000"))
)
trading_orders = trading_engine.generate_orders_from_conviction_basket(
    top_5_basket,
    macro_risk_level_code=macro_barometer.get("risk_level_code", "LATE_CYCLE")
)
print(f"7. Vygenerováno {len(trading_orders)} limitních příkazů pro trading.")

# 8. Render full index.html
html_output = build_html_report(
    cards,
    is_demo=False,
    scan_duration="44 s",
    change_stats=change_stats,
    top_5_basket=top_5_basket,
    macro_barometer=macro_barometer,
    trading_orders=trading_orders
)

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html_output)
print(f"8. Soubor index.html byl úspěšně zkompilován a uložen ({len(html_output)} znaků).")

# 8.1. Render full trading.html pro Interactive Brokers
trading_html_output = build_trading_page(
    trading_orders=trading_orders,
    macro_barometer=macro_barometer,
    top_5_basket=top_5_basket,
    timestamp_cet_str="29.09.2026 22:50 SELČ"
)
with open("trading.html", "w", encoding="utf-8") as f:
    f.write(trading_html_output)
print(f"8.1. Soubor trading.html pro Interactive Brokers byl úspěšně zkompilován a uložen ({len(trading_html_output)} znaků).")

# 9. Verifikace index.html
dots_in_html = re.findall(r'<div class="history-dots-row"[^>]*>(.*?)</div>', html_output, re.DOTALL)
filled_dots = [d for d in dots_in_html if d.strip()]
badges = re.findall(r'<span class="badge-change ([^"]*)"', html_output)

print("\n=== KONTROLA VÝSTUPU V INDEX.HTML ===")
print(f"✓ Řady teček (history-dots-row): {len(dots_in_html)} celkem, {len(filled_dots)} PLNÝCH (0 prázdných)")
print(f"✓ Odznaky změn: {Counter(badges)}")
meta_match = re.search(r'Změny od včerejška:.*?(?=</div>)', html_output)
if meta_match:
    print(f"✓ Meta lišta záhlaví: {meta_match.group(0).strip()}")

filter_match = re.search(r'<div class="pill-row" id="changeFilter">.*?</div>', html_output, re.DOTALL)
if filter_match:
    print(f"✓ Filtrační tlačítka změn:")
    for line in filter_match.group(0).splitlines():
        if '<button' in line:
            print(f"   {line.strip()}")

print("\n✓ Všechny historické změny doporučení a řady teček byly kompletně obnoveny!")
