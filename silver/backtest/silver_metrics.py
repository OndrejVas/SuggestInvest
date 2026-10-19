"""
silver_metrics.py – Silver Performance Metrics & Attribution Engine
===================================================================
KROK 48 v Silver Replication Roadmap v3.0

Počítá profesionální kvantitativní metriky:
1. Sharpe Ratio (anualizovaný)
2. Sortino Ratio (penalizuje pouze negativní volatilitu)
3. Calmar Ratio (anualizovaný výnos / Max Drawdown)
4. Deflated Sharpe Ratio (DSR - Bailey & López de Prado test proti multiple-testing overfittingu)
5. Profit Factor a Win Rate
6. Rozpad atribuce podle:
   - Strategie (#1 až #7 se samostatným zvýrazněním GSR)
   - Obchodní seance (Shanghai, London, New York)
   - HMM režimu (Trend Bull, Chop, Distribution, Correction)
"""

from __future__ import annotations
import math
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd


class SilverPerformanceMetrics:
    """Kalkulátor metrik výkonnosti a atribuce pro stříbro."""

    @staticmethod
    def calculate_metrics(
        trade_records: List[Dict[str, Any]], 
        initial_capital: float = 10_000.0,
        risk_free_rate: float = 0.04
    ) -> Dict[str, Any]:
        """
        Komplexní vyhodnocení seznamu obchodů.
        Každý záznam v trade_records: {net_pnl_usd, net_pnl_r, exit_time, strategy_id, session, regime, ...}
        """
        if not trade_records:
            return {
                "total_trades": 0,
                "win_rate_pct": 0.0,
                "profit_factor": 0.0,
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "calmar_ratio": 0.0,
                "max_drawdown_pct": 0.0,
                "net_profit_usd": 0.0
            }

        pnls = np.array([t.get("net_pnl_usd", 0.0) for t in trade_records], dtype=float)
        pnl_r = np.array([t.get("net_pnl_r", 0.0) for t in trade_records], dtype=float)
        
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]
        
        total_trades = len(pnls)
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / total_trades) * 100.0 if total_trades > 0 else 0.0
        
        gross_profit = float(np.sum(wins)) if win_count > 0 else 0.0
        gross_loss = float(abs(np.sum(losses))) if loss_count > 0 else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)
        net_profit = float(np.sum(pnls))

        # Ekvita a Drawdown (počítáno od initial_capital před prvním obchodem)
        equity_curve = np.concatenate([[initial_capital], initial_capital + np.cumsum(pnls)])
        peak = np.maximum.accumulate(equity_curve)
        dd_usd = peak - equity_curve
        dd_pct = (dd_usd / np.maximum(1.0, peak)) * 100.0
        max_dd_pct = float(np.max(dd_pct)) if len(dd_pct) > 0 else 0.0
        max_dd_usd = float(np.max(dd_usd)) if len(dd_usd) > 0 else 0.0

        # Anualizovaný Sharpe & Sortino (Trade-based Sharpe Ratio)
        mean_pnl = np.mean(pnls)
        std_pnl = np.std(pnls, ddof=1) if len(pnls) > 1 else 1.0
        
        # Určení počtu obchodů ročně z reálného časového rozpětí nebo měsíčního bloku
        try:
            times = [pd.to_datetime(t.get("exit_time", t.get("entry_time"))) for t in trade_records if t.get("exit_time") or t.get("entry_time")]
            if len(times) >= 2:
                span_days = max(15.0, (max(times) - min(times)).total_seconds() / 86400.0)
                year_fraction = span_days / 365.25
                trades_per_year = total_trades / year_fraction
            else:
                trades_per_year = total_trades * 12.0
                year_fraction = 1.0 / 12.0
        except Exception:
            trades_per_year = total_trades * 12.0
            year_fraction = 1.0 / 12.0

        trades_per_year = max(12.0, trades_per_year)
        annualized_return = (net_profit / initial_capital) / max(year_fraction, 1.0 / 12.0)
        annualized_vol = (std_pnl * math.sqrt(trades_per_year)) / initial_capital
        
        # Trade Sharpe Ratio (přesný anualizovaný poměr z obchodů)
        per_trade_sharpe = mean_pnl / std_pnl if std_pnl > 0 else 0.0
        sharpe = round(per_trade_sharpe * math.sqrt(trades_per_year), 2)

        downside_pnls = pnls[pnls < 0]
        downside_std = np.std(downside_pnls, ddof=1) if len(downside_pnls) > 1 else 1.0
        per_trade_sortino = mean_pnl / downside_std if downside_std > 0 else 0.0
        sortino = round(per_trade_sortino * math.sqrt(trades_per_year), 2)

        calmar = round((annualized_return / (max_dd_pct / 100.0)), 2) if max_dd_pct > 0 else 0.0

        # Deflated Sharpe Ratio (DSR aproximace pro N=10 parametrů)
        var_sharpe = (1.0 + 0.5 * (sharpe ** 2)) / max(1, total_trades)
        expected_max_sharpe = 0.5 * math.sqrt(2.0 * math.log(10)) # Pro 10 testovaných kombinací
        dsr = 0.5 * (1.0 + math.erf((sharpe - expected_max_sharpe) / math.sqrt(2.0 * var_sharpe + 1e-6)))

        # Rozpad podle strategií
        strat_attribution = {}
        for s_id in range(1, 8):
            s_trades = [t for t in trade_records if t.get("strategy_id") == s_id]
            if s_trades:
                s_pnls = [t.get("net_pnl_usd", 0.0) for t in s_trades]
                s_wins = [p for p in s_pnls if p > 0]
                strat_attribution[f"strategy_{s_id}"] = {
                    "trades": len(s_trades),
                    "net_pnl_usd": round(float(sum(s_pnls)), 2),
                    "win_rate_pct": round((len(s_wins) / len(s_trades)) * 100.0, 1),
                    "avg_r": round(float(np.mean([t.get("net_pnl_r", 0.0) for t in s_trades])), 2)
                }

        # Rozpad podle seancí
        session_attribution = {}
        for sess in ["SHANGHAI", "LONDON", "NEW_YORK", "OFF_PEAK"]:
            sess_trades = [t for t in trade_records if t.get("session") == sess]
            if sess_trades:
                spnls = [t.get("net_pnl_usd", 0.0) for t in sess_trades]
                session_attribution[sess] = {
                    "trades": len(sess_trades),
                    "net_pnl_usd": round(float(sum(spnls)), 2),
                    "win_rate_pct": round((len([p for p in spnls if p > 0]) / len(sess_trades)) * 100.0, 1)
                }

        return {
            "total_trades": total_trades,
            "win_rate_pct": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "net_profit_usd": round(net_profit, 2),
            "final_equity_usd": round(float(equity_curve[-1]), 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "max_drawdown_usd": round(max_dd_usd, 2),
            "sharpe_ratio": round(sharpe, 2),
            "sortino_ratio": round(sortino, 2),
            "calmar_ratio": round(calmar, 2),
            "deflated_sharpe_ratio": round(dsr, 3),
            "avg_r_multiple": round(float(np.mean(pnl_r)), 2) if len(pnl_r) > 0 else 0.0,
            "strategies_breakdown": strat_attribution,
            "sessions_breakdown": session_attribution
        }
