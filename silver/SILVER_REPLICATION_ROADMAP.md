# Silver Replication Roadmap v3.0 (Critical Path Edition)
*Autor: Argon / Ondřej V.*
*Datum: Říjen 2026*

---

## I. 7 KLÍČOVÝCH TIPŮ NA ZLEPŠENÍ (Kritické opravy před startem)

### 1. ⚠️ Kritický střet velikosti kontraktu SIL (1 000 oz) s účtem $10,000
- **Problém:** V původním návrhu se uvažovalo `full_contract_oz = 1.0` a `SILVER_MAX_CONTRACTS = 3`. U zlata (MGC) je 1 kontrakt = 10 oz, ale u stříbra (SIL) je 1 kontrakt = 1 000 oz! Při ceně stříbra ~$32.50/oz má jeden jediný kontrakt SIL nominální hodnotu $32,500 (páka 3.25× na $10k účet; 3 kontrakty by znamenaly nominál ~$97,500, tedy páku skoro 10×!).
- **Matematika rizika:** Při 3% denním ATR stříbra (~$1.00/oz) udělá 1 kontrakt SIL pohyb $1,000 za den. Pokud máš v `silver_config.py` maximální risk na obchod 4 % ($400), pak tvůj maximální možný Stop-Loss na 1 kontrakt SIL je pouhých $0.40/oz (80 ticků).
- **Řešení v roadmapě:** Zavedení **Volatility Gate (Hard Sizing Filter)**: pokud je požadovaný Stop-Loss strategie (např. 2.0 × ATR) širší než $0.40/oz, bot nesmí zaokrouhlit pozici na 1 kontrakt, ale musí obchod vynechat (Skip Trade) kvůli nedělitelnosti kontraktu. Zároveň pro $10k účet nastavit `SILVER_MAX_CONTRACTS = 1` (zvýšení na 2 povolit až od ekvity > $18,000).

### 2. 📉 Chyba ve výpočtu GSR Proxy (GLD / SLV) a statickém průměru 68.0
- **Problém:** `latest["GLD"] / latest["SLV"]` nedává GSR ~85, ale ~8.5 (GLD představuje ~1/10 oz zlata poníženou o kumulované poplatky fondu od roku 2004). Navíc ETF se obchodují jen během US akciové seance (15:30–22:00 SEČ), takže během Londýna a Šanghaje by byl GSR signál zamrzlý! Statické `gsr_mean=68.0` způsobí, že v roce 2026 (kde se GSR pohybuje kolem 80–90) bude z_score permanentně > +1.2 a strategie bude mít celé měsíce slepý LONG bias.
- **Řešení v roadmapě:** Počítat GSR přímo z futures cen v databázi a IBKR streamu (`MGC_close` / `SIL_close` nebo `GC=F` / `SI=F`), které běží 23 hodin denně. Místo statického průměru 68 použít **Rolling Z-Score** (okno 60–120 dní) nebo cointegration spread ($\log(\text{Gold}) - \beta \cdot \log(\text{Silver})$) přes Kalmanův filtr.

### 3. 🌏 Šanghajská seance (SHFE) nemůže používat americká ETF (MCHI, FXI)
- **Problém:** Snaha monitorovat SHFE seanci (02:00–08:00 SEČ) pomocí ETF MCHI, FXI, GXC. Jenže tato ETF se obchodují na burze v New Yorku – mezi 02:00 a 08:00 našeho času je v USA noc a tyto tickery se vůbec nehýbou.
- **Řešení v roadmapě:** Jako live proxy v asijských hodinách použít instrumenty, které se v noci reálně obchodují: Futures na měď (HG / Micro Copper MHG), kurz offshore jüanu (USD/CNH) a Hang Seng / China A50 futures. Měď (HG) je navíc nejlepší real-time průmyslový leading indikátor pro stříbro.

### 4. ⏳ Zásadní změna pořadí: Paper Trading a Dashboard musí běžet PARALELNĚ
- **Problém v původním pořadí:** Ve Fázi 5 se stavělo 15 vizuálních widgetů vč. mobilního zobrazení a teprve ve Fázi 6 se spouštěl 30denní Paper Trading. Tím by se ztratilo několik týdnů kódováním HTML/JS, zatímco bot ještě neposlal jediný příkaz na IBKR.
- **Řešení v roadmapě:** Jakmile model projde backtestem a unit testy, postavit exekuční jádro a okamžitě spustit 30denní IBKR Paper Trading (logující do `.jsonl`). Během těchto 30 dní, kdy se pasivně čeká na nasbírání tržních fillů a roll-overu, se paralelně staví Dashboard UI přímo nad reálnými daty z paper tradingu! Ušetří se tím celý měsíc.

### 5. 🧪 Přesun Unit Testů (Krok 50) PŘED Backtesty a OOS Tranše (Kroky 36–44)
- **Problém:** Pokud se spustí Walk-Forward OOS testy na uzamčených datech 2026 a až poté se napíší unit testy, které odhalí chybu ve výpočtu GSR nebo 2-Stage BE, znehodnotí se OOS data (už byla viděna, hrozí data snooping).
- **Řešení v roadmapě:** pytest sada a automatický test na Look-Ahead Bias uzavírají vývoj modelu před prvním spuštěním backtesteru.

### 6. 📅 Chybějící data 2020–2021 v DB vs. Stress Testy a COT Look-Ahead Bias
- **Chybějící historie:** Současná DB `silver_m1_history.db` začíná 13. 10. 2021, ale ve stress testech chceme testovat COVID crash (březen 2020) a Reddit Silver Squeeze (leden/únor 2021). Pro tato dvě období je nutné dotáhnout separátní historický dataset.
- **Point-in-Time (PIT) u COT a Makro dat:** CFTC COT report nese v tabulce datum úterý, ale zveřejňuje se až v pátek v 15:30 ET (21:30 SEČ). V backtestu i DB musí být každá hodnota COT posunuta na pátek 21:30 SEČ, jinak model ve středu a ve čtvrtek obchoduje podle budoucích dat!

### 7. 🔌 IBKR Gateway Porty vs. clientId (Krok 98)
- **Problém:** V původním návrhu stál port 4001 pro Gold a port 4002 pro Silver. V IBKR Gateway však port 4001 znamená Live API a port 4002 znamená Paper API!
- **Řešení:** Oba boti (Gold i Silver) se připojují na stejný port (4002 v paperu, 4001 v live), ale musí mít striktně oddělené `clientId` (Argon Gold = `clientId=10`, SilverEdge = `clientId=20`) a filtrovat pozice/příkazy přes `contract.symbol == "SIL"`.

---

## 🔄 II. PŘESKLÁDANÝ 100-KROKOVÝ ROADMAP v3.0 (Critical Path Edition)

### ✅ FÁZE 0: Hotový Baseline a Konfigurace (Kroky 1–12) — 100% DOKONČENO
- **KROK 1 [pův. 1]** – Market microstructure analýza Silver vs Gold: Rozhodnuto obchodovat SIL Micro Silver. ✅
- **KROK 2 [pův. 8]** – Definice trading universe: SIL (NYMEX, 1000 oz, tick $0.005 = $5.00), SLV jako sentiment proxy. ✅
- **KROK 3 [pův. 2]** – Stažení historických M1 dat Silver (2021-10 → 2026-10): `silver_m1_history.db` (1,777,739 svíček). ✅
- **KROK 4 [pův. Úvod]** – Projektová struktura `silver/` a centrální `silver_config.py`: Modulární adresář vytvořen. ✅
- **KROK 5 [pův. 37-manifest]** – Uzamčení 10 měsíčních OOS tranší 2026: `silver_2026_walkforward_manifest.json` a `silver_walkforward_manager.py`. ✅
- **KROK 6 [pův. 21]** – Killzone kalibrace v `silver_config.py`: NY (14:30–17:00), Londýn (09:00–11:30), Shanghai (02:00–08:00 se sizingem 50 %). ✅
- **KROK 7 [pův. 22]** – Kelly sizing konstanty v `silver_config.py`: Max risk 4 %, divisor f*/3, Sovereign Floor $9,000. ✅
- **KROK 8 [pův. 28]** – Roll-over konfigurace v `silver_config.py`: Expirační měsíce [3, 5, 7, 9, 12], roll 10 dní předem. ✅
- **KROK 9 [pův. 30]** – OPEX kalibrace v `silver_config.py`: `SILVER_OPEX_SIZE_MULTIPLIER = 0.50` (3. středa v měsíci). ✅
- **KROK 10 [pův. 31]** – Sovereign Floor a Emergency Stop limity v `silver_config.py`: Max denní ztráta $400 (`SILVER_MAX_CONTRACTS = 1` pro $10k účet). ✅
- **KROK 11 [pův. 33]** – Margin safety buffer v `silver_config.py`: `MARGIN_SAFETY_BUFFER = 1.5 × initial margin`. ✅
- **KROK 12 [pův. 57]** – Prahy pro Silver Alerting System v `silver_config.py`: Squeeze (>8 %), GSR extrémy, China PMI šok, Roll alert, Margin warning. ✅

---

### 🔬 FÁZE 1: Čištění dat, Kontinuita a Kvantitativní Research (Kroky 13–22)
*Cíl: Než napíšeme jediný řádek strategie, musíme odstranit cenové skoky při expiracích v M1 databázi, doplnit krizová data 2020–2021 a spočítat statistické rozdělení ATR a GSR.*

- **KROK 13 [rozšíření pův. 2 a 39]** – Dotáhnutí krizových dat 2020-01 až 2021-10 pro Stress Testy (COVID pád -35 %, WSB Silver Squeeze).
- **KROK 14 [pův. 14 + 59]** – Migrace `data_continuity_service.py` a Back-Adjustment M1 historie (Panama / Ratio metoda).
- **KROK 15 [pův. 6]** – Volatilita profiling Silver vs Gold na očištěných M1 datech (SHFE vs London vs NY).
- **KROK 16 [pův. 20]** – Kalibrace ATR(14), ATR(21) a ATR(100) + Volatility Gate pro 1 000 oz SIL.
- **KROK 17 [pův. 3]** – Gold/Silver Ratio (GSR) historická a kointegrační analýza (Futures-based MGC/SIL).
- **KROK 18 [pův. 7]** – CFTC COT Silver historická analýza (Point-in-Time, ukotvení na pátek 15:30 ET).
- **KROK 19 [pův. 4]** – Průmyslová poptávka Silver a korelace s Mědí (HG Futures SI/HG).
- **KROK 20 [pův. 5]** – Identifikace a kvantifikace makro katalyzátorů specifických pro Silver (ISM, Caixin, EIA, RBI).
- **KROK 21 [pův. 9]** – Sezónní a Day-of-Week analýza Silver.
- **KROK 22 [pův. 10]** – Analýza Silver ETF flow (SLV) a COMEX Warehouse zásob (Registered vs Eligible).

---

### 🗄️ FÁZE 2: Asynchronní Datová Infrastruktura & DB Vrstva (Kroky 23–32)
*Cíl: Nejprve postavit atomické ukládání a asynchronní engine (Kroky 23–24), a teprve do této hotové šablony psát jednotlivé datové konektory (Kroky 25–31) + okamžitě je otestovat (Krok 32).*

- **KROK 23 [pův. 29]** – SQLite WAL Mode & Atomický I/O manažer (`safe_write_portfolio`).
- **KROK 24 [pův. 16]** – Asyncio core pipeline pro data fetching (`aiohttp` s timeouty a backoffem).
- **KROK 25 [pův. 60]** – Dynamický TTL Cache Manager (5 min pro FOMC/CPI dny, 15 min běžně).
- **KROK 26 [pův. 15]** – Vytvoření `silver_macro_calendar.db` (s Point-in-Time schématem).
- **KROK 27 [pův. 11]** – Implementace `silver/data/silver_high_alpha_feeds.py` (SI=F, GC=F, HG=F, CNH=X, SLV, VIX).
- **KROK 28 [pův. 13]** – Implementace `silver/data/silver_cot_fetcher.py` (CFTC COT report s pátečním PIT razítkem).
- **KROK 29 [pův. 12]** – Implementace `silver/data/silver_industrial_proxy.py` (EIA, USGS, HG=F, TAN).
- **KROK 30 [pův. 25]** – Implementace `silver/data/silver_shfe_monitor.py` (Shanghai Session Monitor 02:00–08:00 SEČ).
- **KROK 31 [pův. 19]** – Implementace `silver/data/silver_macro_bridge.py` (cross-asset makro skóre pro Silver).
- **KROK 32 [pův. 50-feeds]** – Unit testy pro datovou vrstvu (`silver/tests/test_silver_feeds.py`).

---

### 🧠 FÁZE 3: Model Core Engine, Strategie & Unit Testy (Kroky 33–46)
*Cíl: Kompletně vyvinout matematické jádro, všech 7 strategií, sizing a 100% je pokrýt unit testy PŘED spuštěním prvního backtestu.*

- **KROK 33 [pův. 17]** – Implementace `silver/models/silver_regime_engine.py` (contract_oz = 1000.0, DD 6 %, Hurst 0.40).
- **KROK 34 [pův. 35]** – Implementace Volatility Regime Switcher (KAMA + Yang-Zhang Volatility).
- **KROK 35 [pův. 18]** – Implementace Silver BlowOff Exhaustion Detector (parabolická detekce vrcholů stříbra).
- **KROK 36 [pův. 24]** – Implementace Strategie #7: GSR Mean Reversion (`silver_gsr_strategy.py`).
- **KROK 37 [pův. 23]** – Implementace a kalibrace Strategií #1–#6 (`silver_strategies.py`).
- **KROK 38 [pův. 34]** – Kalibrace 2-Stage Break-Even a Fee-Plus pro Silver (Stage 1 na -0.30R při +0.80R, Stage 2 Fee-Plus na +$0.025/oz při +1.00R).
- **KROK 39 [pův. 26]** – Implementace `silver/models/silver_online_trainer.py` (inkrementální SGDClassifier s forgetting faktorem).
- **KROK 40 [pův. 32 + 58]** – Implementace `silver_correlation_monitor.py` & Cross-Commodity Monitoru (Gold ↔ Silver korelace).
- **KROK 41 [pův. 55]** – Implementace Silver Position Sizing Engine (Kelly f*/3, Volatility Gate, ATR, GSR, korelace).
- **KROK 42 [pův. 61]** – Implementace Silver Intraday Scalping Mode (NY seance 14:30–17:00 SEČ).
- **KROK 43 [pův. 50-regime]** – Unit testy pro Regime Engine a BlowOff (`test_silver_regime.py`).
- **KROK 44 [pův. 50-gsr]** – Unit testy pro GSR Strategii #7 (`test_silver_gsr.py`).
- **KROK 45 [pův. 50-strat]** – Unit testy pro Strategie #1–#6, Sizing a 2-Stage BE (`test_silver_strategies.py`).
- **KROK 46 [doplněk k pův. 50]** – Automatizovaný Look-Ahead Bias & Data Leakage Test (`conftest.py`).

---

### 🧪 FÁZE 4: Backtest, Stress Testy a OOS Walk-Forward Validace (Kroky 47–60)
*Cíl: Provést přísnou vědeckou validaci na již otestovaném kódu. OOS tranše 2026 odemykáme až úplně na konci této fáze postupně s uživatelem!*

- **KROK 47 [soubor z projektové struktury]** – Implementace `silver/backtest/silver_backtester.py`.
- **KROK 48 [pův. 65]** – Implementace Silver Performance Metrics Engine (Sharpe, Sortino, Calmar, Deflated Sharpe Ratio).
- **KROK 49 [pův. 36]** – In-Sample Backtest Silver (2021-10 → 2024-12).
- **KROK 50 [pův. 40]** – Parameter Sensitivity Analysis (`silver/scripts/silver_parameter_sweep.py`).
- **KROK 51 [pův. 37]** – Out-of-Time Validation Backtest (2025-01 → 2025-12).
- **KROK 52 [pův. 39]** – Stress Test: Silver-specifické krize (`silver/backtest/silver_stress_test.py`).
- **KROK 53 [pův. 38]** – Monte Carlo simulace – 10 000 iterací (`silver/backtest/silver_monte_carlo.py`).
- **KROK 54 [pův. 41]** – OOS Walk-Forward Backtest 2026-Q1 (leden–březen) *(ve spolupráci s uživatelem)*.
- **KROK 55 [pův. 42]** – OOS Walk-Forward Backtest 2026-Q2 (duben–červen) *(ve spolupráci s uživatelem)*.
- **KROK 56 [pův. 43]** – OOS Walk-Forward Backtest 2026-Q3 (červenec–září) *(ve spolupráci s uživatelem)*.
- **KROK 57 [pův. 44]** – OOS Walk-Forward Backtest 2026-Q4 (říjen) *(ve spolupráci s uživatelem)*.
- **KROK 58 [pův. 49]** – Inkrementální model retraining (Warm Start) & Catastrophic Forgetting Check.
- **KROK 59 [pův. 45]** – Backtest Comparison Report: SilverEdge vs. Argon Gold.
- **KROK 60 [pův. 46]** – Equity Curve Correlation & Portfolio Synergy Analysis.

---

### ⚡ FÁZE 5: Exekuční Infrastruktura & Okamžitý Start IBKR Paper Tradingu (Kroky 61–75)
*Cíl: Postavit bota a ihned spustit 30denní Paper Trading na IBKR. Nečekat na grafický dashboard!*

- **KROK 61 [pův. 53]** – Implementace Silver IBKR Contract Manager (SIL FUT, NYMEX, roll 10 dní před FND).
- **KROK 62 [pův. 54]** – Implementace Silver Execution Engine (Adaptive Limit / Pegged-to-Midpoint).
- **KROK 63 [pův. 27 + 51]** – Implementace `silver_futures_bot.py` a lehké orchestrace `silver_bot_main.py` (< 5 kB).
- **KROK 64 [pův. 52]** – Implementace `silver_watchdog.py` (3s heartbeat, IBKR clientId = 20).
- **KROK 65 [pův. 56]** – Implementace Silver Trade Journal (`silver/logs/silver_trades.jsonl`).
- **KROK 66 [pův. 62 + 63]** – Implementace Silver EOD Reconciliation (22:45 SEČ) & Weekend Risk Manageru.
- **KROK 67 [pův. 64]** – Implementace Silver Error Recovery & Resilience.
- **KROK 68 [pův. 81]** – 🚀 START 30denního IBKR Paper Tradingu (port 4002, clientId=20).
- **KROK 69 [pův. 84]** – Paper Trading: Izolovaný tracking GSR Strategie #7 (14 dní).
- **KROK 70 [pův. 85]** – Paper Trading: 7denní audit Shanghai Session (02:00–08:00 SEČ).
- **KROK 71 [pův. 83]** – Paper Trading: L2 DOM Analysis pro Silver.
- **KROK 72 [pův. 47 + 82]** – Paper Trading: Fill Quality & Slippage Model validace.
- **KROK 73 [pův. 86]** – Paper Trading: Stress Day Simulation (FOMC / CPI / NFP den).
- **KROK 74 [pův. 48 + 87]** – Paper Trading: Live Roll-Over Test a validace nákladů.
- **KROK 75 [pův. 88 + 89 + 90]** – Forward Test Audit Report, Rekalibrace & Go / No-Go Decision.

---

### 📊 FÁZE 6: Dashboard a Vizualizační Telemetrie (Kroky 76–90) — BĚŽÍ PARALELNĚ S FÁZÍ 5!
*Cíl: Během 30 dní, kdy bot ve Fázi 5 sbírá paper-trading obchody, stavíme webový dashboard.*

- **KROK 76 [pův. 80]** – Integrace `/silver` route a JSON API endpointů do `server.py` (`/api/silver/state`, `/api/silver/trades`, `/api/silver/telemetry`).
- **KROK 77 [pův. 66]** – Kostra `SilverInvestDemo.html` (stříbrná/antracitová/ledově modrá paleta).
- **KROK 78 [pův. 78]** – Widget: Silver Risk Dashboard (DD vs 6 %, Margin, Max Daily Loss $400, Volatility Gate stav).
- **KROK 79 [pův. 77]** – Widget: Silver Watchdog Status & Feed Latency (clientId=20).
- **KROK 80 [pův. 67]** – Widget: GSR Ratio Gauge & Rolling Z-Score Mini-Chart.
- **KROK 81 [pův. 72]** – Widget: Silver Equity Curve & Drawdown Overlay (Sovereign Floor $9,000).
- **KROK 82 [pův. 71]** – Widget: Silver Trade History Table.
- **KROK 83 [pův. 75]** – Widget: Silver Regime Timeline & BlowOff Detector ikony.
- **KROK 84 [pův. 73]** – Widget: Silver Strategy Attribution Dashboard (#1–#7).
- **KROK 85 [pův. 70]** – Widget: Shanghai (SHFE) Session Indikátor & Premium.
- **KROK 86 [pův. 68]** – Widget: COT Managed Money Positioning Chart.
- **KROK 87 [pův. 69]** – Widget: China Caixin PMI + ISM Manufacturing + Copper Telemetry.
- **KROK 88 [pův. 74]** – Widget: Silver vs. Gold Comparison & Combined Portfolio.
- **KROK 89 [pův. 76]** – Widget: Silver Sezónní Heatmap.
- **KROK 90 [pův. 79]** – Mobile-Responsive Layout & Push/Telegram Notifikace.

---

### 🚀 FÁZE 7: Produkční VPS Nasazení, Live Trading a Škálování (Kroky 91–100)
*Cíl: Nejprve připravit produkční server a monitoring, provést kontrolu a teprve poté pustit reálné peníze.*

- **KROK 91 [pův. 98]** – Cloud VPS Deployment (Gold + Silver v produkci, port 4001, clientId 10 & 20).
- **KROK 92 [pův. 99]** – Monitoring & Observability Stack (System Reporter).
- **KROK 93 [pův. 91]** – Finální Live Deployment Checklist & Kill-Switch Drill.
- **KROK 94 [pův. 92]** – Live Trading: Měsíc 1 (Konzervativní pilot, max 1 SIL).
- **KROK 95 [pův. 93]** – Live Trading: Měsíc 2 (Postupná stabilizace, SHFE zapojení).
- **KROK 96 [pův. 94]** – Live Trading: Měsíc 3+ (Full Autonomous Mode, Kelly f*/3).
- **KROK 97 [pův. 95]** – A/B Testing: Gold Model (Argon) vs. Silver Model (SilverEdge) (6 měsíců).
- **KROK 98 [pův. 96]** – Dynamická kapitálová alokace Gold / Silver (Risk-Parity 70/30).
- **KROK 99 [pův. 97]** – Kompletní dokumentace `SILVER_METHODOLOGY.md`.
- **KROK 100 [pův. 100]** – Kvartální Continuous Improvement & Alpha Decay Loop.
