"""
instruments.py
--------------
Definice a specifikace nízkonákladových pákových aktiv pro ultra-krátkodobý intraday scalping.
Filtrováno podle kritéria: poměr Spread / ATR(M5) < 6 %.
"""

from typing import Dict, Any, List

SCALPING_INSTRUMENTS: Dict[str, Dict[str, Any]] = {
    # 1. INDEXOVÉ DERIVÁTY (Ultra-likvidní CFD / Futures s těsným spreadem)
    "US500": {
        "symbol_xtb": "US500",
        "symbol_ibkr": "MES",  # Micro E-mini S&P 500 Futures / CFD
        "symbol_yahoo": "^GSPC",
        "name": "S&P 500 Index",
        "category": "INDEX",
        "currency": "USD",
        "leverage": 20,  # 1:20 CFD (nebo 1:50 futures)
        "typical_spread": 0.45,  # body
        "tick_size": 0.25,
        "avg_m5_atr": 8.5,
        "spread_atr_ratio_pct": 5.2,
        "best_session": "US (15:30 - 22:00 CET)",
        "correlated_with": ["USTEC", "DE40"],
        "inverse_correlated_with": ["VIX"],
        "desc": "Základní pilíř globálního tradingu s největší hloubkou trhu."
    },
    "USTEC": {
        "symbol_xtb": "US100",
        "symbol_ibkr": "MNQ",  # Micro E-mini Nasdaq 100 Futures / CFD
        "symbol_yahoo": "^NDX",
        "name": "Nasdaq 100 Index",
        "category": "INDEX",
        "currency": "USD",
        "leverage": 20,
        "typical_spread": 1.2,  # body
        "tick_size": 0.25,
        "avg_m5_atr": 45.0,
        "spread_atr_ratio_pct": 2.7,
        "best_session": "US (15:30 - 22:00 CET)",
        "correlated_with": ["US500", "SOXL"],
        "inverse_correlated_with": ["TNX"],
        "desc": "Nejvyšší intraday dynamika a čisté swingové trendy."
    },
    "DE40": {
        "symbol_xtb": "DE40",
        "symbol_ibkr": "FDAX", # nebo Micro FDXS
        "symbol_yahoo": "^GDAXI",
        "name": "DAX 40 Index",
        "category": "INDEX",
        "currency": "EUR",
        "leverage": 20,
        "typical_spread": 1.1,
        "tick_size": 1.0,
        "avg_m5_atr": 25.0,
        "spread_atr_ratio_pct": 4.4,
        "best_session": "EU (09:00 - 12:30 CET)",
        "correlated_with": ["US500", "EU50"],
        "inverse_correlated_with": ["EURUSD"],
        "desc": "Evropský lídr pro ranní a dopolední scalpingové seance."
    },

    # 2. FOREX MAJORS (Nulový / Raw spread, nulové komise)
    "EURUSD": {
        "symbol_xtb": "EURUSD",
        "symbol_ibkr": "EUR.USD",
        "symbol_yahoo": "EURUSD=X",
        "name": "Euro vs US Dollar",
        "category": "FOREX",
        "currency": "USD",
        "leverage": 30,  # 1:30 pro retail, 1:100+ pro pro
        "typical_spread": 0.00004,  # 0.4 pipu
        "tick_size": 0.00001,
        "avg_m5_atr": 0.00110,  # 11 pips
        "spread_atr_ratio_pct": 3.6,
        "best_session": "Overlap Londýn / New York (14:00 - 18:00 CET)",
        "correlated_with": ["GBPUSD"],
        "inverse_correlated_with": ["USDCHF", "DX-Y.NYB"],
        "desc": "Světový etalon likvidity. Minimální skluz a okamžitá exekuce."
    },
    "GBPUSD": {
        "symbol_xtb": "GBPUSD",
        "symbol_ibkr": "GBP.USD",
        "symbol_yahoo": "GBPUSD=X",
        "name": "British Pound vs US Dollar (Cable)",
        "category": "FOREX",
        "currency": "USD",
        "leverage": 30,
        "typical_spread": 0.00008,  # 0.8 pipu
        "tick_size": 0.00001,
        "avg_m5_atr": 0.00190,  # 19 pips
        "spread_atr_ratio_pct": 4.2,
        "best_session": "Londýn (09:00 - 17:30 CET)",
        "correlated_with": ["EURUSD"],
        "inverse_correlated_with": ["USDCHF"],
        "desc": "Výraznější intraday swingy než EUR/USD při zachování nízkých nákladů."
    },
    "USDJPY": {
        "symbol_xtb": "USDJPY",
        "symbol_ibkr": "USD.JPY",
        "symbol_yahoo": "USDJPY=X",
        "name": "US Dollar vs Japanese Yen",
        "category": "FOREX",
        "currency": "JPY",
        "leverage": 30,
        "typical_spread": 0.005,  # 0.5 pipu
        "tick_size": 0.001,
        "avg_m5_atr": 0.140,  # 14 pips
        "spread_atr_ratio_pct": 3.5,
        "best_session": "Tokyo + NY seance",
        "correlated_with": ["^TNX"],
        "inverse_correlated_with": ["GOLD"],
        "desc": "Extrémně citlivý na pohyb amerických dluhopisových výnosů (TNX)."
    },

    # 3. KOMODITY
    "GOLD": {
        "symbol_xtb": "GOLD",
        "symbol_ibkr": "XAUUSD",
        "symbol_yahoo": "GC=F",
        "name": "Zlato (Gold vs USD)",
        "category": "COMMODITY",
        "currency": "USD",
        "leverage": 20,
        "typical_spread": 0.25,  # USD
        "tick_size": 0.01,
        "avg_m5_atr": 4.80,
        "spread_atr_ratio_pct": 5.2,
        "best_session": "US & Londýn (13:30 - 20:00 CET)",
        "correlated_with": ["SILVER"],
        "inverse_correlated_with": ["USDJPY", "DX-Y.NYB"],
        "desc": "Silné reakce na technické hladiny, floating průměry a pivoty."
    },

    # 4. PÁKOVÁ ETF (0% komise u vybraných brokerů)
    "TQQQ": {
        "symbol_xtb": "TQQQ.US",
        "symbol_ibkr": "TQQQ",
        "symbol_yahoo": "TQQQ",
        "name": "ProShares UltraPro QQQ (3x Long)",
        "category": "LEVERAGED_ETF",
        "currency": "USD",
        "leverage": 3,
        "typical_spread": 0.01,
        "tick_size": 0.01,
        "avg_m5_atr": 0.75,
        "spread_atr_ratio_pct": 1.3,
        "best_session": "US (15:30 - 21:30 CET)",
        "correlated_with": ["USTEC", "SOXL"],
        "inverse_correlated_with": ["SQQQ"],
        "desc": "3x denní expozice na Nasdaq bez nutnosti CFD poplatků za financování přes den."
    },
    "SQQQ": {
        "symbol_xtb": "SQQQ.US",
        "symbol_ibkr": "SQQQ",
        "symbol_yahoo": "SQQQ",
        "name": "ProShares UltraPro Short QQQ (3x Short)",
        "category": "LEVERAGED_ETF",
        "currency": "USD",
        "leverage": 3,
        "typical_spread": 0.01,
        "tick_size": 0.01,
        "avg_m5_atr": 0.45,
        "spread_atr_ratio_pct": 2.2,
        "best_session": "US (15:30 - 21:30 CET)",
        "correlated_with": ["VIX"],
        "inverse_correlated_with": ["TQQQ", "USTEC"],
        "desc": "Ideální nástroj pro čistý intraday SHORT na technologiích."
    }
}


def get_instruments_by_category(category: str) -> List[Dict[str, Any]]:
    """Vrátí seznam instrumentů podle kategorie."""
    return [v for k, v in SCALPING_INSTRUMENTS.items() if v["category"] == category.upper()]


def get_correlation_pairs() -> List[Dict[str, Any]]:
    """Vrátí definované korelační páry pro detekci Lead-Lag divergencí."""
    return [
        {
            "pair": ("USTEC", "US500"),
            "type": "POSITIVE_BETA",
            "lead": "USTEC",
            "lag": "US500",
            "desc": "Při průrazu technologického sektoru sledujeme zpoždění širšího indexu S&P 500."
        },
        {
            "pair": ("GOLD", "USDJPY"),
            "type": "NEGATIVE_MACRO",
            "lead": "USDJPY",
            "lag": "GOLD",
            "desc": "Inverzní vztah mezi dolarem/jenem a zlatem při prudkých měnových pohybech."
        },
        {
            "pair": ("EURUSD", "GBPUSD"),
            "type": "RELATIVE_STRENGTH",
            "lead": "GBPUSD",
            "lag": "EURUSD",
            "desc": "Měření relativní síly evropských měn vůči americkému dolaru."
        }
    ]
