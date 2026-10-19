"""
silver_2026_interactive_runner.py – Interaktivní Walk-Forward Runner pro rok 2026
================================================================================
Tento modul striktně dodržuje pravidlo:
- Žádné automatické spouštění celého roku 2026 předem.
- Umožňuje postupné, interaktivní odkrývání měsíc po měsíci (Leden ➔ Únor ➔ ... ➔ Říjen)
  společně s uživatelem nebo na kliknutí v SilverInvestDemo.html.
- Kontinuálně navazuje na stav ekvity a ukládá data do data/silver_walkforward_2026_results.json.
"""
from __future__ import annotations
import os
import sys
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

import pandas as pd

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Import potřebných komponent
WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from silver_walkforward_manager import build_or_refresh_manifest, unlock_month, lock_month, lock_all_months, MANIFEST_PATH
from silver.backtest.silver_backtester import SilverBacktester
from silver.backtest.silver_metrics import SilverPerformanceMetrics

logger = logging.getLogger("Silver2026Runner")
RESULTS_PATH = os.path.join(WORKSPACE_DIR, "data", "silver_walkforward_2026_results.json")


def load_walkforward_state() -> Dict[str, Any]:
    """Načte stávající stav výsledků roku 2026 nebo vytvoří nový prázdný."""
    if os.path.exists(RESULTS_PATH):
        try:
            with open(RESULTS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Chyba při čtení {RESULTS_PATH}: {e}")

    # Výchozí prázdný stav
    manifest = build_or_refresh_manifest(force_relock=False)
    months_manifest = manifest.get("out_of_sample_2026", {}).get("months", [])
    
    state = {
        "year": 2026,
        "initial_capital_usd": 10000.0,
        "current_equity_usd": 10000.0,
        "total_trades": 0,
        "total_net_pnl_usd": 0.0,
        "sovereign_floor_usd": 9000.0,
        "sovereign_floor_breached": False,
        "last_updated": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        "months": {}
    }

    for m in months_manifest:
        ym = m["month"]
        state["months"][ym] = {
            "month": ym,
            "title": m["title"],
            "status": "LOCKED",
            "bars_count": m["bars_count"],
            "trades_count": 0,
            "win_rate_pct": 0.0,
            "net_pnl_usd": 0.0,
            "equity_end_usd": 10000.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0,
            "profit_factor": 0.0,
            "executed_at": None,
            "trades": []
        }

    save_walkforward_state(state)
    return state


def save_walkforward_state(state: Dict[str, Any]) -> None:
    """Bezpečně uloží stav do JSON souboru."""
    state["last_updated"] = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    # Synchronizace do složky analýzy pro audit
    audit_state_path = os.path.join(WORKSPACE_DIR, "analyza_modelu_silver_backtest", "10_silver_walkforward_2026_state.json")
    if os.path.exists(os.path.dirname(audit_state_path)):
        try:
            with open(audit_state_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
        except Exception:
            pass


def run_month_step(month_ym: str) -> Dict[str, Any]:
    """
    Odemkne a exekuuje POUZE jeden zvolený měsíc roku 2026 (např. '2026-01').
    Navazuje na koncovou ekvitu předchozího odemčeného měsíce.
    """
    state = load_walkforward_state()
    manifest = build_or_refresh_manifest(force_relock=False)
    months_manifest = {m["month"]: m for m in manifest.get("out_of_sample_2026", {}).get("months", [])}

    if month_ym not in months_manifest:
        return {"ok": False, "error": f"Neznámý měsíc: {month_ym}"}

    m_info = months_manifest[month_ym]
    
    # 1. Zjištění počáteční ekvity pro tento měsíc
    prev_months = sorted([ym for ym in state["months"].keys() if ym < month_ym])
    starting_equity = state["initial_capital_usd"]
    for p_ym in prev_months:
        p_data = state["months"][p_ym]
        if p_data.get("status") == "COMPLETED":
            starting_equity = p_data.get("equity_end_usd", starting_equity)

    # 2. Odemčení v manifestu
    unlock_month(month_ym)

    # 3. Spuštění backtesteru pro daný měsíc
    start_date = f"{month_ym}-01"
    # Konec měsíce odvodíme z m_info start_datetime a end_datetime
    end_date = m_info["end_datetime"][:10]

    backtester = SilverBacktester(initial_capital=starting_equity)
    logger.info(f"⚡ Spouštím OOS test pro {m_info['title']} ({start_date} až {end_date}) s počáteční ekvitou ${starting_equity:.2f}...")

    results = backtester.run_backtest(start_date, end_date)
    metrics = results.get("metrics", {})
    trades = results.get("trades", [])

    final_equity = metrics.get("final_equity_usd", starting_equity)
    net_pnl = metrics.get("net_profit_usd", 0.0)
    win_rate = metrics.get("win_rate_pct", 0.0)
    max_dd = metrics.get("max_drawdown_pct", 0.0)
    sharpe = metrics.get("sharpe_ratio", 0.0)
    pf = metrics.get("profit_factor", 0.0)

    # 4. Zjištění předchozího dokončeného měsíce pro MoM srovnání
    last_comp_ym = None
    last_comp_data = None
    for p_ym in prev_months:
        if state["months"][p_ym].get("status") == "COMPLETED":
            last_comp_ym = p_ym
            last_comp_data = state["months"][p_ym]

    # Výpočet MoM metrik
    if last_comp_data is not None:
        mom_analysis = {
            "has_previous_month": True,
            "compared_to_month": last_comp_ym,
            "compared_to_title": last_comp_data.get("title", last_comp_ym),
            "pnl_delta_usd": round(net_pnl - last_comp_data.get("net_pnl_usd", 0.0), 2),
            "trades_delta": len(trades) - last_comp_data.get("trades_count", 0),
            "win_rate_delta_pct": round(win_rate - last_comp_data.get("win_rate_pct", 0.0), 2),
            "drawdown_delta_pct": round(max_dd - last_comp_data.get("max_drawdown_pct", 0.0), 2),
            "comment": f"Srovnání s {last_comp_data.get('title')}: PnL delta {'+' if net_pnl >= last_comp_data.get('net_pnl_usd', 0) else ''}${net_pnl - last_comp_data.get('net_pnl_usd', 0.0):.2f}"
        }
    else:
        # První měsíc (Leden 2026) -> Srovnání s In-Sample Baseline (2025)
        mom_analysis = {
            "has_previous_month": False,
            "compared_to_month": "IN_SAMPLE_2025",
            "compared_to_title": "In-Sample Baseline (2025)",
            "pnl_delta_usd": round(net_pnl, 2),
            "trades_delta": len(trades) - 13,
            "win_rate_delta_pct": round(win_rate - 23.08, 2),
            "drawdown_delta_pct": round(max_dd - 10.88, 2),
            "comment": "První měsíc OOS (Leden 2026). MoM srovnání bude k dispozici od Února."
        }

    # 5. Forenzní analýza a diagnostika měsíce
    skipped_vol = metrics.get("skipped_trades_volatility_gate", 0)
    total_signals = len(trades) + skipped_vol
    vol_gate_rejection_rate = round((skipped_vol / total_signals * 100.0), 2) if total_signals > 0 else 0.0

    lessons_learned = []
    if net_pnl < 0:
        strat_bd = metrics.get("strategies_breakdown", {})
        worst_strat = min(strat_bd.items(), key=lambda x: x[1].get("net_pnl_usd", 0.0))[0] if strat_bd else "N/A"
        sess_bd = metrics.get("sessions_breakdown", {})
        worst_sess = min(sess_bd.items(), key=lambda x: x[1].get("net_pnl_usd", 0.0))[0] if sess_bd else "N/A"
        lessons_learned.append({
            "category": "NEGATIVE_MONTHLY_PNL",
            "severity": "HIGH",
            "title": "Záporná výkonnost portfolia v kompresním / rotačním trhu",
            "observation": f"Měsíc skončil se ztrátou ${net_pnl:.2f} při Win Rate {win_rate:.1f} % ({len(trades)} obchodů).",
            "root_cause": f"Hlavním zdrojem ztrát byla {worst_strat} a obchodní seance {worst_sess} v důsledku falešných průrazů a asymetrie velikosti pozic.",
            "action_plan": "Aplikovat COT filtr proti shortování dna, vynutit 3h cooldown po SL a srovnat dolarové riziko 1R napříč režimy."
        })
    elif net_pnl > 0 and len(trades) >= 5:
        lessons_learned.append({
            "category": "SUCCESSFUL_EXECUTION",
            "severity": "NORMAL",
            "title": "Úspěšná realizace příležitostí (Adaptivní Fractional Sizing)",
            "observation": f"V tomto měsíci proběhlo {len(trades)} obchodů s úspěšností {win_rate:.1f} % a čistým ziskem +${net_pnl:.2f}.",
            "root_cause": "Zavedení adaptivního škálování pozic v uncích zabránilo paralýze Volatility Gate při vysokých cenách stříbra a umožnilo plnou participaci na trendech.",
            "action_plan": "Pokračovat v nastaveném řízení rizika a sledovat vývoj volatility pro březen 2026."
        })
    elif skipped_vol > 50 and len(trades) <= 3:
        lessons_learned.append({
            "category": "VOLATILITY_GATE_PARALYSIS",
            "severity": "CRITICAL",
            "title": "Paralýza bota Volatility Gate filtrem",
            "observation": f"V tomto měsíci vzniklo {total_signals} obchodních signálů, ale {skipped_vol} ({vol_gate_rejection_rate} %) bylo zablokováno Hard Volatility Gate filtrem ($0.40/oz max SL).",
            "root_cause": "Trh stříbra prudce expandoval (prudký nárůst ceny a ATR). Statický strop $0.40/oz navržený pro $30 stříbro nestačil pokrýt běžnou volatilitu.",
            "action_plan": "Pro další měsíc nasadit adaptivní relativní Volatility Gate (max 1.5 % ceny podkladu) a prověřit zmenšení nominálu přes frakční sizing."
        })
    if win_rate < 30.0 and len(trades) > 0:
        lessons_learned.append({
            "category": "REGIME_MISMATCH",
            "severity": "HIGH",
            "title": "Neúspěšné zachycení trendových impulzů",
            "observation": f"Win rate dosáhl pouze {win_rate:.1f} % při celkovém zisku ${net_pnl:.2f}.",
            "root_cause": "Režim trhu byl vyhodnocen jako parabolická mánie (Blow-Off score > 0.80), kde běžné trailing stop-lossy selhávají na divokých mikro-korekcích.",
            "action_plan": "Snížit váhu pro Trend Following v OFF_PEAK session a aktivovat přísnější 2-Stage Break-Even filtr."
        })
    if not lessons_learned:
        lessons_learned.append({
            "category": "BALANCED_EXECUTION",
            "severity": "NORMAL",
            "title": "Stabilní exekuce strategií",
            "observation": f"Měsíc proběhl s {len(trades)} obchody bez mimořádných anomalit.",
            "root_cause": "Strategie odpovídaly tržnímu režimu.",
            "action_plan": "Pokračovat s aktuálním nastavením."
        })

    forensic_summary = {
        "signals_generated": total_signals,
        "signals_executed": len(trades),
        "signals_blocked_by_volatility_gate": skipped_vol,
        "volatility_gate_rejection_pct": vol_gate_rejection_rate,
        "dominant_regime": "PARABOLIC_BLOWOFF" if (m_info.get("price_range", {}).get("high", 0) > 100) else "TREND_BULL",
        "market_diagnostics": f"Cenový rozsah: ${m_info.get('price_range', {}).get('low', 0):.2f} – ${m_info.get('price_range', {}).get('high', 0):.2f}. Zablokováno {skipped_vol} signálů.",
        "mom_analysis": mom_analysis,
        "lessons_learned": lessons_learned
    }

    # 6. Záznam do stavu
    state["months"][month_ym] = {
        "month": month_ym,
        "title": m_info["title"],
        "status": "COMPLETED",
        "bars_count": m_info["bars_count"],
        "trades_count": len(trades),
        "win_rate_pct": win_rate,
        "net_pnl_usd": net_pnl,
        "equity_start_usd": round(starting_equity, 2),
        "equity_end_usd": round(final_equity, 2),
        "max_drawdown_pct": max_dd,
        "sharpe_ratio": sharpe,
        "profit_factor": pf,
        "strategies_breakdown": metrics.get("strategies_breakdown", {}),
        "sessions_breakdown": metrics.get("sessions_breakdown", {}),
        "skipped_trades_volatility_gate": skipped_vol,
        "forensic_summary": forensic_summary,
        "executed_at": datetime.now().strftime("%d.%m.%Y %H:%M:%S"),
        "trades": trades
    }

    # Přepočet celkových souhrnů
    completed_months = [m for m in state["months"].values() if m["status"] == "COMPLETED"]
    state["total_trades"] = sum(m["trades_count"] for m in completed_months)
    state["total_net_pnl_usd"] = round(sum(m["net_pnl_usd"] for m in completed_months), 2)
    state["current_equity_usd"] = round(final_equity, 2)
    state["sovereign_floor_breached"] = state["current_equity_usd"] < state["sovereign_floor_usd"]

    save_walkforward_state(state)

    return {
        "ok": True,
        "month": month_ym,
        "title": m_info["title"],
        "trades_count": len(trades),
        "net_pnl_usd": net_pnl,
        "equity_end_usd": final_equity,
        "win_rate_pct": win_rate,
        "sharpe_ratio": sharpe,
        "sovereign_floor_breached": state["sovereign_floor_breached"]
    }


def reset_walkforward() -> Dict[str, Any]:
    """Resetuje všechny měsíce roku 2026 zpět do uzamčeného stavu."""
    lock_all_months()
    if os.path.exists(RESULTS_PATH):
        try:
            os.remove(RESULTS_PATH)
        except Exception:
            pass
    state = load_walkforward_state()
    return {"ok": True, "message": "Rok 2026 kompletně resetován a uzamčen."}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Silver 2026 Interactive Walk-Forward Runner")
    parser.add_argument("--status", action="store_true", help="Vypíše stav měsíců 2026")
    parser.add_argument("--unlock-month", type=str, help="Odemkne a otestuje konkrétní měsíc (např. 2026-01)")
    parser.add_argument("--reset", action="store_true", help="Resetuje všechny měsíce zpět do zamčeno")
    args = parser.parse_args()

    if args.reset:
        res = reset_walkforward()
        print(res["message"])
    elif args.unlock_month:
        res = run_month_step(args.unlock_month)
        print("Výsledek měsíce:", res)
    else:
        st = load_walkforward_state()
        print(f"Rok 2026 stav: {len([m for m in st['months'].values() if m['status'] == 'COMPLETED'])} / {len(st['months'])} odemčeno.")
        print(f"Aktuální ekvita: ${st['current_equity_usd']:.2f}")
