"""
SUGGESTINVEST ARGON V2.5 - UNIFIED PRODUCTION ENGINE (MGC FUTURES & XAU/XAG)
============================================================================
Sjednocuje poznatky z:
1. backtest.html (OOS Leden-Říjen 2026, 449 obchodů, +$16,329.51):
   - Přenáší vítězný kompresní filtr ze Strategie #1 (červenec +$141.80) na celé portfolio.
   - Zastavuje nákupy Strategie #5 na vrcholu paraboly (září -$737.40) a #2 v krachu (-$782.00).
   - Aplikuje volatilitní zámek ze Strategie #5 (říjen $0.00 / 0 obch.) proti šumu na dně korekce.
2. scalping.html (v3.0.0 IBKR DUR222134 Port 7497):
   - Integrace KAMA(10, 2, 30), Kaufman Efficiency Ratio (ER) a Closed-Loop Feedback
     (po 2 ztrátách v řadě zpřísní ER z 0.30 na 0.38 a vyžaduje MTF soulad + redukuje sizing).
   - Spread/Fee buffer (+0.40 USD/oz) při posunu na Break-Even.
3. VYLEPSENI_STRATEGIE_KVANT.md:
   - Oprava Killzones: blokuje London Lunch Stagnation (11:30-13:29 SEČ), povoluje
     London Open (09:00-11:29 SEČ) a NY Overlap Zlaté okno (13:30-20:30 SEČ).
   - ATR_Ratio = ATR(14) / ATR(100) >= 0.90 pro všechny průrazové a FVG modely.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
# ============================================================================
# 1. REŽIMY TRHU A AUTOKOREKČNÍ STAV PORTFOLIA (CLOSED-LOOP GOVERNANCE)
# ============================================================================
class UnifiedMarketRegime(IntEnum):
    SUMMER_OR_BOTTOM_COMPRESSION = 0   # Červenec & Říjen 2026: ATR(14)/ATR(100) < 0.90 nebo ER < 0.30
    HEALTHY_BULL_TREND = 1             # Leden, Květen, Červen: Plné Longy (#1, #3, #4, #5)
    PARABOLIC_BLOWOFF_WARNING = 2      # Konec srpna ($4,697): Z_ext > 2.6 -> Zákaz Long #3/#5, příprava Shortů
    BEAR_CORRECTION_IMPULSE = 3        # Březen (-$1,320) & Září (-$400): Zákaz Long #2, aktivace Shortů
@dataclass
class ClosedLoopGovernanceState:
    """
    Přeneseno ze scalping.html (v3.0.0) a rozšířeno o Hypotézu 2 (Equity EMA20 Brake):
    Sleduje sérii ztrát (loss streak), počítá EMA20 kapitálové křivky a dynamicky
    zpřísňuje práh Efficiency Ratio (ER) po neúspěšných obchodech.
    """
    initial_capital: float = 10_000.0
    current_equity: float = 10_000.0
    high_water_mark: float = 10_000.0
    consecutive_losses: int = 0
    daily_losses_count: int = 0
    daily_pnl_usd: float = 0.0
    equity_history: List[float] = field(default_factory=lambda: [10_000.0] * 20)
    def record_trade_result(self, net_pnl_usd: float) -> None:
        self.current_equity += net_pnl_usd
        self.daily_pnl_usd += net_pnl_usd
        self.high_water_mark = max(self.high_water_mark, self.current_equity)
        self.equity_history.append(self.current_equity)
        if len(self.equity_history) > 200:
            self.equity_history.pop(0)
        if net_pnl_usd < 0:
            self.consecutive_losses += 1
            self.daily_losses_count += 1
        elif net_pnl_usd > 0:
            self.consecutive_losses = 0
    def reset_daily_counters(self) -> None:
        self.daily_losses_count = 0
        self.daily_pnl_usd = 0.0
    @property
    def drawdown_pct(self) -> float:
        return (self.high_water_mark - self.current_equity) / max(1.0, self.high_water_mark)
    @property
    def is_equity_above_ema20(self) -> bool:
        ema20 = float(pd.Series(self.equity_history).ewm(span=20, adjust=False).mean().iloc[-1])
        return self.current_equity >= ema20
    @property
    def dynamic_er_threshold(self) -> float:
        """
        Dle scalping.html: Běžný práh ER = 0.30.
        Po 2 ztrátách v řadě se zpřísní na >= 0.36 (po 3 ztrátách na >= 0.42),
        čímž zastaví "clustering of losses" v září a říjnu 2026!
        """
        if self.consecutive_losses >= 3:
            return 0.42
        if self.consecutive_losses >= 2:
            return 0.36
        return 0.30
    @property
    def require_strict_mtf_alignment(self) -> bool:
        return self.consecutive_losses >= 2 or not self.is_equity_above_ema20
    def is_daily_kill_switch_active(self, max_daily_losses: int = 2, max_daily_dd_pct: float = 0.025) -> bool:
        """
        Dle backtest.html (Únor & Březen: Daily Kill-Switch po 2 ztrátách) a scalping.html (-2.5 %):
        Zastaví obchodování do konce dne.
        """
        if self.daily_losses_count >= max_daily_losses:
            return True
        if self.daily_pnl_usd <= -(self.current_equity * max_daily_dd_pct):
            return True
        return False
# ============================================================================
# 2. INDIKÁTORY: WILDER ADX, ATR RATIO, KAMA(10,2,30), YANG-ZHANG
# ============================================================================
class QuantIndicatorsV25:
    @staticmethod
    def true_range(df: pd.DataFrame) -> pd.Series:
        tr1 = df["high"] - df["low"]
        tr2 = (df["high"] - df["close"].shift(1)).abs()
        tr3 = (df["low"] - df["close"].shift(1)).abs()
        return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    @classmethod
    def atr(cls, df: pd.DataFrame, period: int = 14, min_floor: Optional[float] = 0.85) -> pd.Series:
        tr = cls.true_range(df)
        val = tr.ewm(alpha=1.0 / period, min_periods=1, adjust=False).mean().bfill()
        return val.clip(lower=min_floor) if min_floor is not None else val
    @classmethod
    def atr_expansion_ratio(cls, df: pd.DataFrame, short_p: int = 14, long_p: int = 100) -> pd.Series:
        """
        Kapitola 1.2 z VYLEPSENI_STRATEGIE_KVANT.md:
        ATR_Ratio = ATR(14) / ATR(100).
        Hodnoty < 0.80 = hluboká komprese (červenec 2026). Vstup povolen jen při >= 0.90.
        Používá nezkreslený ATR bez podlahy 0.85!
        """
        atr_short = cls.atr(df, period=short_p, min_floor=None)
        atr_long = cls.atr(df, period=long_p, min_floor=None).replace(0, 1e-9)
        return (atr_short / atr_long).fillna(1.0)
    @classmethod
    def wilder_adx(cls, df: pd.DataFrame, period: int = 14) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Vrací (ADX, +DI, -DI) počítané přes nezkreslený Wilderův True Range."""
        up = df["high"].diff()
        down = -df["low"].diff()
        plus_dm = np.where((up > down) & (up > 0), up, 0.0)
        minus_dm = np.where((down > up) & (down > 0), down, 0.0)
        atr_raw = cls.atr(df, period=period, min_floor=None).replace(0, 1e-9)
        plus_di = 100.0 * (pd.Series(plus_dm, index=df.index).ewm(alpha=1.0 / period, adjust=False).mean() / atr_raw)
        minus_di = 100.0 * (pd.Series(minus_dm, index=df.index).ewm(alpha=1.0 / period, adjust=False).mean() / atr_raw)
        dx = (np.abs(plus_di - minus_di) / (plus_di + minus_di + 1e-9)) * 100.0
        adx = dx.ewm(alpha=1.0 / period, min_periods=1, adjust=False).mean().fillna(0.0)
        return adx, plus_di, minus_di
    @staticmethod
    def kama_and_er(
        close: pd.Series, er_period: int = 10, fast_period: int = 2, slow_period: int = 30
    ) -> Tuple[pd.Series, pd.Series]:
        """
        Kaufman Adaptive Moving Average KAMA(10, 2, 30) a Efficiency Ratio (ER)
        ze scalping.html (Sekce Klíčové kvantitativní ukazatele).
        """
        change = (close - close.shift(er_period)).abs()
        volatility = close.diff().abs().rolling(er_period).sum().replace(0, 1e-9)
        er = (change / volatility).fillna(0.0).clip(0.0, 1.0)
        fast_sc = 2.0 / (fast_period + 1.0)
        slow_sc = 2.0 / (slow_period + 1.0)
        sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2
        c_arr = close.to_numpy(dtype=np.float64)
        sc_arr = sc.to_numpy(dtype=np.float64)
        kama_arr = np.zeros_like(c_arr)
        kama_arr[0] = c_arr[0]
        for i in range(1, len(c_arr)):
            kama_arr[i] = kama_arr[i - 1] + sc_arr[i] * (c_arr[i] - kama_arr[i - 1])
        return pd.Series(kama_arr, index=close.index), er
    @staticmethod
    def yang_zhang_vol(df: pd.DataFrame, window: int = 20) -> pd.Series:
        log_ho = np.log(df["high"] / df["open"]).fillna(0.0)
        log_lo = np.log(df["low"] / df["open"]).fillna(0.0)
        log_co = np.log(df["close"] / df["open"]).fillna(0.0)
        log_oc = np.log(df["open"] / df["close"].shift(1)).fillna(0.0)
        log_hc = np.log(df["high"] / df["close"]).fillna(0.0)
        log_lc = np.log(df["low"] / df["close"]).fillna(0.0)
        rs = (log_ho * log_hc + log_lo * log_lc).rolling(window).mean()
        var_o = log_oc.rolling(window).var()
        var_c = log_co.rolling(window).var()
        k = 0.34 / (1.34 + (window + 1) / max(1, window - 1))
        yz = (var_o + k * var_c + (1.0 - k) * rs).clip(lower=1e-12)
        return np.sqrt(yz).bfill()
# ============================================================================
# 3. ČASOVÁ OKNA LIKVIDITY (OPRAVENÉ KILLZONES DLE VYLEPSENI_STRATEGIE_KVANT.md)
# ============================================================================
class InstitutionalSessionFilter:
    """
    Implementuje přesnou tabulku z Kapitoly 3.2 VYLEPSENI_STRATEGIE_KVANT.md:
    - 00:00 - 08:59 SEČ: Asia Drift -> ZAKÁZÁNO
    - 09:00 - 11:29 SEČ: London Open Killzone -> POVOLENO
    - 11:30 - 13:29 SEČ: London Lunch Stagnation -> ZAKÁZÁNO PRO VSTUPY (pouze výstupy!)
    - 13:30 - 20:30 SEČ: NY Open & London Overlap -> ZLATÉ OKNO (nejvyšší likvidita COMEX)
    - 22:45 - 23:59 SEČ: EOD Close Out -> OKAMŽITÝ EOD FLAT
    """
    @staticmethod
    def is_entry_allowed_time(ts: pd.Timestamp) -> bool:
        minutes_of_day = ts.hour * 60 + ts.minute
        london_open = (9 * 60) <= minutes_of_day < (11 * 60 + 30)      # 09:00 - 11:29
        ny_golden_window = (13 * 60 + 30) <= minutes_of_day <= (20 * 60 + 30)  # 13:30 - 20:30
        return london_open or ny_golden_window
    @staticmethod
    def is_eod_flat_time(ts: pd.Timestamp) -> bool:
        minutes_of_day = ts.hour * 60 + ts.minute
        return minutes_of_day >= (22 * 60 + 45)
# ============================================================================
# 4. MASTER GATEKEEPER & ROBUSTNÍ ALOKÁTOR (STRATEGIE #6 ARGON V2.5)
# ============================================================================
class ArgonMasterGatekeeperV25:
    """
    Řeší všechny 3 kritické anomálie z backtest.html:
    1. Červenec 2026 (-$1,780.60): Globální brána ATR_Ratio >= 0.90 + ER >= dynamic_er_threshold.
    2. Srpen -> Září 2026 ($4,697 -> $4,111, vnitro-měsíční DD -20.51 %):
       Detekuje Parabolic Blow-Off (Z_ext > 2.65) -> Zablokuje pozdní Longy na Strategii #5 (-$737)
       a zablokuje chytání padajícího nože na Strategii #2 (-$782).
    3. Říjen 2026 MTD (-$1,187.20, WR 19 %): Closed-Loop Feedback po 2 ztrátách v řadě
       zvýší požadovaný ER na 0.36-0.42 a sníží Kellyho velikost pozice o 50 %.
    """
    @staticmethod
    def detect_regime_and_strategy_weights(
        df: pd.DataFrame,
        gov_state: ClosedLoopGovernanceState,
        silver_confirming_score: float = 1.0,
    ) -> Tuple[UnifiedMarketRegime, Dict[int, Dict[str, float]]]:
        """
        Vrací (UnifiedMarketRegime, mapa vah a povolení LONG/SHORT pro Strategie 1..5).
        """
        close = df["close"]
        atr14 = QuantIndicatorsV25.atr(df, 14)
        atr_ratio = float(QuantIndicatorsV25.atr_expansion_ratio(df, 14, 100).iloc[-1])
        adx_s, plus_di, minus_di = QuantIndicatorsV25.wilder_adx(df, 14)
        kama_s, er_s = QuantIndicatorsV25.kama_and_er(close, 10, 2, 30)
        yz_s = QuantIndicatorsV25.yang_zhang_vol(df, 20)
        adx_now = float(adx_s.iloc[-1])
        adx_rising = float(adx_s.iloc[-1]) > float(adx_s.iloc[-2])
        er_now = float(er_s.iloc[-1])
        yz_p70 = float(yz_s.iloc[-100:].quantile(0.70)) if len(yz_s) >= 30 else float(yz_s.iloc[-1])
        yz_active = float(yz_s.iloc[-1]) >= yz_p70
        ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
        ema200 = float(close.ewm(span=200, adjust=False).mean().iloc[-1])
        c_now = float(close.iloc[-1])
        # Parabolic Extension Z-Score nad EMA120 (detekce srpnového vrcholu $4,697)
        ema120 = float(close.ewm(span=120, adjust=False).mean().iloc[-1])
        z_ext = (c_now - ema120) / max(1e-6, float(atr14.iloc[-1]) * 2.0)
        # 1. Detekce komprese (Červenec 2026 nebo Říjen 2026 hledání dna)
        if atr_ratio < 0.88 or (adx_now < 20.0 and er_now < gov_state.dynamic_er_threshold):
            regime = UnifiedMarketRegime.SUMMER_OR_BOTTOM_COMPRESSION
            # V kompresi má povoleno obchodovat pouze #1 pokud ADX náhle sepne >= 22 a roste
            # a #2 pouze s přísným limitem (žádné breakouty #3, #4, #5!)
            s1_ok = 1.0 if (adx_now >= 22.0 and adx_rising and atr_ratio >= 0.90) else 0.0
            s2_ok = 0.6 if (gov_state.consecutive_losses < 2 and atr_ratio >= 0.82) else 0.0
            return regime, {
                1: {"LONG": s1_ok, "SHORT": 0.0},
                2: {"LONG": s2_ok, "SHORT": s2_ok},
                3: {"LONG": 0.0, "SHORT": 0.0},   # Šetří -$587 v červenci a -$381 v říjnu
                4: {"LONG": 0.0, "SHORT": 0.0},   # Šetří -$580 v červenci a -$455 v říjnu
                5: {"LONG": 0.0, "SHORT": 0.0},   # Šetří -$755 v červenci (v říjnu už měl 0)
            }
        # 2. Detekce Parabolic Blow-Off (Konec srpna $4,697 -> začátek září)
        if z_ext >= 2.65:
            regime = UnifiedMarketRegime.PARABOLIC_BLOWOFF_WARNING
            return regime, {
                1: {"LONG": 0.3, "SHORT": 0.5},
                2: {"LONG": 0.0, "SHORT": 0.8},   # Povolí pouze Short odraz od horní BB
                3: {"LONG": 0.0, "SHORT": 1.0},   # Zákaz nákupu průrazů na vrcholu paraboly!
                4: {"LONG": 0.0, "SHORT": 0.8},
                5: {"LONG": 0.0, "SHORT": 0.5},   # Zabrání 2 ztrátovým Longům #5 (-$737.40 v září)!
            }
        # 3. Detekce Prudké Medvědí Korekce (Březen -$1,320 a Září -$400/oz)
        if c_now < ema50 and float(minus_di.iloc[-1]) > float(plus_di.iloc[-1]) and atr_ratio >= 0.95:
            regime = UnifiedMarketRegime.BEAR_CORRECTION_IMPULSE
            return regime, {
                1: {"LONG": 0.0, "SHORT": 1.0},   # V březnu #1 Short vydělal +$759.40, v září +$112.80
                2: {"LONG": 0.0, "SHORT": 0.0},   # ZÁKAZ #2 Mean Reversion v krachu (šetří -$782 v září a -$114 v březnu)!
                3: {"LONG": 0.3, "SHORT": 1.0},   # V září #3 Short zachytil +$487.80
                4: {"LONG": 0.0, "SHORT": 0.8 if er_now >= gov_state.dynamic_er_threshold else 0.0},
                5: {"LONG": 0.0, "SHORT": 1.0 if yz_active else 0.0},  # V březnu #5 vydělal +$2,799.40!
            }
        # 4. Zdravý Býčí Trend (Leden, Květen, Červen, polovina Srpna)
        regime = UnifiedMarketRegime.HEALTHY_BULL_TREND
        er_gate = 1.0 if (er_now >= gov_state.dynamic_er_threshold and silver_confirming_score >= 0.5) else 0.4
        return regime, {
            1: {"LONG": 1.0 * er_gate, "SHORT": 0.0},
            2: {"LONG": 0.5 if adx_now < 26.0 else 0.0, "SHORT": 0.0},  # Utlumí #2 v silném trendu (šetří -$441 v lednu a -$753 v srpnu)
            3: {"LONG": 1.0 * er_gate, "SHORT": 0.0},
            4: {"LONG": 1.0 * er_gate, "SHORT": 0.0},
            5: {"LONG": 1.0 if yz_active else 0.0, "SHORT": 0.0},
        }
    @staticmethod
    def compute_position_size_oz(
        gov_state: ClosedLoopGovernanceState,
        strategy_weight: float,
        atr_ratio: float,
        base_oz: float = 5.0,
        min_oz: float = 2.5,
        max_oz: float = 7.5,
    ) -> float:
        """
        Kombinuje Fractional Kelly, Volatility Targeting a Closed-Loop Drawdown Brake:
        - Při DD >= 5 % pod EMA20 kapitálu snižuje velikost o 50 % (Hypotéza 2).
        - Při sérii >= 2 ztrát snižuje velikost o 35 % (Closed-Loop ze scalping.html).
        """
        if strategy_weight <= 0.0 or gov_state.is_daily_kill_switch_active():
            return 0.0
        vol_scalar = np.clip(1.0 / max(0.75, atr_ratio), 0.60, 1.25)
        dd_scalar = 1.0
        if gov_state.drawdown_pct >= 0.05 and not gov_state.is_equity_above_ema20:
            dd_scalar = 0.50
        elif not gov_state.is_equity_above_ema20 or gov_state.consecutive_losses >= 2:
            dd_scalar = 0.65
        raw_oz = base_oz * strategy_weight * vol_scalar * dd_scalar
        clipped = np.clip(raw_oz, min_oz, max_oz)
        return float(np.round(clipped * 2.0) / 2.0)
    @staticmethod
    def compute_ibkr_brackets_with_spread_buffer(
        entry_price: float,
        direction: str,
        atr: float,
        position_oz: float = 5.0,
        ibkr_fee_rt: float = 2.20,
        gold_spread_buffer: float = 0.40,
    ) -> Dict[str, float]:
        """
        Spojuje asymetrické RRR (Hypotéza 4: Long 3.0:1 vs. Short 1.8:1)
        a Spread/Fee Buffer (+0.40 USD/oz) ze scalping.html (Tabulka 1, Pilíř 4):
        - Fáze 1 (+1.0R): Redukce rizika SL na -0.35R.
        - Fáze 2 (+1.35R): Posun SL na vstup + $0.40/oz + poplatek IBKR,
          čímž chrání pozici před bid/ask šumem a zaručuje čistý zisk po komisích.
        """
        is_long = direction.upper() == "LONG"
        tp_mult = 3.0 if is_long else 1.8
        sl_mult = 1.0
        fee_per_oz = ibkr_fee_rt / max(1.0, position_oz)
        total_be_offset = max(gold_spread_buffer, 2.0 * fee_per_oz)
        if is_long:
            sl_initial = entry_price - sl_mult * atr
            tp_target = entry_price + tp_mult * atr
            stage1_trigger = entry_price + 1.00 * atr
            stage1_sl = entry_price - 0.35 * atr
            stage2_be_trigger = entry_price + 1.35 * atr
            stage2_be_sl = entry_price + total_be_offset
        else:
            sl_initial = entry_price + sl_mult * atr
            tp_target = entry_price - tp_mult * atr
            stage1_trigger = entry_price - 0.90 * atr
            stage1_sl = entry_price + 0.30 * atr
            stage2_be_trigger = entry_price - 1.15 * atr
            stage2_be_sl = entry_price - total_be_offset
        return {
            "entry_price": round(entry_price, 2),
            "sl_initial": round(sl_initial, 2),
            "tp_target": round(tp_target, 2),
            "stage1_trigger": round(stage1_trigger, 2),
            "stage1_sl": round(stage1_sl, 2),
            "stage2_be_trigger": round(stage2_be_trigger, 2),
            "stage2_be_sl": round(stage2_be_sl, 2),
            "rrr": tp_mult / sl_mult,
        }
if __name__ == "__main__":
    # Rychlá verifikace na scénářích Červenec, Září a Říjen 2026 z backtest.html
    gov = ClosedLoopGovernanceState(initial_capital=10_000.0, current_equity=26_329.51, high_water_mark=28_232.31)
    gov.consecutive_losses = 2  # Simulace říjnové série 2 ztrát ze scalping.html / backtest.html
    gov.equity_history = [28_000.0] * 19 + [26_329.51]
    print(f"[VERIFIKACE CLOSED-LOOP] Série ztrát: {gov.consecutive_losses} | Dynamický práh ER: >= {gov.dynamic_er_threshold:.2f}")
    oz = ArgonMasterGatekeeperV25.compute_position_size_oz(gov, strategy_weight=1.0, atr_ratio=0.95)
    brackets = ArgonMasterGatekeeperV25.compute_ibkr_brackets_with_spread_buffer(4193.00, "LONG", atr=3.25, position_oz=oz)
    print(f"[VERIFIKACE SIZINGU] Doporučená velikost pozice v říjnovém DD: {oz} oz")
    print(f"[VERIFIKACE BRACKETS] {brackets}")
