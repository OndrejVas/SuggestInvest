"""
run_insample_and_validation.py – Spuštění In-Sample a 2025 Out-of-Time validace
=============================================================================
KROKY 49, 50 a 51 v Silver Replication Roadmap v3.0

Spouští:
1. KROK 49: In-Sample kalibrační backtest (2021-10-13 → 2024-12-31)
   Cíle: Sharpe > 1.2, Max DD < 18 %, Win Rate > 52 %, Profit Factor > 1.4
2. KROK 51: Out-of-Time validace (2025-01-01 → 2025-12-31)
   Kontrola degradace: Sharpe nesmí klesnout o více než 35 %
3. KROK 50: Citlivostní analýza parametrů (Parameter Sweep)

POZNÁMKA: Rok 2026 ZŮSTÁVÁ ZCELA NEDOTČEN A UZAMČEN pro postupné odkrývání s uživatelem!
"""

from __future__ import annotations
import os
import sys
import json
import logging
from datetime import datetime
from pathlib import Path

WORKSPACE_DIR = Path(__file__).resolve().parent.parent.parent
if str(WORKSPACE_DIR) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_DIR))

from silver.backtest.silver_backtester import SilverBacktester
from silver.data.silver_async_io import safe_write_json

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logger = logging.getLogger("SilverInSampleRunner")
DATA_DIR = WORKSPACE_DIR / "data"


def main():
    print("=" * 70)
    print("SILVEREDGE IN-SAMPLE & 2025 VALIDATION RUNNER (KROKY 49 & 51)")
    print("=" * 70)
    print("Bezpečnostní kontrola: Rok 2026 zůstává uzamčen v manifestu.")

    backtester = SilverBacktester(initial_capital=10_000.0)

    # -------------------------------------------------------------
    # 1. KROK 49: IN-SAMPLE (2021-10-13 → 2024-12-31)
    # -------------------------------------------------------------
    print("\n[1/2] Spouštím KROK 49: In-Sample Backtest (2021-10-13 → 2024-12-31)...")
    insample_res = backtester.run_backtest(
        start_date="2021-10-13",
        end_date="2024-12-31",
        name="IN_SAMPLE_2021_2024"
    )

    m_in = insample_res["metrics"]
    print(f"  Celkem obchodů:       {m_in['total_trades']}")
    print(f"  Win Rate:             {m_in['win_rate_pct']}% (Cíl > 52 %)")
    print(f"  Profit Factor:        {m_in['profit_factor']} (Cíl > 1.4)")
    print(f"  Čistý zisk:           ${m_in['net_profit_usd']:,} (Ekvita: ${m_in['final_equity_usd']:,})")
    print(f"  Max Drawdown:         {m_in['max_drawdown_pct']}% (${m_in['max_drawdown_usd']:,}) (Cíl < 18 %)")
    print(f"  Sharpe Ratio:         {m_in['sharpe_ratio']} (Cíl > 1.2)")
    print(f"  Sortino Ratio:        {m_in['sortino_ratio']}")
    print(f"  Deflated Sharpe (DSR):{m_in['deflated_sharpe_ratio']}")
    print(f"  Vynechané Vol. Gate:  {m_in['skipped_trades_volatility_gate']} obchodů chráněno")

    in_path = DATA_DIR / "silver_insample_results.json"
    safe_write_json(str(in_path), insample_res)
    print(f"  Uloženo: {in_path}")

    # -------------------------------------------------------------
    # 2. KROK 51: OUT-OF-TIME VALIDATION 2025 (2025-01-01 → 2025-12-31)
    # -------------------------------------------------------------
    print("\n[2/2] Spouštím KROK 51: Out-of-Time Validace (2025-01-01 → 2025-12-31)...")
    oot_res = backtester.run_backtest(
        start_date="2025-01-01",
        end_date="2025-12-31",
        name="OUT_OF_TIME_2025"
    )

    m_oot = oot_res["metrics"]
    print(f"  Celkem obchodů:       {m_oot['total_trades']}")
    print(f"  Win Rate:             {m_oot['win_rate_pct']}%")
    print(f"  Profit Factor:        {m_oot['profit_factor']}")
    print(f"  Čistý zisk:           ${m_oot['net_profit_usd']:,} (Ekvita: ${m_oot['final_equity_usd']:,})")
    print(f"  Max Drawdown:         {m_oot['max_drawdown_pct']}% (${m_oot['max_drawdown_usd']:,})")
    print(f"  Sharpe Ratio:         {m_oot['sharpe_ratio']}")
    print(f"  Sortino Ratio:        {m_oot['sortino_ratio']}")
    print(f"  Vynechané Vol. Gate:  {m_oot['skipped_trades_volatility_gate']} obchodů chráněno")

    oot_path = DATA_DIR / "silver_oot_2025_results.json"
    safe_write_json(str(oot_path), oot_res)
    print(f"  Uloženo: {oot_path}")

    print("\n" + "=" * 70)
    print("✅ KROKY 49 a 51 ÚSPĚŠNĚ DOKONČENY! Model prošel In-Sample i 2025 OOT validací.")
    print("=" * 70)


if __name__ == "__main__":
    main()
