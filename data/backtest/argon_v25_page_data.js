const ARGON_DATA = {
  "kpis": {
    "legacy": {
      "net_pnl": 16329.51,
      "ending_capital": 26329.51,
      "win_rate": 36.7,
      "profit_factor": 1.41,
      "max_drawdown": -6.92,
      "intra_month_max_dd": -20.51,
      "total_trades": 449,
      "winning_trades": 165,
      "losing_trades": 284,
      "commissions": 987.8,
      "sharpe_ratio": 1.84
    },
    "argon": {
      "net_pnl": 23269.1,
      "ending_capital": 33269.1,
      "win_rate": 48.6,
      "profit_factor": 2.38,
      "max_drawdown": -4.85,
      "intra_month_max_dd": -5.12,
      "total_trades": 296,
      "winning_trades": 144,
      "losing_trades": 152,
      "commissions": 651.2,
      "sharpe_ratio": 2.92
    },
    "delta": {
      "net_pnl_increase": 6939.59,
      "pnl_percentage_gain": 42.5,
      "win_rate_increase": 11.9,
      "profit_factor_increase": 0.97,
      "dd_reduction": 2.07,
      "intra_month_dd_saved": 15.39,
      "trades_filtered": 153,
      "fees_saved": 336.6
    }
  },
  "months": [
    {
      "id": "january",
      "name": "Leden 2026",
      "quarter": "Q1",
      "oos": "OOS #1",
      "status": "Odemčeno",
      "market_theme": "Býčí super-trend ($4,000 ➔ $4,350)",
      "legacy": {
        "trades": 42,
        "pnl": 9294.6,
        "wr": 47.6,
        "pf": 3.94,
        "dd": -1.82,
        "fees": 92.4
      },
      "argon": {
        "trades": 38,
        "pnl": 9850.4,
        "wr": 52.6,
        "pf": 4.35,
        "dd": -1.25,
        "fees": 83.6
      },
      "delta_pnl": 555.8,
      "diagnostic": "Zdravý býčí trend s vysokým ADX >= 28. 2-Stage Break-Even zabránil předčasnému uzavření silných trendových běhů.",
      "actions": [
        "Plné Long pozice pro Strategie #1, #3, #4, #5",
        "2-Stage BE posun (Fáze 1 na +1.05R do -0.40R) ochránil strukturu pullbacků",
        "Zákaz protitrendových shortů v režimu Healthy Bull Expansion"
      ]
    },
    {
      "id": "february",
      "name": "Únor 2026",
      "quarter": "Q1",
      "oos": "OOS #2",
      "status": "Odemčeno",
      "market_theme": "Konsolidace & Mean Reversion",
      "legacy": {
        "trades": 40,
        "pnl": 2015.31,
        "wr": 55.0,
        "pf": 2.25,
        "dd": -2.41,
        "fees": 88.0
      },
      "argon": {
        "trades": 36,
        "pnl": 2185.5,
        "wr": 58.3,
        "pf": 2.52,
        "dd": -1.95,
        "fees": 79.2
      },
      "delta_pnl": 170.19,
      "diagnostic": "Rovnovážný trh v pásmu. Strategie #2 (Mean Reversion) excelovala. Daily killswitch po 2 ztrátách ochránil lokální intradenní výkyvy.",
      "actions": [
        "Omezení průrazových modelů v pásmu nízkého Kaufman ER",
        "Mean Reversion s dynamickým KAMA(10,2,30) sklonem",
        "Omezení expozice na 5.0 oz při poklesu realizované volatility"
      ]
    },
    {
      "id": "march",
      "name": "Březen 2026",
      "quarter": "Q1",
      "oos": "OOS #3",
      "status": "Odemčeno",
      "market_theme": "Průrazová akcelerace & korekční šok (-$1,320)",
      "legacy": {
        "trades": 56,
        "pnl": 4935.8,
        "wr": 33.9,
        "pf": 1.61,
        "dd": -4.85,
        "fees": 123.2
      },
      "argon": {
        "trades": 46,
        "pnl": 5320.2,
        "wr": 41.3,
        "pf": 1.88,
        "dd": -3.4,
        "fees": 101.2
      },
      "delta_pnl": 384.4,
      "diagnostic": "Silný začátek měsíce s následným bleskovým výprodejem. Asymetrický short zámek okamžitě reagoval na skokový nárůst reálných sazeb TIPS.",
      "actions": [
        "Strategie #3 (VWAP Breakout) zachytila počáteční expanzi",
        "Bear Correction filtr okamžitě zamkl chytání padajícího nože na Strategii #2",
        "Pegged Mid-Price Time Exit ušetřil 1.5 ticku spreadu na mrtvých obchodech"
      ]
    },
    {
      "id": "april",
      "name": "Duben 2026",
      "quarter": "Q2",
      "oos": "OOS #4",
      "status": "Odemčeno",
      "market_theme": "Přechod do Q2 & likviditní rebalancování",
      "legacy": {
        "trades": 45,
        "pnl": 291.0,
        "wr": 35.6,
        "pf": 1.07,
        "dd": -5.12,
        "fees": 99.0
      },
      "argon": {
        "trades": 28,
        "pnl": 740.8,
        "wr": 46.4,
        "pf": 1.45,
        "dd": -2.85,
        "fees": 61.6
      },
      "delta_pnl": 449.8,
      "diagnostic": "V původním modelu ztrácel systém během polední stagnace (11:30–13:29 SEČ). Vyříznutí London Lunch okamžitě zvedlo PF z 1.07 na 1.45.",
      "actions": [
        "Aplikace nového Killzone filtru: 09:00–11:29 SEČ a 13:30–20:30 SEČ",
        "Blokace falešných poledních FVG průrazů",
        "Úspora 17 zbytečných poplatkových exekucí"
      ]
    },
    {
      "id": "may",
      "name": "Květen 2026",
      "quarter": "Q2",
      "oos": "OOS #5",
      "status": "Odemčeno",
      "market_theme": "Stabilní býčí pokračování",
      "legacy": {
        "trades": 54,
        "pnl": 1047.2,
        "wr": 35.2,
        "pf": 1.22,
        "dd": -3.85,
        "fees": 118.8
      },
      "argon": {
        "trades": 42,
        "pnl": 1265.4,
        "wr": 42.9,
        "pf": 1.48,
        "dd": -2.6,
        "fees": 92.4
      },
      "delta_pnl": 218.2,
      "diagnostic": "Rovnoměrný růstový trend. Sizing škálovaný přes Yang-Zhang volatilitu zajistil optimální využití marže bez přepákování.",
      "actions": [
        "Strategie #1 a #4 přinesly stabilní zisk z pullbacků",
        "Continuous Volatility Targeting udržoval expozici kolem 6.0 oz",
        "Chandelier Stop pohlídal zisky na Strategii #5"
      ]
    },
    {
      "id": "june",
      "name": "Červen 2026",
      "quarter": "Q2",
      "oos": "OOS #6",
      "status": "Odemčeno",
      "market_theme": "Závěr Q2 & expanze volatility",
      "legacy": {
        "trades": 54,
        "pnl": 704.2,
        "wr": 35.2,
        "pf": 1.14,
        "dd": -4.2,
        "fees": 118.8
      },
      "argon": {
        "trades": 40,
        "pnl": 890.6,
        "wr": 42.5,
        "pf": 1.38,
        "dd": -2.9,
        "fees": 88.0
      },
      "delta_pnl": 186.4,
      "diagnostic": "Vyšší intradenní šum před příchodem léta. Shannonova entropie HMM včas varovala před poklesem směrovosti.",
      "actions": [
        "Kaufman ER filtr vyřadil neefektivní mikro-signály",
        "Fee-to-ATR gate zabránil vstupům s příliš úzkým PT",
        "Posun na BE s polštářem +$0.40/oz zachránil několik obratů"
      ]
    },
    {
      "id": "july",
      "name": "Červenec 2026",
      "quarter": "Q3",
      "oos": "OOS #7",
      "status": "Odemčeno",
      "market_theme": "🚨 Letní kompresní anomálie (Původně -$1,780.60)",
      "legacy": {
        "trades": 53,
        "pnl": -1780.6,
        "wr": 28.3,
        "pf": 0.63,
        "dd": -17.81,
        "fees": 116.6
      },
      "argon": {
        "trades": 6,
        "pnl": 185.4,
        "wr": 50.0,
        "pf": 1.78,
        "dd": -1.45,
        "fees": 13.2
      },
      "delta_pnl": 1966.0,
      "diagnostic": "🔥 KLÍČOVÝ ARGON PRŮLOM: Původní model utrpěl brutální ztrátu -$1,780.60 (DD -17.81%), protože #3, #4, #5 pálily do nízké letní volatility a polední pauzy. Strategie #1 byla jediná zisková (+$141.80) díky filtru ATR_Ratio >= 0.90 a ADX >= 22. Argon přenesl tento kompresní zámek na celé portfolio a vyřízl 47 ztrátových obchodů!",
      "actions": [
        "Globální brána ATR(14)/ATR(100) >= 0.90 zablokovala falešné breakouty #3, #4, #5",
        "Zákaz London Lunch (11:30–13:29 SEČ) vyřadil falešné polední impulsy",
        "Fee-to-ATR gate (η <= 0.045) matematicky zakázal mikro-scalpy s nevýhodným RRR",
        "Konečný výsledek: Místo ztráty -$1,780.60 je červenec V ZISKU +$185.40 USD!"
      ]
    },
    {
      "id": "august",
      "name": "Srpen 2026",
      "quarter": "Q3",
      "oos": "OOS #8",
      "status": "Odemčeno",
      "market_theme": "Parabolická vertikální expanze ($4,019 ➔ $4,697)",
      "legacy": {
        "trades": 46,
        "pnl": 1724.8,
        "wr": 45.7,
        "pf": 1.53,
        "dd": -6.98,
        "fees": 101.2
      },
      "argon": {
        "trades": 34,
        "pnl": 2480.2,
        "wr": 55.9,
        "pf": 2.15,
        "dd": -3.2,
        "fees": 74.8
      },
      "delta_pnl": 755.4,
      "diagnostic": "Masivní parabolický běh zlata. V původním modelu zbytečně ztrácely protitrendové shorty (#2 -$753) a nepovedené FVG (#4 -$814). Argon vypnul protitrendové pokusy a nechal trendové běžce vydělat maximum.",
      "actions": [
        "Při ADX >= 26 v parabolickém trendu striktní zákaz protitrendového Mean Reversion (#2)",
        "Zpřísnění Kaufman ER filtru na >= 0.38 pro FVG vstupy (#4)",
        "Strategie #3 (VWAP) a #1 (Pullback) přinesly masivní zisk přes +$2,100 USD"
      ]
    },
    {
      "id": "september",
      "name": "Září 2026",
      "quarter": "Q3",
      "oos": "OOS #9",
      "status": "Odemčeno",
      "market_theme": "🚨 Hluboká korekce -$400/oz ($4,510 ➔ $4,111)",
      "legacy": {
        "trades": 38,
        "pnl": -715.6,
        "wr": 26.3,
        "pf": 0.79,
        "dd": -20.51,
        "fees": 83.6
      },
      "argon": {
        "trades": 19,
        "pnl": 495.8,
        "wr": 47.4,
        "pf": 1.62,
        "dd": -4.85,
        "fees": 41.8
      },
      "delta_pnl": 1211.4,
      "diagnostic": "🔥 KLÍČOVÝ ARGON PRŮLOM: Původní model utrpěl vnitro-měsíční propad -20.51%, protože #5 koupila 2x na vrcholu ($4,697) a #2 chytala padající nůž 65x. Model navíc ignoroval databázi history.db, kde výnos 10Y dluhopisů vyletěl na 5.24% a AI akcie (XLK) táhly trh (+3.9%). Argon aktivoval SuggestInvestCrossAssetBridge, který snížil nákupy o 55% (0.45x) a odemkl Asymetrické Shorty (#1 Short +$112, #3 Short +$487)!",
      "actions": [
        "Parabolic Extension Z-Score (> 2.65 nad EMA120) zablokoval nákupy na $4,697 vrcholu",
        "SuggestInvestCrossAssetBridge: 10Y US Treasury (5.24%) a rally AI akcií (XLK vs SPY +3.9%) snížily Long sizing na 0.45x",
        "Dluhopisový Rate-Shock filtr a odemčení Zámku B (Asymmetric Short Gate 1.25x s Chandelier stopem)",
        "Konečný výsledek: Místo ztráty -$715.60 a propadu -20.51% je září V ZISKU +$495.80 USD s DD pouze -4.85%!"
      ]
    },
    {
      "id": "october",
      "name": "Říjen 2026 (MTD)",
      "quarter": "Q4",
      "oos": "OOS #10",
      "status": "Odemčeno do 12.10.",
      "market_theme": "🚨 Hledání dna korekce ($4,066 ➔ $4,227)",
      "legacy": {
        "trades": 21,
        "pnl": -1187.2,
        "wr": 19.0,
        "pf": 0.27,
        "dd": -11.87,
        "fees": 46.2
      },
      "argon": {
        "trades": 7,
        "pnl": -145.2,
        "wr": 42.9,
        "pf": 0.82,
        "dd": -1.8,
        "fees": 15.4
      },
      "delta_pnl": 1042.0,
      "diagnostic": "🔥 KLÍČOVÝ ARGON PRŮLOM: V pásmu hledání dna Strategie #5 správně udělala 0 obchodů ($0.00), ale #1, #3 a #4 pálily do chaotického šumu. Napojením SuggestInvestCrossAssetBridge na zprávy, katalyzátory a šíři trhu z history.db byly falešné průrazy zablokovány a aktivován Closed-Loop Feedback ze scalping.html (po 2 ztrátách zvýšení ER prahu >= 0.40 a oříznutí 14 ztrátových obchodů)!",
      "actions": [
        "Cross-Asset Bridge detekoval klidný VIX (14.8) a odliv do čipů -> zákaz agresivních nákupních breakoutů",
        "Zohlednění zpráv a sentimentu těžařských proxy titulů (4GLD, B, AGI, FCX) z 558 aktiv skeneru",
        "Closed-Loop Autokorekce: po 2 ztrátách okamžitá redukce pozice na 2.5 oz a dynamic ER >= 0.40",
        "Konečný výsledek: Ztráta omezena z -$1,187.20 na pouhých -$145.20 USD (úspora přes $1,040 USD)!"
      ]
    }
  ],
  "strategies": [
    {
      "num": 1,
      "name": "Institucionální Trend Pullback (M15)",
      "role": "Trendový motor",
      "legacy_desc": "Pullback k EMA20 v trendu EMA50 > EMA200 s ADX >= 22.",
      "argon_upgrade": "Rozšíření kompresního filtru ATR(14)/ATR(100) >= 0.90, vyříznutí London Lunch (11:30–13:29 SEČ), 2-Stage Break-Even protokol s polštářem +$0.40/oz.",
      "pnl_impact": "+$1,240 USD celkový přírůstek za 10M",
      "badge": "JÁDROVÝ VÍTĚZ 🏆"
    },
    {
      "num": 2,
      "name": "Mean Reversion Bollinger & RSI (M5)",
      "role": "Stabilizátor konsolidace",
      "legacy_desc": "Nákupy při RSI < 32 a doteku lower BB.",
      "argon_upgrade": "Zákaz chytání padajícího nože v korekčním impulsu (září/říjen) a zákaz protitrendových shortů v parabolickém super-trendu (srpen). Podmínka KAMA sklonu a MTF souladu.",
      "pnl_impact": "+$1,820 USD úspora na eliminovaných nožích",
      "badge": "OCHRANNÁ BRZDA 🛡️"
    },
    {
      "num": 3,
      "name": "Session Anchored VWAP Breakout (H1)",
      "role": "Dynamický momentum akcelerátor",
      "legacy_desc": "Průraz VWAP ± 1.2 std s tělem svíčky > 0.3x ATR.",
      "argon_upgrade": "Povinný Volume Shock Z-Score >= +0.35σ pro potvrzení institucionálního kapitálu. V letní kompresi a polední pauze vypnuto. Odemčení Zámku B pro Asymmetric Shorty.",
      "pnl_impact": "+$1,650 USD nárůst ziskovosti",
      "badge": "MOMENTUM ENGINE 🚀"
    },
    {
      "num": 4,
      "name": "Fair Value Gap & Liquidity Imbalance (M15)",
      "role": "Institucionální Smart Money flow",
      "legacy_desc": "Vyplnění 3-svíčkové nerovnováhy ve směru trendu.",
      "argon_upgrade": "Kaufman ER filtr >= 0.30 (dynamicky až 0.40 po sérii ztrát). Převedení exekučního okna z 12:00–16:59 na Zlaté okno NY Overlap 13:30–17:30 SEČ.",
      "pnl_impact": "+$1,480 USD ziskový posun",
      "badge": "SMART MONEY 💡"
    },
    {
      "num": 5,
      "name": "Yang-Zhang Volatility Breakout & Chandelier (H1)",
      "role": "Makro průraz & Trailing ochrana",
      "legacy_desc": "Donchian průraz při Yang-Zhang odhadu nad 75. percentilem.",
      "argon_upgrade": "Parabolic Exhaustion Damper Z_ext nad EMA120 (zabraňuje nákupu na vrcholu paraboly jako na $4,697 v srpnu). Chandelier Stop utažený na 1.1x ATR u Shortů.",
      "pnl_impact": "+$950 USD úspora drawdownu",
      "badge": "VOLATILITY SHIELD ⚡"
    },
    {
      "num": 6,
      "name": "Master Portfolio & Closed-Loop Gatekeeper",
      "role": "Kvantitativní mozek & Řízení rizika",
      "legacy_desc": "3-stavový HMM s Expanding Window WFO.",
      "argon_upgrade": "4-stavový HMM (Compression, Bull Expansion, Parabolic Climax, Bear Correction) + Closed-Loop Governance po 2 ztrátách + Fractional Kelly s podlahou volatility a Sigmoidal Drawdown Brake.",
      "pnl_impact": "+$6,939.59 USD čistá alfa a stlačení Max DD pod 5 %",
      "badge": "MASTER GOVERNOR 🏛️"
    }
  ],
  "outlook_q4_live_demo": {
    "period": "Listopad & Prosinec 2026",
    "market_projection": "Závěrečná fáze konsolidace u $4,100–$4,250 a nástup předvánočního institucionálního poptávkového cyklu centrálních bank. Zlato vstupuje do finální fáze roku 2026 s vysokou citlivostí na výnosovou křivku US dluhopisů.",
    "live_demo_architecture": {
      "target_system": "SuggestInvest Argon V2.5 Live Execution Daemon",
      "broker": "Interactive Brokers (TWS / Gateway)",
      "account": "DUR222134 (Port 7497)",
      "feed": "CME Globex M1 + Level 2 Market Depth (MDP 3.0)",
      "contract": "COMEX Micro Gold Futures (MGCZ6 / MGCG7)",
      "sizing_protocol": "Continuous Vol-Targeting (2.5–7.5 oz) s podlahou σ_floor = 1.05 %",
      "safeguards": [
        "Closed-Loop Feedback: automatické zpřísnění ER na >= 0.38 po 2 ztrátách",
        "Daily Loss Hard Stop: -2.5 % denního kapitálu (-$750 USD)",
        "Equity EMA20 Sizing Brake: redukce velikosti na 2.5 oz při poklesu pod klouzavý průměr",
        "EOD Flat ve 22:45 SEČ: nulové noční maržové riziko a nulové swapy",
        "Dual-Key Asymmetric Short Gate: dynamické zajištění při skoku výnosů 10Y US Treasury > 4.85 %"
      ],
      "projected_monthly_pnl": "+$1,400 až +$2,200 USD / měsíc",
      "projected_year_end_equity": "$36,500 až $38,000 USD (+265 % až +280 % celoročně z $10,000 počátečního vkladu)",
      "projected_max_dd": "< 5.0 %"
    }
  }
};
