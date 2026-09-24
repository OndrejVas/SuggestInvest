import os
import logging
from typing import List, Dict, Any, Set

from xtb_parser import load_xtb_catalog, map_xtb_to_yahoo

logger = logging.getLogger("Universe")

# ==============================================================================
# 🥇 TIER 1: TOP LEADERS (35 klíčových stálic trhu, indexy a BCPP)
# ==============================================================================
TIER_1_TOP: List[Dict[str, str]] = [
    # US Tech & AI Mega-Caps
    {"xtb_symbol": "NVDA.US", "yahoo_symbol": "NVDA", "name": "NVIDIA Corp", "asset_type": "AKCIE", "currency": "USD", "tier": "TOP"},
    {"xtb_symbol": "AAPL.US", "yahoo_symbol": "AAPL", "name": "Apple Inc", "asset_type": "AKCIE", "currency": "USD", "tier": "TOP"},
    {"xtb_symbol": "MSFT.US", "yahoo_symbol": "MSFT", "name": "Microsoft Corp", "asset_type": "AKCIE", "currency": "USD", "tier": "TOP"},
    {"xtb_symbol": "GOOGL.US", "yahoo_symbol": "GOOGL", "name": "Alphabet Inc (Google)", "asset_type": "AKCIE", "currency": "USD", "tier": "TOP"},
    {"xtb_symbol": "AMZN.US", "yahoo_symbol": "AMZN", "name": "Amazon.com Inc", "asset_type": "AKCIE", "currency": "USD", "tier": "TOP"},
    {"xtb_symbol": "META.US", "yahoo_symbol": "META", "name": "Meta Platforms Inc", "asset_type": "AKCIE", "currency": "USD", "tier": "TOP"},
    {"xtb_symbol": "TSLA.US", "yahoo_symbol": "TSLA", "name": "Tesla Inc", "asset_type": "AKCIE", "currency": "USD", "tier": "TOP"},
    {"xtb_symbol": "PLTR.US", "yahoo_symbol": "PLTR", "name": "Palantir Technologies", "asset_type": "AKCIE", "currency": "USD", "tier": "TOP"},
    {"xtb_symbol": "AMD.US", "yahoo_symbol": "AMD", "name": "Advanced Micro Devices", "asset_type": "AKCIE", "currency": "USD", "tier": "TOP"},
    {"xtb_symbol": "AVGO.US", "yahoo_symbol": "AVGO", "name": "Broadcom Inc", "asset_type": "AKCIE", "currency": "USD", "tier": "TOP"},
    {"xtb_symbol": "INTC.US", "yahoo_symbol": "INTC", "name": "Intel Corp", "asset_type": "AKCIE", "currency": "USD", "tier": "TOP"},
    {"xtb_symbol": "NFLX.US", "yahoo_symbol": "NFLX", "name": "Netflix Inc", "asset_type": "AKCIE", "currency": "USD", "tier": "TOP"},
    {"xtb_symbol": "UBER.US", "yahoo_symbol": "UBER", "name": "Uber Technologies", "asset_type": "AKCIE", "currency": "USD", "tier": "TOP"},

    # US Core Blue-Chips & Finanční lídři
    {"xtb_symbol": "JPM.US", "yahoo_symbol": "JPM", "name": "JPMorgan Chase & Co", "asset_type": "AKCIE", "currency": "USD", "tier": "TOP"},
    {"xtb_symbol": "V.US", "yahoo_symbol": "V", "name": "Visa Inc", "asset_type": "AKCIE", "currency": "USD", "tier": "TOP"},
    {"xtb_symbol": "WMT.US", "yahoo_symbol": "WMT", "name": "Walmart Inc", "asset_type": "AKCIE", "currency": "USD", "tier": "TOP"},
    {"xtb_symbol": "LLY.US", "yahoo_symbol": "LLY", "name": "Eli Lilly and Co", "asset_type": "AKCIE", "currency": "USD", "tier": "TOP"},
    {"xtb_symbol": "XOM.US", "yahoo_symbol": "XOM", "name": "Exxon Mobil Corp", "asset_type": "AKCIE", "currency": "USD", "tier": "TOP"},
    {"xtb_symbol": "BA.US", "yahoo_symbol": "BA", "name": "Boeing Co", "asset_type": "AKCIE", "currency": "USD", "tier": "TOP"},
    {"xtb_symbol": "LMT.US", "yahoo_symbol": "LMT", "name": "Lockheed Martin Corp", "asset_type": "AKCIE", "currency": "USD", "tier": "TOP"},

    # Kompletní likvidní česká burza na XTB (BCPP - CZK)
    {"xtb_symbol": "CEZ1.CZ", "yahoo_symbol": "CEZ.PR", "name": "ČEZ a.s.", "asset_type": "AKCIE", "currency": "CZK", "tier": "TOP"},
    {"xtb_symbol": "KOMB.CZ", "yahoo_symbol": "KOMB.PR", "name": "Komerční banka a.s.", "asset_type": "AKCIE", "currency": "CZK", "tier": "TOP"},
    {"xtb_symbol": "MONET.CZ", "yahoo_symbol": "MONET.PR", "name": "Moneta Money Bank", "asset_type": "AKCIE", "currency": "CZK", "tier": "TOP"},
    {"xtb_symbol": "RBAG.CZ", "yahoo_symbol": "ERBAG.PR", "name": "Erste Group Bank AG", "asset_type": "AKCIE", "currency": "CZK", "tier": "TOP"},
    {"xtb_symbol": "CZG.CZ", "yahoo_symbol": "COLT.PR", "name": "Colt CZ Group SE", "asset_type": "AKCIE", "currency": "CZK", "tier": "TOP"},
    {"xtb_symbol": "TABAK.CZ", "yahoo_symbol": "TABAK.PR", "name": "Philip Morris ČR a.s.", "asset_type": "AKCIE", "currency": "CZK", "tier": "TOP"},
    {"xtb_symbol": "KOFOL.CZ", "yahoo_symbol": "KOFOL.PR", "name": "Kofola ČeskoSlovensko", "asset_type": "AKCIE", "currency": "CZK", "tier": "TOP"},
    {"xtb_symbol": "VIG.CZ", "yahoo_symbol": "VIG.PR", "name": "Vienna Insurance Group", "asset_type": "AKCIE", "currency": "CZK", "tier": "TOP"},

    # Evropští lídři (EUR)
    {"xtb_symbol": "ASML.NL", "yahoo_symbol": "ASML.AS", "name": "ASML Holding NV", "asset_type": "AKCIE", "currency": "EUR", "tier": "TOP"},
    {"xtb_symbol": "SAP.DE", "yahoo_symbol": "SAP.DE", "name": "SAP SE", "asset_type": "AKCIE", "currency": "EUR", "tier": "TOP"},
    {"xtb_symbol": "SIE.DE", "yahoo_symbol": "SIE.DE", "name": "Siemens AG", "asset_type": "AKCIE", "currency": "EUR", "tier": "TOP"},
    {"xtb_symbol": "MC.FR", "yahoo_symbol": "MC.PA", "name": "LVMH Moët Hennessy", "asset_type": "AKCIE", "currency": "EUR", "tier": "TOP"},
    {"xtb_symbol": "AIR.FR", "yahoo_symbol": "AIR.PA", "name": "Airbus SE", "asset_type": "AKCIE", "currency": "EUR", "tier": "TOP"},

    # Klíčová XTB UCITS ETF
    {"xtb_symbol": "VWCE.DE", "yahoo_symbol": "VWCE.DE", "name": "Vanguard FTSE All-World ETF", "asset_type": "ETF", "currency": "EUR", "tier": "TOP"},
    {"xtb_symbol": "SXR8.DE", "yahoo_symbol": "SXR8.DE", "name": "iShares Core S&P 500 ETF", "asset_type": "ETF", "currency": "EUR", "tier": "TOP"},
    {"xtb_symbol": "QDVE.DE", "yahoo_symbol": "QDVE.DE", "name": "iShares S&P 500 Info Tech ETF", "asset_type": "ETF", "currency": "EUR", "tier": "TOP"},
    {"xtb_symbol": "EUNL.DE", "yahoo_symbol": "EUNL.DE", "name": "iShares Core MSCI World ETF", "asset_type": "ETF", "currency": "EUR", "tier": "TOP"},

    # Krypto benchmark
    {"xtb_symbol": "BTC-USD", "yahoo_symbol": "BTC-USD", "name": "Bitcoin USD", "asset_type": "KRYPTO", "currency": "USD", "tier": "TOP"},
]

# ==============================================================================
# 🥈 TIER 2: MID GROWTH & THEMATIC (48 aktiv: Polovodiče, Uran, Kosmonautika, DAX)
# ==============================================================================
TIER_2_MID: List[Dict[str, str]] = [
    # AI Hardware, Polovodiče & Software
    {"xtb_symbol": "ARM.US", "yahoo_symbol": "ARM", "name": "Arm Holdings plc", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},
    {"xtb_symbol": "SMCI.US", "yahoo_symbol": "SMCI", "name": "Super Micro Computer", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},
    {"xtb_symbol": "QCOM.US", "yahoo_symbol": "QCOM", "name": "Qualcomm Inc", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},
    {"xtb_symbol": "TXN.US", "yahoo_symbol": "TXN", "name": "Texas Instruments", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},
    {"xtb_symbol": "MU.US", "yahoo_symbol": "MU", "name": "Micron Technology", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},
    {"xtb_symbol": "ADBE.US", "yahoo_symbol": "ADBE", "name": "Adobe Inc", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},
    {"xtb_symbol": "CRM.US", "yahoo_symbol": "CRM", "name": "Salesforce Inc", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},
    {"xtb_symbol": "ORCL.US", "yahoo_symbol": "ORCL", "name": "Oracle Corp", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},
    {"xtb_symbol": "CSCO.US", "yahoo_symbol": "CSCO", "name": "Cisco Systems", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},
    {"xtb_symbol": "IBM.US", "yahoo_symbol": "IBM", "name": "International Business Machines", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},

    # Jaderná energie, Uran a nová energetika
    {"xtb_symbol": "CCJ.US", "yahoo_symbol": "CCJ", "name": "Cameco Corp (Uranium)", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},
    {"xtb_symbol": "SMR.US", "yahoo_symbol": "SMR", "name": "NuScale Power (SMR Nuclear)", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},
    {"xtb_symbol": "OKLO.US", "yahoo_symbol": "OKLO", "name": "Oklo Inc (Advanced Fission)", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},
    {"xtb_symbol": "UEC.US", "yahoo_symbol": "UEC", "name": "Uranium Energy Corp", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},
    {"xtb_symbol": "FSLR.US", "yahoo_symbol": "FSLR", "name": "First Solar Inc", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},
    {"xtb_symbol": "NUKL.DE", "yahoo_symbol": "NUKL.DE", "name": "VanEck Uranium & Nuclear ETF", "asset_type": "ETF", "currency": "EUR", "tier": "MID"},

    # Krypto proxies & FinTech
    {"xtb_symbol": "MSTR.US", "yahoo_symbol": "MSTR", "name": "MicroStrategy Inc", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},
    {"xtb_symbol": "COIN.US", "yahoo_symbol": "COIN", "name": "Coinbase Global Inc", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},
    {"xtb_symbol": "SOFI.US", "yahoo_symbol": "SOFI", "name": "SoFi Technologies", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},
    {"xtb_symbol": "HOOD.US", "yahoo_symbol": "HOOD", "name": "Robinhood Markets", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},
    {"xtb_symbol": "PYPL.US", "yahoo_symbol": "PYPL", "name": "PayPal Holdings", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},
    {"xtb_symbol": "BTCE.DE", "yahoo_symbol": "BTCE.DE", "name": "BTCetc Physical Bitcoin ETC", "asset_type": "ETF", "currency": "EUR", "tier": "MID"},

    # Kosmický sektor, Kvantum & Obrana
    {"xtb_symbol": "RKLB.US", "yahoo_symbol": "RKLB", "name": "Rocket Lab USA", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},
    {"xtb_symbol": "ASTS.US", "yahoo_symbol": "ASTS", "name": "AST SpaceMobile", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},
    {"xtb_symbol": "IONQ.US", "yahoo_symbol": "IONQ", "name": "IonQ Inc (Quantum)", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},
    {"xtb_symbol": "RGTI.US", "yahoo_symbol": "RGTI", "name": "Rigetti Computing", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},
    {"xtb_symbol": "RTX.US", "yahoo_symbol": "RTX", "name": "RTX Corp (Raytheon)", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},
    {"xtb_symbol": "NOC.US", "yahoo_symbol": "NOC", "name": "Northrop Grumman Corp", "asset_type": "AKCIE", "currency": "USD", "tier": "MID"},

    # Němečtí a francouzští lídři (DAX & CAC - EUR)
    {"xtb_symbol": "BMW.DE", "yahoo_symbol": "BMW.DE", "name": "Bayerische Motoren Werke (BMW)", "asset_type": "AKCIE", "currency": "EUR", "tier": "MID"},
    {"xtb_symbol": "MBG.DE", "yahoo_symbol": "MBG.DE", "name": "Mercedes-Benz Group", "asset_type": "AKCIE", "currency": "EUR", "tier": "MID"},
    {"xtb_symbol": "VOW3.DE", "yahoo_symbol": "VOW3.DE", "name": "Volkswagen AG", "asset_type": "AKCIE", "currency": "EUR", "tier": "MID"},
    {"xtb_symbol": "ALV.DE", "yahoo_symbol": "ALV.DE", "name": "Allianz SE", "asset_type": "AKCIE", "currency": "EUR", "tier": "MID"},
    {"xtb_symbol": "DTE.DE", "yahoo_symbol": "DTE.DE", "name": "Deutsche Telekom AG", "asset_type": "AKCIE", "currency": "EUR", "tier": "MID"},
    {"xtb_symbol": "BAS.DE", "yahoo_symbol": "BAS.DE", "name": "BASF SE", "asset_type": "AKCIE", "currency": "EUR", "tier": "MID"},
    {"xtb_symbol": "OR.FR", "yahoo_symbol": "OR.PA", "name": "L'Oréal SA", "asset_type": "AKCIE", "currency": "EUR", "tier": "MID"},
    {"xtb_symbol": "TTE.FR", "yahoo_symbol": "TTE.PA", "name": "TotalEnergies SE", "asset_type": "AKCIE", "currency": "EUR", "tier": "MID"},
    {"xtb_symbol": "SAN.FR", "yahoo_symbol": "SAN.PA", "name": "Sanofi SA", "asset_type": "AKCIE", "currency": "EUR", "tier": "MID"},
    {"xtb_symbol": "RMS.FR", "yahoo_symbol": "RMS.PA", "name": "Hermes International", "asset_type": "AKCIE", "currency": "EUR", "tier": "MID"},

    # Sektorová & Komoditní ETF na XTB (EUR)

    {"xtb_symbol": "4GLD.DE", "yahoo_symbol": "4GLD.DE", "name": "Xetra-Gold ETC", "asset_type": "ETF", "currency": "EUR", "tier": "MID"},
    {"xtb_symbol": "CBRS.DE", "yahoo_symbol": "CBRS.DE", "name": "First Trust Nasdaq Cybersecurity ETF", "asset_type": "ETF", "currency": "EUR", "tier": "MID"},
    {"xtb_symbol": "EQQQ.DE", "yahoo_symbol": "EQQQ.DE", "name": "Invesco EQQQ Nasdaq-100 ETF", "asset_type": "ETF", "currency": "EUR", "tier": "MID"},
    {"xtb_symbol": "IS3N.DE", "yahoo_symbol": "IS3N.DE", "name": "iShares Core Emerging Markets ETF", "asset_type": "ETF", "currency": "EUR", "tier": "MID"},
    {"xtb_symbol": "IUSN.DE", "yahoo_symbol": "IUSN.DE", "name": "iShares MSCI World Small Cap ETF", "asset_type": "ETF", "currency": "EUR", "tier": "MID"},
    {"xtb_symbol": "VUSA.DE", "yahoo_symbol": "VUSA.DE", "name": "Vanguard S&P 500 ETF (Dist)", "asset_type": "ETF", "currency": "EUR", "tier": "MID"},
]

# ==============================================================================
# 🥉 TIER 3: LOW / SPECULATIVE DISCOVERY (28 aktiv: Momentum, Biotech, Čína, EV)
# ==============================================================================
TIER_3_LOW: List[Dict[str, str]] = [
    # Krypto těžaři & Momentum
    {"xtb_symbol": "MARA.US", "yahoo_symbol": "MARA", "name": "MARA Holdings (Bitcoin Mining)", "asset_type": "AKCIE", "currency": "USD", "tier": "LOW"},
    {"xtb_symbol": "RIOT.US", "yahoo_symbol": "RIOT", "name": "Riot Platforms", "asset_type": "AKCIE", "currency": "USD", "tier": "LOW"},

    # Robotika & Automatizace
    {"xtb_symbol": "SYM.US", "yahoo_symbol": "SYM", "name": "Symbotic Inc (AI Robotics)", "asset_type": "AKCIE", "currency": "USD", "tier": "LOW"},
    {"xtb_symbol": "PATH.US", "yahoo_symbol": "PATH", "name": "UiPath Inc (Automation)", "asset_type": "AKCIE", "currency": "USD", "tier": "LOW"},

    # Baterie & Zelená transformace
    {"xtb_symbol": "QS.US", "yahoo_symbol": "QS", "name": "QuantumScape (Solid-State)", "asset_type": "AKCIE", "currency": "USD", "tier": "LOW"},
    {"xtb_symbol": "ENPH.US", "yahoo_symbol": "ENPH", "name": "Enphase Energy", "asset_type": "AKCIE", "currency": "USD", "tier": "LOW"},
    {"xtb_symbol": "PLUG.US", "yahoo_symbol": "PLUG", "name": "Plug Power Inc", "asset_type": "AKCIE", "currency": "USD", "tier": "LOW"},
    {"xtb_symbol": "ALB.US", "yahoo_symbol": "ALB", "name": "Albemarle Corp (Lithium)", "asset_type": "AKCIE", "currency": "USD", "tier": "LOW"},

    # Čínské růstové technologické akcie
    {"xtb_symbol": "BABA.US", "yahoo_symbol": "BABA", "name": "Alibaba Group Holding", "asset_type": "AKCIE", "currency": "USD", "tier": "LOW"},
    {"xtb_symbol": "NIO.US", "yahoo_symbol": "NIO", "name": "NIO Inc (EV Mobility)", "asset_type": "AKCIE", "currency": "USD", "tier": "LOW"},
    {"xtb_symbol": "BIDU.US", "yahoo_symbol": "BIDU", "name": "Baidu Inc (China AI)", "asset_type": "AKCIE", "currency": "USD", "tier": "LOW"},
    {"xtb_symbol": "JD.US", "yahoo_symbol": "JD", "name": "JD.com Inc", "asset_type": "AKCIE", "currency": "USD", "tier": "LOW"},

    # Biotech & Genomika
    {"xtb_symbol": "CRSP.US", "yahoo_symbol": "CRSP", "name": "CRISPR Therapeutics", "asset_type": "AKCIE", "currency": "USD", "tier": "LOW"},
    {"xtb_symbol": "DNA.US", "yahoo_symbol": "DNA", "name": "Ginkgo Bioworks", "asset_type": "AKCIE", "currency": "USD", "tier": "LOW"},

    # EV Mobility & Satelity
    {"xtb_symbol": "RIVN.US", "yahoo_symbol": "RIVN", "name": "Rivian Automotive", "asset_type": "AKCIE", "currency": "USD", "tier": "LOW"},
    {"xtb_symbol": "LCID.US", "yahoo_symbol": "LCID", "name": "Lucid Group", "asset_type": "AKCIE", "currency": "USD", "tier": "LOW"},
    {"xtb_symbol": "PL.US", "yahoo_symbol": "PL", "name": "Planet Labs PBC", "asset_type": "AKCIE", "currency": "USD", "tier": "LOW"},

    # Tradiční giganti s potenciálem obratu
    {"xtb_symbol": "DIS.US", "yahoo_symbol": "DIS", "name": "Walt Disney Co", "asset_type": "AKCIE", "currency": "USD", "tier": "LOW"},
    {"xtb_symbol": "CAT.US", "yahoo_symbol": "CAT", "name": "Caterpillar Inc", "asset_type": "AKCIE", "currency": "USD", "tier": "LOW"},
    {"xtb_symbol": "GE.US", "yahoo_symbol": "GE", "name": "GE Aerospace", "asset_type": "AKCIE", "currency": "USD", "tier": "LOW"},
    {"xtb_symbol": "INGA.NL", "yahoo_symbol": "INGA.AS", "name": "ING Groep NV", "asset_type": "AKCIE", "currency": "EUR", "tier": "LOW"},
]


def load_custom_watchlist(file_path: str = "watchlist.txt") -> List[Dict[str, str]]:
    """Načte volitelný uživatelský seznam XTB symbolů ze souboru watchlist.txt a spáruje je s katalogem."""
    custom_items = []
    if not os.path.exists(file_path):
        return custom_items

    catalog = load_xtb_catalog()
    catalog_map = {item["xtb_symbol"].upper(): item for item in catalog}

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = [line.strip().upper() for line in f if line.strip() and not line.startswith("#")]

        for sym in lines:
            if sym in catalog_map:
                it = catalog_map[sym]
                custom_items.append({
                    "xtb_symbol": it["xtb_symbol"],
                    "yahoo_symbol": it["yahoo_symbol"],
                    "name": it["name"],
                    "asset_type": it["asset_type"],
                    "currency": it["currency"],
                    "tier": "TOP", # Vlastní položky řadíme prioritně
                })
            else:
                yahoo_sym = map_xtb_to_yahoo(sym)
                custom_items.append({
                    "xtb_symbol": sym,
                    "yahoo_symbol": yahoo_sym,
                    "name": sym,
                    "asset_type": "AKCIE",
                    "currency": "USD",
                    "tier": "TOP",
                })
        logger.info(f"Načteno {len(custom_items)} vlastních titulů ze souboru {file_path}.")
    except Exception as e:
        logger.warning(f"Chyba při čtení {file_path}: {e}")

    return custom_items


def get_all_universe(tiers: List[str] = None) -> List[Dict[str, str]]:
    """Sestaví kompletní univerzum aktiv pro skener (včetně vlastního watchlistu bez duplicit)."""
    selected = []
    if tiers is None:
        tiers = ["TOP", "MID", "LOW"]

    tier_upper = [t.upper() for t in tiers]
    if "TOP" in tier_upper or "1" in tier_upper:
        selected.extend(TIER_1_TOP)
    if "MID" in tier_upper or "2" in tier_upper:
        selected.extend(TIER_2_MID)
        # Načtení rozšířených balíků titulů (A-L a M-Z včetně top ETF)
        for b_name in ["universe_batch_a_l.json", "universe_batch_m_z.json"]:
            batch_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), b_name)
            if os.path.exists(batch_file):
                try:
                    import json
                    with open(batch_file, "r", encoding="utf-8") as f:
                        selected.extend(json.load(f))
                except Exception as e:
                    logger.warning(f"Chyba při čtení {batch_file}: {e}")
    if "LOW" in tier_upper or "3" in tier_upper:
        selected.extend(TIER_3_LOW)

    # Načtení případného vlastního watchlist.txt
    custom = load_custom_watchlist()
    if custom:
        selected = custom + selected

    # Deduplikace podle yahoo_symbol a vyřazení GBP
    seen_symbols: Set[str] = set()
    unique_items: List[Dict[str, str]] = []
    for item in selected:
        if item.get("currency") == "GBP":
            continue
        sym = item["yahoo_symbol"].upper()
        if sym not in seen_symbols:
            seen_symbols.add(sym)
            unique_items.append(item)

    return unique_items


if __name__ == "__main__":
    u = get_all_universe()
    print(f"Celkem aktivních položek v univerzu: {len(u)}")
    by_tier = {}
    for x in u:
        by_tier[x['tier']] = by_tier.get(x['tier'], 0) + 1
    print("Rozdělení dle košů:", by_tier)
