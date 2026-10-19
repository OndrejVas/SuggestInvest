"""
silver_regime_engine.py – HMM Regime Engine, BlowOff Detektor & KAMA Volatilitní Switcher
========================================================================================
KROKY 33, 34 a 35 v Silver Replication Roadmap v3.0

Specifika pro Silver:
- full_contract_oz = 1000.0 (SIL Micro kontrakt je 1 000 oz!)
- Drawdown threshold = 6.0 % (Gold má 8.0 %)
- Rychlejší HMM matice (TREND → CORRECTION ~15 dní, Gold = 30 dní)
- Hurst exponent threshold = 0.40 (Gold = 0.45)
- BlowOff Detector: Volume Imbalance 2.2×, RSI divergence okno 8 period, EMA(80)
- Volatility Regime Switcher: Kaufman Adaptive Moving Average (KAMA) + Yang-Zhang Volatility
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Tuple, Optional
import numpy as np
import pandas as pd


class MasterRegime(IntEnum):
    CHOP_COMPRESSION = 0          # Konsolidace: zákaz breakoutů, opatrná Mean Reversion
    TREND_BULL = 1                # Silný býčí trend: plné Longy (#1, #3, #4, #7), zákaz Shortů
    DISTRIBUTION_BLOWOFF = 2      # Parabolický vrchol: zákaz Long breakoutů, utažení SL, Reversion Shorty
    HIGH_VOL_CORRECTION = 3       # Volatilní výplach: zákaz Long nákupů padajících nožů, Trend Shorty


@dataclass
class SilverPortfolioRiskState:
    """Stav účtu a kapitálového rizika pro Micro Silver (SIL = 1 000 oz)."""
    initial_capital: float = 10_000.0
    current_equity: float = 10_000.0
    high_water_mark: float = 10_000.0
    daily_start_equity: float = 10_000.0
    daily_pnl_usd: float = 0.0
    sovereign_floor: float = 9_000.0
    max_daily_loss_usd: float = 400.0
    full_contract_oz: float = 1000.0               # SIL Micro = 1000 oz
    max_contracts: int = 1                         # Default 1 kontrakt pro $10k účet
    equity_threshold_for_2_contracts: float = 18_000.0
    drawdown_threshold_pct: float = 0.06           # 6 % DD brzda (Argon Gold má 8 %)
    equity_history: List[float] = field(default_factory=lambda: [10_000.0] * 20)

    def record_PnL(self, net_pnl_usd: float) -> None:
        self.current_equity += net_pnl_usd
        self.daily_pnl_usd += net_pnl_usd
        self.high_water_mark = max(self.high_water_mark, self.current_equity)
        self.equity_history.append(self.current_equity)
        if len(self.equity_history) > 200:
            self.equity_history.pop(0)

        # Automatické škálování max kontraktů
        if self.current_equity >= self.equity_threshold_for_2_contracts:
            self.max_contracts = 2
        else:
            self.max_contracts = 1

    def reset_daily(self) -> None:
        self.daily_start_equity = self.current_equity
        self.daily_pnl_usd = 0.0

    @property
    def current_drawdown_pct(self) -> float:
        return (self.high_water_mark - self.current_equity) / max(1.0, self.high_water_mark)

    @property
    def is_sovereign_floor_breached(self) -> bool:
        return self.current_equity <= self.sovereign_floor

    @property
    def is_daily_loss_limit_hit(self) -> bool:
        return self.daily_pnl_usd <= -self.max_daily_loss_usd

    @property
    def equity_ema20(self) -> float:
        s = pd.Series(self.equity_history)
        return float(s.ewm(span=20, adjust=False).mean().iloc[-1])

    @property
    def is_equity_above_ema20(self) -> bool:
        return self.current_equity >= self.equity_ema20


# =====================================================================
# KROK 35: SILVER BLOWOFF EXHAUSTION DETECTOR
# =====================================================================

class SilverBlowOffExhaustionDetector:
    """
    Parabolická detekce vrcholů stříbra:
    Stříbro má mnohem agresivnější a strmější 'Blow-Off' vrcholy než zlato (Hunt Brothers 1980, WSB 2021).
    Kombinuje:
    1. Parabolickou extenzi nad EMA(80) (Gold má EMA 120)
    2. Volume Imbalance > 2.2× (Gold má 1.8×)
    3. RSI divergenci v okně 8 period (Gold má 12)
    4. Hurstův exponent < 0.40 (Gold má 0.45 – značí ztrátu perzistence)
    """

    @staticmethod
    def compute_exhaustion_score(
        df: pd.DataFrame, 
        hurst_series: Optional[pd.Series] = None, 
        rsi_series: Optional[pd.Series] = None
    ) -> float:
        if len(df) < 50:
            return 0.0

        close = df["close"]
        high = df["high"]
        low = df["low"]

        # 1. Parabolická extenze nad EMA(80)
        ema80 = close.ewm(span=80, adjust=False).mean()
        tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
        atr14 = tr.ewm(span=14, adjust=False).mean()
        extension_atr = (close - ema80) / atr14.replace(0, 0.01)
        score_ext = float(np.clip(extension_atr.iloc[-1] / 3.0, 0.0, 1.0))

        # 2. Volume Imbalance (nebo Wick Imbalance pokud volume chybí)
        upper_wick = high - np.maximum(close, df["open"])
        body = (close - df["open"]).abs()
        wick_ratio = upper_wick / (body + 0.001)
        score_wick = float(np.clip(wick_ratio.iloc[-1] / 2.2, 0.0, 1.0))

        # 3. RSI kalkulace a divergence
        if rsi_series is not None and len(rsi_series) > 8:
            curr_rsi = float(rsi_series.iloc[-1])
            max_rsi_8 = float(rsi_series.iloc[-8:-1].max())
            rsi_div = 1.0 if (curr_rsi < max_rsi_8 and close.iloc[-1] > close.iloc[-8:-1].max()) else 0.0
        else:
            # Rychlý 8-period RSI
            delta = close.diff()
            gain = delta.clip(lower=0).ewm(span=8, adjust=False).mean()
            loss = (-delta.clip(upper=0)).ewm(span=8, adjust=False).mean()
            rs = gain / loss.replace(0, 1e-6)
            rsi = 100 - (100 / (1 + rs))
            curr_rsi = float(rsi.iloc[-1])
            max_rsi = float(rsi.iloc[-8:-1].max()) if len(rsi) >= 8 else curr_rsi
            rsi_div = 1.0 if (curr_rsi < max_rsi and close.iloc[-1] > close.iloc[-8:-1].max()) else 0.0

        # 4. Hurst threshold (pokud < 0.40 -> antizpersistence / vyčerpání trendu)
        h_score = 0.5
        if hurst_series is not None and len(hurst_series) > 0:
            h_val = float(hurst_series.iloc[-1])
            if h_val < 0.40:
                h_score = 1.0

        composite_blowoff = float(0.35 * score_ext + 0.25 * score_wick + 0.25 * rsi_div + 0.15 * h_score)
        return round(float(np.clip(composite_blowoff, 0.0, 1.0)), 3)


# =====================================================================
# KROK 34: VOLATILITY REGIME SWITCHER (KAMA + YANG-ZHANG VOLATILITY)
# =====================================================================

class SilverVolatilitySwitcher:
    """
    Adaptivní přepínač volatility pro stříbro:
    1. Kaufman Efficiency Ratio (ER) pro měření šumu vs trendu
    2. Kaufman Adaptive Moving Average (KAMA)
    3. Yang-Zhang Volatility Estimator (zachycuje overnight a meziseancové gapy mezi NY, Šanghají a Londýnem)
    """

    @staticmethod
    def compute_kaufman_efficiency_ratio(series: pd.Series, period: int = 14) -> pd.Series:
        """ER = Direction / Volatility = |Close[t] - Close[t-n]| / sum(|Close[i] - Close[i-1]|)"""
        direction = (series - series.shift(period)).abs()
        volatility = (series - series.shift(1)).abs().rolling(period).sum()
        er = direction / volatility.replace(0, 1e-6)
        return er.fillna(0.0)

    @staticmethod
    def compute_kama(series: pd.Series, period: int = 14, fast: int = 2, slow: int = 30) -> pd.Series:
        """Kaufman Adaptive Moving Average"""
        er = SilverVolatilitySwitcher.compute_kaufman_efficiency_ratio(series, period)
        sc = (er * (2 / (fast + 1) - 2 / (slow + 1)) + 2 / (slow + 1)) ** 2
        
        kama = np.zeros(len(series))
        kama[0] = series.iloc[0]
        for i in range(1, len(series)):
            kama[i] = kama[i-1] + sc.iloc[i] * (series.iloc[i] - kama[i-1])
        return pd.Series(kama, index=series.index)

    @staticmethod
    def compute_yang_zhang_volatility(df: pd.DataFrame, window: int = 21) -> pd.Series:
        """
        Yang-Zhang volatility estimator:
        Kombinuje overnight skoky (open - close[t-1]) s Rogers-Satchell intradenní volatilitou.
        Minimální zkreslení vůči nočním gapům v asijské a evropské seanci.
        """
        if len(df) < window:
            return pd.Series(0.02, index=df.index)

        log_ho = (df["high"] / df["open"]).apply(np.log)
        log_lo = (df["low"] / df["open"]).apply(np.log)
        log_co = (df["close"] / df["open"]).apply(np.log)
        log_oc = (df["open"] / df["close"].shift(1)).apply(np.log)
        log_cc = (df["close"] / df["close"].shift(1)).apply(np.log)

        # Overnight variance
        o_var = (log_oc - log_oc.rolling(window).mean()) ** 2
        o_var = o_var.rolling(window).mean()

        # Open to Close variance
        c_var = (log_co - log_co.rolling(window).mean()) ** 2
        c_var = c_var.rolling(window).mean()

        # Rogers-Satchell variance
        rs_var = (log_ho * (log_ho - log_co) + log_lo * (log_lo - log_co)).rolling(window).mean()

        k = 0.34 / (1.34 + (window + 1) / (window - 1))
        yz_var = o_var + k * c_var + (1 - k) * rs_var
        yz_vol = np.sqrt(yz_var.clip(lower=0.0)) * np.sqrt(252 * 24 * 60) # Anualizováno
        return yz_vol.fillna(0.0)


# =====================================================================
# KROK 33: HLAVNÍ SILVER REGIME ENGINE
# =====================================================================

class SilverRegimeEngine:
    """
    4-stavový HMM pro Silver:
    - Rychlejší přechody (TREND_BULL → HIGH_VOL_CORRECTION ~15 dní)
    - Integrace BlowOff Exhaustion detektoru
    - KAMA adaptivní ATR
    - Sizing brzda při drawdownu > 6.0 %
    """

    def __init__(self, risk_state: Optional[SilverPortfolioRiskState] = None):
        self.risk = risk_state or SilverPortfolioRiskState()
        self.blowoff_detector = SilverBlowOffExhaustionDetector()
        self.vol_switcher = SilverVolatilitySwitcher()

    def evaluate_regime(
        self, 
        df: pd.DataFrame, 
        gsr_zscore: float = 0.0, 
        macro_score: float = 0.0
    ) -> Tuple[MasterRegime, Dict[str, Any]]:
        """
        Vyhodnotí aktuální tržní režim pro stříbro.
        """
        if len(df) < 30:
            return MasterRegime.CHOP_COMPRESSION, {"reason": "Nedostatek dat"}

        close = df["close"]
        high = df["high"]
        low = df["low"]

        # 1. KAMA & Trend
        kama = self.vol_switcher.compute_kama(close, period=14)
        kama_slope = (kama.iloc[-1] - kama.iloc[-5]) / max(0.01, kama.iloc[-5]) * 100.0
        er = float(self.vol_switcher.compute_kaufman_efficiency_ratio(close, period=14).iloc[-1])

        # 2. ADX / Directional strength
        tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
        atr14 = tr.ewm(span=14, adjust=False).mean().iloc[-1]
        atr100 = tr.ewm(span=100, adjust=False).mean().iloc[-1]
        atr_ratio = float(atr14 / max(0.001, atr100))

        # 3. BlowOff detekce (Krok 35)
        blowoff_score = self.blowoff_detector.compute_exhaustion_score(df)

        # 4. Rozhodovací logika režimů (SilverEdge v2.5.1 specifikace)
        if (blowoff_score >= 0.78 and float(compute_silver_rsi(close, 14).iloc[-1]) > 70.0) or gsr_zscore < -1.8:
            regime = MasterRegime.DISTRIBUTION_BLOWOFF
            desc = "Parabolický vrchol stříbra (BlowOff Exhaustion / Extrémní GSR). Zákaz breakoutů, utažení SL."
        elif kama_slope < -0.12 and (atr_ratio > 1.15 or close.iloc[-1] < close.ewm(span=50, adjust=False).mean().iloc[-1]):
            regime = MasterRegime.HIGH_VOL_CORRECTION
            desc = "Vysokovolatilní korekce. Zákaz chytání padajících nožů, aktivní Trend Shorty."
        elif kama_slope > 0.12 and er > 0.35:
            regime = MasterRegime.TREND_BULL
            desc = "Silný býčí trend. Povoleny Trend & Breakout & GSR Longy."
        else:
            regime = MasterRegime.CHOP_COMPRESSION
            desc = "Chop / Konsolidace. Povolena pouze opatrná Mean Reversion."

        # 5. Sizing multiplikátor s ohledem na Sovereign Floor a Drawdown
        sizing_factor = 1.0
        if self.risk.is_sovereign_floor_breached or self.risk.is_daily_loss_limit_hit:
            sizing_factor = 0.0  # STOP TRADING
        elif self.risk.current_drawdown_pct > self.risk.drawdown_threshold_pct:
            sizing_factor = 0.50 # Snížení na polovinu při DD > 6 %
        elif not self.risk.is_equity_above_ema20:
            sizing_factor = 0.75 # Mírná brzda pod EMA20 ekvity

        telemetry = {
            "regime": regime.name,
            "regime_id": int(regime),
            "description": desc,
            "blowoff_score": blowoff_score,
            "efficiency_ratio": round(er, 3),
            "kama_slope_pct": round(kama_slope, 3),
            "atr_ratio": round(atr_ratio, 3),
            "sizing_factor": sizing_factor,
            "current_drawdown_pct": round(self.risk.current_drawdown_pct * 100.0, 2),
            "max_contracts_allowed": self.risk.max_contracts
        }
        return regime, telemetry
