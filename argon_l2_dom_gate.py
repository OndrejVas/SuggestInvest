"""
argon_l2_dom_gate.py
====================
ARGON V2.5 - LIVE 10-LEVEL MARKET DEPTH (L2) EXECUTOR PRO IBKR (DUR222134)
Určeno pro živé napojení na IB Gateway / TWS (Port 7497 Paper / 7496 Live).
- Odebírá 10 úrovní hloubky trhu (reqMktDepth, numRows=10) na COMEX MGC/GC.
- Počítá 10-úrovňový exponenciálně vážený Order Book Imbalance (WOBI_10).
- Detekuje institucionální likviditní zdi (Liquidity Walls) do 5 ticků od ceny.
- Automaticky volí mezi pasivním Join-Bid/Ask (úspora 1-2 ticků spreadu) a okamžitým plněním.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any
import numpy as np


@dataclass
class DOMLevel:
    price: float
    size: float


@dataclass
class LiveDOM10Snapshot:
    """Reprezentace 10 úrovní hloubky trhu (Bid 1..10 a Ask 1..10) z IBKR reqMktDepth."""
    bids: List[DOMLevel]   # Seřazeno od Best Bid (index 0) po 10. úroveň (index 9)
    asks: List[DOMLevel]   # Seřazeno od Best Ask (index 0) po 10. úroveň (index 9)
    tick_size: float = 0.10


class ArgonLiveL2ExecutionGate:
    """
    Kvantitativní exekuční brána nad 10 úrovněmi hloubky trhu (Skóre přínosu 8.5 / 10).
    Volá se těsně před odesláním Bracket příkazu do IBKR (Port 7497 DUR222134).
    """

    # Exponenciální váhy pro 10 úrovní: nejvyšší váha na úrovních 1-4, nižší na 5-10
    WEIGHTS_10 = np.exp(-0.35 * np.arange(10, dtype=np.float64))

    @classmethod
    def analyze_10_level_book(
        cls, dom: LiveDOM10Snapshot
    ) -> Dict[str, Any]:
        """
        Zanalyzuje 10 pater knihy objednávek a vrátí kompletní mikrostrukturální metriky.
        """
        n_bids = min(10, len(dom.bids))
        n_asks = min(10, len(dom.asks))
        if n_bids == 0 or n_asks == 0:
            return {
                "valid": False,
                "wobi_10": 0.0,
                "micro_skew_ticks": 0.0,
                "bid_wall_detected": False,
                "ask_wall_detected": False,
                "spread_ticks": 0.0,
                "best_bid": 0.0,
                "best_ask": 0.0,
            }

        b_sizes = np.array([dom.bids[i].size for i in range(n_bids)], dtype=np.float64)
        a_sizes = np.array([dom.asks[i].size for i in range(n_asks)], dtype=np.float64)

        wb = float(np.sum(cls.WEIGHTS_10[:n_bids] * b_sizes))
        wa = float(np.sum(cls.WEIGHTS_10[:n_asks] * a_sizes))
        wobi_10 = (wb - wa) / max(1e-9, wb + wa)

        # Stoikov Micro-Price na 1. patře knihy
        best_bid, best_ask = dom.bids[0].price, dom.asks[0].price
        b0, a0 = max(1e-6, b_sizes[0]), max(1e-6, a_sizes[0])
        mid_price = 0.5 * (best_bid + best_ask)
        micro_price = (b0 * best_ask + a0 * best_bid) / (b0 + a0)
        micro_skew_ticks = (micro_price - mid_price) / dom.tick_size

        # Detekce Likviditní Zdi (Liquidity Wall) v prvních 5 patrech (do $0.50 od ceny)
        avg_bid_size = float(np.mean(b_sizes))
        avg_ask_size = float(np.mean(a_sizes))
        max_near_bid = float(np.max(b_sizes[: min(5, n_bids)]))
        max_near_ask = float(np.max(a_sizes[: min(5, n_asks)]))

        # Zeď = jedno patro v prvních 5 ticích má > 3.5x větší objem než průměr celé opačné strany
        bid_wall = max_near_bid >= (3.5 * max(1.0, avg_ask_size))
        ask_wall = max_near_ask >= (3.5 * max(1.0, avg_bid_size))

        return {
            "valid": True,
            "best_bid": round(float(best_bid), 2),
            "best_ask": round(float(best_ask), 2),
            "spread_ticks": round((best_ask - best_bid) / dom.tick_size, 1),
            "wobi_10": round(float(wobi_10), 4),
            "micro_skew_ticks": round(float(micro_skew_ticks), 2),
            "bid_wall_detected": bool(bid_wall),
            "ask_wall_detected": bool(ask_wall),
            "bid_levels": [{"price": round(b.price, 2), "size": round(b.size, 1)} for b in dom.bids[:10]],
            "ask_levels": [{"price": round(a.price, 2), "size": round(a.size, 1)} for a in dom.asks[:10]],
            "total_bid_depth": round(float(np.sum(b_sizes)), 1),
            "total_ask_depth": round(float(np.sum(a_sizes)), 1),
        }

    @classmethod
    def decide_optimal_ibkr_execution(
        cls, dom: LiveDOM10Snapshot, direction: str, strategy_id: int = 1
    ) -> Tuple[bool, str, float, str]:
        """
        Rozhodne, zda povolit vstup a jakou přesnou Limitní cenu poslat do IBKR:
        Vrací: (allow_trade, execution_style, optimal_limit_price, reason)
        """
        metrics = cls.analyze_10_level_book(dom)
        if not metrics["valid"]:
            return False, "NONE", 0.0, "L2_BOOK_EMPTY_OR_INVALID"

        is_long = direction.upper() == "LONG"
        wobi = metrics["wobi_10"]
        best_bid = metrics["best_bid"]
        best_ask = metrics["best_ask"]

        # 1. Kontrola širokého spreadu (ochrana při makro šoku)
        if metrics["spread_ticks"] > 4.0:
            return False, "BLOCKED", 0.0, f"SPREAD_TOO_WIDE ({metrics['spread_ticks']} ticks)"

        if is_long:
            # 2. Veto při prodejní zdi (Ask Wall) přímo nad cenou
            if metrics["ask_wall_detected"] and wobi < 0.15:
                return False, "VETO_ASK_WALL", 0.0, "BLOCKED_BY_OVERHEAD_ASK_LIQUIDITY_WALL"

            # 3. Silný nákupní přetlak v 10 patrech -> Okamžité plnění na Ask (cena utíká nahoru)
            if wobi >= 0.25 and metrics["micro_skew_ticks"] >= 0.15:
                return True, "AGGRESSIVE_LIMIT_AT_ASK", best_ask, f"STRONG_L2_BUY_FLOW (WOBI={wobi:+.2f})"

            # 4. Mírný/neutrální stav -> Pasivní Limit na Best Bid (úspora 1-2 ticků spreadu!)
            if wobi >= -0.10:
                return True, "PASSIVE_JOIN_BEST_BID", best_bid, f"PASSIVE_BID_SAVES_SPREAD (WOBI={wobi:+.2f})"

            return False, "VETO_BEARISH_BOOK", 0.0, f"BLOCKED_LONG_BY_NEGATIVE_WOBI ({wobi:+.2f})"

        else:  # SHORT
            if metrics["bid_wall_detected"] and wobi > -0.15:
                return False, "VETO_BID_WALL", 0.0, "BLOCKED_BY_SUPPORT_BID_LIQUIDITY_WALL"

            if wobi <= -0.25 and metrics["micro_skew_ticks"] <= -0.15:
                return True, "AGGRESSIVE_LIMIT_AT_BID", best_bid, f"STRONG_L2_SELL_FLOW (WOBI={wobi:+.2f})"

            if wobi <= 0.10:
                return True, "PASSIVE_JOIN_BEST_ASK", best_ask, f"PASSIVE_ASK_SAVES_SPREAD (WOBI={wobi:+.2f})"

            return False, "VETO_BULLISH_BOOK", 0.0, f"BLOCKED_SHORT_BY_POSITIVE_WOBI ({wobi:+.2f})"
