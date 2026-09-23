import os
import sys
import re
import json
import logging
from typing import List, Dict, Any, Optional

try:
    import pypdfium2 as pdfium
except ImportError:
    pdfium = None

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("XTBParser")

DEFAULT_PDF_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spectabomicz29062026.pdf")
DEFAULT_JSON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "xtb_catalog.json")

# Mapování specifických českých a evropských tickerů z XTB na Yahoo Finance
EXCHANGE_MAPPING = {
    "CEZ1.CZ": "CEZ.PR",
    "CZG.CZ": "CZG.PR",
    "COLT.CZ": "CZG.PR",
    "KOFOL.CZ": "KOFOL.PR",
    "KOMB.CZ": "KOMB.PR",
    "MONET.CZ": "MONET.PR",
    "RBAG.CZ": "ERBAG.PR",
    "TABAK.CZ": "TABAK.PR",
    "VIG.CZ": "VIG.PR",
}


def map_xtb_to_yahoo(xtb_symbol: str) -> str:
    """Převede symbol z XTB na odpovídající symbol pro Yahoo Finance / tržní data."""
    s = xtb_symbol.replace("*", "").strip()
    if s in EXCHANGE_MAPPING:
        return EXCHANGE_MAPPING[s]
    
    # Americké akcie a ETF (AAPL.US -> AAPL)
    if s.endswith(".US"):
        return s[:-3]
    # Německá Xetra (SAP.DE -> SAP.DE)
    if s.endswith(".DE"):
        return s
    # Londýnská burza LSE (.UK -> .L)
    if s.endswith(".UK"):
        return s[:-3] + ".L"
    # Paříž Euronext (.FR -> .PA)
    if s.endswith(".FR"):
        return s[:-3] + ".PA"
    # Amsterdam Euronext (.NL -> .AS)
    if s.endswith(".NL"):
        return s[:-3] + ".AS"
    # Milán Borsa Italiana (.IT -> .MI)
    if s.endswith(".IT"):
        return s[:-3] + ".MI"
    # Madrid BME (.ES -> .MC)
    if s.endswith(".ES"):
        return s[:-3] + ".MC"
    # Varšavská burza GPW (.PL -> .WA)
    if s.endswith(".PL"):
        return s[:-3] + ".WA"
    
    return s


def parse_xtb_pdf(pdf_path: str = DEFAULT_PDF_PATH) -> List[Dict[str, Any]]:
    """Vyparsuje XTB specifikační tabulku z PDF a vyřadí mrtvý odpad (CLOSE ONLY)."""
    if not pdfium:
        raise ImportError("Knihovna 'pypdfium2' není nainstalována. Spusťte: pip install pypdfium2")
        
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF soubor nebyl nalezen: {pdf_path}")

    logger.info(f"Otevírám a analyzuji XTB PDF: {pdf_path}")
    pdf = pdfium.PdfDocument(pdf_path)
    total_pages = len(pdf)
    logger.info(f"Celkem načteno {total_pages} stran PDF.")

    isin_pattern = re.compile(r"\b([A-Z]{2}[A-Z0-9]{9}\d)\b")
    
    instruments = []
    close_only_count = 0

    for p_num in range(1, total_pages):
        text = pdf[p_num].get_textpage().get_text_range()
        is_etf_section = (p_num >= 121) # Strana 122+ je sekce ETF, ETN, ETC

        for line in text.split("\n"):
            line_str = line.strip()
            if not line_str:
                continue

            # TRASH FILTER: Okamžité vyřazení titulů CLOSE ONLY (zavřené pozice, delistované, nelze koupit)
            if "CLOSE ONLY" in line_str or "Close only" in line_str or "CLOSE_ONLY" in line_str:
                close_only_count += 1
                continue

            m = isin_pattern.search(line_str)
            if m:
                isin = m.group(1)
                parts = line_str.split(isin)
                if len(parts) >= 2:
                    left = parts[0].strip()
                    right = parts[1].strip()
                    tokens_left = left.split()
                    tokens_right = right.split()

                    if tokens_left and tokens_right:
                        raw_symbol = tokens_left[0]
                        # Název společnosti (zbytek textu před ISIN)
                        name = " ".join(tokens_left[1:]).strip()
                        if not name:
                            name = raw_symbol
                            
                        # Měna je první token za ISIN
                        currency = tokens_right[0].upper()
                        
                        # Určení typu aktiva
                        if is_etf_section or any(k in line_str for k in ["ETF", "ETN", "ETC", "UCITS"]):
                            asset_type = "ETF"
                        else:
                            asset_type = "AKCIE"

                        xtb_symbol = raw_symbol.replace("*", "").strip()
                        yahoo_symbol = map_xtb_to_yahoo(xtb_symbol)

                        instruments.append({
                            "xtb_symbol": xtb_symbol,
                            "yahoo_symbol": yahoo_symbol,
                            "name": name,
                            "isin": isin,
                            "currency": currency,
                            "asset_type": asset_type
                        })

    logger.info(f"Parsování dokončeno: Zpracováno {len(instruments)} platných instrumentů.")
    logger.info(f"Vyřazeno jako odpad (CLOSE ONLY): {close_only_count} instrumentů.")
    return instruments


def build_and_save_catalog(pdf_path: str = DEFAULT_PDF_PATH, json_path: str = DEFAULT_JSON_PATH) -> List[Dict[str, Any]]:
    """Vygeneruje a uloží XTB katalog do JSON souboru pro bleskové načítání."""
    instruments = parse_xtb_pdf(pdf_path)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(instruments, f, ensure_ascii=False, indent=2)
    logger.info(f"Katalog byl úspěšně uložen do: {json_path}")
    return instruments


def load_xtb_catalog(json_path: str = DEFAULT_JSON_PATH, auto_rebuild: bool = True) -> List[Dict[str, Any]]:
    """Načte předem vygenerovaný katalog z JSONu, nebo jej automaticky vygeneruje z PDF."""
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    elif auto_rebuild and os.path.exists(DEFAULT_PDF_PATH):
        return build_and_save_catalog(DEFAULT_PDF_PATH, json_path)
    else:
        logger.warning(f"Katalog {json_path} ani zdrojové PDF nebyly nalezeny.")
        return []


if __name__ == "__main__":
    build_and_save_catalog()
