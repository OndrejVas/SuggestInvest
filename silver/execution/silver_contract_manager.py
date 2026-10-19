"""
silver_contract_manager.py – Správa IBKR futures kontraktů Micro Silver (SIL)
=============================================================================
KROK 61 v Silver Replication Roadmap v3.0

Dynamicky spravuje kontrakty pro Interactive Brokers:
1. Kontrakt SIL: secType="FUT", exchange="NYMEX", currency="USD", multiplier=1000
2. Automatický výběr Front-Month kontraktu podle kalendáře expiračních měsíců [3, 5, 7, 9, 12]:
   - H (Březen), K (Květen), N (Červenec), U (Září), Z (Prosinec)
3. Roll-over trigger: 10 dní před First Notice Day (FND)
4. Sestavení Calendar Spread kontraktu pro nákladově efektivní roll-over
"""

from __future__ import annotations
import os
import sys
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from silver.config.silver_config import SilverInstrumentConfig

logger = logging.getLogger("SilverContractManager")


class SilverContractManager:
    """Správce front-month a roll-over kontraktů pro Micro Silver (SIL)."""

    MONTH_CODES = {3: "H", 5: "K", 7: "N", 9: "U", 12: "Z"}
    CODE_TO_MONTH = {"H": 3, "K": 5, "N": 7, "U": 9, "Z": 12}
    EXPIRY_MONTHS = [3, 5, 7, 9, 12]

    def __init__(self, instrument_cfg: Optional[SilverInstrumentConfig] = None):
        self.cfg = instrument_cfg or SilverInstrumentConfig()

    def get_front_month_expiry(self, current_dt: Optional[datetime] = None) -> Tuple[int, int]:
        """
        Určí rok a měsíc aktivního front-month kontraktu k danému datu.
        Pravidlo: Pokud zbývá <= 10 dní do FND (konec předchozího měsíce), rolujeme na další!
        """
        dt = current_dt or datetime.now()
        y = dt.year
        m = dt.month

        # Najdeme nejbližší expirační měsíc
        for exp_m in self.EXPIRY_MONTHS:
            # Přibližné datum FND: 28. den měsíce před expiračním měsícem
            prev_m = 12 if exp_m == 1 else exp_m - 1
            prev_y = y - 1 if exp_m == 1 else y
            approx_fnd = datetime(prev_y, prev_m, 28)
            roll_cutoff = approx_fnd - timedelta(days=self.cfg.ROLL_DAYS_BEFORE_EXPIRY)

            if dt < roll_cutoff:
                return y, exp_m

        # Pokud jsme za všemi v daném roce, rollujeme na březen dalšího roku
        return y + 1, 3

    def get_contract_code(self, current_dt: Optional[datetime] = None) -> str:
        """Vrací IBKR kód front-month kontraktu (např. 'SILZ26' nebo 'SILH27')."""
        y, m = self.get_front_month_expiry(current_dt)
        code = self.MONTH_CODES[m]
        yr_short = str(y)[-2:]
        return f"{self.cfg.symbol}{code}{yr_short}"

    def get_ibkr_contract_spec(self, current_dt: Optional[datetime] = None) -> Dict[str, Any]:
        """Vrací parametry pro ib_insync / IBKR API Contract objekt."""
        y, m = self.get_front_month_expiry(current_dt)
        last_trade_date_str = f"{y}{m:02d}"

        return {
            "symbol": self.cfg.symbol,
            "secType": self.cfg.sec_type,
            "exchange": self.cfg.exchange,
            "currency": self.cfg.currency,
            "multiplier": str(self.cfg.contract_multiplier),
            "lastTradeDateOrContractMonth": last_trade_date_str,
            "localSymbol": self.get_contract_code(current_dt)
        }

    def get_calendar_spread_spec(self, current_dt: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Sestaví specifikaci Calendar Spreadu (Combo) pro přerolování do next-month.
        Sell Front-Month + Buy Next-Month.
        """
        y_front, m_front = self.get_front_month_expiry(current_dt)
        
        # Next month
        idx = self.EXPIRY_MONTHS.index(m_front)
        if idx == len(self.EXPIRY_MONTHS) - 1:
            y_next, m_next = y_front + 1, self.EXPIRY_MONTHS[0]
        else:
            y_next, m_next = y_front, self.EXPIRY_MONTHS[idx + 1]

        return {
            "symbol": self.cfg.symbol,
            "secType": "BAG",
            "exchange": self.cfg.exchange,
            "currency": self.cfg.currency,
            "front_leg": f"{self.cfg.symbol}{self.MONTH_CODES[m_front]}{str(y_front)[-2:]}",
            "next_leg": f"{self.cfg.symbol}{self.MONTH_CODES[m_next]}{str(y_next)[-2:]}"
        }


def main():
    mgr = SilverContractManager()
    curr_spec = mgr.get_ibkr_contract_spec()
    spread_spec = mgr.get_calendar_spread_spec()
    print("=" * 60)
    print("SILVER IBKR CONTRACT MANAGER (Krok 61)")
    print("=" * 60)
    print(f"Aktivní Front-Month: {curr_spec['localSymbol']} ({curr_spec['lastTradeDateOrContractMonth']})")
    print(f"Specifikace:         {curr_spec['symbol']} {curr_spec['secType']} {curr_spec['exchange']} ({curr_spec['multiplier']} oz)")
    print(f"Calendar Spread:     {spread_spec['front_leg']} → {spread_spec['next_leg']}")
    print("✅ KROK 61 DOKONČEN!")

if __name__ == "__main__":
    main()
