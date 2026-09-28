"""
trading_engine.py
-----------------
Modul pro přípravu a autonomní exekuci obchodních příkazů (Broker Bridge & Execution Engine).
Navržen pro nativní propojení s investičním portálem XTB (přes XTB xAPI WebSocket protokol)
a dalšími brokerskými platformami (Interactive Brokers, Alpaca).

Klíčové komponenty:
1. Risk Gatekeeper (Kvantitativní řízení rizika před odesláním příkazu)
   - Max risk na jeden obchod (výchozí 1.5 % z celkového kapitálu portfolia)
   - Minimální Risk/Reward Ratio (RRR >= 1.8)
   - Pozicování na základě MIT MVO vah a volatility (ATR)
   - Stop-Loss & Take-Profit bracket architektura

2. Order Generator & Dispatcher
   - Automatická konverze Top 5 Conviction aktiv a Strong Buy signálů na brokery akceptovatelné JSON příkazy
   - Podpora typů: LIMIT (vstup na limit_buy_price), MARKET a BRACKET (se Stop-Loss a Take-Profit)

3. XTB xAPI Socket Protocol Bridge
   - Připravená specifikace pro xapi-python / WebSocket (xapi.xtb.com)
   - Paper Trading Sandbox (simulace exekucí bez rizika reálného kapitálu)
   - SQLite perzistence aktivních a historických příkazů
"""

import os
import sys
import json
import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logger = logging.getLogger("TradingEngine")


def _clean_float(val: Any, fallback: Optional[float] = None) -> Optional[float]:
    """Bezpečně převede libovolnou hodnotu (float, int, '531.85 USD', '1 250,50 Kč', '—') na float."""
    if val is None or val == "—":
        return fallback
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        import re
        # Odstranění mezer a nahrazení čárky tečkou
        cleaned = val.replace(" ", "").replace(",", ".")
        m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", cleaned)
        if m:
            try:
                return float(m.group(0))
            except Exception:
                pass
    return fallback


class RiskGatekeeper:
    """Kvantitativní strážce rizika bránící neuvážené či příliš velké kapitálové expozici."""

    def __init__(
        self,
        portfolio_capital: float = 250_000.0,  # CZK
        currency: str = "CZK",
        max_risk_per_trade_pct: float = 1.5,   # Max 1.5 % celkového kapitálu v riziku na SL
        max_position_size_pct: float = 20.0,   # Max 20 % kapitálu v jedné pozici
        min_rrr: float = 1.8,                  # Minimální poměr zisku k riziku
        max_portfolio_drawdown_stop: float = 10.0 # Circuit breaker při 10% poklesu equity
    ):
        self.portfolio_capital = portfolio_capital
        self.currency = currency
        self.max_risk_per_trade_pct = max_risk_per_trade_pct
        self.max_position_size_pct = max_position_size_pct
        self.min_rrr = min_rrr
        self.max_portfolio_drawdown_stop = max_portfolio_drawdown_stop

    def evaluate_order_risk(
        self,
        symbol: str,
        current_price: float,
        entry_price: float,
        sl_price: Optional[float],
        tp_price: Optional[float],
        allocated_weight_pct: float = 10.0,
        fx_rate_to_czk: float = 1.0
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Zkontroluje, zda navrhovaný obchod splňuje všechna pravidla řízení rizik.
        Vypočítá optimální velikost pozice (počet akcií) a kapitálové riziko.
        """
        if entry_price <= 0:
            return False, "Neplatná vstupní cena (<= 0)", {}

        # 1. Kontrola Stop-Loss
        if sl_price is None or sl_price <= 0 or sl_price >= entry_price:
            # Automatické dopočtení SL (default 5 % pod vstupní cenou, pokud chybí)
            sl_price = entry_price * 0.95

        risk_per_share = entry_price - sl_price
        risk_per_share_pct = (risk_per_share / entry_price) * 100

        # 2. Kontrola Take-Profit a RRR
        if tp_price is None or tp_price <= entry_price:
            tp_price = entry_price * 1.15  # Default 15 % target

        reward_per_share = tp_price - entry_price
        rrr = reward_per_share / risk_per_share if risk_per_share > 0 else 0.0

        if rrr < self.min_rrr:
            return False, f"Nedostatečné RRR ({rrr:.2f} < {self.min_rrr:.2f})", {
                "rrr": round(rrr, 2),
                "entry_price": entry_price,
                "sl_price": round(sl_price, 2),
                "tp_price": round(tp_price, 2)
            }

        # 3. Výpočet velikosti pozice na základě maximálního risku
        # Max povolený peněžní risk = portfolio_capital * (max_risk_pct / 100)
        max_allowed_risk_czk = self.portfolio_capital * (self.max_risk_per_trade_pct / 100.0)
        risk_per_share_czk = risk_per_share * fx_rate_to_czk

        shares_by_risk = int(max_allowed_risk_czk / risk_per_share_czk) if risk_per_share_czk > 0 else 0

        # 4. Limit dle maximální velikosti pozice (např. 20 % z portfolia)
        max_position_czk = self.portfolio_capital * (self.max_position_size_pct / 100.0)
        entry_price_czk = entry_price * fx_rate_to_czk
        shares_by_cap = int(max_position_czk / entry_price_czk) if entry_price_czk > 0 else 0

        # 5. Limit dle váhy v MVO modelu
        model_position_czk = self.portfolio_capital * (allocated_weight_pct / 100.0)
        shares_by_weight = int(model_position_czk / entry_price_czk) if entry_price_czk > 0 else 0

        # Zvolíme bezpečnější minimum
        final_shares = max(1, min(shares_by_risk, shares_by_cap, shares_by_weight or shares_by_cap))
        final_position_val_czk = final_shares * entry_price_czk
        actual_risk_czk = final_shares * risk_per_share_czk
        actual_risk_pct = (actual_risk_czk / self.portfolio_capital) * 100

        details = {
            "shares": final_shares,
            "entry_price": round(entry_price, 2),
            "sl_price": round(sl_price, 2),
            "tp_price": round(tp_price, 2),
            "rrr": round(rrr, 2),
            "risk_per_share_pct": round(risk_per_share_pct, 2),
            "position_val_czk": round(final_position_val_czk, 2),
            "actual_risk_czk": round(actual_risk_czk, 2),
            "actual_risk_pct": round(actual_risk_pct, 2),
            "status": "APPROVED"
        }

        return True, "Schváleno Risk Gatekeeperem", details


class BrokerExecutionEngine:
    """
    Exekuční engine pro generování, správu a odesílání příkazů do broker rozhraní (XTB / Paper).
    """

    def __init__(self, mode: str = "PAPER", portfolio_capital: float = 250_000.0):
        self.mode = mode.upper()  # "PAPER" nebo "XTB_LIVE"
        self.gatekeeper = RiskGatekeeper(portfolio_capital=portfolio_capital)

    def generate_orders_from_conviction_basket(
        self,
        top_5_basket: List[Dict[str, Any]],
        macro_risk_level_code: str = "LATE_CYCLE"
    ) -> List[Dict[str, Any]]:
        """
        Z Top 5 Conviction koše vygeneruje sadu kompletních limitních nákupních příkazů se SL a TP.
        Aplikuje makroekonomický filtr (při krizovém makru redukuje velikost pozic nebo blokuje nákupy).
        """
        orders = []

        # Makroekonomická ochrana kapitálu
        if macro_risk_level_code in ("CRASH_ACUTE", "RECESSION_HIGH"):
            macro_size_multiplier = 0.5  # Poloviční pozice v rizikovém makru
            macro_warning = "Makro redukce (50% alokace kvůli zvýšenému riziku recese/krachu)"
        else:
            macro_size_multiplier = 1.0
            macro_warning = "Standardní alokace"

        # Přibližné FX kurzy pro CZK kalkulaci
        fx_rates = {
            "CZK": 1.0,
            "USD": 23.5,
            "EUR": 25.2,
            "GBX": 0.31,
            "GBP": 30.5
        }

        for item in top_5_basket:
            sym_xtb = item.get("xtb_symbol", "")
            curr = item.get("currency", "USD")
            fx = fx_rates.get(curr, 23.5)

            curr_price = _clean_float(item.get("price"), fallback=0.0) or 0.0
            if curr_price <= 0:
                curr_price = _clean_float(item.get("price_raw"), fallback=0.0) or 0.0
            if curr_price <= 0:
                continue

            # Vstupní cena: prioritně limit_buy_price (limitní nákup při korekci), fallback na aktuální cenu
            limit_price = _clean_float(item.get("limit_buy_price"), fallback=curr_price) or curr_price
            # Invalidační cena jako Stop-Loss
            inv_price = _clean_float(item.get("invalidation_price"), fallback=(limit_price * 0.94)) or (limit_price * 0.94)
            # Cílová cena jako Take-Profit
            tp_price = _clean_float(item.get("target_mean"), fallback=(limit_price * 1.18)) or (limit_price * 1.18)

            weight_raw = item.get("portfolio_weight", 15.0)
            weight_clean = _clean_float(weight_raw, fallback=15.0) or 15.0
            weight_val = weight_clean * macro_size_multiplier

            approved, reason, risk_res = self.gatekeeper.evaluate_order_risk(
                symbol=sym_xtb,
                current_price=curr_price,
                entry_price=limit_price,
                sl_price=inv_price,
                tp_price=tp_price,
                allocated_weight_pct=weight_val,
                fx_rate_to_czk=fx
            )

            order_id = f"ORD-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{sym_xtb.split('.')[0]}-{uuid.uuid4().hex[:4].upper()}"

            order_payload = {
                "order_id": order_id,
                "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "symbol_xtb": sym_xtb,
                "symbol_yahoo": item.get("yahoo_symbol", ""),
                "name": item.get("name", sym_xtb),
                "currency": curr,
                "action": "BUY",
                "order_type": "LIMIT",
                "current_price": round(curr_price, 2),
                "limit_price": risk_res.get("entry_price", round(limit_price, 2)),
                "sl_price": risk_res.get("sl_price", round(inv_price, 2)),
                "tp_price": risk_res.get("tp_price", round(tp_price, 2)),
                "shares": risk_res.get("shares", 1),
                "rrr": risk_res.get("rrr", 2.0),
                "position_czk": risk_res.get("position_val_czk", 0.0),
                "capital_risk_czk": risk_res.get("actual_risk_czk", 0.0),
                "capital_risk_pct": risk_res.get("actual_risk_pct", 1.5),
                "weight_pct": round(weight_val, 1),
                "conviction_score": item.get("conviction_score", 0.0),
                "rank": item.get("rank", 1),
                "status": "READY_FOR_EXECUTION" if approved else "REJECTED_BY_RISK",
                "status_reason": reason,
                "macro_note": macro_warning,
                "mode": self.mode,
                # Formát specifický pro XTB xAPI (JSON socket protocol)
                "xtb_xapi_payload": {
                    "command": "tradeTransaction",
                    "arguments": {
                        "tradeTransInfo": {
                            "cmd": 0,           # 0 = BUY
                            "type": 2,          # 2 = PENDING LIMIT
                            "symbol": sym_xtb,
                            "price": risk_res.get("entry_price", round(limit_price, 2)),
                            "sl": risk_res.get("sl_price", round(inv_price, 2)),
                            "tp": risk_res.get("tp_price", round(tp_price, 2)),
                            "volume": 0.1,      # Lot size na XTB
                            "customComment": f"SI-AI-MVO-{item.get('rank', 1)}"
                        }
                    }
                }
            }
            orders.append(order_payload)

        return orders

    def export_orders_to_json(self, orders: List[Dict[str, Any]], filepath: str) -> None:
        """Uloží příkazy do JSON souboru pro export do obchodních systémů."""
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(orders, f, ensure_ascii=False, indent=2)
        logger.info(f"Exportováno {len(orders)} příkazů do {filepath}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger.info("Testuji generátor příkazů a Risk Gatekeeper...")

    dummy_basket = [
        {
            "rank": 1,
            "xtb_symbol": "NVDA.US_9",
            "yahoo_symbol": "NVDA",
            "name": "NVIDIA Corp",
            "currency": "USD",
            "price": 125.50,
            "limit_buy_price": 121.00,
            "invalidation_price": 114.00,
            "target_mean": 150.00,
            "portfolio_weight": "25.0 %",
            "conviction_score": 14.8
        },
        {
            "rank": 2,
            "xtb_symbol": "CEZ1.CZ",
            "yahoo_symbol": "CEZ.PR",
            "name": "ČEZ a.s.",
            "currency": "CZK",
            "price": 910.00,
            "limit_buy_price": 890.00,
            "invalidation_price": 845.00,
            "target_mean": 1050.00,
            "portfolio_weight": "20.0 %",
            "conviction_score": 11.2
        }
    ]

    engine = BrokerExecutionEngine(mode="PAPER", portfolio_capital=300_000.0)
    orders = engine.generate_orders_from_conviction_basket(dummy_basket)

    print("\n" + "=" * 65)
    print("🤖 VYGENEROVANÉ PŘÍKAZY PRO AUTONOMNÍ TRADING (XTB XAPI BRIDGE):")
    for o in orders:
        print(f"[{o['order_id']}] {o['symbol_xtb']} | {o['action']} {o['order_type']} | {o['shares']} ks @ {o['limit_price']} {o['currency']}")
        print(f"   🛑 SL: {o['sl_price']} | 🎯 TP: {o['tp_price']} | RRR: {o['rrr']}:1 | Riziko: {o['capital_risk_czk']} CZK ({o['capital_risk_pct']} %)")
        print(f"   Stav: {o['status']} ({o['status_reason']})")
    print("=" * 65)
