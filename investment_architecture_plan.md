# Masterplan: Kvantitativní investiční a analytická architektura

> **Status:** Fáze 1 – Návrh řídící struktury (Architektonická osnova bez implementačního kódu)  
> **Role:** Senior Data Architekt & Kvantitativní Investiční Analytik  
> **Poslední aktualizace:** 25. 09. 2026  
> **Cíl dokumentu:** Standardizovat a sjednotit modulární architekturu pro pokročilý kvantitativní výzkum, asynchronní sběr dat, strojové učení, řízení rizik a exekuci.

---

## 1. Strategický rámec & Znalostní báze

### 1.1 Architektonická vize a poslání enginu
- **Účel systému:** Robustní, rozšiřitelný a asynchronní investiční engine kombinující statistickou arbitráž, pokročilé hluboké učení a alternativní NLP data.
- **Základní principy návrhu:**
  - *Separation of Concerns:* Striktní oddělení datové vrstvy, prediktivních modelů, řízení rizik a prezentační/exekuční vrstvy.
  - *No Lookahead Bias:* Přísná kauzální integrita časových řad a point-in-time zpracování dat.
  - *Asynchronní propustnost:* Nezávislý sběr a paralelní vyhodnocování stovek instrumentů v reálném čase.
  - *Deterministická reprodukovatelnost:* Každý signál a výpočet musí být plně auditovatelný a zpětně reprodukovatelný.

### 1.2 Propojení s existující metodikou SuggestInvest (Operational Baseline & Extension Anchor)
Architektonický plán nevzniká ve vzduchoprázdnu, ale přímo navazuje a systematicky rozšiřuje provozní metodiku produkčního systému **SuggestInvest**:

1. **Strukturované investiční univerzum (541 aktiv ve 3 koších):**
   - **Segmentace do 3 prioritních košů:**
     - 🥇 *TIER 1 (TOP Leaders - 48 aktiv):* US Mega-Caps (AAPL, NVDA, MSFT), kompletní Pražská burza (BCPP v CZK: CEZ, KB, Moneta, Colt), evropské blue-chips (ASML, SAP) a hlavní indexová ETF (S&P 500, All-World). Maximální likvidita a minimální spread.
     - 🥈 *TIER 2 (MID Growth - 472 aktiv):* Globální technologické, polovodičové, obranné, energetické a krypto-proxy tituly a sektorová UCITS ETF.
     - 🥉 *TIER 3 (LOW Discovery - 21 aktiv):* Dynamické spekulace, turnaround situace a asymetrický rizikový profil.
   - **XTB katalog a hygienický trash filter:**
     - Křížová validace mezinárodních kódů ISIN proti oficiálnímu katalogu XTB (14 692 instrumentů).
     - Automatická filtrace a okamžité vyřazení emisí v režimu `CLOSE ONLY` (> 689 nelikvidních/delistovaných emisí).

2. **Předstihové indikátory & 7 tržních katalyzátorů (Forward Triggers):**
   - Pravidlový engine vyhodnocující fundamentální diskont a časové milníky:
     - `CAT_HIGH_DISCOUNT`: Očekávaný růst k cílové ceně analytiků (Target Upside) > +25 % při $\ge 5$ doporučeních.
     - `CAT_OVER_TARGET`: Tržní cena překročila konsenzuální cíl (přepálená valuace, zákaz nákupních doporučení).
     - `CAT_EARNINGS_7D`: Kvartální výsledky do 7 dnů (zvýšené binární riziko, strop na konfidenci modelu 65 %).
     - `CAT_EARNINGS_21D`: Kvartální výsledky za 8–21 dnů (fáze předvýsledkového run-up akumulačního momenta).
     - `CAT_DIVIDEND_SOON`: Rozhodný den pro dividendu (Ex-Dividend) v horizontu $\le 14$ dnů.
     - `CAT_STRONG_MOMENTUM`: Denní skok ceny > +3.0 % v souladu se střednědobým 1M/3M momentem.
     - `CAT_ATH_TEST`: Aktuální tržní cena $\ge 97 \%$ z 52týdenního maxima (býčí síla a test rezistence).

3. **Kvantitativní hloubkové anomálie a stavové sledování:**
   - **Ex-Dividend Recovery Velocity:** Statistické vyhodnocení historických Ex-Dates aktiv (Dividend Drop-Off Ratio DDR, Pre-Ex Run-up 20d momentum, Recovery Velocity $T_{\text{rec}}$ do 15/30 obchodních dní $\rightarrow$ arbitráž *Dividend Capture* vs. *Run-up Harvest*).
   - **Daily Delta & Change Tracker:** Sledování derivace sentimentu vůči referenčnímu stavu v relační databázi SQLite (`history.db`):
     - Rating Upgrade / Downgrade (pětistupňová škála: Strong Buy, Buy, Hold, Sell, Strong Sell).
     - Confidence Velocity ($\Delta \text{Confidence} \ge \pm 10\%$).
     - Target Price Shift ($\Delta \text{Target Mean} \ge \pm 8\%$).
     - Aktivace nových katalyzátorů a nově zalistovaná aktiva.

4. **Hybridní AI & Quant Engine a produkční pipeline:**
   - Paralelní zpracování trhu: Yahoo Finance feed (`yfinance`) s 24hodinovou souborovou mezipamětí (`cache_fundamentals.json`).
   - Dvousložková inference: Google Gemini AI v 22 dávkách (~25 aktiv na dávku se strukturovaným JSON výstupem a systémovým nastavením *Head of Portfolio Risk*) s deterministickým kvantitativním fallback režimem při výpadku API.
   - Serverless CI/CD exekuce: GitHub Actions workflow (`market_cron.yml`) běžící každé ráno v 8:00 CET s celkovou dobou běhu pod 3 minuty + manuální on-demand spouštění přes GitHub Workflow Dispatch a automatický deployment na GitHub Pages.

5. **Architektonický princip rozšiřování (Extension Principle):**
   - Nově studované výzkumné architektury (SRC-1 až SRC-7) nenahrazují funkční pipeline, ale vystupují jako **analytické rozšiřující vrstvy (Pluginy)**.
   - Každá nová metoda je posuzována prizmatem: (a) jak zapadá do stávajícího datového toku, (b) jaké má výpočetní limity v serverless běhu a (c) zda generuje skutečný statistický alfa přínos vůči našim stávajícím pravidlovým katalyzátorům.

### 1.3 Evidence výzkumných zdrojů (Knowledge Base Registry)
| ID | Zkratka / Název | Odkaz | Plánovaná aplikační doména | Status zpracování |
| :--- | :--- | :--- | :--- | :--- |
| **SRC-1** | **HARN** | [arXiv:2609.26822v1](https://arxiv.org/html/2609.26822v1) | Hierarchické asociační sítě a rezonanční tržní vzorce | 🔬 Analyzováno & Zhodnoceno (Fáze 2) |
| **SRC-2** | **LiMT** | [arXiv:2609.25617v1](https://arxiv.org/html/2609.25617v1) | Multi-task učení se zohledněním mikrostrukturální likvidity | 🔬 Analyzováno & Zhodnoceno (Fáze 2) |
| **SRC-3** | **OrderFusion+** | [arXiv:2609.23598v1](https://arxiv.org/html/2609.23598v1) | Pravděpodobnostní trajektorie cen a mikrostrukturální fúze nákup/prodej | 🔬 Analyzováno & Zhodnoceno (Fáze 2) |
| **SRC-4** | **Universal Diffusion IVS** | [arXiv:2609.22893v1](https://arxiv.org/html/2609.22893v1) | Generativní difúzní modely povrchu implikované volatility a mezitržní dynamika rizika | 🔬 Analyzováno & Zhodnoceno (Fáze 2) |
| **SRC-5** | **AI a NLP Trading** | [DSpace UK 120426710](https://dspace.cuni.cz/bitstream/handle/20.500.11956/176640/120426710.pdf) | FinBERT vs TweetEval sentiment, DDQN Deep RL a limity transakčních nákladů | 🔬 Analyzováno & Zhodnoceno (Fáze 2) |
| **SRC-6** | **Pairs Trading & Kointegrace** | [DSpace UK 130215669](https://dspace.cuni.cz/bitstream/handle/20.500.11956/91435/130215669.pdf) | Statistická arbitráž, testování kointegrace a mean-reversion | 🔬 Analyzováno & Zhodnoceno (Fáze 2) |
| **SRC-7** | **Decoding the Quant Market** | [SSRN 4422374](https://smallake.kr/wp-content/uploads/2023/04/SSRN-id4422374.pdf) | Metodologie kvantitativního tradingu, feature engineering, purged CV a risk management | 🔬 Analyzováno & Zhodnoceno (Fáze 2) |

---

## 2. Datová vrstva & Ingestion Pipeline

### 2.1 Tržní časové řady (Market Data Engine)
- **Struktura slotu:**
  - Zdroj: `yfinance`, burzovní API (XTB / Interactive Brokers)
  - Granularita: Minutové, hodinové a denní OHLCV řady, bid/ask spready
  - Správa chybějících hodnot, dividendových splitů a očištění přežití (survivorship bias)
- **Implementovaná metodika čištění a normalizace (ze zdroje SRC-7):**
  - **Robustní průřezové škálování (Median / IQR Normalization):**
    Klasická normalizace $\frac{x - \mu}{\sigma}$ selhává při tlustých chvostech finančních výnosů a extrémních skocích malých satelitních akcií. Zavádí se robustní normalizace:
    $$Z_{i,t}^{\text{robust}} = \frac{X_{i,t} - \text{Median}_t(X)}{\text{IQR}_t(X)}, \quad \text{kde } \text{IQR}_t = Q_{0.75, t} - Q_{0.25, t}$$
  - **Point-in-Time Universum a ochrana před zkreslením přežití (Survivorship Bias):**
    Při historické evaluaci jsou sledována i delistovaná aktiva a nedochází k zpětné projekci současného seznamu 541 akcií do minulosti.

### 2.2 Alternativní data & Textový Scraping (Alternative & NLP Stream)
- **Struktura slotu:**
  - Asynchronní scrapování zpráv a regulatorních hlášení (`yfinance.news`, RSS feedy, sociální signály)
  - Čištění textového korpusu, tokenizace a deduplikace zpráv v čase
- **Implementovaná metodika NLP Streamu (ze zdroje SRC-5):**
  - **Ortogonální fúze zpráv a sociálních médií:**
    Jak prokázal Benk (IES UK), zprávy z médií a sociální sentiment (Twitter/X) vykazují minimální vzájemnou korelaci ($r \approx 0.11$). Zatímco zprávy zachycují fundamentální korporátní události s časovým zpožděním, sociální sítě zachycují bezprostřední retailové a momentum reakce.
  - **Sentiment Momentum / Delta ($\Delta S_t$):**
    Statický sentiment je perzistentní a často již oceněný v trhu. Prediktivní signál vzniká z mezidenní odchylky vůči klouzavému průměru:
    $$\Delta S_t = S_t - \text{EMA}_{14}(S)$$
  - **Dávkové zpracování (Batch Prompting v Google Gemini):**
    Namísto náročného lokálního běhu stovek modelů FinBERT/TweetEval na CPU jsou zprávy pro 541 titulů agregovány do 22 dávek a ohodnoceny v rámci strukturované JSON odpovědi Gemini 2.5 Flash během ranního GitHub Actions cronu.

### 2.3 Perzistence, caching a stavový management
- **Struktura slotu:**
  - Úrovně úložiště: Rychlá mezipaměť (In-memory / Redis), relační metadata a historie signálů (SQLite), analytický Lake (Parquet časové řady)
  - Správa verzování datových snapshotů pro auditní reprodukovatelnost
- *Slot pro budoucí logiku:*
  <!-- SPECIFIKACE SCHÉMATU ÚLOŽIŠTĚ -->

---

## 3. Asynchronní Event-Driven Engine

### 3.1 Událostmi řízený orchestrátor (Event-Driven Core)
- **Struktura slotu:**
  - Architektura Publisher-Subscriber pro tržní ticky, dokončení barů a příchod zpráv
  - Fronty událostí (`asyncio.Queue` / worker pools)
- *Slot pro budoucí logiku a specifikaci parametrů:*
  <!-- NÁVRH EVENT LOOPU A TYPŮ UDÁLOSTÍ: MarketEvent, SignalEvent, OrderEvent, FillEvent -->

### 3.2 Paralelní zpracování a izolace výpočetních úloh
- **Struktura slotu:**
  - Asynchronní I/O pro síťovou komunikaci (API volání, web scraping)
  - Vícevláknové/víceprocesové zpracování pro numericky náročné matematické modely
- *Slot pro budoucí logiku:*
  <!-- STRATEGIE ŠKÁLOVÁNÍ VÝPOČETNÍ ZÁTĚŽE -->

---

## 4. Kvantitativní a prediktivní modely (Quant Modeling Hub)

### 4.1 Hierarchické asociační sítě a rezonance (HARN modul)
- **Teoretická báze:** `SRC-1: HARN (Hierarchical Associative Resonance Network for Event-Driven Multi-Timeframe Forecasting, arXiv:2609.26822v1, 2026)`
- **Role v architektuře:** Kauzální asynchronní zpracování multi-timeframe dat bez lookahead leakage, modelování vnitřní stavové paměti a matematická kvantifikace tržního překvapení (*Surprise-driven writes*).

#### A. Matematický a architektonický aparát (Formalizace dle arXiv:2609.26822v1)
1. **Event-Driven Multi-Timeframe Alignment & Masked Transitions:**
   - Systém definuje uspořádanou hierarchii časových rozlišení od nejjemnějšího po nejhrubší: $T_1 < T_2 < \dots < T_L$ (např. M15, H1, H4, D1).
   - Nejjemnější perioda $T_1$ tvoří kotevní proud událostí $\tau$ (*Anchor Event Stream*).
   - Pro každou úroveň $k$ je v události $\tau$ vyhodnocen binární indikátor dokončení baru:
     $$u_\tau^k = \mathbb{I}[t_{\text{latest}}^k(\tau) = \tau] \in \{0, 1\}$$
   - Každá úroveň udržuje persistentní stavový vektor $r_\tau^k \in \mathbb{R}^{d_s}$ a asociační maticovou paměť $M_\tau^k \in \mathbb{R}^{d_s \times d_m}$ ($d_s = 72, d_m = 18$).
   - Přechodové pravidlo je striktně kauzální a maskované (nulový lookahead bias):
     $$r_{\tau+1}^k = u_\tau^k \tilde{r}_{\tau+1}^k + (1 - u_\tau^k) r_\tau^k$$
     $$M_{\tau+1}^k = u_\tau^k \tilde{M}_{\tau+1}^k + (1 - u_\tau^k) M_\tau^k$$
     Pokud vyšší rámec nedokončil bar ($u_\tau^k = 0$), stav i paměť jsou beze změny přeneseny do dalšího kroku.

2. **Kauzální Multi-Scale Enkodér:**
   - Vstupem pro úroveň $k$ je dokončené okno surových cen $X^k \in \mathbb{R}^{B \times T \times 5}$ (OHLCV) rozšířené o 6 odvozených kanálů krátkodobé cenové struktury $d_t^k$:
     $$d_t^k = (c_t - c_{t-1},\, c_t - o_t,\, h_t - \ell_t,\, h_t - \max(o_t, c_t),\, \min(o_t, c_t) - \ell_t,\, v_t)$$
   - Lineární projekce $z_t^k = W_{\text{raw}} x_t^k + W_{\text{derived}} d_t^k$.
   - 4 hradlované depthwise-separable konvoluční větve s levým paddingem (zamezujícím pohled do budoucna) a dilatacemi $D = \{1, 2, 4, 8\}$:
     $$C_d = V_d \odot \sigma(G_d), \qquad C = \sum_{d \in D} \text{softmax}(\alpha)_d C_d$$
   - Učitelné exponenciální poolingové tlumení preferující čerstvé bary:
     $$p_c = \sum_{t=1}^T (1 - \lambda_c)\lambda_c^{T-t} C_{t,c}, \qquad \lambda_c = \sigma(\phi_c)$$
   - Finální embedding okna: $e^k = \text{LN}(p^k + W_{\text{tail}} [C_T^k; \text{mean}(C_{T-\min(4,T)+1:T}^k)]) \in \mathbb{R}^{72}$.

3. **Gated Asociační paměť s reziduálním zápisem (Residual-Driven Writes):**
   - Vstup buňky tvoří embedding $e^k$ spojený s rezonančním kontextem a případnými důkazy z nižších pater (dimenze 144 na bázi, 216 výše).
   - Generování normalizovaného klíče, hodnoty a dotazu:
     $$k_t = \text{normalize}(W_k x_t), \quad v_t = \tanh(W_v x_t), \quad q_t = \text{normalize}(W_q x_t)$$
   - Asociační vybavení a výpočet vnitřního rezidua ("Surprise"):
     $$\bar{v}_t = M_t k_t, \qquad s_t = v_t - \bar{v}_t$$
   - Reziduum $s_t$ (odchylka vstupu od očekávání paměti) vstupuje do ohraničeného zápisu ranku 1:
     $$\Omega_t = \tanh\left(\frac{s_t k_t^\top}{\sqrt{d_m}}\right)$$
     $$M_{t+1} = (1 - \eta_t) \odot_B M_t + \eta_t \odot_B \Omega_t$$
   - Query projekce $\mu_t = M_{t+1} q_t$ a aktualizace stavu:
     $$r_{t+1} = \text{LN}\left(r_t + \rho_t \odot W_r \mu_t + (1 - \rho_t) \odot \tanh(W_c g_t)\right)$$

4. **Křížová rezonance & Directional Bottom-Up Evidence:**
   - *Resonance (All-to-all napříč časovými rámci):* Současné stavy všech úrovní interagují přes multi-head self-attention s naučeným párovým biasm $S$:
     $$A = \text{softmax}\left(\frac{QK^\top}{\sqrt{d_r}} + S\right), \quad R' = \text{LN}(R + \text{Dropout}(W_o AV))$$
   - *Bottom-Up Evidence:* Každá vyšší úroveň sleduje historii nižší úrovně v bufferu délky 4 ($H_i$):
     $$E_i = \text{LN}(\text{Attention}(H_i) + 0.35 H_{i,\text{latest}} + 0.15 \text{mean}(H_i))$$

5. **Stacionární cílová reprezentace v bazických bodech (BPS):**
   - Model netrénuje přímo na nestacionární nominální ceně, ale na výnosu v bazických bodech:
     $$y_{\tau+1}^k = 10{,}000 \cdot \left(\frac{P_{\tau+1}^k}{P_\tau^k} - 1\right)\;\text{bps}$$
   - Rekonstrukce kurzu: $\hat{P}_{\tau+1}^k = P_\tau^k \cdot (1 + \hat{y}_{\tau+1}^k / 10{,}000)$.

---

#### B. Aplikační mapování do stávajícího systému SuggestInvest
1. **Asynchronní synchronizace dat bez leakage:**
   - SuggestInvest v současnosti operuje primárně s denními daty (1d change, 1M/3M momentum). Pro Tier 1 (48 TOP Leaders) systém sleduje i ranní předburzovní vývoj. HARN přináší formální protokol: pokud ještě nebyla uzavřena denní svíčka nebo evropská seance, vyšší úroveň se neaktualizuje a nemíchá se do ranního fundamentálního promptu.
2. **Matematický upgrade pro Daily Delta Tracker (Surprise Vector):**
   - Náš stávající Daily Delta Tracker detekuje posuny konfidence $\ge \pm 10\%$ a ratingové skoky.
   - HARN poskytuje přesnou rovnici pro tržní překvapení: $s_t = v_t - \bar{v}_t$. Místo prostého porovnání dvou statických čísel můžeme definovat *Surprise Index* jako odchylku reálného pohybu od vnitřního stavu trhu $\rightarrow$ přesnější odznak `⚡ STRUKTURÁLNÍ OBRAT`.
3. **Event-Gated spouštění katalyzátorů:**
   - Aktivace forward spouštěčů (`CAT_EARNINGS_7D`, `CAT_ATH_TEST`) se naváže na indikátor $u_\tau^k$, což zabrání falešným poplachům z neuzavřených intradenních gapů.

---

#### C. Rigorózní evaluace a technické limity

| Hodnotící dimenze | Skóre (1–10) | Zdůvodnění a identifikované limity |
| :--- | :---: | :--- |
| **Realizovatelnost (Plný PyTorch HARN)** | **4 / 10** | **Kritické technické limity v serverless prostředí:**<br>• *Výpočetní náročnost:* Trénování plného modelu vyžaduje GPU, spojité streamovací dávky (batch 256, contiguous streams, CUDA AMP, AdamW s patience 15). Na našem GitHub Actions runneru (2 vCPU, 7 GB RAM, CPU-only) by trénink 541 modelů trval desítky hodin (timeout runneru).<br>• *Závislosti a CI/CD budget:* Instalace balíku `torch` (~1.5–2 GB) by prodloužila běh ranní pipeline z 2–3 minut na 8–12 minut, což ohrožuje spolehlivost ranního otevíracího skenu v 8:00 CET.<br>• *Datové limity a Rate-limiting:* Stahování multi-timeframe intradenních řad (M15, H1, H4, D1) pro 541 instrumentů přes bezplatné `yfinance` by okamžitě vedlo k zablokování IP adresy (HTTP 429 Rate Limit Exceeded). Bez placeného XTB streamu je neproveditelné. |
| **Realizovatelnost (Odlehčený HARN-Light)** | **8.5 / 10** | **Vysoká proveditelnost:** Přejmutí pouze matematických principů (Completed-bar alignment, stavové maskování $u_\tau^k$ a výpočet Surprise Indexu) v čistém Pythonu/NumPy bez PyTorch a bez trénování neuronových vah. Běh v řádu milisekund v rámci stávajícího skriptu. |
| **Dopad na přesnost (1–3M Swing investování)** | **4 / 10** | **Nízký přínos pro střednědobý horizont:** Pro 1–3měsíční investiční teze (podhodnocení > 20 %, dividendový růst, kvartální earnings) má intradenní rezonance 15minutových svíček minimální informační hodnotu. Dominantní alfa přichází z fundamentů a konsenzu analytiků. |
| **Dopad na přesnost (Krátkodobé časování vstupů)** | **8.5 / 10** | **Vysoký přínos pro exekuci:** Pro přesné načasování nákupu u Tier 1 (TOP Leaders) po vyhlášení signálu Buy dokáže multi-timeframe sladění vyfiltrovat falešné intradenní průrazy. |
| **Celkový dopad na predikce SuggestInvest** | **6.5 / 10** | **Mírný celkový přínos:** Jak přiznává samotná studie na arXiv (kapitoly 1, 7 a 10), nízká chyba rekonstrukce ceny je z velké části způsobena ukotvením na poslední známou cenu $P_\tau$ přes bps prostor ($\hat{P}_{\tau+1} = P_\tau (1 + \hat{y}/10000)$). Ablativní studie (Table 5) prokázala, že odstranění rezonance (A2) či paměti (A1) změnilo výsledky o méně než 0.5 %. |

#### D. Strategické architektonické rozhodnutí (Verdikt)
- ❌ **ZAMÍTNUTO (Full Neural HARN):** Nebudeme do produkční pipeline v GitHub Actions implementovat plnou neuronovou síť HARN v PyTorch pro všech 541 aktiv. Náklady na infrastrukturu, instalaci a riziko API limitů výrazně převyšují reálný přínos k investiční alfe.
- ✅ **SCHVÁLENO K ADAPTACI (HARN-Light State Protocol):** Integrovat do SuggestInvestu jádrovou logiku HARN ve formě lehkého matematického stavového modulu:
  1. **Strict Completed-Bar Protocol ($u_\tau^k$):** Všechny technické a katalyzátorové filtry se počítají výhradně z plně uzavřených period, čímž je zaručena matematická kauzalita.
  2. **Surprise-Driven Delta Metric ($s_t$):** Rozšíření Daily Delta Trackeru o formální metodu porovnání skutečného tržního pohybu vůči konsenzuálnímu očekávání trhu.
  3. **Tier 1 Selective Multi-Timeframe:** Aplikace 2úrovňové hierarchie (Denní trend + H1 vstup) výhradně na 48 klíčových instrumentů koše Tier 1 při přímém napojení na brokerské API XTB.

### 4.2 Multi-Task Learning s ohledem na likviditu (LiMT modul)
- **Teoretická báze:** `SRC-2: LiMT (Hierarchical Multi-Task Learning with Liquidity-Aware Signals for Stock Selection and Portfolio Management, arXiv:2609.25617v1, 2026)`
- **Role v architektuře:** Současné učení budoucích výnosů ($z_r$), objemových šoků ($z_v$) a volatility ($z_\sigma$) pomocí Multi-gate Mixture-of-Experts (MMoE) s hradlovaným přenosem signálů likvidity do výnosové reprezentace; a následná konstrukce exekutivně realizovatelných vah portfolia (APO - Adaptive Portfolio Optimization) s ohledem na tržní dopad a brokerské spready.

#### A. Matematický a architektonický aparát (Formalizace dle arXiv:2609.25617v1)
1. **Hierarchická reprezentace a Market Regime Encoder (MRE):**
   - Vstupní tenzor pro množinu instrumentů $\mathcal{S}_t = \{1, \dots, S\}$ a historii délky $T=21$: $X_t \in \mathbb{R}^{S \times T \times F}$ (např. Alpha158 příznaky).
   - Vstup je promítnut do skryté dimenze $d=256$: $H^{(0)} = X_t W_e + b_e$.
   - **Krok 1: Mezitržní pozornost (Cross-Stock Attention):**
     - Pro každý časový krok $j \in \{1, \dots, T\}$ síť nejprve modeluje interakce napříč všemi aktivy na trhu:
       $$A_c^{(i)} = \text{Softmax}\left(\frac{(H_c W^{Q,(i)})(H_c W^{K,(i)})^\top}{\sqrt{d_k}}\right) \in \mathbb{R}^{S \times S}$$
     - Multi-head projekce ($head_{cross}=4$) generuje reprezentaci zachycující tržní režim a sektorovou synchronizaci.
   - **Krok 2: Intra-aktivní temporální pozornost (Temporal Attention):**
     - Následně pro každou akcii $u$ aplikuje temporální pozornost napříč historií $T$:
       $$A_t^{(i)} = \text{Softmax}\left(\frac{(H_t \tilde{W}^{Q,(i)})(H_t \tilde{W}^{K,(i)})^\top}{\sqrt{d_k}}\right) \in \mathbb{R}^{T \times T}$$
     - Dvojúrovňová pozornost brání prolínání systémového tržního šumu s individuálním momentem titulu.
     - Interakce mezi aktivy a časem je formalizována maticí šíření vlivu (*Cross-Time Propagation Matrix*):
       $$M[j, v] = A_{t,u}[-1, j] \cdot A_{c,j}[u, v]$$
       což kvantifikuje, jak moc se historický krok $j$ cizí akcie $v$ propisuje do předpovědi cílové akcie $u$.

2. **Liquidity-Driven Learning (LDL) s Multi-Task MMoE:**
   - Model definuje 3 paralelní cílové veličiny pro horizont $t+2$ (prevence exekuční nerealizovatelnosti při nákupu na Open $t+1$):
     - **Hlavní cíl (Budoucí výnos $z_r$):**
       $$z_r = \frac{\text{Close}(t+2)}{\text{Close}(t+1)} - 1$$
     - **Pomocný cíl 1 (Objemový šok / Likvidita $z_v$):**
       $$z_v = \log(\text{Volume}_{t+2}) - \frac{1}{5}\sum_{i=1}^5 \log(\text{Volume}_{t+2-i})$$
     - **Pomocný cíl 2 (Volatilita / Rozpětí $z_\sigma$):**
       $$z_\sigma = \frac{\text{High}_{t+2} - \text{Low}_{t+2}}{\text{VWAP}_{t+2}}$$
   - Všechny tři cíle jsou normalizovány pomocí průřezového Z-skóre.
   - **Multi-gate Mixture of Experts:**
     - Sdílený pool $E$ expertních sítí $\{\text{Expert}_e\}_{e=1}^E$.
     - Specifické hradlovací funkce pro každý úkol $k \in \{r, v, \sigma\}$:
       $$\alpha^k = \text{Softmax}(\Phi_k(h^*)) \in \mathbb{R}^E$$
       $$o_k = \sum_{e=1}^E \alpha^k[e] \cdot \text{Expert}_e(h^*)$$
   - **Cross-Task Gated Transfer (Hradlovaný přenos likvidity do výnosu):**
     - Aby informace o likviditě a volatilitě přímo kultivovaly výnosovou predikci, model zavádí skalární transferová hradla:
       $$\beta_v = \sigma(\text{Linear}_{v \to r}(G_v(o_v))) \in (0, 1)$$
       $$\beta_\sigma = \sigma(\text{Linear}_{\sigma \to r}(G_\sigma(o_\sigma))) \in (0, 1)$$
     - Výsledná výnosová reprezentace obohacená o likviditní filtr:
       $$o'_r = G_r(o_r) + \beta_v \odot G_v(o_v) + \beta_\sigma \odot G_\sigma(o_\sigma)$$
   - **Multi-task Loss:**
     $$\mathcal{L} = \lambda_r \cdot \text{MSE}(\hat{z}_r, z_r) + \lambda_v \cdot \text{MSE}(\hat{z}_v, z_v) + \lambda_\sigma \cdot \text{MSE}(\hat{z}_sigma, z_\sigma)$$
     kde optimální hyperparametry jsou $\lambda_r \approx 0.65, \lambda_v \approx 0.30, \lambda_\sigma \approx 0.05$.

3. **Adaptive Portfolio Optimization (APO) s kapacitním limitem:**
   - Predikované Z-skóre $\hat{z}_v$ a $\hat{z}_\sigma$ jsou de-normalizovány zpět do fyzických veličin:
     $$\hat{A}_{i,t+2} = \mu_{A,i,t} + \sigma_{A,i,t} \cdot \hat{z}_{v,i} \quad (\text{odhadovaný obrat / objem})$$
     $$\hat{\sigma}_{i,t+2} = \mu_{\sigma,i,t} + \sigma_{\sigma,i,t} \cdot \hat{z}_{\sigma,i} \quad (\text{odhadovaná volatilita})$$
   - Normalizované likviditní váhy: $w_i^A = \frac{\hat{A}_{i,t+2}}{\sum_{j \in \mathcal{G}_t} \hat{A}_{j,t+2}}$
   - Normalizované inverzně-volatilní váhy: $w_i^\sigma = \frac{1 / \hat{\sigma}_{i,t+2}}{\sum_{j \in \mathcal{G}_t} (1 / \hat{\sigma}_{j,t+2})}$
   - **Konečná alokační váha aktiva s 2% limitem denního obratu:**
     $$w_i^* = \min\left(r \cdot w_i^\sigma + (1 - r) \cdot w_i^A,\; \frac{\alpha \cdot A_{i,t}}{C}\right)$$
     kde $\alpha = 0.02$ (maximálně 2 % denního obratu dané akcie), $C$ je celkový kapitál a $r = 0.1$ (empiricky optimální váha silně upřednostňující likviditu před čistou paritou rizika).

#### B. Integrace do stávající architektury SuggestInvest
1. **Vazba na stávající univerzium 541 titulů a brokerské spready XTB:**
   - V SuggestInvestu máme instrumenty rozdělené do 3 košů: Core (60), Mid (140) a Satellites (341).
   - Zásadní hrozba pro malé a střední tituly (Tier 2 a Tier 3) na platformě XTB spočívá v **bid-ask spreadech a nízké hloubce trhu** (spready u méně likvidních akcií a ETF dosahují 0.3 % až 0.8 %, což spolehlivě maže generovanou alfu).
   - LiMT-APO modul přináší přesný aparát: jakýkoliv signál pro titul s denním objemem pod limitem nebo spreadem nad prahovou hodnotou bude škálován dolů nebo zcela vyřazen z exekuce.
2. **Nový nativní katalyzátor `CAT_VOLUME_SHOCK`:**
   - Definice dle LDL: $z_v = \log(\text{Volume}_t) - \text{SMA}_5(\log(\text{Volume}))$.
   - Pokud $z_v > 2.0$ při současném růstu ceny, jedná se o institucionální akumulaci (*Volume Breakout Catalyst*).
3. **Spread-Aware Conviction Sizer:**
   - Nahrazení čistě lineárního vážení pozic dle Conviction Score pravidlem APO:
     $$\text{FinalWeight}_i = \min\left(\text{BaseWeight}_i \cdot \frac{1}{1 + \gamma \cdot \text{Spread}_i},\; \frac{0.02 \cdot \text{DailyTurnover}_i}{\text{PortfolioValue}}\right)$$

#### C. Kvantitativní evaluace a technické limity (Realizovatelnost vs. Dopad)

| Kritérium | Skóre | Technické limity a analytické odůvodnění |
| :--- | :---: | :--- |
| **Realizovatelnost (Plná PyTorch MMoE síť)** | **3.5 / 10** | **Kritické technické limity pro CI/CD:**<br>1. *Kvadratická složitost pozornosti:* Mezitržní matice $A_c$ pro $S=541$ akcií vyžaduje $541 \times 541 = 292\,681$ hran na každý z 21 časových kroků a 4 hlavy pozornosti ($\approx 2.45 \times 10^7$ operací na krok).<br>2. *Infrastrukturní limit:* Autoři v paperu trénovali model na serveru s Intel Xeon, **2 TB RAM** a **RTX 3090 (24 GB VRAM)**. Běžný GitHub Actions runner disponuje pouze 2 vCPU, 7 GB RAM a 0 GPU. Plné trénování či denní inference MMoE sítě by vedlo k Out-Of-Memory a pádu CI/CD pipeline.<br>3. *Zpoždění a rate-limity:* Stažení Alpha158 příznaků pro 541 titulů denně by spotřebovalo stovky API požadavků na yfinance. |
| **Realizovatelnost (LiMT-Light APO Rule Engine)** | **9.5 / 10** | **Vysoká realizovatelnost bez neural overheadu:**<br>1. Výpočet objemového šoku $z_v$ a volatility $z_\sigma$ v čistém `pandas`/`numpy` trvá pro všech 541 titulů **< 0.2 sekundy**.<br>2. Implementace APO alokačního filtru ($w_i^* = \min(0.1 w^\sigma + 0.9 w^A, \frac{0.02 A_i}{C})$) a spread-penalizace nevyžaduje žádné externí závislosti kromě standardní knihovny SuggestInvestu.<br>3. Nulové dodatečné nároky na RAM a plná kompatibilita s 5minutovým limitem GitHub Actions. |
| **Dopad na přesnost predikcí (Raw IC/ICIR)** | **7.0 / 10** | **Mírný posun v čisté predikci výnosu:** Informační koeficient (IC) stoupl z 0.0538 (XGBoost) na 0.0575 (+6.88 %), ICIR z 0.3979 na 0.4462 (+12.1 %). Samotná MMoE síť vylepšuje predikci směru mírně. |
| **Dopad na čisté realizované výnosy (Net Alpha & Sharpe po nákladech)** | **9.0 / 10** | **Zásadní a revoluční přínos pro reálné obchodování:**<br>1. Při započtení transakčních nákladů (10 bps) a limitu obratu (2 %) zvýšila metoda APO roční výnos z **3.99 % na 10.01 %** (+150 % relativně) a Sharpe Ratio z **1.22 na 1.86** oproti rovnovážnému portfoliu.<br>2. Ochrana před iluzorní alfou: V praxi zabrání SuggestInvestu doporučovat pozice v nelikvidních titulech s vysokým teoretickým ziskem, který by byl při nákupu/prodeji na XTB okamžitě zlikvidován spreadem a slippage. |

#### D. Strategické architektonické rozhodnutí (Verdikt)
- ❌ **ZAMÍTNUTO (Full Neural MRE + MMoE Model):** Nebudeme nasazovat těžkou neuronovou síť se čtvercovou mezitržní pozorností $541 \times 541$. Zátěž na paměť a výpočetní čas neodpovídá možnostem bezplatné serverless infrastruktury.
- ✅ **SCHVÁLENO K IMPLEMENTACI (LiMT-APO Liquidity & Volatility Sizer):**
  1. **Nový katalyzátor `CAT_VOLUME_SHOCK`:** Začlenění 5denního logaritmického objemového šoku $z_v$ mezi oficiální katalyzátory SuggestInvestu pro detekci institucionálního vstupu.
  2. **APO Liquidity Guard & Spread Penalty v sekci 5.1 / 5.2:** Každý vygenerovaný investiční nápad projde kontrolou exekutability:
     - Výpočet denního obratu v USD ($A_{i,t} = \text{Volume}_t \times \text{Close}_t$).
     - Zastropování doporučené alokace pravidlem 2 % denního obratu.
     - Automatická diskvalifikace či penalizace titulů s bid-ask spreadem $> 0.30\%$ u brokera XTB.

### 4.3 Statistická arbitráž, kointegrace a limity párového obchodování (Pairs Trading modul)
- **Teoretická báze:** `SRC-6: Pairs trading at CEE markets (DSpace UK 130215669, Univerzita Karlova, FSV IES, Jakub Šedivý, vedoucí práce: Ing. Aleš Maršál, 2017)`
- **Role v architektuře:** Rigorózní identifikace rovnovážných kointegrovaných vztahů mezi blízkými substituty, matematické modelování návratu k průměru (Mean-Reversion) pomocí Ornsteinova-Uhlenbeckova procesu a empirická dekonstrukce rizik párového obchodování (absence odvětvové homogenity, široké spready, strukturální divergence a swapové náklady).

#### A. Matematický a architektonický aparát (Formalizace dle DSpace UK 130215669)
1. **Dvě konkurenční metodiky párování (Distance vs. Cointegration):**
   - **Vzdálenostní metoda (Distance Method / SSD dle Gatev et al., 2006):**
     - Normalizované kumulativní výnosové indexy: $R_{it}^c = \sum_{s=1}^t \hat{R}_{is}$.
     - Suma čtverců odchylek (Sum of Squared Deviations):
       $$SSD_{i,j} = \sum_{t=1}^T (R_{it}^c - R_{jt}^c)^2, \quad \forall i \neq j$$
     - V 15měsíčním formačním okně (formation period) se vybere 5 párů s nejnižším $SSD$.
     - V 6měsíčním obchodním okně (trading period) se pozice otevírá při rozestupu $\pm 2\sigma$ a uzavírá při návratu ke střední hodnotě $0\sigma$.
   - **Dvoukroková kointegrační metoda (Engle & Granger, 1987):**
     - *Krok 1 (Test jednotkového kořene):* Ověření, že obě cenové řady $y_t$ a $x_t$ jsou nestacionární řádu $I(1)$ pomocí Augmented Dickey-Fuller (ADF) testu se zpožděním voleným dle Akaikeho informačního kritéria (AIC).
     - *Krok 2 (Kointegrující regrese):*
       $$y_t = \alpha + \beta x_t + e_t$$
       s restrikcí na $\beta > 0$ (aby strategie byla tržně neutrální a nekupovala či neprodávala obě akcie současně).
     - *Krok 3 (Stacionarita reziduí):* Test stacionarity reziduí $\hat{e}_t = y_t - \hat{\alpha} - \hat{\beta} x_t$ pomocí ADF testu s asymptotickými kritickými hodnotami (Hamilton 1994, kritická hodnota $-3.37$ na $5\%$ hladině významnosti).
     - *Krok 4 (Obchodní signál na spreadu):*
       $$S_t = y_t - \hat{\alpha} - \hat{\beta} x_t$$
       Vstup při $S_t > \bar{S} + 2\sigma_e$ (short $y$, long $\beta \cdot x$) nebo $S_t < \bar{S} - 2\sigma_e$ (long $y$, short $\beta \cdot x$), výstup při konvergenci $S_t = \bar{S}$.

2. **Modelování rychlosti návratu k průměru (Ornstein-Uhlenbeck proces):**
   - Šíření kointegrovaného spreadu v čase je modelováno stochastickou diferenciální rovnicí:
     $$dS_t = \theta (\mu - S_t) dt + \sigma dW_t$$
     kde $\theta$ je rychlost návratu k průměru (*mean-reversion speed*) a $\mu$ je dlouhodobá rovnováha.
   - V diskrétním čase odpovídá AR(1) regresi: $\Delta S_t = a + b S_{t-1} + \epsilon_t$, kde $\theta = -\frac{\ln(1+b)}{\Delta t}$.
   - **Poločas návratu k rovnováze (Half-Life of Mean Reversion):**
     $$t_{1/2} = \frac{\ln 2}{\theta} = -\frac{\ln 2 \cdot \Delta t}{\ln(1 + b)}$$
   - Pokud $t_{1/2} > 30\text{ obchodních dní}$, spread konverguje příliš pomalu a je vyřazen jako neefektivní.

#### B. Empirické výsledky práce & Proč párové obchodování v CEE selhalo
- **Testované trhy:** Burza cenných papírů Praha (PSE), Budapešťská burza (BSE), Bukurešťská burza (BVB) v období červen 2008 – březen 2017.
- **Klíčové empirické statistiky autorova výzkumu:**
  - **Distance Method:** Průměrný nadvýnos byl v Praze a Budapešti záporný (PSE: $-0.49\%$, BSE: $-1.16\%$, BVB: $+0.06\%$), Information Ratio bylo zanedbatelné ($0.12$ až $-0.06$).
  - **Cointegration Method:** Průměrný nadvýnos byl na všech trzích **statisticky signifikantně záporný** (PSE: $-3.61\%$, BSE: $-5.54\%$, BVB: $-0.95\%$; $t$-stat pro BSE $-2.59$ na $p < 0.05$!).
  - **Míra dokončení ziskového cyklu (Share of Round-Trips):** Pouze **28.6 % až 42.2 %** otevřených pozic dokázalo konvergovat zpět ke střední hodnotě! Více než $60\%$ pozic zůstalo na konci 6měsíčního obchodního okna otevřeno a muselo být nuceně zlikvidováno s těžkou ztrátou.
- **4 strukturální příčiny selhání odhalené Šedivým:**
  1. *Absence odvětvové homogenity (Mezisektorové párování):* Malá burza s pouhými 10–17 tituly nutila algoritmus párovat firmy z naprosto nesouvisejících odvětví (např. ČEZ a textilku Pegas Nonwovens, nebo banku s telekomunikacemi). Matematická kointegrace ve formačním okně byla pouhou **náhodnou iluzí (spurious correlation)** a out-of-sample se okamžitě rozpadla. V USA naproti tomu párové obchodování funguje výhradně u firem ze stejného odvětví (např. dvě utility nebo těžaři ropy).
  2. *Nelikvidita a bid-ask spready:* Široké spready na málo likvidních trzích okamžitě vymazaly jakýkoliv teoretický arbitrážní zisk (bid-ask bounce).
  3. *Strukturální zlomy (Divergence místo konvergence):* Rozšíření spreadu na $2\sigma$ na nelikvidním trhu často neznamenalo přechodnou anomálii, ale trvalou fundamentální změnu (např. ztráta klíčového trhu, fraud, propad tržeb). Bez striktního Stop-Lossu vedlo pasivní čekání na konvergenci ke katastrofální ztrátě.
  4. *Omezení a swapové náklady shortování:* Teoretický předpoklad bezplatného a neomezeného shortování byl v praxi nerealizovatelný.

#### C. Integrace a přenositelnost do SuggestInvest
1. **Reálná architektura SuggestInvest vs. Kvantitativní párování:**
   - Sledujeme **541 instrumentů**.
   - **Kombinatorická exploze:** Úplné testování všech možných dvojic představuje:
     $$P = \binom{541}{2} = \frac{541 \times 540}{2} = 146\,070\text{ párů}$$
     Provádět denně 146 070 OLS regresí a ADF testů v 5minutovém GitHub Actions cronu (2 vCPU) by vedlo k okamžitému pádu pipeline na Timeout či Out-Of-Memory.
   - **Bariéra brokera XTB (Swap Drag na Short CFD):**
     U brokera XTB je nákup fyzických akcií bez poplatku. Avšak **shortování je možné výhradně přes CFD kontrakty**, které nesou denní swapový poplatek (typicky 8–10 % p.a.!). Pokud je párový obchod otevřen v průměru 61 dní (jak naměřil Šedivý), swapový poplatek odčerpá $1.5\%$ až $2.0\%$ z kapitálu, což spolehlivě zničí jakoukoliv arbitrážní marži.
2. **Přenositelné principy SRC-6 pro SuggestInvest (Pairs-Light & Sector Cointegration):**
   - **Princip 1: Striktní vnitro-sektorové omezení (Intra-Sector Constrained Pairing):**
     Kategoricky odmítáme náhodné párování napříč celým trhem. Kointegraci testujeme výhradně mezi přímými konkurenty v rámci stejného GICS sub-odvětví v elitním koši Core 60 (např. Visa vs. Mastercard, Chevron vs. ExxonMobil, AMD vs. Nvidia, Home Depot vs. Lowe's, nebo ETF páry jako EEM vs. VWO). Tím se počet testovaných párů zredukuje ze 146 070 na **méně než 50 ekonomicky opodstatněných dvojic**.
   - **Princip 2: Long-Only relativní valuace (Ochrana před CFD swapy):**
     Místo nákladného shortování CFD využíváme kointegraci jako **relativní nákupní filtr**:
     Pokud jsou akcie A i B kointegrované a obě mají pozitivní fundamentální momentum, ale akcie A se nachází na spodní hranici spreadu ($S_t < -2\sigma$), alokujeme kapitál do akcie A a akcii B vynecháme. Získáváme statistickou výhodu bez nutnosti platit swapové poplatky za shortování.
   - **Princip 3: Stop-Loss při strukturálním zlomu (Structural Break Filter):**
     Pokud se spread rozšíří nad $3.5\sigma$, model to interpretuje nikoliv jako "skvělou nákupní příležitost", ale jako strukturální rozpad kointegrace (jak varoval Šedivý) a okamžitě ruší doporučení, čímž eliminuje osud 60 % neuzavřených ztrátových pozic.

#### D. Kvantitativní evaluace a technické limity (Realizovatelnost vs. Dopad)

| Kritérium | Skóre | Technické limity a analytické odůvodnění |
| :--- | :---: | :--- |
| **Realizovatelnost (Plný Long/Short Pairs Trading na 146 070 párech přes XTB CFD)** | **2.0 / 10** | **Nepřekročitelné technické a finanční limity:**<br>1. *Kombinatorický limit:* Testování 146 070 párů denně by v GitHub Actions (2 vCPU, 7 GB RAM) trvalo desítky minut.<br>2. *Swapový poplatek XTB:* Shortování přes CFD stojí 8–10 % p.a. na swapovém financing rate. Při průměrné době držení 61 dní swap sežere 1.5–2.0 % kapitálu, což převyšuje hrubý zisk strategie.<br>3. *Regulační a kapitálové požadavky:* Vyžaduje složitou maržovou správu a neustálé rebalancování hedge poměru $\beta$. |
| **Realizovatelnost (Pairs-Light: Vnitro-sektorový kointegrační filtr pro Core 60 a Long-Only rotaci)** | **9.0 / 10** | **Okamžitá a blesková realizovatelnost:**<br>1. Omezení na ~50 provázaných párů v rámci stejného sektoru trvá v `statsmodels` a `numpy` **< 0.5 sekundy**.<br>2. Žádné swapové poplatky (využívá se pro Long-Only selekci relativně podhodnoceného titulu v páru).<br>3. Zanedbatelná paměťová náročnost plně slučitelná se serverless limitem 5 minut. |
| **Dopad na přesnost predikcí (Směrová selekce ziskových titulů na dny/týdny)** | **6.5 / 10** | Kointegrace identifikuje relativní ocenění mezi dvěma substituty, nikoliv absolutní tržní směr celého odvětví. |
| **Dopad na robustnost a prevenci strukturálních pastí (Structural Break Guard)** | **8.5 / 10** | **Zásadní ochrana kapitálu:** Zavedení filtru poločasu návratu ($t_{1/2} < 30\text{ dní}$) a Stop-Lossu při divergenci ($> 3.5\sigma$) chrání systém před vstupem do titulů postižených fundamentálním rozpadem byznysu. |

#### E. Strategické architektonické rozhodnutí (Verdikt)
- ❌ **ZAMÍTNUTO (Full Long/Short CFD Pairs Trading Engine pro 541 aktiv):** Z důvodu kombinatorické neúnosnosti (146 070 párů) a zničujícího swapového poplatku u brokera XTB nebudeme provozovat klasickou tržně-neutrální Long/Short strategii.
- ✅ **SCHVÁLENO K IMPLEMENTACI (Pairs-Light Relative Value & Structural Break Engine):**
  1. **Vnitro-sektorový kointegrační filtr v Sekci 4.3:** Monitorovat kointegraci a poločas návratu k průměru ($t_{1/2}$) u předem definovaných párů v koši Core 60 (např. V/MA, KO/PEP, CVX/XOM).
  2. **Relativní nákupní timing:** Při výskytu pozitivního katalyzátoru u obou firem v páru upřednostnit nákup titulu se Z-skóre spreadu $S_t < -2.0\sigma$.
  3. **Pravidlo okamžitého Stop-Lossu (Sekce 5.3):** Pokud spread překročí $3.5\sigma$, pozice je okamžitě uzavřena z důvodu rozpadu kointegrace (prevence strukturálního zlomu).

### 4.4 NLP Sentiment, Deep RL a limity transakčních nákladů (AI & NLP Trading modul)
- **Teoretická báze:** `SRC-5: Stock Trading Using a Deep Reinforcement Learning and Text Analysis (DSpace UK 120426710, Univerzita Karlova, FSV IES, Dominik Benk, vedoucí práce: Prof. Jozef Baruník, 2022)`
- **Role v architektuře:** Kvantifikace tržního sentimentu ze zpráv a sociálních médií, komparace prediktivní síly institucionálního vs. retailového textu, modelování rozhodovacího procesu pomocí zpětnovazebního učení (Deep RL) a empirická analýza destrukce alfy pod vlivem transakčních nákladů a spreadů.

#### A. Matematický a architektonický aparát (Formalizace dle DSpace UK 120426710)
1. **Dvousložkový aparát finančního NLP (News vs. Social Media):**
   - **FinBERT (Specializovaný jazykový model pro zprávy):**
     - Předtrénovaný model BERT jemně dotrénovaný (fine-tuned) na specializovaných finančních korpusech (*Reuters* a *Financial PhraseBank*).
     - Pro libovolný text článku či titulku $T_i$ model generuje pravděpodobnostní rozdělení sentimentu napříč 3 třídami: $[p_{\text{neg}}, p_{\text{neu}}, p_{\text{pos}}]$.
     - Spojitá polarita sentimentu:
       $$S_{\text{FinBERT}}(T_i) = p_{\text{pos}}(T_i) - p_{\text{neg}}(T_i) \in [-1, 1]$$
   - **TweetEval (Specializovaný model pro sociální média a mikroblogy):**
     - RoBERTa architektura přizpůsobená specifickému jazyku Twitteru/X (slang, zkratky, emojis, cashtags např. `$AAPL`, `$TSLA`).
     - Spojitá polarita sociálního sentimentu:
       $$S_{\text{TweetEval}}(Tweet_j) = p_{\text{pos}}(Tweet_j) - p_{\text{neg}}(Tweet_j) \in [-1, 1]$$
   - **Denní agregace a textový objem (Text Volume & Polarity Aggregation):**
     - Pro každou akcii $i$ a den $t$ je vypočten průměrný sentiment a normalizovaný objem pozornosti:
       $$\bar{S}_t^{\text{news}} = \frac{1}{N_{n,t}} \sum_{k=1}^{N_{n,t}} S_{\text{FinBERT}}(T_{k,t}), \quad V_t^{\text{news}} = \log(1 + N_{n,t})$$
       $$\bar{S}_t^{\text{social}} = \frac{1}{N_{s,t}} \sum_{j=1}^{N_{s,t}} S_{\text{TweetEval}}(Tweet_{j,t}), \quad V_t^{\text{social}} = \log(1 + N_{s,t})$$
   - **Zjištění ortogonality (Pearsonova korelační matice autorova výzkumu):**
     - Korelace mezi titulkem zprávy a obsahem zprávy: $r = 0.555$ (silná redundance, pro rychlé rozhodování stačí titulek).
     - Korelace mezi zprávami (News) a sociálními sítěmi (Twitter Cashtags): **$r = 0.074 \text{ až } 0.124$** (naprostá nekorelovanost!).
     - **Teoretický závěr:** Zprávy a sociální sítě přinášejí do rozhodovacího modelu vzájemně nezávislou, ortogonální informaci.

2. **Formulace Deep Reinforcement Learning (DDQN Agent):**
   - Obchodování je modelováno jako Markovův rozhodovací proces $(\mathcal{S}, \mathcal{A}, \mathcal{P}, \mathcal{R}, \gamma)$:
     - **Stavový prostor $s_t \in \mathcal{S}$:**
       $$s_t = [R_t, \text{RSI}_t, \text{MACD}_t, \text{ATR}_t, \bar{S}_t^{\text{news}}, \bar{S}_t^{\text{social}}, V_t^{\text{news}}, V_t^{\text{social}}, p_t]$$
       kde $p_t \in \{-1, 0, 1\}$ je aktuální držená pozice (Short, Flat, Long).
     - **Akční prostor $a_t \in \mathcal{A}$:** Diskrétní volba $\{ \text{Sell} (-1), \text{Hold} (0), \text{Buy} (+1) \}$.
     - **Odměnová funkce (Reward Function) s explicitními transakčními náklady:**
       $$r_{t+1} = p_t \cdot R_{t+1} - c_{\text{trans}} \cdot |p_{t+1} - p_t|$$
       kde $c_{\text{trans}}$ reprezentuje transakční poplatek a spread brokera.
   - **Double Deep Q-Network (DDQN):**
     - K odstranění systematického nadhodnocování Q-hodnot standardního Q-learningu používá DDQN dvě nezávislé sítě: online síť s parametry $\theta_t$ a cílovou síť (target network) $\theta_t^-$:
       $$Y_t^{\text{DoubleQ}} = r_{t+1} + \gamma Q\left(s_{t+1}, \operatorname{argmax}_a Q(s_{t+1}, a; \theta_t);\, \theta_t^-\right)$$
     - Minimalizace střední kvadratické chyby Bellmanova rezidua na náhodně vzorkovaných zkušenostech z paměťového bufferu (Experience Replay).

#### B. Empirické výsledky práce & Odhalené limity a úskalí
- **Testovací universum:** 11 heterogenních US akcií (AAPL, MSFT, GOOGL, AMZN, FB/META, TSLA, BRK-A, TSM, NVDA, JPM, GME) v časovém okně 2018–2022.
- **Klíčové empirické srovnání strategií (Annualized Sharpe Ratio na Out-of-Sample testovacích datech):**
  - **Pasivní benchmark (Buy & Hold):** Sharpe = **0.852** (Equal Weights), 0.823 (Min-Var).
  - **DDQN pouze na technických datech (`core-set`):** Sharpe = **-0.865** (drastický propad, čistý technický RL agent selhal a skončil v hluboké ztrátě).
  - **DDQN pouze se zprávami (`news-set-1` až `6`):** Sharpe = **-1.517 až -0.018** (zprávy samy o sobě trpí zpožděním a způsobily přehnané obchodování na zpožděných impulsech).
  - **DDQN pouze se sociálními sítěmi (`twitter-set-4`):** Sharpe = **+0.790** (sociální sítě reagují okamžitě a výrazně zlepšily dynamiku agenta).
  - **DDQN s fúzí zpráv i Twitteru (`full-set`):** Sharpe = **+1.286** (jediný model, který statisticky i prakticky překonal pasivní Buy & Hold benchmark!).
- **Kritická zjištění autora o selhání Deep RL v praxi:**
  1. *Extrémní výpočetní náročnost:* Trénování DDQN pro pouhých 11 akcií trvalo **18 dní nepřetržitého běhu distribuovaného na 3 počítačích**!
  2. *Nestabilita a přetrénování (Overfitting):* Výsledky byly drasticky citlivé na náhodný inicializační seed a délku epizod. Na meme-akciích (GME, TSLA) agent generoval iluzorní zisky na trénovacích datech, ale na testovacích datech zcela zkolaboval.
  3. *Kolaps při reálných transakčních nákladech:* Když autor zvýšil transakční náklady na realistické hodnoty ($c_{\text{trans}} \ge 0.5\% - 1.0\%$, což odpovídá typickému spreadu a slippage na retailových účtech), **učení DDQN agenta se kompletně zhroutilo**. Agent bud' nedokázal konvergovat vůbec, nebo se stal 100% pasivním a neprovedl ani jediný obchod.

#### C. Integrace a přenositelnost do SuggestInvest
1. **Reálná architektura SuggestInvest vs. Benkův experiment:**
   - SuggestInvest pokrývá **541 akcií a ETF**, nikoliv 11.
   - Běžíme v bezplatném **GitHub Actions runneru** (2 vCPU, 7 GB RAM, limit běhu < 3–5 minut, žádné dedikované GPU).
   - Trénovat DDQN sítě nebo spouštět těžké lokální transformery FinBERT a TweetEval na CPU pro 541 titulů denně v GitHub Actions je **technicky a matematicky vyloučené** (18 dní na 3 strojích pro 11 akcií $\implies$ stovky hodin pro 541 akcií).
   - End-to-end Deep RL je navíc černá skříňka, která odporuje základnímu požadavku našeho investičního komitétu na vysvětlitelnost a transparentnost (Explainable AI).
2. **Přenositelné principy SRC-5 pro SuggestInvest:**
   - **Princip 1: Fúze institucionálního a retailového sentimentu:**
     Benkův důkaz, že kombinace fundamentálních zpráv a sociálního sentimentu (`full-set`) zvedá Sharpe z $-0.865$ na $+1.286$, potvrzuje správnost naší architektury kombinující fundamentální zprávy z `yfinance` a makro sentiment.
   - **Princip 2: Nahrazení lokálního FinBERT/TweetEval modelem Google Gemini Flash (Serverless LLM):**
     Místo lokálního hostování dvou těžkých PyTorch BERT modelů využíváme API Google Gemini 2.5 Flash, které v 22 dávkách (~25 akcií) provede hloubkovou sémantickou analýzu všech novinek za méně než 90 sekund. Gemini kombinuje porozumění finančnímu žargonu (FinBERT doména) i detekci nuancí tržního tónu bez jakékoliv zátěže našeho serverless runneru.
   - **Princip 3: Sentiment Delta ($\Delta S_t$) namísto statického sentimentu:**
     Zavádíme sledování dynamické odchylky sentimentu vůči 14dennímu exponenciálnímu průměru:
     $$\Delta S_{i,t} = S_{i,t} - \text{EMA}_{14}(S_i)$$
     Akcie s dlouhodobě vysokým sentimentem již mají tuto informaci v ceně; alfa vzniká pouze při pozitivním šoku ($\Delta S_{i,t} > +0.35$).
   - **Princip 4: Potvrzení LiMT-APO bariéry nákladů:**
     Zjištění, že náklady $\ge 0.5\%$ ničí učení a ziskovost, striktně potvrzuje naše pravidlo ze sekce 5.1: diskvalifikovat z nákupních signálů jakékoliv aktivum se spreadem $> 0.30\%$ na XTB.

#### D. Kvantitativní evaluace a technické limity (Realizovatelnost vs. Dopad)

| Kritérium | Skóre | Technické limity a analytické odůvodnění |
| :--- | :---: | :--- |
| **Realizovatelnost (Plný lokální DDQN Agent + FinBERT + TweetEval pipeline pro 541 aktiv)** | **1.5 / 10** | **Zcela nerealizovatelné v produkčním CI/CD:**<br>1. *Extrémní výpočetní čas:* Trénink 11 akcií trval 18 dní na 3 počítačích. Pro 541 aktiv by šlo o stovky dní výpočetního času GPU.<br>2. *Infrastrukturní limit:* GitHub Actions (2 vCPU, bez GPU, 7 GB RAM) by při pokusu o inferenci stovek lokálních transformerů a RL politik skončil s Timeout (po 6 hodinách) nebo Out-Of-Memory chybou do 30 sekund.<br>3. *Nestabilita tréninku:* DDQN trpí náchylností k lokálním minimům a katastrofálnímu zapomínání při změně tržního režimu. |
| **Realizovatelnost (SuggestInvest Cloud-LLM Batched NLP & Sentiment-Delta Rule Engine)** | **9.0 / 10** | **Vysoká efektivita a plná souladnost s CI/CD:**<br>1. Zpracování zpráv pro 541 aktiv probíhá přes dávkové dotazy na Google Gemini API (22 dávek po 25 aktivech) a trvá **< 90 sekund**.<br>2. Výpočet Sentiment Delta $\Delta S_{i,t}$ a křížových filtrů probíhá v `pandas` za **< 0.1 sekundy** s nulovou dodatečnou paměťovou zátěží.<br>3. Plně se vejde do ranního GitHub Actions cronu (celkový běh pipeline pod 3 minuty). |
| **Dopad na přesnost predikcí (Směrová selekce ziskových titulů - Raw Directional Alpha)** | **8.0 / 10** | **Vysoký a empiricky prokázaný přínos:**<br>1. Benkova rigorózní analýza na datech UK prokázala, že zapojení obou složek textu zvedlo Sharpe ratio z **-0.865 na +1.286**.<br>2. Finanční zprávy a textové signály zachycují katalyzátory (např. schválení patentu, regulatorní zásah, earnings beat) dříve, než se plně promítnou do cenového klouzavého průměru. |
| **Dopad na robustnost a stabilitu (Prevence přetrénování a řízení nákladů)** | **8.5 / 10** | Nahrazení nestabilního černoskříňkového DDQN agenta transparentními pravidlovými filtry (Conviction Score + LiMT-APO) eliminuje riziko přetrénování a chrání kapitál před destrukcí způsobenou transakčními spready. |

#### E. Strategické architektonické rozhodnutí (Verdikt)
- ❌ **ZAMÍTNUTO (End-to-End Deep RL DDQN & Local HuggingFace BERT Pipeline):** Z důvodu nepřekročitelných časových limitů (18 dní tréninku), absence GPU v CI/CD a vysoké fragility nebudeme trénovat samostatné RL agenty ani lokálně hostovat FinBERT.
- ✅ **SCHVÁLENO K IMPLEMENTACI (Gemini Batched NLP & Sentiment Momentum Adapter):**
  1. **Sentiment Momentum Delta ($\Delta S_t$ v Sekci 2.2):** Sledovat změnu sentimentu vůči 14dennímu průměru a generovat nákupní signály pouze při prudké kladné akceleraci sentimentu.
  2. **Nový katalyzátor `CAT_SENTIMENT_DIVERGENCE`:** Detekce situace, kdy cena akcie konsoliduje nebo mírně klesá, ale sentiment ze zpráv a sociálních médií prudce roste ($\Delta S_t > 0.40$), což signalizuje skrytou institucionální akumulaci před cenovým výstřelem.
  3. **Striktní transakční filtr v Sekci 5.1:** V souladu s Benkovým zjištěním o kolapsu strategií při nákladech $\ge 0.5\%$ striktně penalizovat jakýkoliv titul s brokerským spreadem nad $0.30\%$.

### 4.5 Metodologické principy kvantitativního trhu, feature engineering a prevence přeučení (Decoding the Quant Market modul)
- **Teoretická báze:** `SRC-7: Decoding the Quant Market: A Guide to Machine Learning in Trading (SSRN 4422374, 2023)`
- **Role v architektuře:** Zavedení institucionálních standardů finančního strojového učení, striktní eliminace informačních úniků (Lookahead Bias, Overlapping Returns) pomocí očistěné křížové validace (Purged Cross-Validation), robustní průřezový feature engineering a dekonstrukce tržního dopadu při exekuci.

#### A. Matematický a architektonický aparát (Formalizace dle SSRN 4422374)
1. **Očistěná křížová validace finančních řad (Purged & Embargoed Cross-Validation):**
   - Finanční časové řady zásadně porušují předpoklad nezávislých a identicky rozdělených pozorování ($I.I.D.$). Standardní K-Fold křížová validace (náhodné míchání dat) způsobuje masivní únik informací z budoucnosti do minulosti (*Lookahead Leakage*).
   - **Purging (Očištění překryvu):**
     Pokud trénovací vzorek $i$ má predikční horizont končící v čase $t_{i, \text{end}}$, a testovací vzorek $j$ začíná v čase $t_{j, \text{start}}$, musí platit:
     $$t_{i, \text{end}} < t_{j, \text{start}} \quad \text{a zároveň} \quad t_{j, \text{end}} < t_{i, \text{start}}$$
     Všechna trénovací pozorování, jejichž návratový horizont zasahuje do testovacího okna, jsou z trénovací množiny nemilosrdně vymazána (Purged).
   - **Embargo (Ochranná paměťová zóna):**
     Vzhledem k autoregresní paměti volatility (volatility clustering) je za každý testovací blok zařazena ochranná lhůta $\Delta_{\text{embargo}}$ (typicky 1–2 % délky datasetu), během níž se nesmí trénovat, aby se zamezilo přenosu stavu volatility.

2. **Dynamické bariérové značkování (Triple Barrier Method & Meta-Labeling):**
   - Běžná regrese budoucího výnosu za pevnou dobu $t+h$ nereflektuje realitu stop-lossů a take-profitů v tradingu.
   - **Triple Barrier Method:** Každé pozorování je označkováno podle toho, která ze 3 bariér je zasažena jako první:
     - Horní horizontální bariéra: $P_t + k \cdot \sigma_t$ (Take-Profit) $\implies +1$
     - Spodní horizontální bariéra: $P_t - k \cdot \sigma_t$ (Stop-Loss) $\implies -1$
     - Vertikální časová bariéra: $t + H$ (Expirace pozice v čase) $\implies \text{Sign}(R_{t+H})$
   - **Meta-Labeling (Dvoustupňové modelování):**
     Primární model (např. katalyzátory SuggestInvestu) predikuje směr (Long). Sekundární model strojového učení nepredikuje směr, ale **binární pravděpodobnost úspěchu** (zda primární model trefí Take-Profit dříve než Stop-Loss). Výstup sekundárního modelu řídí dimenzování pozice:
     $$\text{PositionSize} = f(P(\text{Success} \mid \text{MarketRegime}))$$

3. **Hierarchická parita rizika (Hierarchical Risk Parity - HRP) a Almgren-Chriss Impact:**
   - Markowitzova MPT vyžaduje inverzi kovarianční matice $\Sigma^{-1}$, což pro 541 aktiv vede k masivní amplifikaci šumu a nestabilitě vah ("Markowitz Curse").
   - **HRP algoritmus (López de Prado / SSRN 4422374):**
     1. *Stromové shlukování (Hierarchical Clustering):* Výpočet korelační vzdálenosti $d_{i,j} = \sqrt{\frac{1 - \rho_{i,j}}{2}}$ a sestavení dendrogramu.
     2. *Kvazi-diagonalizace:* Přerovnání kovarianční matice tak, aby nejvíce korelovaná aktiva ležela vedle sebe na diagonále.
     3. *Rekurzivní bisekce:* Shora dolů rozdělování kapitálu mezi větve stromu na bázi inverzní variance klastrů bez nutnosti invertovat celou matici.
   - **Almgren-Chriss Square-Root Law tržního dopadu:**
     $$\text{MarketImpact} \approx Y \cdot \sigma \cdot \sqrt{\frac{Q}{V}}$$
     kde $Q$ je velikost objednávky a $V$ denní obrat. Exaktně odůvodňuje zastropování účasti na $2\%$ denního obratu.

#### B. Integrace a přenositelnost do SuggestInvest
1. **Zpřesnění backtestovacího protokolu (Sekce 6.1 a 6.2):**
   - Všechny dosavadní i nově navržené katalyzátory (`CAT_VOLUME_SHOCK`, `CAT_SENTIMENT_DIVERGENCE`, `CAT_EARNINGS_ACCEL`) musí být validovány výhradně pomocí **Purged Walk-Forward křížové validace** s 14denním purge oknem.
2. **Robustní Z-skórování napříč 541 aktivy:**
   - Nahrazení standardní směrodatné odchylky v indikátorech robustním mediánem a mezikvartilovým rozpětím (IQR) eliminuje zkreslení žebříčků satelitními akciemi (Tier 3), které zažívají anomální jednodenní skoky.
3. **Dvoustupňový filtr (Meta-Labeling analog):**
   - Kvantitativní pravidla detekují kandidáty s fundamentálními a technickými katalyzátory.
   - Google Gemini AI Head of Risk v roli "Meta-Labeleru" ohodnotí kontext, identifikuje rizika a určí finální Conviction Score ($0–100\%$), které řídí velikost pozice.

#### C. Kvantitativní evaluace a technické limity (Realizovatelnost vs. Dopad)

| Kritérium | Skóre | Technické limity a analytické odůvodnění |
| :--- | :---: | :--- |
| **Realizovatelnost (Purged CV, Robust Scaling, Triple Barrier a HRP v SuggestInvestu)** | **9.5 / 10** | **Plná a okamžitá kompatibilita s CI/CD stackem:**<br>1. Výpočet robustního škálování (Median/IQR), purge oken a Almgren-Chriss limitů v `pandas`/`numpy`/`scipy` zabere pro všech 541 aktiv **< 0.3 sekundy**.<br>2. HRP alokace běží deterministicky v milisekundách a na rozdíl od kvadratického programování MPT nikdy neselže na singulární matici.<br>3. Žádné dodatečné hardwarové nároky na RAM ani GPU. |
| **Dopad na přesnost predikcí a eliminaci overfittingu (Validation & Execution Alpha)** | **9.0 / 10** | **Nejvyšší metodologický přínos pro dlouhodobé přežití systému:**<br>1. *Eliminace sebeklamu:* Očistěná křížová validace zamezí nasazení strategií, které vykazují skvělé výsledky v backtestu pouze díky informačním únikům (lookahead leakage).<br>2. *Ochrana před tržním dopadem:* Zastropování pozic dle Almgren-Chriss modelu garantuje, že papírový zisk nebude smazán slippage při reálné exekuci na XTB. |

#### D. Strategické architektonické rozhodnutí (Verdikt)
- ✅ **PLNĚ SCHVÁLENO K IMPLEMENTACI JAKO ZÁKLADNÍ METODOLOGICKÝ STANDARD:**
  1. **Purged Walk-Forward Engine v Sekci 6.2:** Zavedení 14denního purge okna pro veškeré backtesty katalyzátorů.
  2. **Robustní Median/IQR normalizace v Sekci 2.1:** Standardizace všech skóre katalyzátorů přes mezikvartilové rozpětí.
  3. **Hierarchická alokace rizik (HRP v Sekci 5.2):** Rekurzivní alokace kapitálu napříč koši Core, Mid a Satellites s Almgren-Chriss limitem $2\%$ obratu.

### 4.6 Pravděpodobnostní trajektorie cen a mikrostrukturální fúze nákup/prodej (OrderFusion+ modul)
- **Teoretická báze:** `SRC-3: OrderFusion+ (Probabilistic Buy–Sell Price Trajectory Forecasting in Intraday Electricity Markets, arXiv:2609.23598v1, 2026)`
- **Role v architektuře:** Modelování asymetrických interakcí mezi nákupní a prodejní stranou knihy objednávek (Orderbook Microstructure), dynamická adaptace historického okna (Dynamic Lookback Masking) a predikce celých pravděpodobnostních trajektorií cen ve formě kvantilových pásem $[Q_{0.1}, Q_{0.5}, Q_{0.9}]$ pro optimální limitní vstupy a řízení slippage.

#### A. Matematický a architektonický aparát (Formalizace dle arXiv:2609.23598v1)
1. **Dvojstranná tenzorová reprezentace a přechod od skalárních indexů k trajektoriím:**
   - Standardní modely komprimují časové okno do jednoho skalárního indexu (např. denní Close nebo VWAP), čímž zcela zahazují vnitřní dynamiku a rozdíly mezi nákupní (Bid) a prodejní (Ask) stranou.
   - Vstupem pro vzorek $i$ je tenzor pro každou stranu trhu $s \in \{+, -\}$:
     $$X_i^{(s)} \in \mathbb{R}^{T \times P \times F_o}$$
     kde $T = 180\text{ minut}$ (historické časové kroky po 15 min), $P = 12$ (počet sousedních/provázaných kontraktů či sektorových peers) a $F_o = 4$ (cena, realizovaný objem, časová pozice, relativní pozice instrumentu).
   - Vstup je doplněn o cyklické kalendářní příznaky $X_i^c \in \mathbb{R}^{F_c}$ (čtvrthodina $q_i \in \{0,\dots,95\}$, den v týdnu $d_i \in \{0,\dots,6\}$, měsíc $m_i \in \{0,\dots,11\}$ kódované pomocí $\sin/\cos$ projekce a indikátor svátků $h_i$).
   - Cílem predikce není skalár, nýbrž budoucí pravděpodobnostní vektor trajektorie:
     $$\widehat{\mathbf{Y}}_i^{(s)} \in \mathbb{R}^{L \times Q}$$
     kde $L$ je délka predikčního horizontu (např. 12 kroků po 15 min = 180 min) a $Q$ je počet kvantilů ($\mathcal{Q} = \{0.1, 0.5, 0.9\}$).

2. **Asymetrická Buy–Sell křížová pozornost (Cross-Attention Fusion):**
   - Vstupní tenzory jsou nejprve promítnuty konvoluční vrstvou $1 \times 1$ do skryté dimenze $H = 36$:
     $$\widetilde{X}_i^{(+)} = \mathcal{F}_{\text{conv}}^{(+)}(X_i^{(+)}), \quad \widetilde{X}_i^{(-)} = \mathcal{F}_{\text{conv}}^{(-)}(X_i^{(-)}) \in \mathbb{R}^{T \times P \times H}$$
   - Nákupní a prodejní strana se vzájemně podmiňují asymetrickou křížovou pozorností, kde jedna strana tvoří Query a druhá Key/Value:
     $$\mathbf{Q}_i^{(s)} = \widetilde{X}_i^{(s)} W_Q^{(s)}, \quad \mathbf{K}_i^{(\bar{s})} = \widetilde{X}_i^{(\bar{s})} W_K^{(\bar{s})}, \quad \mathbf{V}_i^{(\bar{s})} = \widetilde{X}_i^{(\bar{s})} W_V^{(\bar{s})}$$
     $$\mathbf{C}_i^{(s)} = \text{Softmax}\left(\frac{\mathbf{Q}_i^{(s)} (\mathbf{K}_i^{(\bar{s})})^\top}{\sqrt{d}}\right) \mathbf{V}_i^{(\bar{s})} \in \mathbb{R}^{T \times P \times H}$$
     To umožňuje, aby nákupní reprezentace byla explicitně kontextualizována hloubkou a cenou nabídek prodávajících a naopak.

3. **Dynamické vzorkování masek (Dynamic Mask Sampling Layer):**
   - Model definuje banku 30 strukturovaných kandidátních masek $\mathcal{D} = \mathcal{W} \times \mathcal{N}$:
     - Historická okna: $\mathcal{W} \in \{15, 30, 60, 120, 180\}\text{ minut}$
     - Sousední produkty / sektoroví peers: $\mathcal{N} \in \{0, 1, 2, 4, 8, 12\}$
   - Model se během tréninku učí pravděpodobnostní rozdělení výběru masky pro každou stranu zvlášť:
     $$\boldsymbol{\pi}_i^{(+)} = \text{Softmax}\left(\mathcal{F}_{\text{dense}}^{(+)}(\mathbf{Z}_i)\right) \in [0, 1]^{30}, \quad \boldsymbol{\pi}_i^{(-)} = \text{Softmax}\left(\mathcal{F}_{\text{dense}}^{(-)}(\mathbf{Z}_i)\right) \in [0, 1]^{30}$$
   - **Dvouprůchodový mechanismus pozornosti (Two-Pass Attention):**
     1. První průchod spočte latentní reprezentaci s maskou chybějících hodnot $\mathbf{B}_i^{(s)}$ a vybere optimální masku $\mathbf{D}_i^{(s)}$.
     2. Druhý průchod přepočte křížovou pozornost s efektivní maskou $\mathbf{M}_i^{(s)} = \mathbf{B}_i^{(s)} \odot \mathbf{D}_i^{(s)}$. Obě fáze sdílejí váhy, model tedy nezvyšuje počet parametrů.
   - **Klíčový empirický objev autorů:** Jak se blíží okamžik realizace (od $-180$ min do $-60$ min), model dynamicky zkracuje optimální historické okno z 30 minut na 15 minut. Prediktivní informace se s blížící se exekucí koncentruje do nejčerstvějších transakcí a starší historie se stává šumem.

4. **Agregace a vícekvantilová ztrátová funkce (AQL Loss):**
   - Agregace normalizovaným průměrem přes platné pozice masky:
     $$\mathbf{U}_i^{(s)} = \frac{\sum_{t=1}^T \sum_{p=1}^P M_{i,t,p}^{(s)} \mathbf{C}_{i,t,p}^{(s)}}{\max\left(1, \sum_{t=1}^T \sum_{p=1}^P M_{i,t,p}^{(s)}\right)} \in \mathbb{R}^H$$
   - Sloučení s kalendářem: $\mathbf{Z}_i = \text{concat}(\mathbf{U}_i^{(+)}, \mathbf{U}_i^{(-)}, \widetilde{X}_i^c) \in \mathbb{R}^{3H}$.
   - Výstupní hlavy generují kvantily $\tau \in \{0.1, 0.5, 0.9\}$ minimalizací průměrné kvantilové ztráty (Average Quantile Loss - AQL):
     $$\mathcal{L}_{\text{AQL}} = \frac{1}{Q |\Omega|} \sum_{(i,s,l) \in \Omega} \sum_{\tau \in \mathcal{Q}} \rho_\tau\left(Y_{i,l}^{(s)} - \widehat{Y}_{i,l,\tau}^{(s)}\right)$$
     kde $\rho_\tau(e) = \max(\tau e, (\tau - 1) e)$ je asymetrická pinball loss funkce.

#### B. Empirické výsledky paperu & Benchmark vůči Foundation modelům
- **Testováno na německém intradenním trhu (EPEX SPOT 2024, kontinuální anonymní kniha objednávek).**
- **Porovnání s Foundation modely (TimesFM 3.0, Chronos 2.0, TabPFN-TS, Moirai 2.0):**
  - Obecné foundation modely trénované na stovkách gigabajtů obecných časových řad **nedokázaly v testech na mikrostruktuře knihy objednávek statisticky porazit ani prostý 30minutový baseline (`Persistence-2`)**!
  - Např. TimesFM 3.0 dosáhl AQL 14.85 a TabPFN-TS 12.05 s chybou krytí (AQCE) 8.62 %, zatímco prostý 30minutový VWAP dosáhl AQL 12.07 a krytí 0.33 %.
  - **Důvod:** Obecné základové modely postrádají strukturální apriorní znalost o specifické mikrostruktuře knihy objednávek (vztah Bid-Ask, hloubka trhu a časové krácení okna).
- **Výkonnost OrderFusion+:**
  - Dosáhl nejlepšího výsledku ve všech metrikách: $AQL = 10.62$, $MAE = 28.04$, $RMSE = 101.76$, $R^2 = 0.39$ a nulové křížení kvantilů ($AQCR = 0\%$).
  - Diebold-Mariano test potvrdil statistickou signifikanci ($p < 0.05$) vůči všem 12 konkurenčním modelům.
  - Extrémně kompaktní model: pouhých **35 892 až 41 124 parametrů** ($H=36$, 2 hlavy). Inference trvá **< 1 milisekundu**.

#### C. Integrace a přenositelnost do SuggestInvest
1. **Reálný stav dat v SuggestInvestu vs. L2 Orderbook:**
   - V SuggestInvestu sledujeme 541 akcií a ETF přes data z `yfinance` a brokerské API XTB.
   - **Nemáme k dispozici tick-by-tick Level 2 knihu objednávek (Orderbook depth).** Komerční L2 data pro 541 světových titulů stojí tisíce EUR měsíčně (např. v paperu uvedená cena za německou energii je €3 900/rok na jediný trh) a jejich zpracování v denním GitHub Actions běhu (limit 7 GB RAM a 5 minut) je technicky nemožné.
2. **Přenositelné principy OrderFusion+ pro SuggestInvest:**
   - **Princip 1: Kvantilová pásma exekuce $[Q_{0.1}, Q_{0.9}]$ namísto jedné bodové ceny:**
     Při generování signálu (např. po detekci katalyzátoru `CAT_EARNINGS_ACCEL` nebo `CAT_DIV_ARBITRAGE`) systém nesmí doporučit nákup za "tržní cenu" (Market Order), ale vygeneruje pravděpodobnostní nákupní pásmo. Limitní nákupní příkaz na XTB se umisťuje na hladinu $Q_{0.1}$ (spodní decil očekávané trajektorie), což eliminuje nákup na lokálním vrcholu a šetří 15–35 bps na spreadu.
   - **Princip 2: Dynamická adaptace historického okna (Dynamic Lookback Engine):**
     V klidném tržním režimu počítáme technické a fundamentální metriky z delšího okna (např. 20–50 dní). Jakmile LiMT detekuje objemový šok ($z_v > 2.0$) nebo skokové rozšíření volatility, systém automaticky stáhne lookback okno na 3–5 dní, protože starší data jsou v shock režimu irelevantním šumem.
   - **Princip 3: Sektorové přelévání vlivu (Neighboring Products analog):**
     Při predikci chování satelitních akcií (Tier 3) v daném odvětví využíváme jako "sousední produkty" chování lídrů z koše Core 60 (např. pohyb NVDA determinuje intradenní trajektorii menších polovodičových titulů).

#### D. Kvantitativní evaluace a technické limity (Realizovatelnost vs. Dopad)

| Kritérium | Skóre | Technické limity a analytické odůvodnění |
| :--- | :---: | :--- |
| **Realizovatelnost (Plný L2 Orderbook OrderFusion+ model)** | **2.0 / 10** | **Nepřekročitelné technické a finanční limity:**<br>1. *Náklady na data:* Level 2 orderbook ticková data pro 541 akcií v reálném čase jsou komerčně nedostupná pro retail/automatizovaný projekt (tisíce USD/měsíc).<br>2. *Infrastrukturní limit:* Desítky gigabytů tickových orderbook zpráv denně nelze ukládat ani procesovat v serverless GitHub Actions runneru.<br>3. *Zbytečná granularita:* Pro naše střednědobé katalyzátorové strategie (horizont 1–14 dní) je 15minutová orderbook fúze neadekvátně mikroskopická. |
| **Realizovatelnost (OrderFusion-Light: Kvantilová exekuční pásma v pandas/scipy)** | **9.0 / 10** | **Okamžitá proveditelnost bez dodatečných nákladů:**<br>1. Výpočet empirických kvantilových reziduí $[Q_{0.1}, Q_{0.5}, Q_{0.9}]$ pro stanovení limitních cen na bázi denního/hodinového ATR a bid-ask spreadu z XTB zabere **< 0.1 sekundy**.<br>2. Logika dynamického krácení okna (přepínání 20d $\to$ 5d při $z_v > 2.0$) je čistě pravidlová a běží okamžitě. |
| **Dopad na přesnost predikcí (Směrová selekce aktiv na dny/týdny)** | **5.0 / 10** | Model řeší mikrostrukturu a intradenní trajektorii v rámci hodin. Na to, zda akcie vyroste za 2 týdny díky akceleraci zisků, má orderbook minimální vliv. |
| **Dopad na přesnost exekuce a úsporu nákladů (Execution Alpha & Spread Capture)** | **8.0 / 10** | **Zásadní přínos pro vstupní ceny na XTB:**<br>1. Použití kvantilu $Q_{0.1}$ pro limitní nákup zabraňuje exekuci v tržním skluzu (slippage).<br>2. Znalost asymetrie mezi nákupním a prodejním tlakem poskytuje přesnější validaci, zda trh skutečně absorbuje prodejní tlak. |

#### E. Strategické architektonické rozhodnutí (Verdikt)
- ❌ **ZAMÍTNUTO (Full Neural L2 Orderbook Pipeline):** Nebudeme do SuggestInvestu zavádět infrastrukturu pro ticková data knihy objednávek ani trénovat PyTorch OrderFusion+ sítě pro 541 aktiv.
- ✅ **SCHVÁLENO K IMPLEMENTACI (OrderFusion-Light Execution Adapter):**
  1. **Kvantilová exekuční pásma pro XTB (Sekce 7.3):** Doporučení v UI i API nebudou uvádět pouze statickou cenu, ale nákupní interval:
     $$\text{LimitBuyTarget} = \text{Close}_t - 0.5 \times \text{ATR}_{14, t} \times \left(1 + \frac{\text{Spread}_i}{\text{Mid}_i}\right)$$
     což odpovídá empirickému kvantilu $Q_{0.1}$ očekávané trajektorie.
  2. **Dynamický přepínač periody (Dynamic Lookback Engine v sekci 2.1):** Automatické zkrácení SMA a RSI period při detekci objemového šoku z LiMT ($z_v > 2.0$).

### 4.7 Generativní difúzní modely implikované volatility a mezitržní dynamika rizika (Universal Diffusion IVS modul)
- **Teoretická báze:** `SRC-4: Universal Diffusion Models for Implied Volatility Surfaces: Learning Shared Dynamics Across Stocks (arXiv:2609.22893v1, ICAIF 2026, Mingzhi Yang, Sheng Wang, Chao Zhang, Ruikun Li – HKUST)`
- **Role v architektuře:** Modelování společné mezitržní dynamiky volatility a cenových výnosů, neparametrické generování mnohorozměrných scénářů tržního stresu, bezarbitrážní fyzikální regularizace (No-Arbitrage Physics Losses) a kalibrace dynamických rizikových měr (Value-at-Risk, Conditional VaR) pro ochranu kapitálu a sizing pozic.

#### A. Matematický a architektonický aparát (Formalizace dle arXiv:2609.22893v1)
1. **Diskrétní tenzorová reprezentace povrchu implikované volatility (IVS):**
   - Implikovaná volatilita opce je funkcí moneyness (poměru realizační ceny $K$ k podkladové ceně $S_t$: $m = K/S_t$) a doby do expirace $\tau$.
   - Definice logaritmického povrchu volatility:
     $$g_t(m, \tau) = \ln \sigma_t(m, \tau)$$
   - Diskrétní výpočetní mřížka $\mathcal{G} = \mathcal{M} \times \mathcal{T}$ zahrnuje:
     - 11 uzlů moneyness: $\mathcal{M} = \{0.6, 0.7, 0.8, 0.9, 0.95, 1.0, 1.05, 1.1, 1.2, 1.3, 1.4\}$
     - 9 uzlů expirací: $\mathcal{T} = \{1/252, 5/252, 21/252, 63/252, 126/252, 252/252, \dots\} \in [1\text{ den}, 1\text{ rok}]$
   - Celý denní stav povrchu je tenzor $g_t \in \mathbb{R}^{11 \times 9} = \mathbb{R}^{99}$.
   - Cílem modelu je simultánní generování mezidenního log-výnosu podkladové akcie $R_t = \ln(S_t / S_{t-1})$ a přírůstku celého povrchu volatility:
     $$x_0 = [R_t, \Delta g_t] \in \mathbb{R}^{100}, \quad \text{kde } \Delta g_t = g_t - g_{t-1} \in \mathbb{R}^{99}$$

2. **Univerzální podmiňující stav (Cross-Stock Universal Conditioning):**
   - Na rozdíl od klasických stock-specific modelů (kde se pro každou akcii kalibruje samostatný lokální Heston/SABR/SSVI model) zavádí autoři **jeden univerzální difúzní model** trénovaný na společném průřezu desítek akcií.
   - Vektor tržního stavu pro den $t$:
     $$c_t = [R_{t-1}, R_{t-2}, RV_{t-1}, g_{t-1}] \in \mathbb{R}^{102}$$
     kde $RV_{t-1} = \sqrt{\frac{252}{21} \sum_{k=1}^{21} R_{t-k}^2}$ představuje 21denní anualizovanou realizovanou volatilitu.
   - **Teoretický princip:** Sdílená dynamika volatility napříč trhem (např. reakce na makroekonomické šoky, skokové změny volatility, mean-reversion) má univerzální invariantní vlastnosti. Trénování jedné sítě na sdíleném vzorku chrání model před přetrénováním na individuálním šumu a umožňuje okamžitý transfer na nová aktiva bez nutnosti re-trénování.

3. **Architektura difúzního denoiseru (Conditional DDPM s FiLM modulací):**
   - Dopředný difúzní proces postupně přidává gaussovský šum v $K = 1000$ diskrétních krocích:
     $$q(x_k \mid x_0) = \mathcal{N}\left(x_k; \sqrt{\bar{\alpha}_k} x_0, (1 - \bar{\alpha}_k) \mathbf{I}\right), \quad \alpha_k = 1 - \beta_k, \quad \bar{\alpha}_k = \prod_{s=1}^k \alpha_s$$
   - Reverzní odšumovací proces aproximuje neurální síť $\epsilon_\theta(x_k, k, c_t)$:
     - Časový krok $k$ je zakódován pomocí sinusových bází do časového embeddingu $e(k) \in \mathbb{R}^{d_e}$.
     - Spojený vektor $[x_k, c_t] \in \mathbb{R}^{202}$ prochází sérií reziduálních MLP bloků s **FiLM (Feature-wise Linear Modulation)** vrstvami:
       $$\tilde{h}_\ell = (1 + \gamma_\ell) \odot \text{LayerNorm}(h_\ell) + \beta_\ell, \quad [\gamma_\ell, \beta_\ell] = W_\ell e(k)$$
     - FiLM modulace umožňuje síti dynamicky škálovat a posouvat aktivace v závislosti na tom, v jaké fázi difúzního odšumování se nachází.

4. **Fyzikální bezarbitrážní ztrátová funkce (Physics-Informed No-Arbitrage Losses):**
   - Čisté strojové učení generuje matematicky realistické povrchy, které však často porušují základní finanční axiomy (umožňují arbitráž zápornou cenou nebo zápornou hustotou pravděpodobnosti). Model proto integruje penalizace finanční fyziky:
     - **Kalendářní bezarbitrážnost (Calendar Spread Constraint):** Celková implikovaná variance $w(m, \tau) = \tau \sigma^2(m, \tau)$ musí být striktně neklesající funkcí doby do expirace $\tau$ ($\partial w / \partial \tau \ge 0$):
       $$\mathcal{L}_{\text{cal}} = \sum_{m \in \mathcal{M}} \sum_{j=1}^{|\mathcal{T}|-1} \max\left(0, - \frac{w(m, \tau_{j+1}) - w(m, \tau_j)}{\tau_{j+1} - \tau_j}\right)$$
     - **Motýlková bezarbitrážnost (Butterfly Spread / Convexity Constraint):** Dle Breeden-Litzenbergerovy věty musí být cena call opce konvexní funkcí realizační ceny, aby rizikově-neutrální hustota pravděpodobnosti nebyla záporná ($\partial^2 C / \partial K^2 \ge 0$):
       $$\mathcal{L}_{\text{but}} = \sum_{\tau \in \mathcal{T}} \sum_{i=2}^{|\mathcal{M}|-1} \max\left(0, - \left[ \frac{C(m_{i+1}, \tau) - C(m_i, \tau)}{m_{i+1} - m_i} - \frac{C(m_i, \tau) - C(m_{i-1}, \tau)}{m_i - m_{i-1}} \right]\right)$$
     - **Sobolevova regularizace hladkosti (Sobolev Smoothness):** Penalizace skokových nerealistických derivací povrchu:
       $$\mathcal{L}_{\text{smooth}} = \lambda_m \|\nabla_m g\|^2 + \lambda_\tau \|\nabla_\tau g\|^2$$
   - Celková optimalizační funkce:
     $$\mathcal{L}_{\text{total}} = \mathcal{L}_{\text{diff}} + \lambda_{\text{cal}} \mathcal{L}_{\text{cal}} + \lambda_{\text{but}} \mathcal{L}_{\text{but}} + \mathcal{L}_{\text{smooth}}$$
   - **Scenario Re-weighting:** Při generování $S = 1000$ syntetických scénářů budoucího dne je aplikováno exponenciální převážení s penalizací zbývajících lokálních arbitráží s faktorem $\beta = 50$, což garantuje 100% fyzikální validitu vygenerovaných scénářů.

#### B. Empirické výsledky paperu & Porovnání modelů
- **Datový soubor:** Opční povrchy 100 velkých US titulů z indexu S&P 500 za období 2015–2023. Trénovací množina tvořila 50 akcií, testovací out-of-sample množina zbývajících 50 akcií.
- **Klíčové zjištění autorů:**
  - **Univerzální model porazil stock-specific modely:** Trénování jedné sdílené difúzní sítě dosáhlo nižší chyby generování povrchu (RMSE 0.0182 vs. 0.0241) a věrněji replikovalo empirické stylizované fakty volatility (volatility clustering, leverage effect – asymetrický nárůst volatility při poklesu ceny, fat tails).
  - **Dramatické potlačení arbitráží:** Fyzikální penalizace snížily míru kalendářních a motýlkových arbitráží ve vygenerovaných površích o **98.4 %** oproti standardnímu DDPM bez fyzikálních losses.
  - **Věrnost sdruženého rozdělení:** Model zachovává přesnou nelineární korelaci mezi denním výnosem akcie a změnou volatility ($\text{Corr}(R_t, \Delta g_t(1.0, 1M)) \approx -0.68$).

#### C. Integrace a přenositelnost do SuggestInvest
1. **Reálná datová omezení SuggestInvestu vs. Plné opční povrchy:**
   - Sledujeme 541 akcií a ETF (napříč USA, Evropou a rozvíjejícími se trhy).
   - Bezplatné rozhraní `yfinance` **neposkytuje historické tenzory povrchu implikované volatility $11 \times 9$ pro 541 titulů**. Stahování živých opčních řetězců z Yahoo Finance pro 541 aktiv by vyžadovalo desítky tisíc API dotazů denně, což by vedlo k okamžitému zablokování IP adresy (HTTP 429 Rate Limit) a překročení paměťových a časových limitů.
   - XTB API nabízí primárně CFD, akcie a ETF, nikoliv přímé Level 2 opční řetězce se všemi strikes a expiracemi.
2. **Přenositelné principy SRC-4 pro SuggestInvest (Diffusion-IVS-Light):**
   - **Princip 1: Sdružený stavový vektor volatility (Volatility Regime State $c_t$):**
     Místo sledování izolovaného indikátoru počítáme pro každou akcii unifikovaný stavový vektor:
     $$c_t = [R_{t-1}, R_{t-2}, RV_{21, t}, \text{ATR-Ratio}_t, \text{VIX}_t]$$
     který reprezentuje aktuální režim tržního napětí a averze k riziku.
   - **Princip 2: Dvourozměrné scénářové zátěžové testování (Joint Return-Volatility Stress Scenarios):**
     Při alokaci kapitálu a stanovení Stop-Lossu negenerujeme pouze statickou odchylku, ale simulujeme sdružený scénář: jak hluboko propadne cena, pokud dojde ke skokovému nárůstu volatility (Leverage Effect). Kvantily těchto scénářů determinují přesnou hladinu zneplatnění teze (Invalidation Point).
   - **Princip 3: Univerzální mezitržní transfer volatility (Cross-Stock Volatility Transfer):**
     U méně likvidních satelitních akcií z Tier 2 a Tier 3 (kde nejsou dostupné opce) odvozujeme volatilitní režim a očekávaný rozptyl z lídrů odvětví a sektorových ETF (např. volatilita polovodičových satelitů je škálována přes sdruženou dynamiku NVDA a SMH).

#### D. Kvantitativní evaluace a technické limity (Realizovatelnost vs. Dopad)

| Kritérium | Skóre | Technické limity a analytické odůvodnění |
| :--- | :---: | :--- |
| **Realizovatelnost (Plný 1000krokový Universal Diffusion DDPM model pro 541 IVS)** | **2.5 / 10** | **Nepřekročitelné technické a infrastrukturní limity:**<br>1. *Datová bariéra:* Bezplatný Yahoo Finance feed neposkytuje historické 99-dimenzionální povrchy volatility pro 541 světových titulů. Komerční databáze (např. OptionMetrics) stojí desítky tisíc USD.<br>2. *Výpočetní inferenční limit:* Vzorkování 1000 difúzních kroků reverzního procesu pro 1000 scénářů pro 541 akcií vyžaduje dedikované CUDA GPU. V našem GitHub Actions runneru (2 vCPU, bez GPU, 7 GB RAM a 5 minut celkového běhu) by takový výpočet trval několik hodin.<br>3. *Komplexita tréninku:* Trénování DDPM s FiLM modulací a fyzikálními ztrátami vyžaduje desítky hodin na GPU klastru. |
| **Realizovatelnost (Diffusion-IVS-Light: Kovarianční režimové vektorování a parametrické Monte Carlo scénáře)** | **8.5 / 10** | **Plná okamžitá proveditelnost v produkčním běhu:**<br>1. Výpočet stavového vektoru $c_t$ (výnosy, $RV_{21}$, ATR poměr vůči mediánu a sektorová proxy volatilita) v `pandas`/`numpy` trvá pro všech 541 aktiv **< 1.2 sekundy**.<br>2. Generování 500 parametrických scénářů sdruženého rozdělení pro odhad $VaR_{99\%}$ a $CVaR_{99\%}$ přes Choleského dekompozici kovarianční matice trvá **< 3 sekundy** na standardním 2vCPU runneru.<br>3. Nulové dodatečné náklady na externí API. |
| **Dopad na přesnost predikcí (Směrová selekce ziskových titulů na horizontu dnů/týdnů)** | **5.5 / 10** | Modely implikované volatility modelují především rozptyl, nejistotu a riziko trhu, nikoliv směrový drift (alfa nadvýnos). Samotná IVS vám neřekne, zda akcie vyroste o 10 %, ale řekne vám, jak extrémní může být její pohyb na obě strany. |
| **Dopad na řízení rizik, dimenzování pozic a ochranu kapitálu (Tail-Risk & Dynamic VaR)** | **8.5 / 10** | **Kritický přínos pro přežití portfolia a eliminaci hlubokých drawdownů:**<br>1. Modelování asymetrického vztahu mezi poklesem ceny a explozí volatility (Leverage Effect) zabraňuje držení plné velikosti pozice před volatilitním šokem.<br>2. Scénářové kvantily eliminují arbitrární fixní Stop-Lossy (např. statických -5 %) a nahrazují je vědecky podloženou hladinou zneplatnění teze (Invalidation Level) reflektující skutečnou volatilitní strukturu. |

#### E. Strategické architektonické rozhodnutí (Verdikt)
- ❌ **ZAMÍTNUTO (Full Neural DDPM 99-dim IVS Surface Pipeline):** Nebudeme do produkční serverless pipeline nasazovat hluboké difúzní neuronové sítě generující kompletní 99bodové opční povrchy z důvodu absence opčních dat a tvrdých hardwarových limitů GitHub Actions.
- ✅ **SCHVÁLENO K IMPLEMENTACI (Diffusion-IVS-Light Volatility & Tail-Risk Engine):**
  1. **Stavový vektor volatility $c_t$ v Sekci 2.1:** Implementovat výpočet 21denní realizované volatility $RV_{21}$, ATR normalizovaného šoku a sektorového přenosu volatility.
  2. **Scénářové dimenzování pozic v Sekci 5.3 (Tail-Risk Sizing):** Dynamická úprava Stop-Lossů a velikosti pozic na základě sdruženého zátěžového scénáře výnos–volatilita:
     $$\text{StopLossLevel}_i = \text{EntryPrice}_i \times \left(1 - \max\left(1.5 \times \text{ATR}_{14, i}\%,\, 2.33 \times RV_{21, i} \cdot \sqrt{\frac{5}{252}}\right)\right)$$
     což odpovídá $99\%$ parametrickému scénáři na 5denním horizontu.

---

## 5. Modul pro řízení rizik, likvidity a alokaci portfolia

### 5.1 Modelování tržního dopadu a likviditní omezení
- **Struktura slotu:**
  - Slippage modelování, spread penalties a odhad maximální kapacity pozice
  - Dynamické odmítnutí signálů při vyschnutí likvidity
- **Implementovaná metodika LiMT-APO (ze zdroje SRC-2):**
  - **Zastropování pozice obratem (Turnover Participation Cap):**
    Žádné doporučení nesmí alokovat pozici přesahující $\alpha = 2\%$ očekávaného denního obratu aktiva:
    $$\text{MaxPositionSize}_i = \frac{0.02 \times (\text{Volume}_i \times \text{Close}_i)}{\text{PortfolioValue}}$$
  - **Inverzní penalizace brokerského spreadu (XTB Spread Drag Factor):**
    $$\text{SlippagePenalty}_i = \frac{1}{1 + \gamma \cdot \left(\frac{\text{Ask}_i - \text{Bid}_i}{\text{Mid}_i}\right)}, \quad \gamma = 50.0$$
    Pro spready $> 0.30\%$ dochází k okamžité redukci váhy o více než $13\%$, pro spready $> 0.80\%$ k redukci o téměř $30\%$. Tituly se spreadem $> 1.0\%$ jsou z automatických signálů vyřazeny.
  - **Inverzně-volatilní vážení (Risk Parity Component):**
    $$w_i^\sigma \propto \frac{1}{\text{ATR}_{14, i} / \text{Close}_i}$$

### 5.2 Alokační engine & Optimalizace vah
- **Struktura slotu:**
  - Dynamické dimenzování pozic (Kellyho kritérium, Hierarchical Risk Parity, Volatility Targeting)
  - Vektorová alokace s ohledem na korelaci napříč koši (TOP, MID, LOW)
- **Implementovaná metodika Hierarchical Risk Parity (HRP dle SRC-7):**
  - **Stromové shlukování aktiv (Dendrogram Clustering):**
    Výpočet matice korelačních vzdáleností $d_{i,j} = \sqrt{\frac{1 - \rho_{i,j}}{2}}$ napříč aktivy s aktivním signálem.
  - **Kvazi-diagonalizace a rekurzivní bisekce:**
    Kapitál je alokován shora dolů mezi stabilní klastry bez nutnosti invertovat nestabilní kovarianční matici $\Sigma^{-1}$, což eliminuje Markowitzovo zkreslení extrémních vah.
  - **Syntetická integrace Almgren-Chriss limitu:**
    Každá vypočtená váha z HRP je finálně oříznuta pravidlem:
    $$w_i^{\text{final}} = \min\left(w_i^{\text{HRP}},\, \frac{0.02 \times \text{Turnover}_i}{\text{PortfolioValue}}\right)$$

### 5.3 Ochrana kapitálu a krizové protokoly (Capital Preservation)
- **Struktura slotu:**
  - Maximální povolený drawdown na úrovni portfolia i jednotlivého aktiva
  - Dynamické Stop-Loss a Trailing-Stop úrovně na bázi volatility (ATR / Invalidation price)
  - Circuit breakers při anomální korelaci trhu
- **Implementovaná metodika Diffusion-IVS-Light (ze zdroje SRC-4):**
  - **Dynamická hladina zneplatnění teze (Scenario-Driven Invalidation Level):**
    Stop-Loss není fixní procento, nýbrž dynamický kvantil sdruženého rozdělení výnos-volatilita:
    $$\text{StopLossLevel}_i = \text{EntryPrice}_i \times \left(1 - \max\left(1.5 \times \frac{\text{ATR}_{14, i}}{\text{Close}_i},\, 2.33 \times RV_{21, i} \sqrt{\frac{5}{252}}\right)\right)$$
  - **Sektorový přeliv volatility (Cross-Stock Volatility Proxy):**
    U Tier 2 a Tier 3 aktiv bez likvidních opcí je $RV_{21}$ korigována beta-koeficientem vůči sektorovému proxy ETF (např. SMH, XLK, XLE), aby se zabránilo podcenění rizika v obdobích sektorové turbulence.
  - **Volatilitní de-leveraging (Volatility Shock Circuit Breaker):**
    Pokud $RV_{21, i}$ vzroste o více než 100 % vůči svému 60dennímu klouzavému průměru, pozice je automaticky redukována na polovinu bez ohledu na fundamentální rating.

---

## 6. Backtesting, validace & Walk-Forward analýza

### 6.1 Backtestingový engine
- **Struktura slotu:**
  - Kauzální simulátor exekuce se započtením transakčních nákladů a zpoždění (latency)
  - Zamezení lookahead bias a survivorship bias
- *Slot pro budoucí logiku:*
  <!-- FORMULACE VÝPOČETNÍHO SIMULÁTORU -->

### 6.2 Validační standardy a robustnost
- **Struktura slotu:**
  - Walk-forward optimalizace s out-of-sample testováním
  - Monte Carlo perturbace parametrů pro ověření odolnosti vůči přeučení
- **Implementovaná metodika Purged Walk-Forward (dle SRC-7):**
  - **Purge Window Buffer:** Všechny překrývající se dopředné výnosy (pro $H=14\text{ dní}$) jsou mezi trénovací a testovací množinou striktně odstraněny ($t_{i,\text{end}} < t_{j,\text{start}} - 14\text{ dní}$).
  - **Embargo Buffer:** Aplikace 5denního embarga za každým testovacím oknem pro zamezení přenosu klastrované volatility.
  - **Walk-Forward Rolling Splits:** Klouzavé testování po 6měsíčních cyklech s přeučením pouze na historických datech.

### 6.3 Metriky výkonnosti a rizika
- **Struktura sledovaných ukazatelů:**
  - Sharpe Ratio, Sortino Ratio, Calmar Ratio
  - Maximum Drawdown (MDD) a doba zotavení (Recovery Time)
  - Profit Factor, Win-Loss Ratio, Information Ratio
- *Slot pro budoucí logiku:*
  <!-- MATEMATICKÉ DEFINICE METRIK -->

---

## 7. Integrační, prezentační & Exekuční vrstva

### 7.1 Automatizovaný export do Excel modelů
- **Struktura slotu:**
  - Generování dynamických tabulek, analytických rozpadů a vizuálních scorecardů přes `pandas` a `openpyxl`
  - Automatické formátování, heatmapy a podklady pro fundamentální evaluaci
- *Slot pro budoucí logiku:*
  <!-- ŠABLONA DATOVÝCH EXPORTŮ PRO INVESTIČNÍ KOMITÉT -->

### 7.2 Webové rozhraní & Interaktivní dashboard
- **Struktura slotu:**
  - Prezentace signálů, metrik jistoty a předstihových katalyzátorů (aktuální frontend `SuggestInvest`)
  - Interaktivní filtrace a monitoring mezidenních změn (Daily Delta Tracker)
- *Slot pro budoucí logiku:*
  <!-- NAPOJENÍ NOVÝCH MODELŮ DO EXISTUJÍCÍHO UI -->

### 7.3 API integrace a exekuce
- **Struktura slotu:**
  - Obousměrná komunikace s brokerskými API (XTB, IBKR)
  - Generování a validace objednávek (Order Management System - OMS)
- *Slot pro budoucí logiku:*
  <!-- NÁVRH ADAPTÉRU PRO BROKERSKÁ API -->

---

## 8. Plán realizace (Phased Execution Protocol)

- [x] **Fáze 1:** Inicializace a vytvoření Masterplanu (Architektonická osnova a zakotvení v metodice SuggestInvest)
- [x] **Fáze 2:** Postupné prostudování a plnění faktů z externích zdrojů:
  - [x] **SRC-1 (HARN):** Analýza teoretického aparátu, integrace do SuggestInvestu a evaluace škál (Hotovo)
  - [x] **SRC-2 (LiMT):** Multi-task učení s likviditou a APO alokační filtr (Hotovo)
  - [x] **SRC-3 (OrderFusion+):** Kvantilové trajektorie cen a dynamické maskování historie (Hotovo)
  - [x] **SRC-4 (Universal Diffusion IVS):** Generativní difúzní modely volatility, sdílená dynamika a scénářový tail-risk (Hotovo)
  - [x] **SRC-5 (AI a NLP Trading - DSpace UK 120426710):** FinBERT vs TweetEval sentiment, DDQN Deep RL a limity transakčních nákladů (Hotovo)
  - [x] **SRC-6 (Pairs Trading & Kointegrace - DSpace UK 130215669):** Statistická arbitráž, testování kointegrace a mean-reversion (Hotovo)
  - [x] **SRC-7 (Decoding the Quant Market - SSRN 4422374):** Metodologie kvantitativního tradingu, feature engineering, purged CV a risk management (Hotovo)
- [x] **FÁZE 2 DOKONČENA (Všech 7 výzkumných zdrojů plně prostudováno, formalizováno a evaluováno)**
- [x] **Fáze 3:** Architektonická implementace vybraných modulů a začlenění do produkčního jádra SuggestInvest:
  - [x] **Vektorové in-memory výpočty (`fundamentals_fetcher.py`):** Realizovaná roční volatilita $RV_{21}$, $ATR_{14}$, objemový šok $z_v$, pásmo limitního nákupu $Q_{0.10}$ a 2% APO obratový strop bez dodatečných API volání (0.2s běh na 541 aktivech).
  - [x] **Pravidlový spouštěcí aparát (`trigger_engine.py`):** Integrace 3 nových tržních katalyzátorů (`CAT_VOLUME_SHOCK`, `CAT_SENTIMENT_DIVERGENCE`, `CAT_PAIRS_DISCOUNT`) a nahrazení statického Stop-Lossu adaptivním $VaR_{99\%}$ na bázi $RV_{21}$.
  - [x] **AI Syntéza a záložní model (`main.py`):** Rozšíření Head of Risk systémového promptu pro Gemini 3.5 AI, předávání quant metrik v dávkách a obohacení fallback screeneru.
  - [x] **Vizuální rozhraní (`template.html`):** Dynamické mikroodznaky nových katalyzátorů s jemnou animací a nový taktický blok *Kvantitativní exekuce (OrderFusion+ & LiMT)* v kontextovém detailu aktiva.
  - [x] **Formální aktualizace metodiky (`create_methodology_doc.py` $\to$ `Analyza_Dat_a_Metodika_SuggestInvest.docx`):** Vytvořena nová podrobná kapitola 6.10 dokumentující všech 7 výzkumných prací, matematické vzorce a praktický přínos pro investora.
- [x] **FÁZE 3 DOKONČENA (Plná implementace v kódu i v oficiální dokumentaci)**
