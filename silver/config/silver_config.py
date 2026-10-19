"""
silver_config.py
================
Centrální konfigurace pro SilverEdge v1.0 – Micro Silver (SIL) / Full Silver (SI) Futures.
Odděleno od Gold (Argon) konfigurace. Všechny Silver-specifické parametry jsou zde.

Principy:
- Silver = 55 % průmyslový kov, 45 % investiční → jiná citlivost na makro eventy
- Silver volatilita = 2–3× vyšší než Gold v % ATR
- Gold/Silver Ratio (GSR) = unikátní mean-reversion signál
- Shanghai session (SHFE) = relevantní pro Silver (ne pro Gold)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List

# =====================================================================
# 1. INSTRUMENT SPECIFICATION
# =====================================================================

@dataclass
class SilverInstrumentConfig:
    """Konfigurace futures kontraktu Micro Silver (SIL) nebo Full Silver (SI)."""

    # Micro Silver (SIL) – default pro $10k–$30k účet
    symbol: str = "SIL"
    sec_type: str = "FUT"
    exchange: str = "NYMEX"
    currency: str = "USD"
    contract_multiplier: int = 1000          # 1000 oz / kontrakt (Micro)
    tick_size: float = 0.005                 # $0.005 / oz
    tick_value: float = 5.00                 # $5.00 / tick
    min_tick_move: float = 0.005

    # Full Silver (SI) – pro větší účty ($50k+)
    FULL_SYMBOL: str = "SI"
    FULL_MULTIPLIER: int = 5000              # 5000 oz / kontrakt
    FULL_TICK_VALUE: float = 25.00           # $25.00 / tick

    # Roll-over kalendář Silver
    EXPIRY_MONTHS: List[int] = field(default_factory=lambda: [3, 5, 7, 9, 12])
    ROLL_DAYS_BEFORE_EXPIRY: int = 10
    ESTIMATED_ROLL_COST_PER_OZ: float = 0.15  # $0.10–$0.30

    # Slippage model
    SLIPPAGE_MULTIPLIER: float = 1.30        # 30 % vyšší než Gold (nižší likvidita)
    COMMISSION_PER_CONTRACT: float = 1.25    # $1.25 per side per SIL Micro


# =====================================================================
# 2. KILLZONE – OBCHODNÍ OKNA PRO SILVER
# =====================================================================

@dataclass
class SilverKillzoneConfig:
    """
    Silver má jiné likvidní okno než Gold:
    - Shanghai session (SHFE) je relevantní pro Silver!
    - London PM Fix méně důležitý pro Silver vs Gold
    """
    # Povolené obchodní okna (SEČ / CET)
    SHANGHAI_SESSION_START: int = 2 * 60          # 02:00 SEČ
    SHANGHAI_SESSION_END: int = 8 * 60            # 08:00 SEČ
    LONDON_OPEN_START: int = 9 * 60               # 09:00 SEČ
    LONDON_OPEN_END: int = 11 * 60 + 30           # 11:30 SEČ
    NY_SESSION_START: int = 14 * 60               # 14:00 SEČ
    NY_SESSION_END: int = 20 * 60 + 30            # 20:30 SEČ

    # Zakázané okna
    LONDON_LUNCH_START: int = 11 * 60 + 30        # 11:30 SEČ
    LONDON_LUNCH_END: int = 13 * 60 + 59          # 13:59 SEČ
    COMEX_SETTLEMENT_START: int = 19 * 60 + 15    # 19:15 SEČ
    COMEX_SETTLEMENT_END: int = 19 * 60 + 35      # 19:35 SEČ

    # Teze #2: Shanghai session (SGE/SHFE) je hlavní fyzický trh stříbra -> plný sizing 1.00!
    SHANGHAI_SIZE_MULTIPLIER: float = 1.00        # Zvýšeno z 0.50 na 1.00 (+1,096 USD při býčí Šanghaji)
    LONDON_SIZE_MULTIPLIER: float = 0.75          # Konzervativní multiplikátor 0.75 v Londýně

    def is_valid_killzone(self, hour: int, minute: int) -> bool:
        """Vrací True pokud je aktuální čas v povoleném obchodním okně."""
        minutes_of_day = hour * 60 + minute

        # Zákaz COMEX settlement
        if self.COMEX_SETTLEMENT_START <= minutes_of_day <= self.COMEX_SETTLEMENT_END:
            return False

        # Zákaz London Lunch
        if self.LONDON_LUNCH_START <= minutes_of_day <= self.LONDON_LUNCH_END:
            return False

        # Povolená okna
        shanghai = self.SHANGHAI_SESSION_START <= minutes_of_day < self.SHANGHAI_SESSION_END
        london = self.LONDON_OPEN_START <= minutes_of_day < self.LONDON_OPEN_END
        ny = self.NY_SESSION_START <= minutes_of_day <= self.NY_SESSION_END

        return bool(shanghai or london or ny)

    def get_session_size_multiplier(self, hour: int, minute: int) -> float:
        """Vrací sizing multiplier podle fyziky likvidity jednotlivých seancí stříbra."""
        minutes_of_day = hour * 60 + minute
        if self.SHANGHAI_SESSION_START <= minutes_of_day < self.SHANGHAI_SESSION_END:
            return self.SHANGHAI_SIZE_MULTIPLIER
        if self.LONDON_OPEN_START <= minutes_of_day < self.LONDON_OPEN_END:
            return self.LONDON_SIZE_MULTIPLIER
        return 1.0


# =====================================================================
# 3. RISK & KELLY – KONZERVATIVNĚJŠÍ PRO SILVER VOLATILITU
# =====================================================================

@dataclass
class SilverRiskConfig:
    """
    Silver vyžaduje konzervativnější money management než Gold:
    - ATR v % je 2–3× vyšší
    - Flash crashes jsou častější a hlubší
    - Margin requirements se mění dynamicky více než u Gold
    """
    initial_capital: float = 10_000.0
    sovereign_floor: float = 9_000.0             # Ochranný floor (90 % kapitálu)
    max_daily_loss_usd: float = 400.0            # Max ztráta za den
    max_monthly_loss_usd: float = 550.0          # Max měsíční ztráta (circuit breaker před $9000 floorem)
    max_contracts: int = 1                        # Max otevřené kontrakty pro $10k účet (Argon Tip #1: navýšit na 2 až při equity > $18k)
    max_risk_pct_per_trade: float = 0.015         # 1.5 % per trade ($150 max cap na $10k účtu)
    kelly_half_divisor: int = 3                   # Half-Kelly = f*/3
    drawdown_threshold_pct: float = 0.06          # 6 % drawdown = snížení sizingu (Gold = 8 %)
    equity_ema_span: int = 20                     # EMA pro equity brake
    margin_safety_buffer: float = 1.5             # 1.5× initial margin (Gold = 1.2×)

    # ATR kalibrace
    atr_fast_period: int = 14
    atr_slow_period: int = 100
    atr_min_floor: float = 0.005                  # Silver tick = $0.005 (1 tick SIL floor)

    # Volatility Gate & Adaptive Sizing
    volatility_gate_active: bool = True
    max_sl_dollars_per_oz: float = 0.40           # Max možný SL na 1 kontrakt SIL ($0.40 * 1000 oz = $400 max risk)
    skip_trade_on_wide_sl: bool = True            # Pokud SL > 0.40 $/oz a není povolen fractional sizing, bot obchod přeskočí
    allow_fractional_sizing: bool = True          # Povolit adaptivní škálování pozice v oz (CFD/micro lots) pro zachování stálého rizika
    target_risk_usd_per_trade: float = 120.0      # Cílové dolarové riziko per trade ($120 pro bezpečný $9000 floor buffer)
    min_contract_oz: float = 25.0                 # Minimální velikost pozice (25 oz = 0.025 SIL)
    max_contract_oz: float = 1000.0               # Maximální velikost pozice pro $10k účet (1000 oz = 1 SIL)

    # Size limity v oz (1 SIL Micro = 1000 oz)
    min_contracts: int = 1
    full_contract_oz: float = 1000.0              # 1 SIL Micro = 1000 oz (Argon Tip #1 oprava!)
    equity_threshold_for_2_contracts: float = 18_000.0 # Povolení 2. kontraktu až od $18k ekvity

    # OPEX kalibrace
    opex_size_multiplier: float = 0.50            # Silver OPEX = konzervativnější (Gold = 0.7)

    # Cross-komodita hedge
    correlated_gold_hedge: bool = True            # Automaticky zmenšit pokud Gold+Silver open
    gold_silver_correlation_threshold: float = 0.85


# =====================================================================
# 4. MAKRO VÁHY SPECIFICKÉ PRO SILVER
# =====================================================================

SILVER_MACRO_WEIGHTS: Dict[str, float] = {
    "real_yield_spike":         -0.40,    # Stejné jako Gold
    "gold_silver_ratio_high":   +0.35,    # NOVÉ: GSR > 85 = Silver levný = Long bias
    "gold_silver_ratio_low":    -0.30,    # NOVÉ: GSR < 60 = Silver drahý = Short bias
    "china_pmi_weak":           -0.30,    # NOVÉ: Průmyslová poptávka Číny klesá
    "china_pmi_strong":         +0.25,    # NOVÉ: Průmyslová poptávka Číny roste
    "ism_manufacturing_weak":   -0.25,    # NOVÉ: US ISM Manufacturing < 50
    "ism_manufacturing_strong": +0.20,    # NOVÉ: US ISM Manufacturing > 53
    "gold_vol_stress":          -0.20,    # Zachováno z Gold
    "weak_treasury_auction":    -0.15,    # Zachováno z Gold
    "solar_demand_spike":       +0.20,    # NOVÉ: EIA solární instalace boom
    "ev_demand_spike":          +0.15,    # NOVÉ: EV prodeje nahoru → Silver v elektronice
    "silver_squeeze_risk":      +0.40,    # NOVÉ: Short squeeze pattern (WSB 2021 style)
    "india_festival_demand":    +0.10,    # NOVÉ: Indická sezónní poptávka (Diwali Q4)
}


# =====================================================================
# 5. STRATEGIE PARAMETRY – KALIBROVANÉ PRO SILVER
# =====================================================================

@dataclass
class SilverStrategyParams:
    """Parametry 7 strategií kalibrovaných pro Silver volatilitu."""

    # Strategy #1: Trend Follow
    trend_adx_threshold: float = 22.0          # Gold = 25, Silver trendy kratší
    trend_ema_fast: int = 9
    trend_ema_slow: int = 21

    # Strategy #2: Mean Reversion
    reversion_rsi_oversold: float = 25.0       # Gold = 30, Silver přestřeluje více
    reversion_rsi_overbought: float = 75.0     # Gold = 70
    reversion_bb_period: int = 20
    reversion_bb_std: float = 2.5              # Gold = 2.0, wider pro Silver

    # Strategy #3: Breakout Momentum
    breakout_atr_sl_multiplier: float = 2.0    # Gold = 1.5, wider pro volatilitu
    breakout_atr_tp_multiplier: float = 3.0    # Gold = 2.25
    breakout_volume_surge: float = 1.8

    # Strategy #4: Macro Event
    macro_events_silver: list = field(default_factory=lambda: [
        "CPI", "NFP", "FOMC", "PPI",
        "CHINA_CAIXIN_PMI", "ISM_MANUFACTURING",
        "EIA_SOLAR_MONTHLY", "INDIA_RBI_RATE",
    ])

    # Strategy #5: L2 DOM Flow
    dom_min_levels: int = 5                    # Silver DOM je tenčí
    dom_imbalance_threshold: float = 1.8       # Stejné jako Gold

    # Strategy #6: News & Proxy Sentiment (Silver miners: PAAS, HL, AG)
    silver_proxy_tickers: list = field(default_factory=lambda: [
        "SLV", "PAAS", "HL", "AG", "WPM", "MAG",
    ])

    # Strategy #7: GSR Mean Reversion (UNIKÁTNÍ PRO SILVER - Argon Tip #2)
    gsr_use_rolling: bool = True               # Rolling Z-score místo statického průměru
    gsr_rolling_window_days: int = 90          # Optimální okno 60–120 dní
    gsr_historical_mean: float = 68.0          # Fallback průměr
    gsr_historical_std: float = 15.0
    gsr_strong_long_zscore: float = 2.0        # GSR > mean + 2σ = Strong Long
    gsr_weak_long_zscore: float = 1.2
    gsr_strong_short_zscore: float = -2.0      # GSR < mean - 2σ = Strong Short
    gsr_weak_short_zscore: float = -1.2

    # Teze #1: GSR (Gold/Silver Ratio) kointegrativní prahy
    gsr_mania_long_ban: float = 55.5           # Pod GSR 55.5 (a zejména < 40) striktní zákaz trendových Longů!
    gsr_overheated_threshold: float = 59.0     # Pásmo přehřátého stříbra (povoleno jen Fading / Pullback)
    gsr_undervalued_long_boost: float = 62.0   # Nad GSR 62.0 (a zejména > 80) asymetrický Long boost

    # Teze #2: Šanghajská fyzická prémie & SGE/SHFE Drift
    shanghai_bearish_veto_pct: float = -0.05   # Pokud Šanghaj (02:00-08:00 SEČ) klesá < -0.05 %, zákaz západních Longů
    shanghai_bullish_lead_pct: float = 0.10    # Silná fyzická akumulace v Šanghaji (> +0.10 %)

    # Teze #3: COT Commercial Swap Dealers & Managed Money Crowding
    cot_extreme_spec_long_pct: float = 85.0    # Managed Money > 85. percentil = hrozí organizovaný výplach (zákaz breakoutů)
    cot_commercial_cover_pct: float = 20.0     # Swap Dealers pokrývají shorty (< 20. percentil) = silný Long signál


# =====================================================================
# 6. HMM REGIME – SILVER SPECIFICKÉ PŘECHODY
# =====================================================================

@dataclass
class SilverRegimeConfig:
    """
    4-stavový HMM pro Silver – rychlejší přechody než Gold.
    Silver typicky přechází TREND→CORRECTION za 3 týdny (Gold = 6 týdnů).
    """
    # BlowOff Exhaustion Detector – Silver specific
    hurst_threshold: float = 0.40              # Gold = 0.45, Silver nižší persistence
    volume_imbalance_threshold: float = 2.2    # Gold = 1.8, Silver má vyšší volume spiky
    rsi_divergence_window: int = 8             # Gold = 12, rychlejší divergence

    # Regime transition speeds
    trend_to_correction_bars: int = 60 * 24 * 15  # ~15 dní (Gold = 30 dní)
    chop_min_duration_bars: int = 60 * 24 * 5     # Min 5 dní v Chop (Gold = 10 dní)

    # Squeeze detection
    squeeze_daily_threshold_pct: float = 8.0   # Denní pohyb > 8 % = squeeze alert
    squeeze_position_reduction: float = 0.50   # Snížení pozice na 50 %


# =====================================================================
# 7. ALERTING KONFIGURACE
# =====================================================================

@dataclass
class SilverAlertConfig:
    """Alerty specifické pro Silver rizika."""
    squeeze_daily_move_pct: float = 8.0        # Denní pohyb > 8 % → alert
    gsr_extreme_high: float = 90.0             # GSR > 90 → contrarian Long signal
    gsr_extreme_low: float = 55.0              # GSR < 55 → contrarian Short signal
    china_pmi_miss_threshold: float = 3.0      # Caixin PMI miss > 3 body → zákaz Long 24h
    roll_approaching_days: int = 12            # 12 dní před expirací → notifikace
    margin_call_buffer_pct: float = 0.15       # 15 % nad maintenance margin → warning


# =====================================================================
# 8. DATA SOURCES – SILVER SPECIFIC (Argon Tip #2 a #3)
# =====================================================================

# Futures-based feeds (běží 23h denně)
SILVER_HIGH_ALPHA_TICKERS = ["SI=F", "GC=F", "HG=F", "CNH=X", "SLV", "^GVZ", "^VIX", "TIP", "IEF"]
SILVER_PROXY_MINERS = ["PAAS", "HL", "AG", "WPM", "MAG", "EXK", "SILJ"]

# SHFE asijské proxy (02:00–08:00 SEČ): Používáme reálně obchodované noční instrumenty!
# Copper (HG=F/MHG), USD/CNH a Hang Seng futures – nikoliv US ETF (MCHI/FXI, která spí)
SILVER_SHFE_ACTIVE_PROXIES = ["HG=F", "CNH=X", "^HSI"]
SILVER_US_EQUITY_PROXIES = ["MCHI", "FXI", "GXC"]  # Pouze během US seance (15:30–22:00 SEČ)

# CFTC COT data (Point-in-Time: zveřejnění pátek 15:30 ET / 21:30 SEČ)
CFTC_COT_URL = "https://www.cftc.gov/dea/newcot/deacot.zip"
CFTC_COT_SILVER_FILTER = "SILVER - COMMODITY EXCHANGE INC."
CFTC_UPDATE_DAY = 4  # Pátek (weekday index)
CFTC_RELEASE_TIME_ET = "15:30"

# EIA Solar Data
EIA_SOLAR_API = "https://api.eia.gov/v2/electricity/facility-fuel/data/"

# Silver Institute
SILVER_INSTITUTE_URL = "https://www.silverinstitute.org"

# =====================================================================
# 9. IBKR CONNECTION & CLIENT ID CONFIGURATION (Argon Tip #7)
# =====================================================================
IBKR_HOST = "127.0.0.1"
IBKR_LIVE_PORT = 4001     # Live API port (sdílený s Gold)
IBKR_PAPER_PORT = 4002    # Paper API port (sdílený s Gold)

# Striktně oddělená clientId pro zamezení kolizím mezi Gold a Silver:
IBKR_GOLD_CLIENT_ID = 10
IBKR_SILVER_CLIENT_ID = 20

