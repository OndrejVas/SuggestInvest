"""
silver_position_sizing.py – Centrální Position Sizing Engine & Volatility Gate pro Silver
========================================================================================
KROK 41 v Silver Replication Roadmap v3.0

Spojuje do jednoho deterministického výpočtu:
1. Kellyho kritérium f*/3 (Half-Kelly se zmenšeným dělitelem pro volatilitu stříbra)
2. Volatility Gate (Argon Tip #1):
   - Pro účet $10,000 je max povolený risk $400 (4 %).
   - 1 kontrakt Micro Silver (SIL) = 1 000 oz.
   - Maximální povolený Stop-Loss na 1 kontrakt je $0.40/oz.
   - Pokud požadovaný Stop-Loss strategie přesáhne $0.40/oz, bot obchod PŘESKOČÍ (SKIP_TRADE).
3. Max kontrakty:
   - Pro kapitál < $18,000 je striktní limit 1 kontrakt SIL.
   - Povolení 2 kontraktů nastává až při ekvitě >= $18,000.
4. Session multiplikátor: Shanghai (02:00–08:00 SEČ) = 50 % sizing.
5. Sezónní váhy (leden–prosinec).
6. Cross-komodita multiplikátor (pokud běží Gold ve stejném směru a korelace > 0.85 -> 60 % risk).
7. GSR Conviction boost (při extrémním GSR Z-score > 2.0).
"""

from __future__ import annotations
import os
import sys
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple
import numpy as np

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from silver.config.silver_config import SilverRiskConfig, SilverKillzoneConfig
from silver.models.silver_regime_engine import MasterRegime


@dataclass
class SizingDecision:
    """Výsledek kalkulace Position Sizing Enginu."""
    allow_trade: bool
    contracts: int                      # 0, 1 nebo 2
    recommended_risk_usd: float
    actual_risk_usd: float
    stop_loss_dollars_per_oz: float
    volatility_gate_status: str         # "PASSED" nebo "BLOCKED_WIDE_SL"
    active_multipliers: Dict[str, float]
    rejection_reason: Optional[str] = None
    position_oz: float = 1000.0         # Skutečná expozice v uncích pro CFD / adaptivní sizing


class SilverPositionSizingEngine:
    """Komplexní kalkulátor velikosti pozice pro stříbro s Volatility Gate."""

    def __init__(self, risk_cfg: Optional[SilverRiskConfig] = None):
        self.risk_cfg = risk_cfg or SilverRiskConfig()
        self.killzone = SilverKillzoneConfig()

        # Sezónní multiplikátory z Kroku 21
        self.seasonal_multipliers = {
            1: 1.15, 2: 1.10, 3: 1.05, 4: 0.95,
            5: 0.85, 6: 0.85, 7: 1.05, 8: 1.10,
            9: 0.90, 10: 1.00, 11: 1.10, 12: 1.15
        }

    def compute_size(
        self,
        current_equity: float,
        proposed_sl_dollars_per_oz: float,
        regime: MasterRegime,
        session_hour_cet: int = 15,
        session_minute_cet: int = 0,
        month: int = 10,
        gsr_zscore: float = 0.0,
        cross_gold_multiplier: float = 1.0,
        online_win_prob: float = 0.55
    ) -> SizingDecision:
        """
        Vypočte finální velikost pozice a prověří Volatility Gate.
        """
        multipliers = {}

        # 1. Kontrola Sovereign Flooru a minimálního kapitálu
        if current_equity <= self.risk_cfg.sovereign_floor:
            return SizingDecision(
                allow_trade=False, contracts=0, recommended_risk_usd=0.0, actual_risk_usd=0.0,
                stop_loss_dollars_per_oz=proposed_sl_dollars_per_oz,
                volatility_gate_status="BLOCKED_SOVEREIGN_FLOOR",
                active_multipliers={}, rejection_reason=f"Equity ${current_equity:.2f} <= Sovereign Floor ${self.risk_cfg.sovereign_floor:.2f}"
            )

        # 2. Základní Kelly risk ukotvený na target_risk_usd_per_trade ($120 = 1.2 % na $10k účtu)
        base_risk_pct = getattr(self.risk_cfg, "target_risk_usd_per_trade", 120.0) / self.risk_cfg.initial_capital
        kelly_fraction = base_risk_pct
        if online_win_prob > 0.65:
            kelly_fraction = min(self.risk_cfg.max_risk_pct_per_trade, kelly_fraction * 1.15)
        elif online_win_prob < 0.45:
            kelly_fraction = kelly_fraction * 0.75
        multipliers["online_prob_adj"] = round(kelly_fraction / base_risk_pct, 2)

        base_risk_usd = current_equity * kelly_fraction

        # 3. Session multiplikátor (Shanghai = 1.00, London = 0.75, NY = 1.00)
        mins = session_hour_cet * 60 + session_minute_cet
        if 9 * 60 <= mins < 11 * 60 + 30:
            sess_mult = 0.75
        else:
            sess_mult = self.killzone.get_session_size_multiplier(session_hour_cet, session_minute_cet)
        multipliers["session"] = sess_mult

        # 4. Sezónní multiplikátor
        seas_mult = self.seasonal_multipliers.get(month, 1.0)
        multipliers["seasonality"] = seas_mult

        # 5. Cross-komodita multiplikátor
        multipliers["cross_gold"] = cross_gold_multiplier

        # 6. Teze #1: GSR Conviction boost / tlumič
        if gsr_zscore >= 1.5:
            gsr_boost = 1.25  # Stříbro výrazně levné vůči zlatu -> posílení pozice
        elif gsr_zscore <= -1.5:
            gsr_boost = 0.60  # Stříbro přehřáté vůči zlatu -> redukce expozice
        else:
            gsr_boost = 1.00
        multipliers["gsr_conviction"] = gsr_boost

        # 7. Regime multiplikátor
        regime_mult = 1.0
        if regime == MasterRegime.CHOP_COMPRESSION:
            regime_mult = 0.70
        elif regime == MasterRegime.DISTRIBUTION_BLOWOFF:
            regime_mult = 0.50
        multipliers["regime"] = regime_mult

        # Finální doporučený risk v USD (zastropován max $135 pro NY)
        total_mult = sess_mult * seas_mult * cross_gold_multiplier * gsr_boost * regime_mult
        adjusted_target_risk_usd = min(135.0, base_risk_usd * total_mult)

        # =====================================================================
        # VOLATILITY GATE & ADAPTIVE SIZING
        # =====================================================================
        allow_fractional = getattr(self.risk_cfg, "allow_fractional_sizing", True)
        max_allowed_risk_usd = min(135.0, current_equity * self.risk_cfg.max_risk_pct_per_trade)
        sl_cost_1contract = proposed_sl_dollars_per_oz * self.risk_cfg.full_contract_oz

        if allow_fractional:
            # ADAPTIVNÍ FRACTIONAL REŽIM (CFD / flexibilní unce):
            # Přizpůsobí expozici v uncích tak, aby dolarový risk nikdy nepřekročil povolený kapitálový strop.
            # Dolarový risk je fixován, takže bot může spolehlivě obchodovat i při vysoké ceně a volatilitě stříbra!
            
            # Sovereign Floor Cushioning (Argon Safety Rule #1):
            # Max risk na obchod nesmí přesáhnout 25 % zbývajícího bufferu nad $9,000 dnem
            floor_buffer = current_equity - self.risk_cfg.sovereign_floor
            floor_constrained_risk = max(10.0, floor_buffer * 0.25)
            target_risk_usd = min(max_allowed_risk_usd, adjusted_target_risk_usd, floor_constrained_risk)

            # Harmonizace dolarového rizika 1R (Úkol 4):
            # 1. DISTRIBUTION_BLOWOFF floor $75 při zdravém účtu (> $10,500)
            if regime == MasterRegime.DISTRIBUTION_BLOWOFF and current_equity > 10500.0:
                target_risk_usd = max(75.0, target_risk_usd)

            # 2. Režimy HIGH_VOL_CORRECTION, TREND_BULL a CHOP_COMPRESSION strop $95.00 USD
            if regime in [MasterRegime.HIGH_VOL_CORRECTION, MasterRegime.TREND_BULL, MasterRegime.CHOP_COMPRESSION]:
                target_risk_usd = min(target_risk_usd, 95.0)

            if proposed_sl_dollars_per_oz <= 0:
                calc_oz = 0.0
            else:
                calc_oz = target_risk_usd / proposed_sl_dollars_per_oz

            min_oz = getattr(self.risk_cfg, "min_contract_oz", 25.0)
            max_oz = getattr(self.risk_cfg, "max_contract_oz", 1000.0)

            # Maximální blokovaná marže $320 USD (tj. max 200 oz stříbra) v korekčních a trendových režimech
            if regime in [MasterRegime.HIGH_VOL_CORRECTION, MasterRegime.TREND_BULL, MasterRegime.CHOP_COMPRESSION]:
                max_oz = min(max_oz, 200.0)

            calc_oz = min(max_oz, max(min_oz, round(calc_oz, 1)))
            actual_risk = calc_oz * proposed_sl_dollars_per_oz

            # Extrémní ochrana: pokud by i minimální dávka (25 oz) způsobila překročení max povoleného risku o více než 30 %
            if actual_risk > max_allowed_risk_usd * 1.30:
                return SizingDecision(
                    allow_trade=False,
                    contracts=0,
                    position_oz=0.0,
                    recommended_risk_usd=round(target_risk_usd, 2),
                    actual_risk_usd=0.0,
                    stop_loss_dollars_per_oz=round(proposed_sl_dollars_per_oz, 4),
                    volatility_gate_status="BLOCKED_EXTREME_VOLATILITY",
                    active_multipliers=multipliers,
                    rejection_reason=f"Extrémní volatilita: i minimální pozice {min_oz} oz vyžaduje risk ${actual_risk:.2f} > limit ${max_allowed_risk_usd:.2f}"
                )

            # Ekvivalent kontraktů pro zobrazení
            equiv_contracts = max(1, int(round(calc_oz / 1000.0))) if calc_oz >= 500 else 1

            return SizingDecision(
                allow_trade=True,
                contracts=equiv_contracts,
                position_oz=calc_oz,
                recommended_risk_usd=round(target_risk_usd, 2),
                actual_risk_usd=round(actual_risk, 2),
                stop_loss_dollars_per_oz=round(proposed_sl_dollars_per_oz, 4),
                volatility_gate_status="PASSED",
                active_multipliers=multipliers,
                rejection_reason=None
            )
        else:
            # PŮVODNÍ STRIKTNÍ FUTURES GATE (1 nedělitelný kontrakt SIL = 1000 oz)
            max_allowed_sl = (current_equity * self.risk_cfg.max_risk_pct_per_trade) / self.risk_cfg.full_contract_oz
            if proposed_sl_dollars_per_oz > max_allowed_sl:
                return SizingDecision(
                    allow_trade=False,
                    contracts=0,
                    position_oz=0.0,
                    recommended_risk_usd=round(adjusted_target_risk_usd, 2),
                    actual_risk_usd=0.0,
                    stop_loss_dollars_per_oz=round(proposed_sl_dollars_per_oz, 4),
                    volatility_gate_status="BLOCKED_WIDE_SL",
                    active_multipliers=multipliers,
                    rejection_reason=f"Volatility Gate: Požadovaný SL ${proposed_sl_dollars_per_oz:.4f}/oz překračuje limit ${max_allowed_sl:.4f}/oz (Risk 1 SIL = ${sl_cost_1contract:.2f} > ${current_equity * self.risk_cfg.max_risk_pct_per_trade:.2f})"
                )

            max_contracts_cap = 2 if current_equity >= self.risk_cfg.equity_threshold_for_2_contracts else 1
            if sl_cost_1contract <= 0:
                contracts = 0
            else:
                can_afford = int(adjusted_target_risk_usd / sl_cost_1contract)
                contracts = min(max_contracts_cap, max(1, can_afford))

            actual_risk = contracts * sl_cost_1contract

            return SizingDecision(
                allow_trade=True,
                contracts=contracts,
                position_oz=contracts * self.risk_cfg.full_contract_oz,
                recommended_risk_usd=round(adjusted_target_risk_usd, 2),
                actual_risk_usd=round(actual_risk, 2),
                stop_loss_dollars_per_oz=round(proposed_sl_dollars_per_oz, 4),
                volatility_gate_status="PASSED",
                active_multipliers=multipliers,
                rejection_reason=None
            )
