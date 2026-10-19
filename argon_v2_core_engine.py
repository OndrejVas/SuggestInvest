"""
ARGON QUANT V2 - CORE ENGINE FOR SUGGESTINVEST (COMEX MGC)
==========================================================
Řeší:
1. Červenec 2026 (-$1,780.60): Lo-MacKinlay Variance Ratio + Kaufman ER + Fee-to-ATR Gate.
2. Srpen -> Září/Říjen 2026 ($4,697 -> $4,111): 4D HMM + Parabolic Exhaustion Z-Score Damper
   + Shannon Regime Entropy + Dual-Key Asymmetric Short Gate.
3. Position Sizing: Continuous Yang-Zhang / GJR-GARCH Vol-Targeting + Bayesian Shrunk Kelly
   + Sigmoidal Drawdown Braking Factor.
4. Exekuce IBKR (-$2.20 RT): 2-Stage Break-Even & Volatility-Clock Triple Barrier.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, Optional, Tuple
import numpy as np
import pandas as pd
class MarketRegime(IntEnum):
    COMPRESSION_NOISE = 0      # Letní komprese (Červenec 2026) -> Zákaz breakoutů
    BULL_EXPANSION = 1         # Zdravý bull trend -> Plné Longy, zákaz běžných Shortů
    PARABOLIC_CLIMAX = 2       # Extrémní extenze ($4,697) -> Útlum Long breakoutů, příprava Reversion Shortu
    CORRECTION_BEAR = 3        # Prudká korekce (-$400/oz Září-Říjen) -> Defenzivní režim + Momentum Shorty
@dataclass
class ExecutionConfig:
    initial_capital: float = 10_000.0
    min_oz: float = 2.5
    max_oz: float = 7.5
    base_oz: float = 5.0
    ibkr_rt_commission: float = 2.20
    expected_slippage_per_oz: float = 0.20      # 2 ticky MGC = $0.20/oz
    max_cost_to_pt_ratio: float = 0.045         # Max 4.5 % očekávaného PT může padnout na náklady
    annual_target_vol: float = 0.28             # Cílová roční volatilita portfolia (28 %)
    dd_free_threshold: float = 0.015            # Do 1.5 % DD plná velikost pozice
    dd_critical_threshold: float = 0.060        # U 6.0 % DD maximální brzda (ochrana limitu -6.92 %)
    dd_brake_lambda: float = 2.20
    dd_min_multiplier: float = 0.30
class MicrostructureIndicators:
    """Vektorizované výpočty Yang-Zhang volatility, Variance Ratio a Parabolic Z-Score."""
    @staticmethod
    def yang_zhang_volatility(
        df: pd.DataFrame, window: int = 60, trading_periods_per_year: int = 252 * 1380
    ) -> pd.Series:
        """
        Vypočítá Yang-Zhang (2000) realizovanou volatilitu odolnou vůči overnight gapům a stínům.
        Očekává sloupce: ['open', 'high', 'low', 'close'].
        """
        o = np.log(df["open"] / df["close"].shift(1)).fillna(0.0)
        c = np.log(df["close"] / df["open"]).fillna(0.0)
        h_c = np.log(df["high"] / df["close"]).fillna(0.0)
        h_o = np.log(df["high"] / df["open"]).fillna(0.0)
        l_c = np.log(df["low"] / df["close"]).fillna(0.0)
        l_o = np.log(df["low"] / df["open"]).fillna(0.0)
        # Rogers-Satchell variance
        rs = (h_c * h_o + l_c * l_o).rolling(window).mean()
        sigma_o_sq = o.rolling(window).var()
        sigma_c_sq = c.rolling(window).var()
        k = 0.34 / (1.34 + (window + 1) / (window - 1))
        yz_var = (sigma_o_sq + k * sigma_c_sq + (1.0 - k) * rs).clip(lower=1e-12)
        return np.sqrt(yz_var * trading_periods_per_year)
    @staticmethod
    def gjr_garch_proxy_vol(
        returns: pd.Series,
        yz_vol: pd.Series,
        omega: float = 1e-6,
        alpha: float = 0.06,
        gamma: float = 0.08,  # Asymetrický člen: vyšší odezva na záporné výnosy (korekcí)
        beta: float = 0.88,
        trading_periods_per_year: int = 252 * 1380,
    ) -> pd.Series:
        """
        Rychlý asymetrický GJR-GARCH(1,1) filtr zachycující skokový nárůst rizika při propadech.
        """
        r = returns.fillna(0.0).to_numpy()
        n = len(r)
        h = np.zeros(n, dtype=np.float64)
        init_var = np.nanvar(r[: min(500, n)]) if n > 10 else 1e-6
        h[0] = max(init_var, 1e-10)
        for t in range(1, n):
            neg_shock = 1.0 if r[t - 1] < 0.0 else 0.0
            h[t] = (
                omega
                + (alpha + gamma * neg_shock) * (r[t - 1] ** 2)
                + beta * h[t - 1]
            )
        garch_ann = pd.Series(
            np.sqrt(h * trading_periods_per_year), index=returns.index
        )
        # Hybridní kombinace: 60 % Yang-Zhang (struktura svíčky) + 40 % GJR-GARCH (asymetrie šoku)
        return 0.60 * yz_vol.bfill() + 0.40 * garch_ann
    @staticmethod
    def variance_ratio(close: pd.Series, q: int = 15, window: int = 120) -> pd.Series:
        """
        Lo-MacKinlay Variance Ratio VR(q).
        VR(q) < 1.0 => Mean-reversion / komprese (červenec 2026).
        VR(q) > 1.0 => Pozitivní autokorelace / skutečný trend.
        """
        r1 = np.log(close / close.shift(1))
        rq = np.log(close / close.shift(q))
        var_1 = r1.rolling(window).var()
        var_q = rq.rolling(window).var()
        vr = var_q / (q * var_1.replace(0, np.nan))
        return vr.fillna(1.0).clip(0.2, 3.0)
    @staticmethod
    def kaufman_efficiency_ratio(close: pd.Series, window: int = 60) -> pd.Series:
        direction = (close - close.shift(window)).abs()
        volatility = close.diff().abs().rolling(window).sum()
        return (direction / volatility.replace(0, np.nan)).fillna(0.0)
    @staticmethod
    def parabolic_extension_zscore(
        df: pd.DataFrame, ema_span: int = 240, atr_window: int = 240
    ) -> pd.Series:
        """
        Měří parabolické přepětí ceny nad střednědobou EMA v jednotkách ATR.
        Hodnoty > 2.85 indikují riziko Blow-off Topu (Srpen $4,697).
        """
        ema = df["close"].ewm(span=ema_span, adjust=False).mean()
        tr = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - df["close"].shift(1)).abs(),
                (df["low"] - df["close"].shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(atr_window).mean().bfill()
        return ((df["close"] - ema) / atr.replace(0, np.nan)).fillna(0.0)
class ArgonRegimeEngine:
    """
    4-dimenzionální Bayesovský / HMM Režimový Engine s výpočtem Shannonovy entropie
    a okamžitým Parabolic Exhaustion tlumičem.
    """
    def __init__(self, n_regimes: int = 4):
        self.n_regimes = n_regimes
        # Přechodová matice A s mírnější setrvačností u Parabolic Climax stavu
        self.transition_matrix = np.array(
            [
                [0.960, 0.025, 0.005, 0.010],  # 0: Compression
                [0.015, 0.955, 0.020, 0.010],  # 1: Bull Expansion
                [0.005, 0.025, 0.890, 0.080],  # 2: Parabolic Climax -> Rychlý přechod do Correction!
                [0.025, 0.015, 0.000, 0.960],  # 3: Correction / Bear
            ],
            dtype=np.float64,
        )
        # Centroidy 4D vektoru: [drift_tstat, log_vol_z, variance_ratio, ext_zscore]
        self.means = np.array(
            [
                [0.0, -0.8, 0.82, 0.0],    # 0: Compression (nízká vol, VR < 1)
                [0.8, 0.1, 1.18, 1.2],     # 1: Bull Expansion (zdravý trend, VR > 1)
                [1.8, 0.9, 1.35, 3.2],     # 2: Parabolic Climax (extrémní Z_ext > 3.0)
                [-1.4, 1.1, 1.25, -1.8],   # 3: Correction / Bear (záporný drift, vysoká vol)
            ],
            dtype=np.float64,
        )
        self.scales = np.array(
            [
                [0.6, 0.5, 0.15, 0.8],
                [0.7, 0.5, 0.18, 1.0],
                [0.9, 0.6, 0.25, 0.9],
                [0.8, 0.6, 0.22, 1.1],
            ],
            dtype=np.float64,
        )
        self.state_probs = np.array([0.25, 0.50, 0.05, 0.20], dtype=np.float64)
    def step(self, obs_vector: np.ndarray) -> Tuple[MarketRegime, np.ndarray, float]:
        """
        Jeden krok Hamiltonova / Forward filtru bez look-ahead biasu.
        Vrací: (Aktivní režim, vektor pravděpodobností p_k, koeficient důvěry C_HMM).
        """
        prior = self.state_probs @ self.transition_matrix
        # Diag-Gaussian log-likelihood
        z = (obs_vector - self.means) / self.scales
        log_lik = -0.5 * np.sum(z**2 + 2.0 * np.log(self.scales), axis=1)
        log_lik -= np.max(log_lik)
        lik = np.exp(log_lik)
        posterior = prior * lik
        norm = np.sum(posterior)
        if norm > 1e-12:
            self.state_probs = posterior / norm
        else:
            self.state_probs = prior
        # Shannonova entropie pro detekci fázového přechodu
        eps = 1e-12
        entropy = -np.sum(self.state_probs * np.log(self.state_probs + eps))
        max_entropy = np.log(self.n_regimes)
        confidence = float(np.clip(1.0 - (entropy / max_entropy), 0.15, 1.0))
        regime = MarketRegime(int(np.argmax(self.state_probs)))
        return regime, self.state_probs.copy(), confidence
    @staticmethod
    def compute_long_breakout_damper(
        ext_zscore: float, vr_q: float, er: float, roc_accel: float
    ) -> float:
        """
        Matematický tlumič Long Breakoutů:
        1. V červencové kompresi (VR(q) < 0.95 a ER < 0.22) vrací 0.0.
        2. Na vrcholu srpnové paraboly (Z_ext > 2.5 a zpomalující hybnost) exponenciálně tlumí.
        """
        if vr_q < 0.95 and er < 0.22:
            return 0.0
        if ext_zscore > 2.5:
            gamma = 0.85 if roc_accel < 0 else 0.45
            return float(np.exp(-gamma * ((ext_zscore - 2.5) ** 2)))
        return 1.0
class HybridPositionSizer:
    """
    Spojitý Yang-Zhang/GJR-GARCH Volatility Targeting + Režimově podmíněný Kelly
    + Sigmoidal Drawdown Braking Factor.
    """
    def __init__(self, config: ExecutionConfig):
        self.cfg = config
        self.high_water_mark = config.initial_capital
        # Bayesian Shrunk Quarter-Kelly násobiče podle režimu
        self.regime_kelly_multipliers: Dict[MarketRegime, float] = {
            MarketRegime.COMPRESSION_NOISE: 0.45,
            MarketRegime.BULL_EXPANSION: 1.15,
            MarketRegime.PARABOLIC_CLIMAX: 0.55,  # Snížení expozice na vrcholu paraboly!
            MarketRegime.CORRECTION_BEAR: 0.75,
        }
    def drawdown_braking_factor(self, current_equity: float) -> float:
        """
        Nelineární brzda Φ(dd_t) chránící srpnové zisky při nástupu zářijové korekce.
        """
        self.high_water_mark = max(self.high_water_mark, current_equity)
        dd = (self.high_water_mark - current_equity) / self.high_water_mark
        if dd <= self.cfg.dd_free_threshold:
            return 1.0
        ratio = (dd - self.cfg.dd_free_threshold) / max(
            1e-6, (self.cfg.dd_critical_threshold - self.cfg.dd_free_threshold)
        )
        brake = np.exp(-self.cfg.dd_brake_lambda * (ratio**2))
        return float(np.clip(brake, self.cfg.dd_min_multiplier, 1.0))
    def compute_position_oz(
        self,
        current_equity: float,
        price: float,
        current_vol: float,
        vol_floor: float,
        regime: MarketRegime,
        hmm_confidence: float,
        cross_asset_multiplier: float = 1.0,
    ) -> float:
        # 1. Ochrana proti přepákování v tichém červencovém trhu (Volatility Floor)
        effective_vol = max(current_vol, vol_floor, 0.08)
        # 2. Vol-Target škálování vůči cílové volatilitě
        vol_scalar = self.cfg.annual_target_vol / effective_vol
        # 3. Režimový Kelly + HMM entropická důvěra + Drawdown Brake + Cross-Asset Macro Můstek
        kelly_mult = self.regime_kelly_multipliers.get(regime, 0.75)
        dd_brake = self.drawdown_braking_factor(current_equity)
        equity_scale = current_equity / self.cfg.initial_capital
        raw_oz = (
            self.cfg.base_oz
            * equity_scale
            * vol_scalar
            * kelly_mult
            * (0.5 + 0.5 * hmm_confidence)
            * dd_brake
            * cross_asset_multiplier
        )
        # Zaokrouhlení na 0.5 oz kroky v povoleném pásmu [2.5, 7.5] oz
        clipped_oz = np.clip(raw_oz, self.cfg.min_oz, self.cfg.max_oz)
        return float(np.round(clipped_oz * 2.0) / 2.0)
class AsymmetricShortGate:
    """
    Dvojitý zámek (Dual-Key Gate) pro shortování zlata:
    Zabraňuje krvácení v běžném bull trendu, ale aktivuje shorty během
    parabolického zvratu ($4,697) a potvrzené distribuce (-$400/oz v září).
    """
    @staticmethod
    def is_short_allowed(
        regime: MarketRegime,
        regime_probs: np.ndarray,
        ext_zscore: float,
        price: float,
        ema_macro: float,
        ema_macro_slope: float,
        upper_wick_ratio: float,
        down_up_vol_ratio: float,
        vr_q: float,
    ) -> Tuple[bool, str]:
        # Zámek A: Parabolic Blow-off Reversion (Srpen vrchol $4,697)
        lock_a_parabolic = (
            ext_zscore > 2.85
            and upper_wick_ratio > 0.42
            and down_up_vol_ratio > 1.30
        )
        if lock_a_parabolic:
            return True, "SHORT_LOCK_A_PARABOLIC_REVERSION"
        # Zámek B: Potvrzený strukturální Bear / Korekce (Září-Říjen -$400/oz)
        prob_bear = regime_probs[int(MarketRegime.CORRECTION_BEAR)]
        lock_b_breakdown = (
            price < ema_macro
            and ema_macro_slope < 0.0
            and prob_bear >= 0.55
            and vr_q >= 1.03
        )
        if lock_b_breakdown:
            return True, "SHORT_LOCK_B_STRUCTURAL_BREAKDOWN"
        return False, "BLOCKED_BY_GOLD_BULL_BIAS"
@dataclass
class TripleBarrierOrder:
    direction: int                  # +1 Long, -1 Short
    entry_price: float
    position_oz: float
    sl_price: float
    pt_price: float
    initial_risk_per_oz: float
    max_vol_clock_budget: float     # Vertikální bariéra ve volatilitním čase
    accumulated_vol_clock: float = 0.0
    be_stage: int = 0               # 0 = Initial, 1 = Risk Halved (-0.4R), 2 = Fee-Plus BE
class TripleBarrierExecutionEngine:
    """
    Fee-aware Triple-Barrier Engine optimalizovaný pro COMEX MGC (-$2.20 RT).
    """
    def __init__(self, config: ExecutionConfig):
        self.cfg = config
    def passes_cost_efficiency_gate(
        self, position_oz: float, expected_pt_distance_per_oz: float
    ) -> bool:
        """
        Zablokuje obchod, pokud poplatky IBKR ($2.20) + očekávaná slippage
        tvoří více než 4.5 % hrubého potenciálního zisku (eliminuje červencový šum).
        """
        total_friction_usd = (
            self.cfg.ibkr_rt_commission
            + position_oz * self.cfg.expected_slippage_per_oz
        )
        expected_gross_pt_usd = position_oz * expected_pt_distance_per_oz
        if expected_gross_pt_usd <= 0:
            return False
        return (total_friction_usd / expected_gross_pt_usd) <= self.cfg.max_cost_to_pt_ratio
    def update_barriers_on_bar(
        self,
        order: TripleBarrierOrder,
        bar_high: float,
        bar_low: float,
        bar_close: float,
        current_atr: float,
        vr_q: float,
    ) -> Tuple[Optional[str], Optional[float]]:
        """
        Aktualizuje pozici na novém baru:
        1. Kontroluje zasažení SL / PT.
        2. Aplikuje 2-Stage Break-Even protokol (zabraňuje předčasnému vyhození na BE).
        3. Aktualizuje Volatility-Clock a vyhodnocuje Mid-Price Time Decay Exit.
        """
        # 1. Kontrola SL a PT
        if order.direction == 1:
            if bar_low <= order.sl_price:
                return "STOP_LOSS_OR_BE", order.sl_price
            if bar_high >= order.pt_price:
                return "TAKE_PROFIT", order.pt_price
            unrealized_r = (bar_close - order.entry_price) / order.initial_risk_per_oz
        else:
            if bar_high >= order.sl_price:
                return "STOP_LOSS_OR_BE", order.sl_price
            if bar_low <= order.pt_price:
                return "TAKE_PROFIT", order.pt_price
            unrealized_r = (order.entry_price - bar_close) / order.initial_risk_per_oz
        # 2. Dvoufázový Break-Even (řeší Premature BE Trap)
        fee_buffer_per_oz = (2.0 * self.cfg.ibkr_rt_commission) / order.position_oz
        if order.be_stage == 0 and unrealized_r >= 1.05:
            # Fáze 1: Snížení rizika z -1.0R na -0.40R
            order.sl_price = (
                order.entry_price
                - order.direction * (0.40 * order.initial_risk_per_oz)
            )
            order.be_stage = 1
        elif order.be_stage <= 1 and (
            unrealized_r >= 1.45 or (unrealized_r >= 1.15 and vr_q < 0.95)
        ):
            # Fáze 2: Plný posun na Break-Even + 2x IBKR poplatek
            order.sl_price = order.entry_price + order.direction * fee_buffer_per_oz
            order.be_stage = 2
        # 3. Dynamický Chandelier Trailing pro Shorty (ochrana před V-reversal dnem u $4,111)
        if order.direction == -1 and unrealized_r >= 1.60:
            chandelier_sl = bar_close + 1.15 * current_atr
            order.sl_price = min(order.sl_price, chandelier_sl)
        # 4. Volatility-Clock Vertical Barrier
        bar_vol_step = (bar_high - bar_low) / max(current_atr, 1e-6)
        order.accumulated_vol_clock += bar_vol_step
        # Early Time-Decay Pegged Exit (úspora spreadu u mrtvých obchodů)
        if (
            order.accumulated_vol_clock >= 0.65 * order.max_vol_clock_budget
            and -0.20 <= unrealized_r <= 0.25
            and vr_q < 0.94
        ):
            return "EARLY_TIME_DECAY_PEGGED_LIMIT", bar_close
        if order.accumulated_vol_clock >= order.max_vol_clock_budget:
            return "VERTICAL_BARRIER_TIMEOUT", bar_close
        return None, None
