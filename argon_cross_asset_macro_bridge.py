"""
ARGON V2.5 - CROSS-ASSET & MACRO SNAPSHOT BRIDGE (history.db -> MGC / XAUUSD)
=============================================================================
Propojuje existující databázi akciového a makro skeneru SuggestInvest
(data/history/history.db -> tabulky 'macro_snapshots' a 'signal_history')
přímo s obchodním modelem na Zlato (COMEX MGC v backtest.html, FutureInvestDemo.html a XAU/USD ve scalping.html).

Zohledňuje:
1. Výnos 10Y US Treasuries (^TNX) a výnosovou křivku (10Y-3M)
2. CBOE VIX volatilitu a kreditní spready HYG/LQD
3. Sektorový radar: Rotace do Technologií & AI (XLK) vs. Bankovní stres (XLF) a Komodity (XLE)
4. Sentiment komoditních a těžařských proxy titulů (4GLD.DE, B.US, AGI.US, FCX.US) z 558 titulů
5. Zprávy, katalyzátory a objemové šoky z denního skeneru
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import sqlite3
import json
import logging
import sys
from typing import Dict, List, Optional, Tuple
import numpy as np

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

logger = logging.getLogger("ArgonCrossAssetBridge")


@dataclass
class CrossAssetMacroState:
    """Data načtená z databáze data/history/history.db a index.html."""
    scan_date: str
    barometer_score: float = 33.6          # Celkové skóre Makro Barometru (0-100)
    us10y_yield_pct: float = 5.24          # Výnos 10Y US Treasuries (^TNX v %)
    yield_curve_10y_3m: float = 1.19       # Spread 10Y - 3M v %
    hyg_lqd_ratio_dev_pct: float = 0.47    # Odchylka HYG/LQD od 50d MA v %
    vix_level: float = 14.84               # CBOE ^VIX
    xly_xlp_trend_pct: float = -0.95       # Spotřebitelský cyklus XLY/XLP v %
    xlk_vs_spy_1m_pct: float = 3.92        # Technologie & AI (XLK) 1M vs SPY (rotace do AI akcií)
    xlf_vs_spy_1m_pct: float = -6.18       # Banky (XLF) 1M vs SPY (indikátor bankovního stresu)
    xlf_risk_pct: float = 78.0             # Riziko bankovního sektoru
    xle_vs_spy_1m_pct: float = -1.62       # Energie & Komodity (XLE) 1M vs SPY
    universe_bearish_pct: float = 0.20     # Podíl SELL/STRONG SELL ze všech 558 aktiv v %
    universe_bullish_pct: float = 9.30     # Podíl BUY/STRONG BUY v %
    gold_proxies_net_sentiment: float = 0.0 # Průměrný sentiment komoditních/těžařských titulů v [-1, +1]
    active_catalysts: List[str] = field(default_factory=list)
    recent_news_events: List[str] = field(default_factory=list)


class SuggestInvestCrossAssetBridge:
    """
    Čte živá data z data/history/history.db (která generuje akciový skener SuggestInvest)
    a převádí je na kvantitativní váhy a exekuční multiplikátory pro Zlato (MGC / XAUUSD).
    """

    def __init__(self, history_db_path: Optional[str] = None):
        if history_db_path is None:
            base_dir = Path(__file__).resolve().parent
            history_db_path = base_dir / "data" / "history" / "history.db"
        self.db_path = Path(history_db_path)

    def fetch_latest_macro_snapshot(self, target_date: Optional[str] = None) -> CrossAssetMacroState:
        """
        Načte poslední (nebo k danému datu příslušný) makro snímek, šíři trhu a zprávy z history.db.
        Pokud databáze není nalezena, vrátí kalibrovaný stav z říjnového skeneru.
        """
        state = CrossAssetMacroState(scan_date=target_date or "2026-10-13")
        if not self.db_path.exists():
            logger.warning(f"Databáze history.db nenalezena na {self.db_path}, použit defaultní snímek.")
            return state

        try:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()

                # 1. Načtení z tabulky macro_snapshots
                if target_date:
                    cur.execute(
                        "SELECT * FROM macro_snapshots WHERE scan_date <= ? ORDER BY scan_date DESC, id DESC LIMIT 1",
                        (target_date,),
                    )
                else:
                    cur.execute("SELECT * FROM macro_snapshots ORDER BY scan_date DESC, id DESC LIMIT 1")
                row = cur.fetchone()

                if row:
                    state.scan_date = str(row["scan_date"])
                    if "composite_index" in row.keys() and row["composite_index"] is not None:
                        state.barometer_score = float(row["composite_index"])

                    # Rozbalení detailního JSONu (subfactors a sector_radar)
                    if "macro_json" in row.keys() and row["macro_json"]:
                        try:
                            mj = json.loads(row["macro_json"])
                            sub = mj.get("subfactors", {})
                            
                            # Výnosová křivka
                            yc = sub.get("yield_curve", {})
                            if "tnx_10y" in yc:
                                state.us10y_yield_pct = float(yc["tnx_10y"])
                            if "spread_10y_3m" in yc:
                                state.yield_curve_10y_3m = float(yc["spread_10y_3m"])

                            # Kreditní spready
                            cs = sub.get("credit_spread", {})
                            if "delta_50d_pct" in cs:
                                state.hyg_lqd_ratio_dev_pct = float(cs["delta_50d_pct"])

                            # Volatilita
                            vol = sub.get("volatility", {})
                            if "vix" in vol:
                                state.vix_level = float(vol["vix"])

                            # Spotřebitelský cyklus
                            cons = sub.get("consumer_cycle", {})
                            if "cons_trend_50d_pct" in cons:
                                state.xly_xlp_trend_pct = float(cons["cons_trend_50d_pct"])

                            # Šíře trhu
                            br = sub.get("breadth", {})
                            if "pct_bearish_signals" in br:
                                state.universe_bearish_pct = float(br["pct_bearish_signals"])
                            if "pct_bullish_signals" in br:
                                state.universe_bullish_pct = float(br["pct_bullish_signals"])

                            # Sektorový radar (podpora pro list i dict)
                            sr = mj.get("sector_radar", [])
                            if isinstance(sr, dict):
                                for sym, sec in sr.items():
                                    if isinstance(sec, dict):
                                        diff = float(sec.get("diff", sec.get("rel_1m", 0.0)))
                                        if sym == "XLK":
                                            state.xlk_vs_spy_1m_pct = diff
                                        elif sym == "XLF":
                                            state.xlf_vs_spy_1m_pct = diff
                                            state.xlf_risk_pct = float(sec.get("recession_risk", 78.0))
                                        elif sym == "XLE":
                                            state.xle_vs_spy_1m_pct = diff
                            elif isinstance(sr, list):
                                for sec in sr:
                                    if isinstance(sec, dict):
                                        sym = sec.get("symbol", "")
                                        rel1m = float(sec.get("rel_1m", 0.0))
                                        if sym == "XLK":
                                            state.xlk_vs_spy_1m_pct = rel1m
                                        elif sym == "XLF":
                                            state.xlf_vs_spy_1m_pct = rel1m
                                            state.xlf_risk_pct = float(sec.get("recession_risk", 78.0))
                                        elif sym == "XLE":
                                            state.xle_vs_spy_1m_pct = rel1m

                        except Exception as e:
                            logger.warning(f"Chyba při parsování macro_json: {e}")

                # 2. Načtení sentimentu komoditních / těžařských titulů z signal_history
                cur.execute(
                    """
                    SELECT xtb_symbol, yahoo_symbol, name, signal, confidence, catalysts, catalyst_event
                    FROM signal_history
                    WHERE scan_date = ?
                      AND (xtb_symbol LIKE '%GLD%' OR xtb_symbol LIKE '%GDX%' OR xtb_symbol LIKE '%NEM%'
                           OR xtb_symbol LIKE '%GOLD%' OR xtb_symbol LIKE '%FCX%' OR xtb_symbol LIKE '%AGI%'
                           OR xtb_symbol LIKE '%B.US%' OR name LIKE '%Gold%' OR name LIKE '%Mining%')
                    """,
                    (state.scan_date,),
                )
                proxy_rows = cur.fetchall()
                if proxy_rows:
                    scores = []
                    for pr in proxy_rows:
                        sig = str(pr["signal"]).upper()
                        conf = float(pr["confidence"] or 50.0) / 100.0
                        if "STRONG BUY" in sig:
                            scores.append(1.0 * conf)
                        elif "BUY" in sig:
                            scores.append(0.5 * conf)
                        elif "STRONG SELL" in sig:
                            scores.append(-1.0 * conf)
                        elif "SELL" in sig:
                            scores.append(-0.5 * conf)
                        else:
                            scores.append(0.0)

                        cat_ev = pr["catalyst_event"]
                        if cat_ev and len(cat_ev) > 3:
                            state.recent_news_events.append(f"{pr['yahoo_symbol']}: {cat_ev}")

                    if scores:
                        state.gold_proxies_net_sentiment = float(np.mean(scores))

                # 3. Načtení agregovaných katalyzátorů zpráv (Volume shocks, Earnings, Sentiment divergence)
                cur.execute(
                    """
                    SELECT catalysts, catalyst_event, COUNT(*) as cnt
                    FROM signal_history
                    WHERE scan_date = ? AND catalysts IS NOT NULL AND length(catalysts) > 4
                    GROUP BY catalysts
                    ORDER BY cnt DESC
                    LIMIT 8
                    """,
                    (state.scan_date,)
                )
                cat_rows = cur.fetchall()
                for cr in cat_rows:
                    try:
                        cats = json.loads(cr["catalysts"])
                        if isinstance(cats, list):
                            for c in cats:
                                if c not in state.active_catalysts:
                                    state.active_catalysts.append(c)
                    except Exception:
                        pass

        except Exception as exc:
            logger.error(f"[CrossAssetBridge] Chyba při čtení databáze: {exc}")

        return state

    @staticmethod
    def evaluate_cross_asset_gold_multipliers(
        state: CrossAssetMacroState,
        current_gold_price: Optional[float] = None,
        high_30d: Optional[float] = None,
    ) -> Dict[str, object]:
        """
        Převádí stav 558 akcií, sektorových ETF (XLK, XLF, XLE) a dluhopisů (10Y, HYG/LQD)
        na multiplikátory pro Zlato (MGC / XAUUSD):
        - long_multiplier: [0.0 až 1.35]
        - short_multiplier: [0.0 až 1.35]
        - cross_asset_regime: textový kód a název režimu
        - reasons: detailní kvantitativní zdůvodnění
        - news_signals: vliv novinových zpráv a tržních šoků
        """
        long_mult = 1.0
        short_mult = 1.0
        reasons = []
        regimes = []

        # PRAVIDLO 1: "Tech/AI Melt-Up & High Yield Drain" (Případ Září a Říjen 2026)
        # Když 10Y US Treasury nese >= 4.85 % (v říjnu 5.24 %), VIX je klidný (< 17.5)
        # a kapitál masivně teče do AI akcií (XLK vs SPY >= +2.5 %), institucionální kapitál
        # opouští zlato. Tlumíme Longy a odemykáme Shorty!
        if (
            state.us10y_yield_pct >= 4.85
            and state.vix_level < 17.5
            and state.xlk_vs_spy_1m_pct >= 2.50
        ):
            long_mult *= 0.45
            short_mult *= 1.25
            regimes.append("EQUITY_RISK_ON_HIGH_YIELD_DRAIN")
            reasons.append(
                f"ODLIV_DO_AI_AKCII: 10Y={state.us10y_yield_pct:.2f}% nese vysoký bezrizikový výnos, VIX={state.vix_level:.1f} je klidný, XLK překonává trh o {state.xlk_vs_spy_1m_pct:+.1f}%. Zlato čelí odlivu institucionálního kapitálu -> Longy tlumit na 45%, Shorty povoleny."
            )

        # PRAVIDLO 2: "Systemic Banking / Credit Stress Safe-Haven Bid" (Případ Březen / Srpen 2026)
        # Když padají banky (XLF vs SPY <= -4.0 %) A ZÁROVEŇ se zhoršují kreditní spready (HYG/LQD < -0.5 %)
        # nebo roste VIX (> 20), zlato funguje jako primární bezpečný přístav.
        if state.xlf_vs_spy_1m_pct <= -4.0:
            if state.hyg_lqd_ratio_dev_pct <= -0.50 or state.vix_level >= 20.0:
                long_mult *= 1.30
                short_mult *= 0.20
                regimes.append("SAFE_HAVEN_BANKING_STRESS")
                reasons.append(
                    f"BANKOVNI_STRES_SAFE_HAVEN: XLF zaostává o {state.xlf_vs_spy_1m_pct:+.1f}%, riziko sektoru {state.xlf_risk_pct:.0f}%, VIX={state.vix_level:.1f}. Zlato je v režimu primárního útočiště -> Longy posílit 1.30x, Shorty blokovány."
                )
            else:
                # Banky jsou slabé, ale kreditní trh ještě nepanikaří (latentní napětí)
                reasons.append(
                    f"VAROVANI_BANKY: XLF zaostává o {state.xlf_vs_spy_1m_pct:+.1f}%, kreditní spready HYG/LQD zatím klidné ({state.hyg_lqd_ratio_dev_pct:+.2f}%). Sledovat možnou eskalaci."
                )

        # PRAVIDLO 3: Potvrzení od komoditních/těžařských akcií z 558 titulů
        if state.gold_proxies_net_sentiment <= -0.25:
            long_mult *= 0.65
            short_mult *= 1.15
            reasons.append(f"MEDVEDI_DIVERGENCE_TEZARU: Těžařské tituly oslabují ({state.gold_proxies_net_sentiment:+.2f}).")
        elif state.gold_proxies_net_sentiment >= 0.35:
            long_mult *= 1.15
            short_mult *= 0.60
            reasons.append(f"BYCI_POTVRZENI_TEZARU: Těžařské tituly akumulují ({state.gold_proxies_net_sentiment:+.2f}).")

        # PRAVIDLO 4: Vliv sbíraných zpráv a katalyzátorů
        news_notes = []
        if any("Objemový šok" in c or "Volume Shock" in c for c in state.active_catalysts):
            news_notes.append("Detekován institucionální objemový šok na akciovém trhu.")
        if any("Přeprodáno" in c for c in state.active_catalysts) and state.vix_level > 18:
            news_notes.append("Trh v korekci, volatilita stoupá -> mírné safe-haven nákupy.")

        # PRAVIDLO 5: Reporty rezerv centrálních bank (Sovereign Floor PBOC/NBP/WGC)
        # Centrální banky nakoupily rekordních 289 tun zlata (PBOC, NBP, Turecko) a akumulují v pásmu $4,000–$4,100.
        # Při poklesu o více než -8 % z 30d maxima se aktivuje sovereign floor: zákaz Momentum Shortů (#3, #5).
        sovereign_floor_active = False
        px = current_gold_price if current_gold_price is not None else 4192.0
        h30 = high_30d if high_30d is not None else 4697.0
        if px <= h30 * 0.92 and (abs(px - 4000.0) <= 50.0 or abs(px - 4100.0) <= 50.0 or (4000.0 <= px <= 4120.0)):
            sovereign_floor_active = True
            short_mult *= 0.20
            reasons.append(
                f"SOVEREIGN_CB_FLOOR: PBOC/NBP/WGC institucionální akumulační pásmo $4,000–$4,100 (pokles > 8 % z 30d maxima ${h30:.0f}). Momentum Shorty (#3, #5) zakázány."
            )

        # PRAVIDLO 6: Intradenní syntetický Real Yield (TIP / IEF) + Gold VIX (^GVZ) z High-Alpha feedu
        high_alpha_path = Path(__file__).resolve().parent / "data" / "high_alpha_gold_telemetry.json"
        ha_data = {}
        if high_alpha_path.exists():
            try:
                ha_data = json.loads(high_alpha_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        ha_micro = ha_data.get("intraday_macro_micro", {})
        ha_auctions = ha_data.get("treasury_auctions", {})

        # A) Intradenní šok reálných výnosů
        if ha_micro.get("intraday_real_yield_spike"):
            long_mult *= 0.40
            reasons.append(
                f"INTRADAY_REAL_YIELD_SPIKE: Poměr TIP/IEF klesá ({ha_micro.get('tip_ief_24h_chg_pct', 0.0):+.2f}%) a 10Y výnosy rostou. Reálné sazby prudce stoupají -> Longy potlačeny na 40%, falešné breakouty blokovány."
            )

        # B) Specifický komoditní stres na zlatě (GVZ vs VIX)
        if ha_micro.get("gold_specific_vol_stress"):
            gvz_val = ha_micro.get("gvz_gold_vix", 22.0)
            vix_val = ha_micro.get("equity_vix", 16.0)
            ratio_val = ha_micro.get("gvz_to_vix_ratio", 1.25)
            short_mult *= 1.15
            reasons.append(
                f"GOLD_VOLATILITY_STRESS: Gold VIX ^GVZ={gvz_val:.1f} překračuje akciový VIX={vix_val:.1f} (ratio {ratio_val:.2f} >= 1.25). Zlato je pod specifickým prodejním tlakem nezávisle na akciích."
            )

        # C) Výsledky US Treasury aukcí (Slabá poptávka Bid-to-Cover < 2.30)
        if ha_auctions.get("weak_demand_detected"):
            long_mult *= 0.75
            reasons.append(
                "WEAK_TREASURY_AUCTION_DEMAND: Bid-to-Cover v US Treasury aukci klesl pod 2.30 -> slabá absorpce dluhu tlačí výnosy vzhůru (protivítr pro zlato)."
            )

        final_long = round(float(np.clip(long_mult, 0.0, 1.35)), 2)
        final_short = round(float(np.clip(short_mult, 0.0, 1.35)), 2)
        regime_title = " & ".join(regimes) if regimes else "NEUTRAL_CROSS_ASSET_CYCLE"

        return {
            "scan_date": state.scan_date,
            "long_multiplier": final_long,
            "short_multiplier": final_short,
            "sovereign_floor_active": sovereign_floor_active,
            "regime": regime_title,
            "reasons": reasons or ["Standardní vyvážený makro cyklus bez extrémních sektorových disbalancí."],
            "news_catalysts": state.active_catalysts[:6],
            "high_alpha_telemetry": {
                "tip_ief_ratio": ha_micro.get("tip_ief_ratio", 1.167),
                "tip_ief_chg_pct": ha_micro.get("tip_ief_24h_chg_pct", 0.0),
                "gvz_gold_vix": ha_micro.get("gvz_gold_vix", 22.0),
                "equity_vix": ha_micro.get("equity_vix", 16.5),
                "gvz_vix_ratio": ha_micro.get("gvz_to_vix_ratio", 1.15),
                "gold_vol_stress": ha_micro.get("gold_specific_vol_stress", False),
                "real_yield_spike": ha_micro.get("intraday_real_yield_spike", False),
                "weak_treasury_demand": ha_auctions.get("weak_demand_detected", False)
            },
            "macro_summary": {
                "barometer_score": state.barometer_score,
                "us10y_yield": state.us10y_yield_pct,
                "vix": state.vix_level,
                "xlk_vs_spy": state.xlk_vs_spy_1m_pct,
                "xlf_vs_spy": state.xlf_vs_spy_1m_pct,
                "hyg_lqd_dev": state.hyg_lqd_ratio_dev_pct,
                "miners_sentiment": round(state.gold_proxies_net_sentiment, 2)
            }
        }


def get_latest_bridge_result() -> Dict[str, object]:
    bridge = SuggestInvestCrossAssetBridge()
    snap = bridge.fetch_latest_macro_snapshot()
    return bridge.evaluate_cross_asset_gold_multipliers(snap)


if __name__ == "__main__":
    bridge = SuggestInvestCrossAssetBridge()
    snapshot = bridge.fetch_latest_macro_snapshot("2026-10-13")
    res = bridge.evaluate_cross_asset_gold_multipliers(snapshot)
    print("=" * 65)
    print("🌐 SUGGESTINVEST CROSS-ASSET MACRO & NEWS BRIDGE VERIFIKACE")
    print("=" * 65)
    print(f"Datum skenu:           {res['scan_date']}")
    print(f"Režim trhu:            {res['regime']}")
    print(f"Multiplikátor LONG:    {res['long_multiplier']}x")
    print(f"Multiplikátor SHORT:   {res['short_multiplier']}x")
    print(f"10Y US Yield:          {res['macro_summary']['us10y_yield']} %")
    print(f"XLK vs SPY:            {res['macro_summary']['xlk_vs_spy']:+.2f} %")
    print(f"XLF vs SPY:            {res['macro_summary']['xlf_vs_spy']:+.2f} %")
    print(f"VIX:                   {res['macro_summary']['vix']}")
    print("Kvantitativní důvody:")
    for r in res["reasons"]:
        print(f" • {r}")
    print("Aktivní zprávy a katalyzátory:")
    for c in res["news_catalysts"]:
        print(f" • {c}")
    print("=" * 65)
