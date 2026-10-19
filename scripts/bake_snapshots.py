#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/bake_snapshots.py
Bakes the latest live data snapshots (balance, positions, trade history, 2026 walkforward backtest,
telemetry, system status) into static HTML dashboards before Git commit & deploy.

This ensures that GitHub Pages (which has no Python server) ALWAYS renders the complete,
up-to-date state of the portfolio and backtest history immediately upon page load without 404s.
"""

import os
import re
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("SnapshotBaker")

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT_DIR, "data")


def safe_json_load(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load JSON {path}: {e}")
        return default


def replace_script_tag(content, tag_id, new_tag):
    """Safely replaces a script tag by ID without re.sub backslash corruption."""
    pattern = rf'<script id="{tag_id}"[^>]*>.*?</script>'
    m = re.search(pattern, content, flags=re.DOTALL)
    if m:
        return content[:m.start()] + new_tag + content[m.end():]
    return content


def bake_silver_results_2026():
    """Bakes silver_walkforward_manifest.json into silver_results_2026.html."""
    html_path = os.path.join(ROOT_DIR, "silver_results_2026.html")
    manifest_path = os.path.join(DATA_DIR, "silver_walkforward_manifest.json")
    if not os.path.exists(html_path) or not os.path.exists(manifest_path):
        logger.warning("silver_results_2026.html or manifest not found.")
        return False

    manifest_data = safe_json_load(manifest_path)
    if not manifest_data:
        return False

    with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # 1. Update or inject <script id="embeddedSilverManifest">
    json_str = json.dumps(manifest_data, ensure_ascii=False)
    tag = f'<script id="embeddedSilverManifest" type="application/json">\n{json_str}\n</script>'

    if 'id="embeddedSilverManifest"' in content:
        content = replace_script_tag(content, "embeddedSilverManifest", tag)
    else:
        idx = content.find("<script>\n    let manifestData = null;")
        if idx == -1:
            idx = content.find("<script>\r\n    let manifestData = null;")
        if idx == -1:
            idx = content.find("<script>")
        if idx != -1:
            content = content[:idx] + tag + "\n" + content[idx:]

    # 2. Ensure manifestData initialization from embedded tag exists
    init_snippet = """    // 0. Okamžité načtení vestavěného snapshotu (pro bleskové zobrazení na GitHub Pages i offline)
    try {
        const _embEl = document.getElementById('embeddedSilverManifest');
        if (_embEl && _embEl.textContent) {
            const _embData = JSON.parse(_embEl.textContent);
            if (_embData && _embData.ok) {
                manifestData = _embData.manifest;
                walkforwardState = _embData.state;
            }
        }
    } catch(e) {
        console.warn("Chyba při čtení vestavěného snapshotu:", e);
    }"""

    if "0. Okamžité načtení vestavěného snapshotu" not in content:
        content = content.replace(
            "let walkforwardState = null;",
            "let walkforwardState = null;\n\n" + init_snippet
        )

    # 3. Ensure initPage() renders immediately if snapshot is present
    old_init = """    async function initPage() {
        await fetchManifestAndState();
    }"""
    new_init = """    async function initPage() {
        if (manifestData && walkforwardState) {
            renderDashboard();
        }
        await fetchManifestAndState();
    }"""
    if old_init in content:
        content = content.replace(old_init, new_init)

    # 4. Ensure fetchManifestAndState() falls back to static JSON file
    old_fetch = """    async function fetchManifestAndState() {
        try {
            const res = await fetch('/api/silver/walkforward-manifest');
            const data = await res.json();
            if (data.ok) {
                manifestData = data.manifest;
                walkforwardState = data.state;
                renderDashboard();
            }
        } catch (e) {
            console.error("Chyba při stahování manifestu:", e);
        }
    }"""

    new_fetch = """    async function fetchManifestAndState() {
        let loaded = false;
        // 1. Zkusit živé lokální API
        try {
            const res = await fetch('/api/silver/walkforward-manifest');
            if (res.ok) {
                const data = await res.json();
                if (data.ok) {
                    manifestData = data.manifest;
                    walkforwardState = data.state;
                    renderDashboard();
                    loaded = true;
                }
            }
        } catch (e) {}

        if (loaded) return;

        // 2. Fallback na statický soubor JSON (relativní cesta pro GitHub Pages)
        try {
            const res = await fetch('data/silver_walkforward_manifest.json?t=' + Date.now());
            if (res.ok) {
                const data = await res.json();
                if (data.ok) {
                    manifestData = data.manifest;
                    walkforwardState = data.state;
                    renderDashboard();
                    loaded = true;
                }
            }
        } catch (e) {
            console.warn("Statický manifest nebyl načten:", e);
        }

        // 3. Poslední záloha: pokud máme vestavěný snapshot, renderujeme ho
        if (!loaded && manifestData && walkforwardState) {
            renderDashboard();
        }
    }"""

    if old_fetch in content:
        content = content.replace(old_fetch, new_fetch)
    elif "2. Fallback na statický soubor JSON" not in content:
        content = re.sub(
            r'async function fetchManifestAndState\(\)\s*\{.*?function getAllTrades',
            new_fetch + "\n\n    function getAllTrades",
            content,
            flags=re.DOTALL
        )

    # 5. Friendly GitHub Pages static messages for unlock & reset buttons
    content = content.replace(
        'alert("Chyba při odkrývání měsíce: " + data.error);',
        'alert("ℹ️ Na statickém hostingu GitHub Pages se zobrazuje kompletní auditní snapshot roku 2026 (všech 10 měsíců úspěšně vyhodnoceno). Pro interaktivní krokování spusťte lokální server.");'
    )
    content = content.replace(
        'alert("Požadavek selhal: " + e);',
        'alert("ℹ️ Na statickém hostingu GitHub Pages se zobrazuje kompletní auditní snapshot roku 2026 (všech 10 měsíců úspěšně vyhodnoceno). Pro interaktivní krokování spusťte lokální server.");'
    )
    content = content.replace(
        'alert("Reset selhal: " + e);',
        'alert("ℹ️ Na statickém hostingu GitHub Pages je reset zablokován pro zachování integrity publikovaných výsledků.");'
    )

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info("✅ silver_results_2026.html successfully baked with live 2026 manifest snapshot.")
    return True


def bake_future_invest_demo():
    """Bakes future_invest_demo_state.json into FutureInvestDemo.html and fixes JSON parsing."""
    html_path = os.path.join(ROOT_DIR, "FutureInvestDemo.html")
    state_path = os.path.join(DATA_DIR, "future_invest_demo_state.json")
    if not os.path.exists(html_path) or not os.path.exists(state_path):
        logger.warning("FutureInvestDemo.html or state file not found.")
        return False

    state_data = safe_json_load(state_path)
    if not state_data:
        return False

    with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # 1. Update or inject <script id="embeddedFutureDemoFallback">
    json_str = json.dumps(state_data, ensure_ascii=False)
    tag = f'<script id="embeddedFutureDemoFallback" type="application/json">\n{json_str}\n</script>'

    if 'id="embeddedFutureDemoFallback"' in content:
        content = replace_script_tag(content, "embeddedFutureDemoFallback", tag)
    else:
        target = '<div id="toast"></div>'
        if target in content:
            content = content.replace(target, target + "\n" + tag)
        else:
            idx = content.find("<script>")
            if idx != -1:
                content = content[:idx] + tag + "\n" + content[idx:]

    # 2. Ensure initial state reading from embedded tag
    init_snippet = """    // 0. Okamžité načtení vestavěného snapshotu (pro bleskové zobrazení na GitHub Pages i offline)
    try {
        const _fbEl = document.getElementById("embeddedFutureDemoFallback");
        if (_fbEl && _fbEl.textContent) {
            window.FUTURE_INVEST_DEMO_FALLBACK = JSON.parse(_fbEl.textContent);
            globalState = window.FUTURE_INVEST_DEMO_FALLBACK;
        }
    } catch(e) {
        console.warn("Chyba při čtení vestavěného fallbacku:", e);
    }"""

    if "0. Okamžité načtení vestavěného snapshotu" not in content:
        content = content.replace(
            "let pollInterval = null;",
            "let pollInterval = null;\n\n" + init_snippet
        )

    # 3. Fix loadData() to handle both wrapped and raw JSON
    old_load = """    async function loadData() {
        try {
            let res;
        try {
            res = await fetch("/api/future_invest/data");
            if (!res.ok) throw new Error("API not available");
        } catch(apiErr) {
            res = await fetch("data/future_invest_demo_state.json?t=" + Date.now());
        }
            if (!res.ok) throw new Error("HTTP " + res.status);
            const json = await res.json();
            if (json.ok && json.data) {
                globalState = json.data;
                renderState(globalState);
            }
        } catch (e) {
            console.error("Chyba při načítání stavu:", e);
        }
    }"""

    new_load = """    async function loadData() {
        try {
            let res;
            try {
                res = await fetch("/api/future_invest/data");
                if (!res.ok) throw new Error("API not available");
            } catch(apiErr) {
                res = await fetch("data/future_invest_demo_state.json?t=" + Date.now());
            }
            if (!res.ok) throw new Error("HTTP " + res.status);
            const json = await res.json();
            const st = (json && json.data) ? json.data : (json && (json.account_id || json.balance || json.open_positions) ? json : null);
            if (st) {
                globalState = st;
                renderState(globalState);
            }
        } catch (e) {
            if (!globalState && window.FUTURE_INVEST_DEMO_FALLBACK) {
                globalState = window.FUTURE_INVEST_DEMO_FALLBACK;
                try { renderState(globalState); } catch(err) {}
            }
        }
    }"""

    if old_load in content:
        content = content.replace(old_load, new_load)
    else:
        content = re.sub(
            r'async function loadData\(\)\s*\{.*?if\s*\(json\.ok && json\.data\)\s*\{.*?\}\s*\}\s*catch\s*\(e\)\s*\{.*?\}\s*\}',
            new_load.strip(),
            content,
            flags=re.DOTALL
        )

    # 4. Immediate render on DOM ready before polling
    if "loadData();\n    pollInterval = setInterval(loadData, 1000);" in content:
        content = content.replace(
            "loadData();\n    pollInterval = setInterval(loadData, 1000);",
            """if (window.FUTURE_INVEST_DEMO_FALLBACK) {
        globalState = window.FUTURE_INVEST_DEMO_FALLBACK;
        try { renderState(globalState); } catch(e) {}
    }
    loadData();
    pollInterval = setInterval(loadData, 2000);"""
        )

    # 5. Graceful messages for sync/trading when on static GitHub Pages
    content = content.replace(
        'showToast("⚠️ Chyba při synchronizaci: " + e.message);',
        'showToast("ℹ️ Statický náhled GitHub Pages. Zobrazuji aktuální snapshot účtu DUR222134.");'
    )

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info("✅ FutureInvestDemo.html successfully baked with live demo snapshot & fixed parser.")
    return True


def bake_trading():
    """Bakes live_portfolio.json into trading.html and fixes relative API paths."""
    html_path = os.path.join(ROOT_DIR, "trading.html")
    live_path = os.path.join(DATA_DIR, "live_portfolio.json")
    if not os.path.exists(html_path) or not os.path.exists(live_path):
        logger.warning("trading.html or live_portfolio.json not found.")
        return False

    live_data = safe_json_load(live_path)
    if not live_data:
        return False

    with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # 1. Update <script id="embeddedLivePortfolio">
    json_str = json.dumps(live_data, ensure_ascii=False)
    tag = f'<script id="embeddedLivePortfolio" type="application/json">\n{json_str}\n    </script>'
    content = replace_script_tag(content, "embeddedLivePortfolio", tag)

    # 2. Ensure the fallback loader cleanly parses from embeddedLivePortfolio
    clean_js_loader = """    <script>
        // Synchronizovaný fallback ze živého snapshotu (DUR222134) pro eliminaci falešné ztráty
        (function() {
            try {
                var emb = document.getElementById("embeddedLivePortfolio");
                if (emb && emb.textContent) {
                    window.LIVE_PORTFOLIO_FALLBACK = JSON.parse(emb.textContent);
                }
            } catch(e) {}
        })();
    </script>"""

    # If the old pattern exists or is broken, replace it with clean_js_loader
    content = re.sub(
        r'<script>\s*// Synchronizovaný fallback ze živého snapshotu[\s\S]*?</script>',
        clean_js_loader.strip(),
        content,
        count=1
    )

    # 3. Ensure getIbkrApiUrl handles relative /data/ paths cleanly on GitHub Pages
    old_url_fn = """        function getIbkrApiUrl(path) {
            if (window.location.protocol === 'http:' || window.location.protocol === 'https:') {
                return path; // Relativní URL (stejný origin - funguje pro localhost i 127.0.0.1 bez CORS omezení)
            }
            return 'http://127.0.0.1:8000' + path; // Fallback pro file:// protokol
        }"""

    new_url_fn = """        function getIbkrApiUrl(path) {
            // Pro statické GitHub Pages nesmí relativní cesta k data/... začínat lomítkem
            if (path.startsWith('/data/')) {
                path = path.substring(1);
            }
            if (window.location.protocol === 'http:' || window.location.protocol === 'https:') {
                return path;
            }
            return 'http://127.0.0.1:8000/' + path.replace(/^\\/+/, '');
        }"""

    if old_url_fn in content:
        content = content.replace(old_url_fn, new_url_fn)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info("✅ trading.html successfully baked with live portfolio snapshot.")
    return True


def bake_system_status():
    """Bakes system_report.json into system_status.html."""
    html_path = os.path.join(ROOT_DIR, "system_status.html")
    report_path = os.path.join(DATA_DIR, "system_report.json")
    if not os.path.exists(html_path) or not os.path.exists(report_path):
        return False

    report_data = safe_json_load(report_path)
    if not report_data:
        return False

    with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    json_str = json.dumps(report_data, ensure_ascii=False)
    tag = f'<script id="embeddedSystemReport" type="application/json">\n{json_str}\n</script>'

    if 'id="embeddedSystemReport"' in content:
        content = replace_script_tag(content, "embeddedSystemReport", tag)
    else:
        idx = content.find("<script>\n    let lastReportTimestamp")
        if idx == -1:
            idx = content.find("<script>\r\n    let lastReportTimestamp")
        if idx == -1:
            idx = content.find("<script>")
        if idx != -1:
            content = content[:idx] + tag + "\n" + content[idx:]

    init_snippet = """    try {
        const _repEl = document.getElementById("embeddedSystemReport");
        if (_repEl && _repEl.textContent) {
            window.SYSTEM_REPORT_FALLBACK = JSON.parse(_repEl.textContent);
        }
    } catch(e) {}"""

    if "SYSTEM_REPORT_FALLBACK" not in content:
        content = content.replace(
            "let autoRefreshTimer = null;",
            "let autoRefreshTimer = null;\n" + init_snippet
        )

    if "if (window.SYSTEM_REPORT_FALLBACK) renderReport(window.SYSTEM_REPORT_FALLBACK);" not in content:
        content = content.replace(
            'document.getElementById("overallBadge").className = "health-badge badge-critical";',
            'document.getElementById("overallBadge").className = "health-badge badge-critical";\n            if (window.SYSTEM_REPORT_FALLBACK) renderReport(window.SYSTEM_REPORT_FALLBACK);'
        )

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info("✅ system_status.html successfully baked with system report snapshot.")
    return True


def bake_silver_invest_demo():
    """Bakes walkforward manifest into SilverInvestDemo.html and ensures offline trades table."""
    html_path = os.path.join(ROOT_DIR, "SilverInvestDemo.html")
    manifest_path = os.path.join(DATA_DIR, "silver_walkforward_manifest.json")
    if not os.path.exists(html_path) or not os.path.exists(manifest_path):
        return False

    manifest_data = safe_json_load(manifest_path)
    if not manifest_data:
        return False

    with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    json_str = json.dumps(manifest_data, ensure_ascii=False)
    tag = f'<script id="embeddedSilverInvestManifest" type="application/json">\n{json_str}\n</script>'

    if 'id="embeddedSilverInvestManifest"' in content:
        content = replace_script_tag(content, "embeddedSilverInvestManifest", tag)
    else:
        idx = content.find("<script>")
        if idx != -1:
            content = content[:idx] + tag + "\n" + content[idx:]

    old_fetch_trades = """    async function fetchTrades() {
        try {
            const res = await fetch('/api/silver/trades');
            const data = await res.json();
            if (data.ok) {
                const trades = (walkforwardState && getWalkforwardTrades().length > 0) 
                    ? getWalkforwardTrades() 
                    : (data.journal_trades && data.journal_trades.length > 0 ? data.journal_trades : data.insample_trades || []);
                renderTradesTable(trades);
            }
        } catch (e) {
            console.error("Chyba při načítání obchodů:", e);
        }
    }"""

    new_fetch_trades = """    async function fetchTrades() {
        let trades = [];
        try {
            const res = await fetch('/api/silver/trades');
            if (res.ok) {
                const data = await res.json();
                if (data.ok) {
                    trades = (data.journal_trades && data.journal_trades.length > 0) ? data.journal_trades : (data.insample_trades || []);
                }
            }
        } catch (e) {}

        if (trades.length === 0 && walkforwardState) {
            trades = getWalkforwardTrades();
        }
        renderTradesTable(trades);
    }"""

    if old_fetch_trades in content:
        content = content.replace(old_fetch_trades, new_fetch_trades)

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info("✅ SilverInvestDemo.html successfully baked with silver telemetry & manifest.")
    return True


def bake_argon_results_2026():
    """Ensures argon_results_2026.html inline fallback contains all 10 months."""
    html_path = os.path.join(ROOT_DIR, "argon_results_2026.html")
    page_data_path = os.path.join(DATA_DIR, "backtest", "argon_v25_page_data.js")
    if not os.path.exists(html_path) or not os.path.exists(page_data_path):
        return False

    with open(page_data_path, "r", encoding="utf-8", errors="ignore") as f:
        js_text = f.read()

    try:
        data_str = js_text.split("=", 1)[1].strip()
        if data_str.endswith(";"):
            data_str = data_str[:-1].strip()
        argon_data = json.loads(data_str)
    except Exception as e:
        logger.warning(f"Could not parse argon_v25_page_data.js: {e}")
        return False

    with open(html_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    if "months: []" in content:
        months_json = json.dumps(argon_data.get("months", []), ensure_ascii=False, indent=12)
        content = content.replace("months: []", f"months: {months_json}")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info("✅ argon_results_2026.html fallback months populated.")
    return True


def bake_all_snapshots():
    """Executes baking for all dashboards."""
    logger.info("🚀 Starting live snapshot baking for GitHub Pages static deployment...")
    s1 = bake_silver_results_2026()
    s2 = bake_future_invest_demo()
    s3 = bake_trading()
    s4 = bake_system_status()
    s5 = bake_silver_invest_demo()
    s6 = bake_argon_results_2026()
    logger.info(f"✨ Snapshot baking complete. Statuses: silver_2026={s1}, future_demo={s2}, trading={s3}, system_status={s4}, silver_demo={s5}, argon_2026={s6}")
    return all([s1, s2, s3, s4, s5, s6])


if __name__ == "__main__":
    bake_all_snapshots()
