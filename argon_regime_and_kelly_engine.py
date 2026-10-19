"""
ARGON V2 - STRATEGIE #6: MASTER PORTFOLIO GATEKEEPER & KELLY ENGINE
===================================================================
Implementuje:
- 4-stavový HMM (TREND_BULL, CHOP_COMPRESSION, DISTRIBUTION_BLOWOFF, HIGH_VOL_CORRECTION)
  + integraci FRED TIPS 10Y reálných sazeb.
- Detekci Blow-Off Top Exhaustion (Hypotéza 1: Hurst + Volume Imbalance + H4 RSI divergence).
- Dynamický Volatility & Equity EMA20 Braking Factor (Hypotéza 2).
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Tuple
import numpy as np
import pandas as pd
# Standalone modul – žádné závislosti na 03_CONSOLIDATED_STRATEGIES_CODE.py
class MasterRegime(IntEnum):
    CHOP_COMPRESSION = 0          # Červenec 2026: Zákaz breakoutů (#3, #5), povolena pouze opatrná #2
    TREND_BULL = 1                # Leden, Březen, Květen: Plné Longy (#1, #3, #4, #5), zákaz běžných Shortů
    DISTRIBUTION_BLOWOFF = 2      # Konec srpna ($4,697): Okamžitý zákaz Long breakoutů, aktivace Reversion Shortů
    HIGH_VOL_CORRECTION = 3       # Září-Říjen (-$400/oz): Zákaz chytání padajících nožů (#2 Long), aktivace Trend Shortů
@dataclass
class PortfolioRiskState:
    initial_capital: float = 10_000.0
    current_equity: float = 10_000.0
    high_water_mark: float = 10_000.0
    equity_history: List[float] = field(default_factory=lambda: [10_000.0] * 20)
    min_oz: float = 2.5
    max_oz: float = 7.5
    full_contract_oz: float = 10.0
    def record_PnL(self, net_pnl_usd: float) -> None:
        self.current_equity += net_pnl_usd
        self.high_water_mark = max(self.high_water_mark, self.current_equity)
        self.equity_history.append(self.current_equity)
        if len(self.equity_history) > 200:
            self.equity_history.pop(0)
    @property
    def current_drawdown_pct(self) -> float:
        return (self.high_water_mark - self.current_equity) / max(1.0, self.high_water_mark)
    @property
    def equity_ema20(self) -> float:
        s = pd.Series(self.equity_history)
        return float(s.ewm(span=20, adjust=False).mean().iloc[-1])
    @property
    def is_equity_above_ema20(self) -> bool:
        return self.current_equity >= self.equity_ema20
class BlowOffExhaustionDetector:
    """
    Řeší Hypotézu 1 z 04_ARGON_RESEARCH_CHECKLIST.md:
    Kombinuje Hurstův exponent, Volume/Wick Imbalance a RSI divergenci pro okamžité
    přepnutí HMM ze stavu TREND_BULL do DISTRIBUTION_BLOWOFF na konci srpna ($4,697).
    """
    @staticmethod
    def compute_exhaustion_score(df: pd.DataFrame, hurst_series: pd.Series, rsi_series: pd.Series) -> float:
        if len(df) < 60:
            return 0.0
        close = df["close"]
        high = df["high"]
        low = df["low"]
        # 1. Parabolická extenze nad EMA(120) v jednotkách ATR
        ema120 = close.ewm(span=120, adjust=False).mean()
        tr = (high - low).rolling(60).mean().replace(0, 1e-6)
        z_ext = float((close.iloc[-1] - ema120.iloc[-1]) / tr.iloc[-1])
        # 2. Medvědí divergence RSI na lokálním vrcholu (Cena blízko 20-bar high, ale RSI o >6 bodů níže)
        recent_high_idx = int(high.iloc[-25:-2].argmax())
        rsi_at_prev_peak = float(rsi_series.iloc[-25:-2].iloc[recent_high_idx])
        rsi_now = float(rsi_series.iloc[-1])
        has_rsi_divergence = (
            float(high.iloc[-1]) >= 0.998 * float(high.iloc[-25:-2].max())
            and (rsi_at_prev_peak - rsi_now) >= 6.0
        )
        # 3. Vyčerpání kupců ve svíčce (Upper Wick Absorption + zpomalení Hurstu)
        candle_range = max(1e-6, float(high.iloc[-1] - low.iloc[-1]))
        upper_wick = float(high.iloc[-1] - max(df["open"].iloc[-1], close.iloc[-1]))
        wick_ratio = upper_wick / candle_range
        hurst_delta = float(hurst_series.iloc[-1] - hurst_series.iloc[-5])
        score = 0.0
        if z_ext > 2.6:
            score += 0.40
        if has_rsi_divergence:
            score += 0.35
        if wick_ratio > 0.42 or hurst_delta < -0.04:
            score += 0.25
        return float(np.clip(score, 0.0, 1.0))
class MasterPortfolioHMMGatekeeper:
    """
    STRATEGIE #6: Master Portfolio Gatekeeper & Fractional Kelly Sizer.
    Řídí povolení LONG/SHORT pro Strategie #1 až #5 a počítá optimální počet uncí (2.5 až 7.5 oz).
    """
    def __init__(self):
        # Přechodová matice 4-stavového HMM
        self.trans_mat = np.array(
            [
                [0.95, 0.03, 0.00, 0.02],  # 0: CHOP_COMPRESSION
                [0.02, 0.93, 0.04, 0.01],  # 1: TREND_BULL
                [0.01, 0.02, 0.85, 0.12],  # 2: DISTRIBUTION_BLOWOFF -> Rychlý přechod do korekce!
                [0.03, 0.02, 0.00, 0.95],  # 3: HIGH_VOL_CORRECTION
            ],
            dtype=np.float64,
        )
        self.state_probs = np.array([0.20, 0.60, 0.05, 0.15], dtype=np.float64)
    def evaluate_regime_and_permissions(
        self,
        df: pd.DataFrame,
        hurst_series: pd.Series,
        rsi_series: pd.Series,
        yz_vol_series: pd.Series,
        tips_10y_yield_change_bps: float = 0.0,
    ) -> Tuple[MasterRegime, Dict[str, bool], float]:
        """
        Vyhodnotí aktuální tržní režim a vrátí:
        - MasterRegime
        - Slovník oprávnění (allow_breakout_long, allow_pullback_long, allow_meanrev_long, allow_short)
        - Koeficient jistoty režimu (0.0 až 1.0)
        """
        exhaustion = BlowOffExhaustionDetector.compute_exhaustion_score(df, hurst_series, rsi_series)
        hurst_now = float(hurst_series.iloc[-1])
        yz_now = float(yz_vol_series.iloc[-1])
        yz_median = float(yz_vol_series.iloc[-100:].median()) if len(yz_vol_series) >= 20 else yz_now
        vol_ratio = yz_now / max(1e-8, yz_median)
        close = df["close"]
        ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
        ema200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1])
        c_now = float(close.iloc[-1])
        # Emisní pravděpodobnosti pro 4 stavy
        lik_chop = 1.0 if (hurst_now < 0.48 and vol_ratio < 0.95) else 0.15
        lik_bull = 1.0 if (c_now > ema50 >= ema200 and exhaustion < 0.65 and hurst_now >= 0.48) else 0.15
        lik_blowoff = 1.5 if exhaustion >= 0.65 else 0.05
        # Růst reálných výnosů TIPS 10Y (tips_10y_yield_change_bps > 5 bps) posiluje pravděpodobnost korekce zlata
        macro_headwind = 1.25 if tips_10y_yield_change_bps > 5.0 else 1.0
        lik_correction = (1.2 * macro_headwind) if (c_now < ema50 and vol_ratio > 1.05) else 0.10
        lik_vec = np.array([lik_chop, lik_bull, lik_blowoff, lik_correction], dtype=np.float64)
        prior = self.state_probs @ self.trans_mat
        post = prior * lik_vec
        self.state_probs = post / np.sum(post)
        regime = MasterRegime(int(np.argmax(self.state_probs)))
        entropy = -np.sum(self.state_probs * np.log(self.state_probs + 1e-12))
        confidence = float(np.clip(1.0 - entropy / np.log(4.0), 0.25, 1.0))
        # Matice oprávnění podle režimu (ochrana proti červenci, srpnu i září/říjnu)
        if regime == MasterRegime.CHOP_COMPRESSION:
            permissions = {
                "allow_breakout_long": False,   # Blokuje ztráty #3 a #5 v červenci 2026
                "allow_pullback_long": False,
                "allow_meanrev_long": True,     # Povolena pouze Mean Reversion #2
                "allow_short": False,
            }
        elif regime == MasterRegime.TREND_BULL:
            permissions = {
                "allow_breakout_long": True,
                "allow_pullback_long": True,
                "allow_meanrev_long": True,
                "allow_short": False,           # Zlatý inflační bias: zákaz shortování zdravého bull trendu
            }
        elif regime == MasterRegime.DISTRIBUTION_BLOWOFF:
            permissions = {
                "allow_breakout_long": False,   # OKAMŽITÝ ZÁKAZ nákupů průrazů na vrcholu $4,697!
                "allow_pullback_long": False,
                "allow_meanrev_long": False,
                "allow_short": True,            # Odemčení Blow-Off Reversion Shortů
            }
        else:  # HIGH_VOL_CORRECTION (Září-Říjen -$400/oz)
            permissions = {
                "allow_breakout_long": False,
                "allow_pullback_long": False,
                "allow_meanrev_long": False,    # Zákaz chytání padajícího nože v září a říjnu!
                "allow_short": True,            # Odemčení trendových/momentum Shortů
            }
        return regime, permissions, confidence
    @staticmethod
    def compute_optimal_oz(
        risk_state: PortfolioRiskState,
        regime: MasterRegime,
        regime_confidence: float,
        current_yz_vol: float,
        target_yz_vol: float,
        rolling_win_rate: float = 0.42,
        rolling_payoff: float = 2.10,
    ) -> float:
        """
        Spojuje Quarter-Kelly, Yang-Zhang Volatility Targeting a Hypotézu 2
        (Drawdown Braking Factor + 20-EMA kapitálové křivky) do výsledné velikosti v uncích (2.5 až 7.5 oz).
        """
        p = np.clip(rolling_win_rate, 0.20, 0.75)
        b = max(0.8, rolling_payoff)
        raw_kelly = max(0.05, (p * (b + 1.0) - 1.0) / b)
        quarter_kelly_scalar = np.clip((0.25 * raw_kelly) / 0.04, 0.50, 1.35)
        # Volatility targeting s podlahou proti přepákování v červenci
        eff_vol = max(current_yz_vol, 0.80 * target_yz_vol, 1e-6)
        vol_scalar = np.clip(target_yz_vol / eff_vol, 0.45, 1.25)
        # Hypotéza 2: Drawdown & Equity EMA20 brzda
        dd = risk_state.current_drawdown_pct
        above_ema20 = risk_state.is_equity_above_ema20
        if dd >= 0.05 and not above_ema20:
            dd_brake = 0.50  # Snížení o 50 % při DD >= 5 % pod 20-EMA kapitálu
        elif not above_ema20:
            dd_brake = 0.70
        elif dd >= 0.03:
            dd_brake = 0.80
        else:
            dd_brake = 1.00
        regime_scalar = 0.60 if regime in (MasterRegime.CHOP_COMPRESSION, MasterRegime.DISTRIBUTION_BLOWOFF) else 1.0
        raw_oz = 5.0 * quarter_kelly_scalar * vol_scalar * dd_brake * regime_scalar * (0.6 + 0.4 * regime_confidence)
        clipped = np.clip(raw_oz, risk_state.min_oz, risk_state.max_oz)
        return float(np.round(clipped * 2.0) / 2.0)
