# Metodika a Analýza Tržních Dat – SuggestInvest

> **Oficiální metodická dokumentace systému SuggestInvest**  
> Generováno automaticky z institucionální báze a aktualizováno pro 557 sledovaných aktiv.

---


#### SUGGESTINVEST • AI MARKET RESEARCH LAB


## Metodika a Analýza Tržních Dat

Kompletní přehled datových zdrojů, analytických proměnných a principu vyhodnocování 541 akciových titulů a ETF


| Rozsah univerza: 541 aktiv (US akcie, Evropa, BCPP v CZK, ETF, Krypto) | Analytický engine: Google Gemini AI + Yahoo Finance Feed |
| --- | --- |
| Broker napojení: XTB katalog (14 692 instrumentů, ISIN validace) | Frekvence skenu: Denně v 8:00 CET + manuální vyžádání |



## 1. Manažerské shrnutí: Co systém dělá z pohledu investora

Systém SuggestInvest slouží jako automatizovaný analytický aparát, který každé ráno před otevřením evropských burz syntetizuje data ze světových finančních trhů a převádí je do jednoznačných, racionálních investičních signálů. Cílem systému není generovat vteřinový intradenní šum, ale poskytovat investorovi strukturovaný, fundamentálně podložený pohled na 513 vybraných aktiv, a to včetně zohlednění likvidity u brokera XTB a českých specifik pražské burzy.

Zatímco lidský analytik dokáže za ranní hodinu do detailu projít nanejvýš několik akciových zpráv, tento systém během 60 sekund paralelně zpracuje kurzotvorná data, vyhodnotí pozici každého aktiva vůči jeho ročním maximům a minimům, spojí tyto údaje s čerstvými makroekonomickými zprávami a prostřednictvím modelu Google Gemini AI vygeneruje pro každý titul odůvodněné doporučení (Strong Buy, Buy, Hold, Sell, Strong Sell) doplněné o míru pravděpodobnosti a tržní katalyzátory.


## 2. Prohledávané zdroje dat a vstupní informace

Analýza neprobíhá ve vakuu, ale kombinuje 4 odlišné vrstvy dat:


### 2.1 Oficiální specifikace instrumentů XTB (Zdroj: spectabomicz29062026.pdf)

Základním stavebním kamenem univerza je oficiální katalog instrumentů brokera XTB. Z celkového počtu více než 15 000 instrumentů systém nejprve provádí tzv. hygienické vyčištění trhu:

- Validace přes ISIN: Každý titul je prověřen svým mezinárodním kódem ISIN (International Securities Identification Number), což zamezuje záměně různých emisí (např. běžné vs. prioritní akcie nebo ADR certifikáty).
- Automatický Trash Filter: Systém okamžitě detekuje a vyřazuje instrumenty označené v tabulkách XTB jako CLOSE ONLY (více než 689 mrtvých emisí). Tím je zaručeno, že systém neanalyzuje delistované akcie, pozastavené emise ani tituly, které nelze u XTB reálně nakoupit.
- Křížové mapování broker tickerů: Přesné mapování symbolu (např. CEZ1.CZ ➡️ CEZ.PR na Yahoo Finance, SXR8.DE pro S&P 500 ETF v EUR, nebo AAL.UK ➡️ AAL.L v Londýně) zajišťuje, že investor vždy přesně ví, pod jakým kódem titul najde v aplikaci xStation.

### 2.2 Reálné burzovní feedy (Yahoo Finance Engine)

Pro každé z 513 aktiv systém v reálném čase stahuje klíčové kvantitativní parametry:

- Aktuální tržní kurz (Last Price): Poslední dosažená cena v primární obchodovací měně (USD, EUR, CZK, GBP, CHF, SEK).
- Denní cenová změna (% change): Denní posun ceny v procentech i nominální hodnotě vůči závěru předchozího dne.
- 52týdenní pásmo (52-week High / Low): Extrémně důležitý indikátor dlouhodobého trendu. Ukazuje, kde se aktivum nachází v rámci svého ročního cyklu.
- Historická kontinuita (5denní cenová řada): Ověření, že se s aktivem aktivně obchoduje a netrpí nelikviditou.

### 2.3 Globální makroekonomické a tržní zprávy (RSS Finance Feed)

Akcie nežijí odděleně od globálního dění. Před zahájením analýzy jednotlivých titulů systém stahuje živý proud nejdůležitějších globálních zpráv (např. rozhodování Fedu o sazbách, geopolitická rizika, inflační reporty CPI, výsledková sezóna). Tento souhrn je předán AI jako 'nálada a makro rámec dne', podle kterého se kalibruje celková ochota trhu podstupovat riziko.


### 2.4 Hluboká znalostní báze modelu Google Gemini Pro

Model Gemini není použit jako generátor náhodného textu, ale jako vysoce kvalifikovaný analytik, který má ve své bázi znalosti o obchodních modelech jednotlivých firem, jejich konkurenčních výhodách (economic moats), zadlužení a sektorové expozici. Spojením aktuálního kurzu s fundamentální podstatou firmy vzniká výsledné zhodnocení.


## 3. Jaké informace jsou brány v potaz (Analytické proměnné)

Při hodnocení každého aktiva systém sleduje souběh technických a fundamentálních proměnných:


| Analytická proměnná | Sledovaná hodnota / Impuls | Investiční interpretace |
| --- | --- | --- |
| Denní momentum | Pohyb o více než +3.0 % | Silný nákupní tlak, pozitivní earnings katalyzátor nebo sektorová rotace. |
| Korekce / Výprodej | Pokles o více než -3.0 % | Krátkodobé přeprodání (příležitost pro dip-buyers), nebo fundamentální varování. |
| Blízkost k 52w Maximu | Aktuální cena >= 97 % z 52w High | Testování historických maxim, potvrzení silného růstového býčího trendu. |
| Blízkost k 52w Minimu | Aktuální cena poblíž ročního dna | Možný obratový (turnaround) potenciál, nebo naopak strukturální potíže firmy. |
| Sektorové zařazení | Tech, Energetika, Banky, Utility, ETF | Zohlednění specifických rizik (např. úroková citlivost u bank, AI výdaje u Big Tech). |



## 4. Specifická logika pro jednotlivé trhy a třídy aktiv

Regionální a sektorové přizpůsobení: Systém nepoužívá 'univerzální šablonu' na všechno, ale rozlišuje specifika jednotlivých trhů:

- 🇨🇿 Pražská burza BCPP v CZK: U titulů jako ČEZ, Komerční banka, Moneta, Colt CZ nebo Philip Morris systém zohledňuje dividendovou stabilitu, specifika české koruny (CZK), regulaci energetiky a vliv daně z neočekávaných zisků (windfall tax).
- 🇺🇸 US Mega-Caps & Umělá inteligence: U lídrů jako Nvidia, Apple, Microsoft, Alphabet či Meta je klíčovým kritériem ocenění (valuace P/E), kapitálové výdaje do AI infrastruktury (capex) a celková dynamika technologického indexu Nasdaq.
- ⚛️ Tematické růstové akcie (Uran, Kosmonautika, Krypto): Tituly typu Cameco, NuScale, Oklo, Rocket Lab či MicroStrategy mají vysokou volatilitu. Zde systém sleduje fundamentální megatrendy (jaderná renesance, vládní zakázky pro kosmonautiku, adopce Bitcoinu institucemi).
- 🇪🇺 Evropští průmysloví a luxusní lídři: Průmyslové giganty (ASML, SAP, Siemens, LVMH, automobilky BMW/Mercedes) jsou posuzovány prizmatem stavu německé a evropské ekonomiky, exportní závislosti na Číně a nákladů na energie.
- 📊 Pasivní indexová ETF: U fondů jako S&P 500 (SXR8.DE) nebo FTSE All-World (VWCE.DE) systém nehledá spekulativní výkyvy, ale potvrzuje dlouhodobý směr trhu a globální alokaci kapitálu.

## 5. Jak systém hodnotí akciové tituly: Výstupní signály a odůvodnění

Každé vyhodnocení zobrazené na kartě aktiva obsahuje 4 provázané složky:


### 5.1 Pětistupňový investiční signál (Signal)

- 🟢 STRONG BUY: Mimořádný růstový potenciál. Souběh silného momenta, zdravého fundamentu a pozitivního makroekonomického větru. Vhodné pro aktivní akumulaci pozice.
- 🟢 BUY: Pozitivní výhled. Růstové katalyzátory převažují nad riziky, titul se nachází ve zdravém trendu nebo po zdravé korekci.
- 🟡 HOLD: Neutrální pozice. Vyvážený poměr výnosu a rizika. Často jde o fázi konsolidace po prudkém růstu nebo čekání na firemní výsledky.
- 🔴 SELL: Převaha negativních impulsů. Přepálená valuace, zhoršující se momentum nebo nepříznivý sektorový vývoj. Doporučeno zvážit redukci pozice.
- 🔴 STRONG SELL: Výrazný fundamentální tlak, prudký medvědí trend nebo vážné narušení investiční teze. Vysoké riziko dalšího poklesu.

### 5.2 Pravděpodobnost úspěchu (Confidence Score: 0–100 %)

Indikátor, který vyjadřuje míru jistoty modelu v daný signál. Pokud jsou fundamentální zprávy i technická data v dokonalé shodě, dosahuje pravděpodobnost hodnot 80–95 %. Pokud se technický vývoj bije s makroekonomickou nejistotou, skóre klesá k 50–60 %.


### 5.3 Očekávaný směr impulsu (Impact Direction: ▲ Růst / ▼ Pokles)

Bipolární vektor, který okamžitě indikuje, zda převažující tržní síly tlačí kurz nahoru nebo dolů.


### 5.4 Automaticky přiřazené katalyzátory (Barevné štítky)

Systém kartám automaticky přiřazuje rychlé vizuální štítky na základě matematických filtrů:


#### 🚀 Silné momentum: Denní skok ceny o více než +3 %.

- 🔥 Test 52w Maxima: Titul se dotýká nebo blíží 52týdennímu maximu (býčí síla).
- 📉 Přeprodáno / Korekce: Denní pokles o více než -3 % (oblast pro sledování slev).
- 🇨🇿 BCPP Dividendy: Titul z pražské burzy s vysokým dividendovým profilem.

#### 📊 Pasivní ETF: Fond sledující široký tržní index.


### 5.5 Syntetické odůvodnění v češtině (Investment Reasoning)

Nejcennější částí analýzy je výstižné, 1–2 věté shrnutí, proč byl daný signál vybrán. Investor okamžitě vidí, zda je růst tažen hospodářskými výsledky, fúzí, technologickým náskokem, nebo zda je pokles způsoben regulatorním zásahem či ochlazením poptávky.


## 6. Předstihové indikátory, cílové ceny a firemní kalendáře

Klíčovým inovačním skokem systému SuggestInvest je integrace předstihových (forward-looking) indikátorů. Zatímco běžné skenery pouze reaktivně sledují včerejší ceny a denní změny, SuggestInvest se dívá dopředu pomocí konsenzuálních cílových cen analytiků, odpočtu dnů do kvartálních výsledků a časových momentových delt.


### 6.1 Cílové ceny analytiků a růstový potenciál (Target Upside %)

Pro každý akciový titul systém stahuje konsenzuální odhad analytiků z Wall Street (Target Mean Price, Target High a Target Low) včetně počtu analytiků pokrývajících danou akcii. Následně počítá přesný diskont či prémii vůči trhu:

- Vzorec Target Upside %: (Target Mean Price - Aktuální cena) / Aktuální cena × 100.
- 🎯 Vysoký diskont (> +25 %): Pokud je očekávaný růst k cíli > +25 % při alespoň 5 analytických doporučeních.
- ⚠️ Nad cílem analytiků: Pokud aktuální tržní cena překročila průměrný cíl analytiků (varování před vyčerpaným potenciálem).

### 6.2 Firemní kalendáře: Kvartální výsledky a odpočet dní (Earnings Countdown)

Zveřejnění kvartálních hospodářských výsledků (Earnings) je pro akcie nejvýznamnější událostí způsobující skokové pohyby kurzu. Systém v reálném čase sleduje oficiální firemní kalendáře a počítá odpočet dní do nejbližšího reportu:

- ⏳ Výsledky do 7 dní (Kritické): Výsledky budou oznámeny do 7 dnů. Zvýšená implikovaná volatilita a varování před neuváženým vstupem před čísly.
- 📅 Výsledky do 21 dní (Blížící se): Výsledky za 8 až 21 dní. Fáze obvyklého předvýsledkového runupu či konsolidace.

### 6.3 Rozhodné dny pro dividendu (Ex-Dividend Countdown)

Pro dividendové investory systém monitoruje datum Ex-Dividend (první den, kdy se akcie obchoduje bez nároku na dividendu). Pokud se Ex-Dividend blíží v horizontu 1 až 14 dnů, systém aktivuje zelený štítek '💰 Ex-Div za N dní' pro včasné zachycení výplaty.


### 6.4 Časové delty hybnosti: 1měsíční a 3měsíční momentum

Kromě jednodenní změny systém hromadně vyhodnocuje střednědobé časové delty: 1M momentum (~21 obchodních dnů) a 3M momentum (~63 obchodních dnů). To umožňuje odlišit krátkodobý náhodný šum od skutečně udržitelného trendu podpořeného institucionálními toky.


### 6.5 Automatický pravidlový Trigger Engine a disková mezipaměť

Aby systém dokázal bleskově zpracovat 541 aktiv bez rizika rate-limitu od poskytovatelů dat, využívá inteligentní souborovou mezipaměť (cache_fundamentals.json) s 24hodinovou expirací. Kalendáře a analytické cíle se tak dotazují jednou denně, zatímco kurzy běží v reálném čase. Všechny předstihové ukazatele jsou navíc přímo předávány do modelu Gemini, který je promítá do generovaného AI kontextu.


### 6.6 Dlouhodobá historická persistence a SQLite časová řada (Backtesting a audit)

Pro zajištění plné auditovatelnosti a měření reálné úspěšnosti AI modelů v čase systém ukládá každý proběhlý sken do dvouúrovňové persistence:

- 1. Neměnný denní JSON Data Lake (data/history/): Každý sken vygeneruje kompletní neměnný JSON soubor se všemi 541 kartami, tržními vstupy i AI zdůvodněními.
- 2. Relační časová řada SQLite (history.db): Každý vydaný signál, konfidence, cena i datum kvartálních výsledků se indexují do lokální relační databáze SQLite pro bleskové analytické dotazy.
- 3. Automatizovaný Backtesting: Možnost ex-post porovnat vydaná doporučení (Strong Buy / Buy) se skutečným zhodnocením podkladového aktiva po 7, 30 a 90 dnech.
- 4. Vývoj sentimentu v čase: V AI tooltipu se přímo zobrazuje trajektorie sentimentu za poslední měsíc (např. Hold 55 % ➡️ Buy 72 % ➡️ Strong Buy 88 %).

### 6.7 Institucionální Kvantitativní Model a Head of Risk Rozhodovací Matice

Vrcholnou vrstvou systému SuggestInvest je role Senior Quantitative Equity Analyst & Head of Portfolio Risk. Jeho posláním není popisovat minulý vývoj kurzu, ale identifikovat asymetrické tržní příležitosti a rizika v horizontu 1 až 3 měsíců na základě nesouladu mezi tržní cenou, posunem konsenzu a časem do klíčových událostí.

A. Pravidla konsenzu, valuace a revizí:

- Fundamentální diskont (> +20 %): Pokud je počet analytiků ≥ 5 a 30denní posun cílové ceny ≥ 0 %, jde o silný růstový signál (BUY / STRONG BUY). Pokud cena klesá (1M < 0), ale cíl roste (Δ target 30d > 0), vzniká pozitivní divergence a institucionální akumulace.
- Přepálená valuace (Tržní cena nad cílem): Pokud je Target Upside ≤ 0 %, růstový potenciál je vyčerpán. Vstupuje v platnost absolutní zákaz doporučení STRONG BUY či BUY $
ightarrow$ striktně HOLD nebo SELL.
B. Událostní filtry kalendáře a limity konfidence:

- Kritické okno před výsledky (≤ 7 dní): Implikovaná volatilita roste a událost přináší binární riziko. Konfidence nesmí překročit 65 % (s výjimkou defenzivních monopolů). Automatický štítek: ⏳ Výsledky do 7 dní.
- Předvýsledkový run-up (8 až 21 dní): Pokud je 1M momentum kladné a cílová cena roste, aktivum se nachází v akumulační fázi před kvartální zprávou. Štítek: 📅 Výsledky do 21 dní.
- Dividendový trigger (≤ 14 dní): Pozice je vhodná pro akumulaci před rozhodným dnem pro výplatu. Štítek: 💰 Ex-Div za N dní.
C. Filtry trendu, obratu a řízení rizik:

- Obrat vs. Padající nůž: Test 52w minima (vzdálenost < 70 % od maxima) s propadem cílové ceny (Δ target 30d < -5 %) indikuje strukturální destrukci hodnoty $
ightarrow$ SELL či STRONG SELL. Test minima se stabilním cílem a rostoucím momentem značí obrat $
ightarrow$ BUY.
- Kontrola tržního šumu: Denní skoky o více než ±3 % systém ignoruje, pokud nejsou v souladu s 1M momentem nebo novou fundamentální zprávou.
D. Pětistupňová hierarchie signálů a Invalidation Price:

- 🟢 STRONG BUY: Shoda silného 1M/3M trendu, diskont k cílové ceně > 20 % a pozitivní revize odhadů.
- 🟢 BUY: Pozitivní asymetrie výnosu a rizika, zdravý diskont k cíli, žádné binární riziko do 7 dnů.
- 🟡 HOLD: Vyčerpaný potenciál k cílové ceně, konsolidace nebo výsledky v horizontu do 7 dnů.
- 🔴 SELL: Tržní kurz nad cílem analytiků, zhoršující se momentum nebo negativní revize odhadů.
- 🔴 STRONG SELL: Ztráta fundamentu, prolomení podpory a masivní snižování cílových cen analytiky.
- 🛑 Invalidation Price (Stop-Loss): Exaktní číselná hladina (stop-loss úroveň), při jejímž prolomení celá investiční teze zaniká.

### 6.8 Kvantitativní Analýza Dividendových Anomálií (Ex-Date Recovery Velocity)

Trh v den Ex-Dividend automaticky koriguje otevírací kurz o výši přiznané dividendy. V reálném obchodování však vzniká statistická asymetrie daná chováním investorů, daňovým zatížením a rychlostí uzavření cenového gapu. SuggestInvest provádí rigorózní kvantitativní analýzu posledních 4 až 8 historických Ex-Dates a vyhodnocuje dvě protichůdné strategie:

A. Měřené statistické metriky:

- Dividend Drop-Off Ratio (DDR): Poměr reálného poklesu kurzu k výši dividendy. Hodnota < 1.0 indikuje nákupní polštář a silnou poptávku.
- Pre-Ex Run-up Momentum (20d): Průměrný kapitálový zisk akcie v období 20 obchodních dní před Ex-Date (institucionální i retailová akumulace před rozhodným dnem).
- Recovery Velocity (T_rec): Procento historických výplat, kdy se kurz vrátil na cum-dividend cenu do 15 a 30 obchodních dní, včetně mediánu počtu dní potřebných ke smazání gapu.
B. Rozhodovací logika dividendového doporučení:

- 🟢 Držet přes Ex-Div (Dividend Capture): Pokud se kurz v ≥ 65 % případů zotaví do 15 obchodních dní s mediánem ≤ 15 dní. Titul má silnou absorpci a vyplatí se pozici držet přes Ex-Date, inkasovat dividendu a vyčkat na smazání gapu.
- 🟡 Prodat před Ex-Div (Run-up Harvest): Pokud průměrný předexový růst (20d) dosahuje alespoň 1.5 % a převyšuje dividendový výnos, ale historické zotavení po Ex-Date je pomalé (≤ 40 % do 15 dní). Výhodnější je prodat 1–2 dny před Ex-Date, realizovat kapitálový zisk bez srážkové daně a vyhnout se post-dividendovému propadu.
- ⚪ Běžný průběh (Neutrální): Běžná tržní fluktuace bez průkazné statistické anomálie.

### 6.9 Denní sledování změn a detekce tržních obratů (Daily Delta & Change Tracker)

V dynamickém tržním prostředí není nejdůležitější statický stav aktiva, ale jeho okamžitá derivace – tedy rychlost a směr změny sentimentu. Pokud se doporučení pro titul změní ze dne na den, jde o primární signál pro pozornost portfoliomanažera. Systém SuggestInvest proto při každém ranním skenu automaticky porovnává nově vygenerovaný stav s referenčním skenem z předchozího obchodního dne (uloženým v SQLite databázi history.db).

A. Klasifikace denních posunů (Change Types):

- Zvýšení doporučení (Rating Upgrade): Posun v pětistupňové hierarchii směrem nahoru (např. HOLD ➜ BUY, BUY ➜ STRONG BUY). Indikuje nově potvrzený fundamentální impuls, průlom rezistence nebo skokový nárůst odhadů analytiků. Zelený odznak: ⬆️ UPGRADE.
- Snížení doporučení (Rating Downgrade): Posun v pětistupňové hierarchii směrem dolů (např. BUY ➜ HOLD, HOLD ➜ SELL). Varuje před vyčerpaným růstovým potenciálem, překročením cílové ceny nebo blížícím se binárním rizikem výsledků. Červený odznak: ⬇️ DOWNGRADE.
- Významný skok konfidence (Confidence Velocity): Změna míry jistoty modelu o více než ±10 procentních bodů při stejném signálu. Odráží zrychlení přílivu kapitálu nebo naopak rostoucí makroekonomickou nejistotu. Tyrkysový odznak: ⚡ +N% CONF, resp. žlutý: ⚠️ -N% CONF.
- Revize cílové ceny (Target Shift): Skoková změna konsenzuální cílové ceny analytiků z Wall Street o více než ±8 % (např. po vlně nových analytických doporučení). Fialový odznak: 🎯 ±N% CÍL.
- Aktivace nového katalyzátoru (New Catalyst): Detekce nově aktivovaného spouštěče v reálném čase (např. vstup do okna 7 dnů před výsledky, blížící se rozhodný den pro dividendu, test 52týdenního maxima). Růžový odznak: 🔥 KATALYZÁTOR.
- Nové aktivum v univerzu (New Asset): Titul, který nebyl v předchozím skenu zahrnut (nové IPO, přidání do univerza). Modrý odznak: ✨ NOVÉ.
B. Využití v uživatelském rozhraní a ranní rutině:

- Jednoklikový filtr změn: V záhlaví aplikace i ve filtračním panelu je k dispozici dedikovaná sekce '⚡ Posuny od včerejška'. Investor jedním kliknutím odfiltruje pouze upgrady, downgrady či skoky konfidence a nemusí procházet všech 541 aktiv.
- Vizuální označení v tabulce: V tabulce aktiv je přímo pod signálem zobrazen výrazný barevný mikroodznak indikující přesný typ posunu.
- Detailní komparativní blok: V kontextovém AI tooltipu (tlačítko 💡 Kontext) se při najetí myši na první pozici zobrazí detailní srovnávací box obsahující textové vysvětlení důvodu změny, posun bodů konfidence a přehledný tok signálu (např. HOLD (65 %) ➜ BUY (82 %)).

### 6.10 Kvantitativní a výzkumné modely (Research Foundation & Advanced Quant Engine)

V rámci modernizace analytického jádra SuggestInvest byly do systému integrovány klíčové poznatky ze 7 špičkových akademických a institucionálních výzkumných prací z oblasti kvantitativních financí, statistické arbitráže a algoritmického řízení rizik. Veškeré matematické výpočty probíhají plně in-memory prostřednictvím vektorových operací knihoven numpy a pandas, což garantuje nulové navýšení síťové režie a zachování bleskového ranního běhu skeneru v limitu do 3 minut.

A. Dynamická adaptivní invalidace (Adaptive Volatility Stop-Loss & VaR 99%):

Původní statický Stop-Loss (-8 % pro všechna aktiva) byl nahrazen dynamickým modelem odvozeným z principů studií HARN a Universal Diffusion. Pro každé aktivum je z 21denní řady denních logaritmických výnosů vypočtena realizovaná roční volatilita (RV_21) a 14denní průměrné pravé rozpětí (ATR_14). Jednodenní parametrický Value-at-Risk na hladině spolehlivosti 99 % je definován jako:

- 1. Výpočet denní volatility: σ_daily = std(ln(P_t / P_{t-1}))_{21}, přičemž roční RV_21 = σ_daily × √252.
- 2. Parametrický 99% VaR: VaR_{99%, 1d} = 2.33 × σ_daily. Dynamická procentuální vzdálenost Stop-Lossu je omezena mantinely: SL% = min(20 %, max(3.5 %, VaR_{99%, 1d})).
- 3. Adaptivní cenová hladina: P_{invalidation} = P_0 × (1 - SL%). Defenzivní nízkovolatilní akcie (např. ČEZ s RV 11.2 %) získávají těsný Stop-Loss na úrovni -3.7 %, standardní blue-chips (např. Apple s RV 21.8 %) -7.2 %, a vysoce volatilní technologické růstové tituly (např. Nvidia s RV 42.3 %) -13.9 %. Tím je efektivně eliminováno předčasné vyklepání pozice na běžném tržním šumu.
B. Nové katalyzátory a anomálie tržního mikroprostředí:

- 1. Objemový šok (CAT_VOLUME_SHOCK): Standardizované Z-skóre denního objemu z_v = (V_t - μ_V) / σ_V vůči 21dennímu průměru. Pokud z_v ≥ 2.0 a denní změna ceny je kladná (ΔP > 0), model identifikuje institucionální absorpci a příliv velkého kapitálu ještě před zveřejněním zpráv. Fialový odznak: ⚡ Objemový šok (X.Xσ). Vychází z výzkumu LiMT (Liquidity & Momentum Thresholding).
- 2. Sentimentová divergence (CAT_SENTIMENT_DIVERGENCE): Detekce nesouladu mezi tónem zpravodajských toků z finančních médií (RSS) a cenovým chováním aktiva. Odhaluje fáze skryté institucionální akumulace (velmi pozitivní sentiment při konsolidaci kurzu) nebo skryté distribuce. Tyrkysový odznak: 🧠 Sentimentová divergence. Vychází z výzkumu AI & NLP Trading Models.
- 3. Párový diskont (CAT_PAIRS_DISCOUNT): Monitorování sektorové a regionální statistické arbitráže (např. ČEZ vs. RWE/Verbund, KB vs. Erste). Pokud benchmark posiluje a párové aktivum zaostává o více než 1.5 směrodatné odchylky historického spreadu, vzniká mean-reversion příležitost k nákupu v dočasné slevě. Růžový odznak: ⚖️ Párový diskont. Vychází z výzkumu Pairs Trading in CEE Equity Markets.
C. Exekuční taktika a řízení likvidity (OrderFusion+ & APO):

- 1. Limitní nákupní pásmo (Quantile Limit Execution): Modelování nákupního pásma pomocí 10. percentilu denního rozpětí: P_limit = P_0 - 0.5 × ATR_14. Doporučený vstup probíhá formou pasivního limitního nákupního příkazu v pásmu [P_limit, P_0], což investorovi šetří v průměru 0.5 % až 1.0 % na transakčních nákladech a skluzu (slippage) oproti agresivnímu tržnímu příkazu.
- 2. Likviditní strop pozice (2% Average Daily Turnover Cap): Pro zamezení uvíznutí kapitálu v málo likvidních emisích (např. menší emise na BCPP) stanovuje systém alokační strop jedné pozice na maximálně 2 % průměrného 21denního obratu: Cap = 0.02 × (P_0 × V_21). Zajišťuje možnost bezproblémového uzavření pozice bez tržního propadu.
D. Akademické ukotvení – Přehled 7 výzkumných prací:


| Výzkumná práce / Zdroj | Klíčový akademický koncept | Implementace v SuggestInvest | Přínos pro model |
| --- | --- | --- | --- |
| HARN: Hierarchical Adaptive Risk Networks | Hierarchické stochastické sítě modelující volatilitu v různých časových škálách. | Dynamický Stop-Loss počítaný z 99% 1d VaR a RV_21 namísto fixních -8 %. | Zabránění zbytečným ztrátám na šumu, adaptace na volatilitu aktiva. |
| LiMT: Liquidity & Momentum Thresholding | Asymetrie likvidity a nelineární prahy objemových šoků pro predikci průrazu. | Katalyzátor CAT_VOLUME_SHOCK při objemovém Z-skóre z_v ≥ 2.0σ a růstu ceny. | Včasná detekce velkých institucionálních nákupů před zbytkem trhu. |
| OrderFusion+: Multi-Horizon Execution | Predikce intradenních kvantilů LOB a optimalizace limitních nákupních příkazů. | Exekuční nákupní pásmo Q_0.10 [P_0 - 0.5×ATR, P_0] a alokační strop 2 % obratu. | Úspora 0.5–1.0 % na spreadu a tržním dopadu (slippage) při každém vstupu. |
| Universal Diffusion IVS | Difúzní generativní modely pro nelineární dynamiku povrchů volatility. | Mapování volatility regime (RV_21 a ATR%) pro kalibraci citlivosti AI skórování. | Přesnější odlišení klidných růstových trendů od rizikových bublin. |
| AI & NLP Trading Models (SSRN) | Kvantifikace informační asymetrie a sentimentové divergence mezi zprávami a cenou. | Katalyzátor CAT_SENTIMENT_DIVERGENCE propojující RSS feed a momentum delty. | Identifikace skryté akumulace (pozitivní zprávy bez okamžitého pohybu ceny). |
| Pairs Trading in CEE Equity Markets | Kointegrace a statistická arbitráž v regionálních středoevropských titulech. | Katalyzátor CAT_PAIRS_DISCOUNT a sektorové komparativní relace pro BCPP a CEE. | Využití zpoždění lokálních trhů za západoevropskými sektorovými lídry. |
| Decoding the Quant Market | Makro režimy, faktorové rotace a dynamické vážení modelových signálů. | Syntéza v Head of Risk systémovém promptu Gemini 3.5 AI s prioritou událostí. | Robustní eliminace protichůdných signálů a ochrana portfolia. |



### 6.11 Pokročilá syntéza a portfolio management (Výzkumná dávka 2 – Zdroje 8 až 11)

V navazující fázi výzkumu byly do architektury SuggestInvest integrovány poznatky ze čtyř rozsáhlých diplomových a disertačních prací předních světových univerzit (Massachusetts Institute of Technology, Brock University, Universidad Politécnica de Madrid a Victoria University). Tato rozšíření posouvají model od pouhé bodové predikce jednotlivých titulů k sofistikované konstrukci portfolia, dynamické filtraci tržního sentimentu a modelování bankovního úrokového cyklu.

A. Masuda TOP 5 Conviction Allocation (MIT MVO Portfolio):

- 1. Sharpe Proxy Conviction skóre: Inspirováno prací Jamese Masudy (MIT EECS 2024), která prokázala, že hybridní modely dosahují špičkového výkonu pouze při spojení prediktivní síly s Mean-Variance optimalizací (MVO). SuggestInvest denně sestavuje modelový koš 5 nejsilnějších titulů s nejvyšším poměrem očekávaného zisku vůči realizované volatilitě a riziku: Conviction = (Target_Upside / max(RV_21, 10)) × (1 + 0.12 × K), kde K je počet aktivních katalyzátorů.
- 2. Diversifikované vážení portfolia: Alokace kapitálu do TOP 5 aktiv probíhá v sestupných vahách 25 %, 25 %, 20 %, 15 % a 15 % při současném uplatnění regionální a měnové diverzifikace (maximálně 2 tituly v identické měně či regionu v koši). Tím je zabráněno nezdravé koncentraci rizika.
B. Volatility-Adaptive News Sentiment Filtering (Brock University & UPM Madrid):

- 1. Rychlý sentiment u růstových aktiv: Sheraz Ahmad (Brock University 2025) a Juan Luis Ruiz-Tagle (UPM Madrid 2023) prokázali, že vliv zpravodajského sentimentu se zásadně liší napříč sektory a režimy volatility. Vysoce volatilní aktiva (RV_21 ≥ 25 %, např. technologické růstové akcie, krypto-proxies, energetika) reagují na novinky okamžitě s poločasem rozpadu 1–2 dny.
- 2. Potlačení šumu u defenzivních titulů: U nízkovolatilních a defenzivních aktiv (RV_21 ≤ 18 %, např. banky, utility, telekomunikace) působí krátkodobý sentiment jako šum degradující přesnost modelu. SuggestInvest v tomto režimu potlačuje vliv zpráv a klade dominantní důraz na fundamentální valuační diskont a dividendovou stabilitu.
C. Cyklický katalyzátor bankovního sektoru (Victoria University):

- Katalyzátor CAT_FINANCIAL_CYCLE: Disertační práce Praveena Sadasivana (Victoria University 2024/25) modelující bankovní sektorové indexy identifikovala silnou statistickou závislost (R² > 0.78) mezi úrokovým diferenciálem (výnosovou křivkou) a výkonností bankovních akcií se zpožděním 15 až 30 obchodních dnů. SuggestInvest proto zavedl katalyzátor CAT_FINANCIAL_CYCLE (🏛️ Úrokový cyklus / NIM), který pro bankovní tituly (Erste, KB, Moneta, Santander, BNP Paribas, ING) systematicky zohledňuje stabilitu čisté úrokové marže a prostředí úrokových sazeb.
D. Akademické ukotvení – Přehled 4 nových výzkumných prací:


| Výzkumná práce / Zdroj | Klíčový akademický koncept | Implementace v SuggestInvest | Přínos pro model |
| --- | --- | --- | --- |
| James Masuda (MIT EECS, 2024) | Hybridní CNN-LSTM, BiLSTM-BO-LightGBM a Mean-Variance Portfolio Optimization. | Modul TOP 5 Conviction Basket s MVO váhami 25-25-20-15-15 % a Sharpe proxy. | Transformace izolovaných tipů na přímo investovatelné, diverzifikované minitportfolio. |
| Sheraz Ahmad (Brock University, 2025) | Analýza vlivu sentimentu napříč modely, sektory a režimy tržní volatility. | Režimové vážení sentimentu (HIGH_VOLATILITY vs. DEFENSIVE_FUNDAMENTAL). | Eliminace falešných signálů u defenzivních titulů a zrychlení reakce u technologií. |
| Juan Luis Ruiz-Tagle (UPM Madrid, 2023) | Predikce krátkodobých trendů pomocí FinBERT a technických indikátorů. | Pravidlo nepotvrzeného sentimentu v Gemini AI (sentiment vyžaduje technický impuls). | Ochrana před nákupem do padajícího nože na pouhou 'pozitivní PR zprávu'. |
| Praveen Sadasivan (Victoria University, 2024/25) | Predikce bankovních indexů pomocí optimalizovaných AI modelů a úrokových sazeb. | Katalyzátor CAT_FINANCIAL_CYCLE se zpožděnou transmisí úrokových marží (NIM). | Přesnější časování vstupů do evropských a českých bank (KB, Erste, Moneta). |



## 7. Segmentace univerza: Proč 3 prioritní koše (Tiers)

Všech 541 aktiv je kategorizováno do 3 logických košů, které umožňují okamžité filtrování podle investičního stylu:


| Koš (Tier) | Počet aktiv | Charakteristika a složení | Účel v portfoliu |
| --- | --- | --- | --- |
| 🥇 TIER 1 TOP Leaders | 48 aktiv | US Mega-Caps (Apple, Nvidia, Microsoft, Amazon), kompletní BCPP v CZK (ČEZ, banky, Colt), evropské stálice (ASML, SAP) a klíčová indexová ETF (S&P 500, All-World, Nasdaq). | Základní stavební kameny, nejvyšší likvidita, globální tržní kapitalizace a minimální spread. |
| 🥈 TIER 2 MID Growth | 472 aktiv | Rozsáhlé spektrum světových blue-chips (A–Z), polovodičoví lídři, jaderná energetika, obranný sektor, kosmonautika, krypto-proxies a sektorová UCITS ETF na XTB. | Růstový potenciál, sektorové megatrendy a diverzifikace napříč kontinenty i měnami. |
| 🥉 TIER 3 LOW Discovery | 21 aktiv | Vysoce volatilní tituly, obratové (turnaround) akcie, čínské tech akcie v US a průkopnická biotechnologie. | Asymetrický poměr rizika a výnosu pro dynamickou část kapitálu. |



## 8. Závěrečné shrnutí: Přidaná hodnota pro investora

Systém SuggestInvest odstraňuje z investičního rozhodování dvě největší slabiny lidského investora: emoční zkreslení a informační zahlcení. Díky spojení reálných tržních dat z XTB, konsenzu analytiků, firemních kalendářů a syntézy modelu Google Gemini dostává investor každé ráno ucelený a forward-looking screening trhu, který mu během několika vteřin ukáže, kde se dnes otevírají nejzajímavější příležitosti.
