import os
import sys
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

def set_cell_background(cell, hex_color):
    """Nastaví barvu pozadí buňky tabulky."""
    shading_elm = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{hex_color}"/>')
    cell._tc.get_or_add_tcPr().append(shading_elm)

def set_cell_margins(cell, top=100, bottom=100, left=150, right=150):
    """Nastaví vnitřní okraje buňky tabulky v dxa (1 pt = 20 dxa)."""
    tcPr = cell._tc.get_or_add_tcPr()
    tcMar = OxmlElement('w:tcMar')
    for m, val in [('top', top), ('bottom', bottom), ('left', left), ('right', right)]:
        node = OxmlElement(f'w:{m}')
        node.set(qn('w:w'), str(val))
        node.set(qn('w:type'), 'dxa')
        tcMar.append(node)
    tcPr.append(tcMar)

def create_methodology_document(output_path: str):
    doc = docx.Document()

    # Nastavení okrajů stránky (2,54 cm = 1 inch)
    for section in doc.sections:
        section.top_margin = Inches(1.0)
        section.bottom_margin = Inches(1.0)
        section.left_margin = Inches(1.0)
        section.right_margin = Inches(1.0)

    # Barevná paleta
    COLOR_PRIMARY = RGBColor(15, 23, 42)      # Tmavě břidlicová / Navy (#0f172a)
    COLOR_ACCENT = RGBColor(37, 99, 235)      # Královská modrá (#2563eb)
    COLOR_MUTED = RGBColor(100, 116, 139)     # Šedá (#64748b)
    COLOR_DARK = RGBColor(30, 41, 59)         # Tmavá textová (#1e293b)
    COLOR_GREEN = RGBColor(16, 185, 129)      # Smaragdová pro Strong Buy (#10b981)

    # ==================== TITULNÍ STRANA / ZÁHLAVÍ ====================
    title_p = doc.add_paragraph()
    title_p.paragraph_format.space_before = Pt(10)
    title_p.paragraph_format.space_after = Pt(4)
    run_badge = title_p.add_run("SUGGESTINVEST • AI MARKET RESEARCH LAB")
    run_badge.font.name = "Calibri"
    run_badge.font.size = Pt(10)
    run_badge.font.bold = True
    run_badge.font.color.rgb = COLOR_ACCENT

    title_main = doc.add_paragraph()
    title_main.paragraph_format.space_before = Pt(0)
    title_main.paragraph_format.space_after = Pt(8)
    run_title = title_main.add_run("Metodika a Analýza Tržních Dat")
    run_title.font.name = "Calibri"
    run_title.font.size = Pt(26)
    run_title.font.bold = True
    run_title.font.color.rgb = COLOR_PRIMARY

    sub_p = doc.add_paragraph()
    sub_p.paragraph_format.space_before = Pt(0)
    sub_p.paragraph_format.space_after = Pt(20)
    run_sub = sub_p.add_run("Kompletní přehled datových zdrojů, analytických proměnných a principu vyhodnocování 541 akciových titulů a ETF")
    run_sub.font.name = "Calibri"
    run_sub.font.size = Pt(13)
    run_sub.font.italic = True
    run_sub.font.color.rgb = COLOR_MUTED

    # Metadata tabulka (Informační box)
    meta_table = doc.add_table(rows=2, cols=2)
    meta_table.alignment = WD_TABLE_ALIGNMENT.CENTER
    meta_table.autofit = False

    meta_data = [
        ("Rozsah univerza:", "541 aktiv (US akcie, Evropa, BCPP v CZK, ETF, Krypto)", "Analytický engine:", "Google Gemini AI + Yahoo Finance Feed"),
        ("Broker napojení:", "XTB katalog (14 692 instrumentů, ISIN validace)", "Frekvence skenu:", "Denně v 8:00 CET + manuální vyžádání")
    ]

    for row_idx, data_row in enumerate(meta_data):
        cell_l = meta_table.cell(row_idx, 0)
        cell_r = meta_table.cell(row_idx, 1)

        set_cell_background(cell_l, "f1f5f9")
        set_cell_background(cell_r, "f8fafc")
        set_cell_margins(cell_l, top=100, bottom=100, left=150, right=150)
        set_cell_margins(cell_r, top=100, bottom=100, left=150, right=150)

        p_l = cell_l.paragraphs[0]
        p_l.paragraph_format.space_after = Pt(2)
        r_l_lbl = p_l.add_run(data_row[0] + " ")
        r_l_lbl.font.bold = True
        r_l_lbl.font.size = Pt(9.5)
        r_l_val = p_l.add_run(data_row[1])
        r_l_val.font.size = Pt(9.5)

        p_r = cell_r.paragraphs[0]
        p_r.paragraph_format.space_after = Pt(2)
        r_r_lbl = p_r.add_run(data_row[2] + " ")
        r_r_lbl.font.bold = True
        r_r_lbl.font.size = Pt(9.5)
        r_r_val = p_r.add_run(data_row[3])
        r_r_val.font.size = Pt(9.5)

    doc.add_paragraph().paragraph_format.space_after = Pt(15)

    # Pomocná funkce pro nadpisy sekcí
    def add_section_header(title, level=1):
        p = doc.add_paragraph()
        p.paragraph_format.keep_with_next = True
        if level == 1:
            p.paragraph_format.space_before = Pt(22)
            p.paragraph_format.space_after = Pt(6)
            run = p.add_run(title)
            run.font.name = "Calibri"
            run.font.size = Pt(17)
            run.font.bold = True
            run.font.color.rgb = COLOR_PRIMARY
        elif level == 2:
            p.paragraph_format.space_before = Pt(14)
            p.paragraph_format.space_after = Pt(4)
            run = p.add_run(title)
            run.font.name = "Calibri"
            run.font.size = Pt(13)
            run.font.bold = True
            run.font.color.rgb = COLOR_ACCENT
        elif level == 3:
            p.paragraph_format.space_before = Pt(10)
            p.paragraph_format.space_after = Pt(2)
            run = p.add_run(title)
            run.font.name = "Calibri"
            run.font.size = Pt(11)
            run.font.bold = True
            run.font.color.rgb = COLOR_DARK
        return p

    def add_body_p(text, bold_prefix="", space_after=6):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(space_after)
        p.paragraph_format.line_spacing = 1.15
        if bold_prefix:
            r_bold = p.add_run(bold_prefix)
            r_bold.font.name = "Calibri"
            r_bold.font.size = Pt(10.5)
            r_bold.font.bold = True
            r_bold.font.color.rgb = COLOR_DARK
        r_text = p.add_run(text)
        r_text.font.name = "Calibri"
        r_text.font.size = Pt(10.5)
        r_text.font.color.rgb = COLOR_DARK
        return p

    def add_bullet(text, bold_prefix=""):
        p = doc.add_paragraph(style='List Bullet')
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(3)
        p.paragraph_format.line_spacing = 1.15
        if bold_prefix:
            r_bold = p.add_run(bold_prefix)
            r_bold.font.name = "Calibri"
            r_bold.font.size = Pt(10.5)
            r_bold.font.bold = True
            r_bold.font.color.rgb = COLOR_DARK
        r_text = p.add_run(text)
        r_text.font.name = "Calibri"
        r_text.font.size = Pt(10.5)
        r_text.font.color.rgb = COLOR_DARK
        return p

    # ==================== KAPITOLA 1: MANAŽERSKÉ SHRNUTÍ ====================
    add_section_header("1. Manažerské shrnutí: Co systém dělá z pohledu investora")
    add_body_p(
        "Systém SuggestInvest slouží jako automatizovaný analytický aparát, který každé ráno před otevřením evropských burz "
        "syntetizuje data ze světových finančních trhů a převádí je do jednoznačných, racionálních investičních signálů. "
        "Cílem systému není generovat vteřinový intradenní šum, ale poskytovat investorovi strukturovaný, fundamentálně podložený "
        "pohled na 513 vybraných aktiv, a to včetně zohlednění likvidity u brokera XTB a českých specifik pražské burzy."
    )
    add_body_p(
        "Zatímco lidský analytik dokáže za ranní hodinu do detailu projít nanejvýš několik akciových zpráv, tento systém "
        "během 60 sekund paralelně zpracuje kurzotvorná data, vyhodnotí pozici každého aktiva vůči jeho ročním maximům a minimům, "
        "spojí tyto údaje s čerstvými makroekonomickými zprávami a prostřednictvím modelu Google Gemini AI vygeneruje pro každý titul "
        "odůvodněné doporučení (Strong Buy, Buy, Hold, Sell, Strong Sell) doplněné o míru pravděpodobnosti a tržní katalyzátory."
    )

    # ==================== KAPITOLA 2: PROHLEDÁVANÉ ZDROJE DAT ====================
    add_section_header("2. Prohledávané zdroje dat a vstupní informace")
    add_body_p("Analýza neprobíhá ve vakuu, ale kombinuje 4 odlišné vrstvy dat:")

    add_section_header("2.1 Oficiální specifikace instrumentů XTB (Zdroj: spectabomicz29062026.pdf)", level=2)
    add_body_p(
        "Základním stavebním kamenem univerza je oficiální katalog instrumentů brokera XTB. Z celkového počtu více než 15 000 instrumentů "
        "systém nejprve provádí tzv. hygienické vyčištění trhu:"
    )
    add_bullet(
        " Každý titul je prověřen svým mezinárodním kódem ISIN (International Securities Identification Number), "
        "což zamezuje záměně různých emisí (např. běžné vs. prioritní akcie nebo ADR certifikáty).",
        "Validace přes ISIN:"
    )
    add_bullet(
        " Systém okamžitě detekuje a vyřazuje instrumenty označené v tabulkách XTB jako CLOSE ONLY (více než 689 mrtvých emisí). "
        "Tím je zaručeno, že systém neanalyzuje delistované akcie, pozastavené emise ani tituly, které nelze u XTB reálně nakoupit.",
        "Automatický Trash Filter:"
    )
    add_bullet(
        " Přesné mapování symbolu (např. CEZ1.CZ ➡️ CEZ.PR na Yahoo Finance, SXR8.DE pro S&P 500 ETF v EUR, nebo AAL.UK ➡️ AAL.L v Londýně) "
        "zajišťuje, že investor vždy přesně ví, pod jakým kódem titul najde v aplikaci xStation.",
        "Křížové mapování broker tickerů:"
    )

    add_section_header("2.2 Reálné burzovní feedy (Yahoo Finance Engine)", level=2)
    add_body_p("Pro každé z 513 aktiv systém v reálném čase stahuje klíčové kvantitativní parametry:")
    add_bullet(" Poslední dosažená cena v primární obchodovací měně (USD, EUR, CZK, GBP, CHF, SEK).", "Aktuální tržní kurz (Last Price):")
    add_bullet(" Denní posun ceny v procentech i nominální hodnotě vůči závěru předchozího dne.", "Denní cenová změna (% change):")
    add_bullet(" Extrémně důležitý indikátor dlouhodobého trendu. Ukazuje, kde se aktivum nachází v rámci svého ročního cyklu.", "52týdenní pásmo (52-week High / Low):")
    add_bullet(" Ověření, že se s aktivem aktivně obchoduje a netrpí nelikviditou.", "Historická kontinuita (5denní cenová řada):")

    add_section_header("2.3 Globální makroekonomické a tržní zprávy (RSS Finance Feed)", level=2)
    add_body_p(
        "Akcie nežijí odděleně od globálního dění. Před zahájením analýzy jednotlivých titulů systém stahuje živý proud "
        "nejdůležitějších globálních zpráv (např. rozhodování Fedu o sazbách, geopolitická rizika, inflační reporty CPI, výsledková sezóna). "
        "Tento souhrn je předán AI jako 'nálada a makro rámec dne', podle kterého se kalibruje celková ochota trhu podstupovat riziko."
    )

    add_section_header("2.4 Hluboká znalostní báze modelu Google Gemini Pro", level=2)
    add_body_p(
        "Model Gemini není použit jako generátor náhodného textu, ale jako vysoce kvalifikovaný analytik, který má ve své bázi znalosti "
        "o obchodních modelech jednotlivých firem, jejich konkurenčních výhodách (economic moats), zadlužení a sektorové expozici. "
        "Spojením aktuálního kurzu s fundamentální podstatou firmy vzniká výsledné zhodnocení."
    )

    # ==================== KAPITOLA 3: ANALYTICKÉ PROMĚNNÉ ====================
    add_section_header("3. Jaké informace jsou brány v potaz (Analytické proměnné)")
    add_body_p(
        "Při hodnocení každého aktiva systém sleduje souběh technických a fundamentálních proměnných:"
    )

    # Tabulka proměnných
    table_vars = doc.add_table(rows=6, cols=3)
    table_vars.alignment = WD_TABLE_ALIGNMENT.CENTER
    table_vars.autofit = False

    headers = ["Analytická proměnná", "Sledovaná hodnota / Impuls", "Investiční interpretace"]
    for i, h in enumerate(headers):
        cell = table_vars.cell(0, i)
        set_cell_background(cell, "0f172a")
        set_cell_margins(cell, top=120, bottom=120, left=120, right=120)
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(2)
        r = p.add_run(h)
        r.font.bold = True
        r.font.size = Pt(9.5)
        r.font.color.rgb = RGBColor(255, 255, 255)

    var_rows = [
        ("Denní momentum", "Pohyb o více než +3.0 %", "Silný nákupní tlak, pozitivní earnings katalyzátor nebo sektorová rotace."),
        ("Korekce / Výprodej", "Pokles o více než -3.0 %", "Krátkodobé přeprodání (příležitost pro dip-buyers), nebo fundamentální varování."),
        ("Blízkost k 52w Maximu", "Aktuální cena >= 97 % z 52w High", "Testování historických maxim, potvrzení silného růstového býčího trendu."),
        ("Blízkost k 52w Minimu", "Aktuální cena poblíž ročního dna", "Možný obratový (turnaround) potenciál, nebo naopak strukturální potíže firmy."),
        ("Sektorové zařazení", "Tech, Energetika, Banky, Utility, ETF", "Zohlednění specifických rizik (např. úroková citlivost u bank, AI výdaje u Big Tech).")
    ]

    for row_idx, (c0, c1, c2) in enumerate(var_rows, 1):
        bg = "f8fafc" if row_idx % 2 == 1 else "ffffff"
        for col_idx, text in enumerate([c0, c1, c2]):
            cell = table_vars.cell(row_idx, col_idx)
            set_cell_background(cell, bg)
            set_cell_margins(cell, top=80, bottom=80, left=100, right=100)
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(2)
            r = p.add_run(text)
            r.font.size = Pt(9.0)
            if col_idx == 0:
                r.font.bold = True

    doc.add_paragraph().paragraph_format.space_after = Pt(10)

    # ==================== KAPITOLA 4: REGIONÁLNÍ SPECIFIKA ====================
    add_section_header("4. Specifická logika pro jednotlivé trhy a třídy aktiv")

    add_body_p(
        "Systém nepoužívá 'univerzální šablonu' na všechno, ale rozlišuje specifika jednotlivých trhů:",
        bold_prefix="Regionální a sektorové přizpůsobení: "
    )
    add_bullet(
        " U titulů jako ČEZ, Komerční banka, Moneta, Colt CZ nebo Philip Morris systém zohledňuje dividendovou stabilitu, "
        "specifika české koruny (CZK), regulaci energetiky a vliv daně z neočekávaných zisků (windfall tax).",
        "🇨🇿 Pražská burza BCPP v CZK:"
    )
    add_bullet(
        " U lídrů jako Nvidia, Apple, Microsoft, Alphabet či Meta je klíčovým kritériem ocenění (valuace P/E), "
        "kapitálové výdaje do AI infrastruktury (capex) a celková dynamika technologického indexu Nasdaq.",
        "🇺🇸 US Mega-Caps & Umělá inteligence:"
    )
    add_bullet(
        " Tituly typu Cameco, NuScale, Oklo, Rocket Lab či MicroStrategy mají vysokou volatilitu. "
        "Zde systém sleduje fundamentální megatrendy (jaderná renesance, vládní zakázky pro kosmonautiku, adopce Bitcoinu institucemi).",
        "⚛️ Tematické růstové akcie (Uran, Kosmonautika, Krypto):"
    )
    add_bullet(
        " Průmyslové giganty (ASML, SAP, Siemens, LVMH, automobilky BMW/Mercedes) jsou posuzovány prizmatem "
        "stavu německé a evropské ekonomiky, exportní závislosti na Číně a nákladů na energie.",
        "🇪🇺 Evropští průmysloví a luxusní lídři:"
    )
    add_bullet(
        " U fondů jako S&P 500 (SXR8.DE) nebo FTSE All-World (VWCE.DE) systém nehledá spekulativní výkyvy, "
        "ale potvrzuje dlouhodobý směr trhu a globální alokaci kapitálu.",
        "📊 Pasivní indexová ETF:"
    )

    # ==================== KAPITOLA 5: METODIKA HODNOCENÍ ====================
    add_section_header("5. Jak systém hodnotí akciové tituly: Výstupní signály a odůvodnění")
    add_body_p(
        "Každé vyhodnocení zobrazené na kartě aktiva obsahuje 4 provázané složky:"
    )

    add_section_header("5.1 Pětistupňový investiční signál (Signal)", level=2)
    add_bullet(
        " Mimořádný růstový potenciál. Souběh silného momenta, zdravého fundamentu a pozitivního makroekonomického větru. "
        "Vhodné pro aktivní akumulaci pozice.",
        "🟢 STRONG BUY:"
    )
    add_bullet(
        " Pozitivní výhled. Růstové katalyzátory převažují nad riziky, titul se nachází ve zdravém trendu nebo po zdravé korekci.",
        "🟢 BUY:"
    )
    add_bullet(
        " Neutrální pozice. Vyvážený poměr výnosu a rizika. Často jde o fázi konsolidace po prudkém růstu nebo čekání na firemní výsledky.",
        "🟡 HOLD:"
    )
    add_bullet(
        " Převaha negativních impulsů. Přepálená valuace, zhoršující se momentum nebo nepříznivý sektorový vývoj. Doporučeno zvážit redukci pozice.",
        "🔴 SELL:"
    )
    add_bullet(
        " Výrazný fundamentální tlak, prudký medvědí trend nebo vážné narušení investiční teze. Vysoké riziko dalšího poklesu.",
        "🔴 STRONG SELL:"
    )

    add_section_header("5.2 Pravděpodobnost úspěchu (Confidence Score: 0–100 %)", level=2)
    add_body_p(
        "Indikátor, který vyjadřuje míru jistoty modelu v daný signál. Pokud jsou fundamentální zprávy i technická data v dokonalé shodě, "
        "dosahuje pravděpodobnost hodnot 80–95 %. Pokud se technický vývoj bije s makroekonomickou nejistotou, skóre klesá k 50–60 %."
    )

    add_section_header("5.3 Očekávaný směr impulsu (Impact Direction: ▲ Růst / ▼ Pokles)", level=2)
    add_body_p(
        "Bipolární vektor, který okamžitě indikuje, zda převažující tržní síly tlačí kurz nahoru nebo dolů."
    )

    add_section_header("5.4 Automaticky přiřazené katalyzátory (Barevné štítky)", level=2)
    add_body_p(
        "Systém kartám automaticky přiřazuje rychlé vizuální štítky na základě matematických filtrů:"
    )
    add_bullet(" Denní skok ceny o více než +3 %.", "🚀 Silné momentum:")
    add_bullet(" Titul se dotýká nebo blíží 52týdennímu maximu (býčí síla).", "🔥 Test 52w Maxima:")
    add_bullet(" Denní pokles o více než -3 % (oblast pro sledování slev).", "📉 Přeprodáno / Korekce:")
    add_bullet(" Titul z pražské burzy s vysokým dividendovým profilem.", "🇨🇿 BCPP Dividendy:")
    add_bullet(" Fond sledující široký tržní index.", "📊 Pasivní ETF:")

    add_section_header("5.5 Syntetické odůvodnění v češtině (Investment Reasoning)", level=2)
    add_body_p(
        "Nejcennější částí analýzy je výstižné, 1–2 věté shrnutí, proč byl daný signál vybrán. "
        "Investor okamžitě vidí, zda je růst tažen hospodářskými výsledky, fúzí, technologickým náskokem, "
        "nebo zda je pokles způsoben regulatorním zásahem či ochlazením poptávky."
    )

    # ==================== KAPITOLA 6: PŘEDSTIHOVÉ INDIKÁTORY ====================
    add_section_header("6. Předstihové indikátory, cílové ceny a firemní kalendáře")
    add_body_p(
        "Klíčovým inovačním skokem systému SuggestInvest je integrace předstihových (forward-looking) indikátorů. "
        "Zatímco běžné skenery pouze reaktivně sledují včerejší ceny a denní změny, SuggestInvest se dívá dopředu "
        "pomocí konsenzuálních cílových cen analytiků, odpočtu dnů do kvartálních výsledků a časových momentových delt."
    )

    add_section_header("6.1 Cílové ceny analytiků a růstový potenciál (Target Upside %)", level=2)
    add_body_p(
        "Pro každý akciový titul systém stahuje konsenzuální odhad analytiků z Wall Street (Target Mean Price, Target High a Target Low) "
        "včetně počtu analytiků pokrývajících danou akcii. Následně počítá přesný diskont či prémii vůči trhu:"
    )
    add_bullet(" (Target Mean Price - Aktuální cena) / Aktuální cena × 100.", "Vzorec Target Upside %:")
    add_bullet(" Pokud je očekávaný růst k cíli > +25 % při alespoň 5 analytických doporučeních.", "🎯 Vysoký diskont (> +25 %):")
    add_bullet(" Pokud aktuální tržní cena překročila průměrný cíl analytiků (varování před vyčerpaným potenciálem).", "⚠️ Nad cílem analytiků:")

    add_section_header("6.2 Firemní kalendáře: Kvartální výsledky a odpočet dní (Earnings Countdown)", level=2)
    add_body_p(
        "Zveřejnění kvartálních hospodářských výsledků (Earnings) je pro akcie nejvýznamnější událostí způsobující skokové pohyby kurzu. "
        "Systém v reálném čase sleduje oficiální firemní kalendáře a počítá odpočet dní do nejbližšího reportu:"
    )
    add_bullet(" Výsledky budou oznámeny do 7 dnů. Zvýšená implikovaná volatilita a varování před neuváženým vstupem před čísly.", "⏳ Výsledky do 7 dní (Kritické):")
    add_bullet(" Výsledky za 8 až 21 dní. Fáze obvyklého předvýsledkového runupu či konsolidace.", "📅 Výsledky do 21 dní (Blížící se):")

    add_section_header("6.3 Rozhodné dny pro dividendu (Ex-Dividend Countdown)", level=2)
    add_body_p(
        "Pro dividendové investory systém monitoruje datum Ex-Dividend (první den, kdy se akcie obchoduje bez nároku na dividendu). "
        "Pokud se Ex-Dividend blíží v horizontu 1 až 14 dnů, systém aktivuje zelený štítek '💰 Ex-Div za N dní' pro včasné zachycení výplaty."
    )

    add_section_header("6.4 Časové delty hybnosti: 1měsíční a 3měsíční momentum", level=2)
    add_body_p(
        "Kromě jednodenní změny systém hromadně vyhodnocuje střednědobé časové delty: 1M momentum (~21 obchodních dnů) "
        "a 3M momentum (~63 obchodních dnů). To umožňuje odlišit krátkodobý náhodný šum od skutečně udržitelného trendu podpořeného institucionálními toky."
    )

    add_section_header("6.5 Automatický pravidlový Trigger Engine a disková mezipaměť", level=2)
    add_body_p(
        "Aby systém dokázal bleskově zpracovat 541 aktiv bez rizika rate-limitu od poskytovatelů dat, využívá inteligentní "
        "souborovou mezipaměť (cache_fundamentals.json) s 24hodinovou expirací. Kalendáře a analytické cíle se tak dotazují jednou denně, "
        "zatímco kurzy běží v reálném čase. Všechny předstihové ukazatele jsou navíc přímo předávány do modelu Gemini, "
        "který je promítá do generovaného AI kontextu."
    )

    add_section_header("6.6 Dlouhodobá historická persistence a SQLite časová řada (Backtesting a audit)", level=2)
    add_body_p(
        "Pro zajištění plné auditovatelnosti a měření reálné úspěšnosti AI modelů v čase systém ukládá každý proběhlý sken do dvouúrovňové persistence:"
    )
    add_bullet(" Každý sken vygeneruje kompletní neměnný JSON soubor se všemi 541 kartami, tržními vstupy i AI zdůvodněními.", "1. Neměnný denní JSON Data Lake (data/history/):")
    add_bullet(" Každý vydaný signál, konfidence, cena i datum kvartálních výsledků se indexují do lokální relační databáze SQLite pro bleskové analytické dotazy.", "2. Relační časová řada SQLite (history.db):")
    add_bullet(" Možnost ex-post porovnat vydaná doporučení (Strong Buy / Buy) se skutečným zhodnocením podkladového aktiva po 7, 30 a 90 dnech.", "3. Automatizovaný Backtesting:")
    add_bullet(" V AI tooltipu se přímo zobrazuje trajektorie sentimentu za poslední měsíc (např. Hold 55 % ➡️ Buy 72 % ➡️ Strong Buy 88 %).", "4. Vývoj sentimentu v čase:")

    add_section_header("6.7 Institucionální Kvantitativní Model a Head of Risk Rozhodovací Matice", level=2)
    add_body_p(
        "Vrcholnou vrstvou systému SuggestInvest je role Senior Quantitative Equity Analyst & Head of Portfolio Risk. "
        "Jeho posláním není popisovat minulý vývoj kurzu, ale identifikovat asymetrické tržní příležitosti a rizika "
        "v horizontu 1 až 3 měsíců na základě nesouladu mezi tržní cenou, posunem konsenzu a časem do klíčových událostí."
    )

    add_body_p("A. Pravidla konsenzu, valuace a revizí:")
    add_bullet(" Pokud je počet analytiků ≥ 5 a 30denní posun cílové ceny ≥ 0 %, jde o silný růstový signál (BUY / STRONG BUY). Pokud cena klesá (1M < 0), ale cíl roste (Δ target 30d > 0), vzniká pozitivní divergence a institucionální akumulace.", "Fundamentální diskont (> +20 %):")
    add_bullet(" Pokud je Target Upside ≤ 0 %, růstový potenciál je vyčerpán. Vstupuje v platnost absolutní zákaz doporučení STRONG BUY či BUY $\rightarrow$ striktně HOLD nebo SELL.", "Přepálená valuace (Tržní cena nad cílem):")

    add_body_p("B. Událostní filtry kalendáře a limity konfidence:")
    add_bullet(" Implikovaná volatilita roste a událost přináší binární riziko. Konfidence nesmí překročit 65 % (s výjimkou defenzivních monopolů). Automatický štítek: ⏳ Výsledky do 7 dní.", "Kritické okno před výsledky (≤ 7 dní):")
    add_bullet(" Pokud je 1M momentum kladné a cílová cena roste, aktivum se nachází v akumulační fázi před kvartální zprávou. Štítek: 📅 Výsledky do 21 dní.", "Předvýsledkový run-up (8 až 21 dní):")
    add_bullet(" Pozice je vhodná pro akumulaci před rozhodným dnem pro výplatu. Štítek: 💰 Ex-Div za N dní.", "Dividendový trigger (≤ 14 dní):")

    add_body_p("C. Filtry trendu, obratu a řízení rizik:")
    add_bullet(" Test 52w minima (vzdálenost < 70 % od maxima) s propadem cílové ceny (Δ target 30d < -5 %) indikuje strukturální destrukci hodnoty $\rightarrow$ SELL či STRONG SELL. Test minima se stabilním cílem a rostoucím momentem značí obrat $\rightarrow$ BUY.", "Obrat vs. Padající nůž:")
    add_bullet(" Denní skoky o více než ±3 % systém ignoruje, pokud nejsou v souladu s 1M momentem nebo novou fundamentální zprávou.", "Kontrola tržního šumu:")

    add_body_p("D. Pětistupňová hierarchie signálů a Invalidation Price:")
    add_bullet(" Shoda silného 1M/3M trendu, diskont k cílové ceně > 20 % a pozitivní revize odhadů.", "🟢 STRONG BUY:")
    add_bullet(" Pozitivní asymetrie výnosu a rizika, zdravý diskont k cíli, žádné binární riziko do 7 dnů.", "🟢 BUY:")
    add_bullet(" Vyčerpaný potenciál k cílové ceně, konsolidace nebo výsledky v horizontu do 7 dnů.", "🟡 HOLD:")
    add_bullet(" Tržní kurz nad cílem analytiků, zhoršující se momentum nebo negativní revize odhadů.", "🔴 SELL:")
    add_bullet(" Ztráta fundamentu, prolomení podpory a masivní snižování cílových cen analytiky.", "🔴 STRONG SELL:")
    add_bullet(" Exaktní číselná hladina (stop-loss úroveň), při jejímž prolomení celá investiční teze zaniká.", "🛑 Invalidation Price (Stop-Loss):")

    add_section_header("6.8 Kvantitativní Analýza Dividendových Anomálií (Ex-Date Recovery Velocity)", level=2)
    add_body_p(
        "Trh v den Ex-Dividend automaticky koriguje otevírací kurz o výši přiznané dividendy. "
        "V reálném obchodování však vzniká statistická asymetrie daná chováním investorů, daňovým zatížením a rychlostí uzavření cenového gapu. "
        "SuggestInvest provádí rigorózní kvantitativní analýzu posledních 4 až 8 historických Ex-Dates a vyhodnocuje dvě protichůdné strategie:"
    )

    add_body_p("A. Měřené statistické metriky:")
    add_bullet(" Poměr reálného poklesu kurzu k výši dividendy. Hodnota < 1.0 indikuje nákupní polštář a silnou poptávku.", "Dividend Drop-Off Ratio (DDR):")
    add_bullet(" Průměrný kapitálový zisk akcie v období 20 obchodních dní před Ex-Date (institucionální i retailová akumulace před rozhodným dnem).", "Pre-Ex Run-up Momentum (20d):")
    add_bullet(" Procento historických výplat, kdy se kurz vrátil na cum-dividend cenu do 15 a 30 obchodních dní, včetně mediánu počtu dní potřebných ke smazání gapu.", "Recovery Velocity (T_rec):")

    add_body_p("B. Rozhodovací logika dividendového doporučení:")
    add_bullet(" Pokud se kurz v ≥ 65 % případů zotaví do 15 obchodních dní s mediánem ≤ 15 dní. Titul má silnou absorpci a vyplatí se pozici držet přes Ex-Date, inkasovat dividendu a vyčkat na smazání gapu.", "🟢 Držet přes Ex-Div (Dividend Capture):")
    add_bullet(" Pokud průměrný předexový růst (20d) dosahuje alespoň 1.5 % a převyšuje dividendový výnos, ale historické zotavení po Ex-Date je pomalé (≤ 40 % do 15 dní). Výhodnější je prodat 1–2 dny před Ex-Date, realizovat kapitálový zisk bez srážkové daně a vyhnout se post-dividendovému propadu.", "🟡 Prodat před Ex-Div (Run-up Harvest):")
    add_bullet(" Běžná tržní fluktuace bez průkazné statistické anomálie.", "⚪ Běžný průběh (Neutrální):")

    add_section_header("6.9 Denní sledování změn a detekce tržních obratů (Daily Delta & Change Tracker)", level=2)
    add_body_p(
        "V dynamickém tržním prostředí není nejdůležitější statický stav aktiva, ale jeho okamžitá derivace – tedy rychlost "
        "a směr změny sentimentu. Pokud se doporučení pro titul změní ze dne na den, jde o primární signál pro pozornost portfoliomanažera. "
        "Systém SuggestInvest proto při každém ranním skenu automaticky porovnává nově vygenerovaný stav s referenčním skenem "
        "z předchozího obchodního dne (uloženým v SQLite databázi history.db)."
    )

    add_body_p("A. Klasifikace denních posunů (Change Types):")
    add_bullet(" Posun v pětistupňové hierarchii směrem nahoru (např. HOLD ➜ BUY, BUY ➜ STRONG BUY). Indikuje nově potvrzený fundamentální impuls, průlom rezistence nebo skokový nárůst odhadů analytiků. Zelený odznak: ⬆️ UPGRADE.", "Zvýšení doporučení (Rating Upgrade):")
    add_bullet(" Posun v pětistupňové hierarchii směrem dolů (např. BUY ➜ HOLD, HOLD ➜ SELL). Varuje před vyčerpaným růstovým potenciálem, překročením cílové ceny nebo blížícím se binárním rizikem výsledků. Červený odznak: ⬇️ DOWNGRADE.", "Snížení doporučení (Rating Downgrade):")
    add_bullet(" Změna míry jistoty modelu o více než ±10 procentních bodů při stejném signálu. Odráží zrychlení přílivu kapitálu nebo naopak rostoucí makroekonomickou nejistotu. Tyrkysový odznak: ⚡ +N% CONF, resp. žlutý: ⚠️ -N% CONF.", "Významný skok konfidence (Confidence Velocity):")
    add_bullet(" Skoková změna konsenzuální cílové ceny analytiků z Wall Street o více než ±8 % (např. po vlně nových analytických doporučení). Fialový odznak: 🎯 ±N% CÍL.", "Revize cílové ceny (Target Shift):")
    add_bullet(" Detekce nově aktivovaného spouštěče v reálném čase (např. vstup do okna 7 dnů před výsledky, blížící se rozhodný den pro dividendu, test 52týdenního maxima). Růžový odznak: 🔥 KATALYZÁTOR.", "Aktivace nového katalyzátoru (New Catalyst):")
    add_bullet(" Titul, který nebyl v předchozím skenu zahrnut (nové IPO, přidání do univerza). Modrý odznak: ✨ NOVÉ.", "Nové aktivum v univerzu (New Asset):")

    add_body_p("B. Využití v uživatelském rozhraní a ranní rutině:")
    add_bullet(" V záhlaví aplikace i ve filtračním panelu je k dispozici dedikovaná sekce '⚡ Posuny od včerejška'. Investor jedním kliknutím odfiltruje pouze upgrady, downgrady či skoky konfidence a nemusí procházet všech 541 aktiv.", "Jednoklikový filtr změn:")
    add_bullet(" V tabulce aktiv je přímo pod signálem zobrazen výrazný barevný mikroodznak indikující přesný typ posunu.", "Vizuální označení v tabulce:")
    add_bullet(" V kontextovém AI tooltipu (tlačítko 💡 Kontext) se při najetí myši na první pozici zobrazí detailní srovnávací box obsahující textové vysvětlení důvodu změny, posun bodů konfidence a přehledný tok signálu (např. HOLD (65 %) ➜ BUY (82 %)).", "Detailní komparativní blok:")

    add_section_header("6.10 Kvantitativní a výzkumné modely (Research Foundation & Advanced Quant Engine)", level=2)
    add_body_p(
        "V rámci modernizace analytického jádra SuggestInvest byly do systému integrovány klíčové poznatky "
        "ze 7 špičkových akademických a institucionálních výzkumných prací z oblasti kvantitativních financí, "
        "statistické arbitráže a algoritmického řízení rizik. Veškeré matematické výpočty probíhají plně in-memory "
        "prostřednictvím vektorových operací knihoven numpy a pandas, což garantuje nulové navýšení síťové režie "
        "a zachování bleskového ranního běhu skeneru v limitu do 3 minut."
    )

    add_body_p("A. Dynamická adaptivní invalidace (Adaptive Volatility Stop-Loss & VaR 99%):")
    add_body_p(
        "Původní statický Stop-Loss (-8 % pro všechna aktiva) byl nahrazen dynamickým modelem odvozeným "
        "z principů studií HARN a Universal Diffusion. Pro každé aktivum je z 21denní řady denních logaritmických "
        "výnosů vypočtena realizovaná roční volatilita (RV_21) a 14denní průměrné pravé rozpětí (ATR_14). "
        "Jednodenní parametrický Value-at-Risk na hladině spolehlivosti 99 % je definován jako:"
    )
    add_bullet(" σ_daily = std(ln(P_t / P_{t-1}))_{21}, přičemž roční RV_21 = σ_daily × √252.", "1. Výpočet denní volatility:")
    add_bullet(" VaR_{99%, 1d} = 2.33 × σ_daily. Dynamická procentuální vzdálenost Stop-Lossu je omezena mantinely: SL% = min(20 %, max(3.5 %, VaR_{99%, 1d})).", "2. Parametrický 99% VaR:")
    add_bullet(" P_{invalidation} = P_0 × (1 - SL%). Defenzivní nízkovolatilní akcie (např. ČEZ s RV 11.2 %) získávají těsný Stop-Loss na úrovni -3.7 %, standardní blue-chips (např. Apple s RV 21.8 %) -7.2 %, a vysoce volatilní technologické růstové tituly (např. Nvidia s RV 42.3 %) -13.9 %. Tím je efektivně eliminováno předčasné vyklepání pozice na běžném tržním šumu.", "3. Adaptivní cenová hladina:")

    add_body_p("B. Nové katalyzátory a anomálie tržního mikroprostředí:")
    add_bullet(" Standardizované Z-skóre denního objemu z_v = (V_t - μ_V) / σ_V vůči 21dennímu průměru. Pokud z_v ≥ 2.0 a denní změna ceny je kladná (ΔP > 0), model identifikuje institucionální absorpci a příliv velkého kapitálu ještě před zveřejněním zpráv. Fialový odznak: ⚡ Objemový šok (X.Xσ). Vychází z výzkumu LiMT (Liquidity & Momentum Thresholding).", "1. Objemový šok (CAT_VOLUME_SHOCK):")
    add_bullet(" Detekce nesouladu mezi tónem zpravodajských toků z finančních médií (RSS) a cenovým chováním aktiva. Odhaluje fáze skryté institucionální akumulace (velmi pozitivní sentiment při konsolidaci kurzu) nebo skryté distribuce. Tyrkysový odznak: 🧠 Sentimentová divergence. Vychází z výzkumu AI & NLP Trading Models.", "2. Sentimentová divergence (CAT_SENTIMENT_DIVERGENCE):")
    add_bullet(" Monitorování sektorové a regionální statistické arbitráže (např. ČEZ vs. RWE/Verbund, KB vs. Erste). Pokud benchmark posiluje a párové aktivum zaostává o více než 1.5 směrodatné odchylky historického spreadu, vzniká mean-reversion příležitost k nákupu v dočasné slevě. Růžový odznak: ⚖️ Párový diskont. Vychází z výzkumu Pairs Trading in CEE Equity Markets.", "3. Párový diskont (CAT_PAIRS_DISCOUNT):")

    add_body_p("C. Exekuční taktika a řízení likvidity (OrderFusion+ & APO):")
    add_bullet(" Modelování nákupního pásma pomocí 10. percentilu denního rozpětí: P_limit = P_0 - 0.5 × ATR_14. Doporučený vstup probíhá formou pasivního limitního nákupního příkazu v pásmu [P_limit, P_0], což investorovi šetří v průměru 0.5 % až 1.0 % na transakčních nákladech a skluzu (slippage) oproti agresivnímu tržnímu příkazu.", "1. Limitní nákupní pásmo (Quantile Limit Execution):")
    add_bullet(" Pro zamezení uvíznutí kapitálu v málo likvidních emisích (např. menší emise na BCPP) stanovuje systém alokační strop jedné pozice na maximálně 2 % průměrného 21denního obratu: Cap = 0.02 × (P_0 × V_21). Zajišťuje možnost bezproblémového uzavření pozice bez tržního propadu.", "2. Likviditní strop pozice (2% Average Daily Turnover Cap):")

    add_body_p("D. Akademické ukotvení – Přehled 7 výzkumných prací:")

    table_quant = doc.add_table(rows=8, cols=4)
    table_quant.alignment = WD_TABLE_ALIGNMENT.CENTER
    table_quant.autofit = False

    q_headers = ["Výzkumná práce / Zdroj", "Klíčový akademický koncept", "Implementace v SuggestInvest", "Přínos pro model"]
    for i, h in enumerate(q_headers):
        cell = table_quant.cell(0, i)
        set_cell_background(cell, "0f172a")
        set_cell_margins(cell, top=120, bottom=120, left=100, right=100)
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(2)
        r = p.add_run(h)
        r.font.bold = True
        r.font.size = Pt(9.0)
        r.font.color.rgb = RGBColor(255, 255, 255)

    quant_rows = [
        ("HARN: Hierarchical Adaptive Risk Networks", "Hierarchické stochastické sítě modelující volatilitu v různých časových škálách.", "Dynamický Stop-Loss počítaný z 99% 1d VaR a RV_21 namísto fixních -8 %.", "Zabránění zbytečným ztrátám na šumu, adaptace na volatilitu aktiva."),
        ("LiMT: Liquidity & Momentum Thresholding", "Asymetrie likvidity a nelineární prahy objemových šoků pro predikci průrazu.", "Katalyzátor CAT_VOLUME_SHOCK při objemovém Z-skóre z_v ≥ 2.0σ a růstu ceny.", "Včasná detekce velkých institucionálních nákupů před zbytkem trhu."),
        ("OrderFusion+: Multi-Horizon Execution", "Predikce intradenních kvantilů LOB a optimalizace limitních nákupních příkazů.", "Exekuční nákupní pásmo Q_0.10 [P_0 - 0.5×ATR, P_0] a alokační strop 2 % obratu.", "Úspora 0.5–1.0 % na spreadu a tržním dopadu (slippage) při každém vstupu."),
        ("Universal Diffusion IVS", "Difúzní generativní modely pro nelineární dynamiku povrchů volatility.", "Mapování volatility regime (RV_21 a ATR%) pro kalibraci citlivosti AI skórování.", "Přesnější odlišení klidných růstových trendů od rizikových bublin."),
        ("AI & NLP Trading Models (SSRN)", "Kvantifikace informační asymetrie a sentimentové divergence mezi zprávami a cenou.", "Katalyzátor CAT_SENTIMENT_DIVERGENCE propojující RSS feed a momentum delty.", "Identifikace skryté akumulace (pozitivní zprávy bez okamžitého pohybu ceny)."),
        ("Pairs Trading in CEE Equity Markets", "Kointegrace a statistická arbitráž v regionálních středoevropských titulech.", "Katalyzátor CAT_PAIRS_DISCOUNT a sektorové komparativní relace pro BCPP a CEE.", "Využití zpoždění lokálních trhů za západoevropskými sektorovými lídry."),
        ("Decoding the Quant Market", "Makro režimy, faktorové rotace a dynamické vážení modelových signálů.", "Syntéza v Head of Risk systémovém promptu Gemini 3.5 AI s prioritou událostí.", "Robustní eliminace protichůdných signálů a ochrana portfolia.")
    ]

    col_widths = [Inches(1.8), Inches(1.8), Inches(1.9), Inches(1.5)]
    for row_idx, (c0, c1, c2, c3) in enumerate(quant_rows, 1):
        bg = "f8fafc" if row_idx % 2 == 1 else "ffffff"
        for col_idx, text in enumerate([c0, c1, c2, c3]):
            cell = table_quant.cell(row_idx, col_idx)
            set_cell_background(cell, bg)
            set_cell_margins(cell, top=80, bottom=80, left=100, right=100)
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(2)
            r = p.add_run(text)
            r.font.size = Pt(8.5)
            if col_idx == 0:
                r.font.bold = True

    for row in table_quant.rows:
        for idx, width in enumerate(col_widths):
            row.cells[idx].width = width

    doc.add_paragraph().paragraph_format.space_after = Pt(12)

    # ==================== KAPITOLA 6.11: VÝZKUMNÁ DÁVKA 2 ====================
    add_section_header("6.11 Pokročilá syntéza a portfolio management (Výzkumná dávka 2 – Zdroje 8 až 11)", level=2)
    add_body_p(
        "V navazující fázi výzkumu byly do architektury SuggestInvest integrovány poznatky ze čtyř rozsáhlých "
        "diplomových a disertačních prací předních světových univerzit (Massachusetts Institute of Technology, "
        "Brock University, Universidad Politécnica de Madrid a Victoria University). Tato rozšíření posouvají "
        "model od pouhé bodové predikce jednotlivých titulů k sofistikované konstrukci portfolia, dynamické filtraci "
        "tržního sentimentu a modelování bankovního úrokového cyklu."
    )

    add_body_p("A. Masuda TOP 5 Conviction Allocation (MIT MVO Portfolio):")
    add_bullet(" Inspirováno prací Jamese Masudy (MIT EECS 2024), která prokázala, že hybridní modely dosahují špičkového výkonu pouze při spojení prediktivní síly s Mean-Variance optimalizací (MVO). SuggestInvest denně sestavuje modelový koš 5 nejsilnějších titulů s nejvyšším poměrem očekávaného zisku vůči realizované volatilitě a riziku: Conviction = (Target_Upside / max(RV_21, 10)) × (1 + 0.12 × K), kde K je počet aktivních katalyzátorů.", "1. Sharpe Proxy Conviction skóre:")
    add_bullet(" Alokace kapitálu do TOP 5 aktiv probíhá v sestupných vahách 25 %, 25 %, 20 %, 15 % a 15 % při současném uplatnění regionální a měnové diverzifikace (maximálně 2 tituly v identické měně či regionu v koši). Tím je zabráněno nezdravé koncentraci rizika.", "2. Diversifikované vážení portfolia:")

    add_body_p("B. Volatility-Adaptive News Sentiment Filtering (Brock University & UPM Madrid):")
    add_bullet(" Sheraz Ahmad (Brock University 2025) a Juan Luis Ruiz-Tagle (UPM Madrid 2023) prokázali, že vliv zpravodajského sentimentu se zásadně liší napříč sektory a režimy volatility. Vysoce volatilní aktiva (RV_21 ≥ 25 %, např. technologické růstové akcie, krypto-proxies, energetika) reagují na novinky okamžitě s poločasem rozpadu 1–2 dny.", "1. Rychlý sentiment u růstových aktiv:")
    add_bullet(" U nízkovolatilních a defenzivních aktiv (RV_21 ≤ 18 %, např. banky, utility, telekomunikace) působí krátkodobý sentiment jako šum degradující přesnost modelu. SuggestInvest v tomto režimu potlačuje vliv zpráv a klade dominantní důraz na fundamentální valuační diskont a dividendovou stabilitu.", "2. Potlačení šumu u defenzivních titulů:")

    add_body_p("C. Cyklický katalyzátor bankovního sektoru (Victoria University):")
    add_bullet(" Disertační práce Praveena Sadasivana (Victoria University 2024/25) modelující bankovní sektorové indexy identifikovala silnou statistickou závislost (R² > 0.78) mezi úrokovým diferenciálem (výnosovou křivkou) a výkonností bankovních akcií se zpožděním 15 až 30 obchodních dnů. SuggestInvest proto zavedl katalyzátor CAT_FINANCIAL_CYCLE (🏛️ Úrokový cyklus / NIM), který pro bankovní tituly (Erste, KB, Moneta, Santander, BNP Paribas, ING) systematicky zohledňuje stabilitu čisté úrokové marže a prostředí úrokových sazeb.", "Katalyzátor CAT_FINANCIAL_CYCLE:")

    add_body_p("D. Akademické ukotvení – Přehled 4 nových výzkumných prací:")

    table_quant2 = doc.add_table(rows=5, cols=4)
    table_quant2.alignment = WD_TABLE_ALIGNMENT.CENTER
    table_quant2.autofit = False

    for i, h in enumerate(q_headers):
        cell = table_quant2.cell(0, i)
        set_cell_background(cell, "0f172a")
        set_cell_margins(cell, top=120, bottom=120, left=100, right=100)
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(2)
        r = p.add_run(h)
        r.font.bold = True
        r.font.size = Pt(9.0)
        r.font.color.rgb = RGBColor(255, 255, 255)

    quant2_rows = [
        ("James Masuda\n(MIT EECS, 2024)", "Hybridní CNN-LSTM, BiLSTM-BO-LightGBM a Mean-Variance Portfolio Optimization.", "Modul TOP 5 Conviction Basket s MVO váhami 25-25-20-15-15 % a Sharpe proxy.", "Transformace izolovaných tipů na přímo investovatelné, diverzifikované minitportfolio."),
        ("Sheraz Ahmad\n(Brock University, 2025)", "Analýza vlivu sentimentu napříč modely, sektory a režimy tržní volatility.", "Režimové vážení sentimentu (HIGH_VOLATILITY vs. DEFENSIVE_FUNDAMENTAL).", "Eliminace falešných signálů u defenzivních titulů a zrychlení reakce u technologií."),
        ("Juan Luis Ruiz-Tagle\n(UPM Madrid, 2023)", "Predikce krátkodobých trendů pomocí FinBERT a technických indikátorů.", "Pravidlo nepotvrzeného sentimentu v Gemini AI (sentiment vyžaduje technický impuls).", "Ochrana před nákupem do padajícího nože na pouhou 'pozitivní PR zprávu'."),
        ("Praveen Sadasivan\n(Victoria University, 2024/25)", "Predikce bankovních indexů pomocí optimalizovaných AI modelů a úrokových sazeb.", "Katalyzátor CAT_FINANCIAL_CYCLE se zpožděnou transmisí úrokových marží (NIM).", "Přesnější časování vstupů do evropských a českých bank (KB, Erste, Moneta).")
    ]

    for row_idx, (c0, c1, c2, c3) in enumerate(quant2_rows, 1):
        bg = "f8fafc" if row_idx % 2 == 1 else "ffffff"
        for col_idx, text in enumerate([c0, c1, c2, c3]):
            cell = table_quant2.cell(row_idx, col_idx)
            set_cell_background(cell, bg)
            set_cell_margins(cell, top=80, bottom=80, left=100, right=100)
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(2)
            r = p.add_run(text)
            r.font.size = Pt(8.5)
            if col_idx == 0:
                r.font.bold = True

    for row in table_quant2.rows:
        for idx, width in enumerate(col_widths):
            row.cells[idx].width = width

    doc.add_paragraph().paragraph_format.space_after = Pt(12)

    # ==================== KAPITOLA 7: ARCHITEKTURA KOŠŮ ====================
    add_section_header("7. Segmentace univerza: Proč 3 prioritní koše (Tiers)")
    add_body_p(
        "Všech 541 aktiv je kategorizováno do 3 logických košů, které umožňují okamžité filtrování podle investičního stylu:"
    )

    table_tiers = doc.add_table(rows=4, cols=4)
    table_tiers.alignment = WD_TABLE_ALIGNMENT.CENTER
    table_tiers.autofit = False

    t_headers = ["Koš (Tier)", "Počet aktiv", "Charakteristika a složení", "Účel v portfoliu"]
    for i, h in enumerate(t_headers):
        cell = table_tiers.cell(0, i)
        set_cell_background(cell, "0f172a")
        set_cell_margins(cell, top=120, bottom=120, left=100, right=100)
        p = cell.paragraphs[0]
        p.paragraph_format.space_after = Pt(2)
        r = p.add_run(h)
        r.font.bold = True
        r.font.size = Pt(9.0)
        r.font.color.rgb = RGBColor(255, 255, 255)

    tier_rows = [
        ("🥇 TIER 1\nTOP Leaders", "48 aktiv", "US Mega-Caps (Apple, Nvidia, Microsoft, Amazon), kompletní BCPP v CZK (ČEZ, banky, Colt), evropské stálice (ASML, SAP) a klíčová indexová ETF (S&P 500, All-World, Nasdaq).", "Základní stavební kameny, nejvyšší likvidita, globální tržní kapitalizace a minimální spread."),
        ("🥈 TIER 2\nMID Growth", "472 aktiv", "Rozsáhlé spektrum světových blue-chips (A–Z), polovodičoví lídři, jaderná energetika, obranný sektor, kosmonautika, krypto-proxies a sektorová UCITS ETF na XTB.", "Růstový potenciál, sektorové megatrendy a diverzifikace napříč kontinenty i měnami."),
        ("🥉 TIER 3\nLOW Discovery", "21 aktiv", "Vysoce volatilní tituly, obratové (turnaround) akcie, čínské tech akcie v US a průkopnická biotechnologie.", "Asymetrický poměr rizika a výnosu pro dynamickou část kapitálu.")
    ]

    for row_idx, (c0, c1, c2, c3) in enumerate(tier_rows, 1):
        bg = "f8fafc" if row_idx % 2 == 1 else "ffffff"
        for col_idx, text in enumerate([c0, c1, c2, c3]):
            cell = table_tiers.cell(row_idx, col_idx)
            set_cell_background(cell, bg)
            set_cell_margins(cell, top=80, bottom=80, left=100, right=100)
            p = cell.paragraphs[0]
            p.paragraph_format.space_after = Pt(2)
            r = p.add_run(text)
            r.font.size = Pt(8.5)
            if col_idx == 0:
                r.font.bold = True

    doc.add_paragraph().paragraph_format.space_after = Pt(12)

    # ==================== KAPITOLA 8: ZÁVĚR ====================
    add_section_header("8. Závěrečné shrnutí: Přidaná hodnota pro investora")
    add_body_p(
        "Systém SuggestInvest odstraňuje z investičního rozhodování dvě největší slabiny lidského investora: "
        "emoční zkreslení a informační zahlcení. Díky spojení reálných tržních dat z XTB, konsenzu analytiků, "
        "firemních kalendářů a syntézy modelu Google Gemini dostává investor každé ráno ucelený "
        "a forward-looking screening trhu, který mu během několika vteřin ukáže, kde se dnes otevírají nejzajímavější příležitosti."
    )

    # Uložení dokumentu
    doc.save(output_path)
    print(f"Word dokument byl úspěšně vygenerován do: {output_path}")

if __name__ == "__main__":
    out_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Analyza_Dat_a_Metodika_SuggestInvest.docx")
    create_methodology_document(out_file)
