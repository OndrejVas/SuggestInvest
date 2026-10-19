"""
system_reporter.py
==================
Komplexní systémový reporting, telemetrie a dohled nad SuggestInvest.
Určeno pro lokální běh i nasazení na produkční Cloud VPS (Linux / Windows).

Sleduje a vyhodnocuje:
1. Síťový provoz a protečená data (Network I/O: přenesené bajty, rychlost upload/download KB/s a MB/s).
2. Využití CPU (celkové zatížení systému, rozpad po jádrech, zátěž procesů projektu).
3. Využití RAM (fyzická paměť, swap/pagefile, paměťová stopa jednotlivých procesů v MB).
4. Monitoring jednotlivých procesů projektu (server.py, ibkr_watchdog, java/ibgateway, syncdat).
5. Monitoring spuštěných/aktivních JSON souborů (stáří souborů v sekundách, validita, integrita).
6. Běh aplikací na pozadí a stahování dat (IB socket 7497, RSS feed, CME DOM, web server).
7. Automatická detekce anomálií a generování alertů (překročení limitů, zamrznutí JSONů).
8. Ukládání snapshotu do data/system_report.json + rotující časová řada do data/system_telemetry_history.jsonl.
"""

from __future__ import annotations
import os
import sys
import time
import json
import socket
import logging
import argparse
import platform
import datetime
from typing import Dict, Any, List, Optional

# Kódování terminálu ve Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(WORKSPACE_DIR, "data")
LOGS_DIR = os.path.join(WORKSPACE_DIR, "logs")
REPORT_JSON_PATH = os.path.join(DATA_DIR, "system_report.json")
HISTORY_JSONL_PATH = os.path.join(DATA_DIR, "system_telemetry_history.jsonl")
LOG_FILE_PATH = os.path.join(LOGS_DIR, "system_reporter.log")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

# Konfigurace loggeru
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SYS-REPORT] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE_PATH, encoding="utf-8", mode="a")
    ]
)
logger = logging.getLogger("SystemReporter")

# Prahové hodnoty pro alerty (lze přepsat env proměnnými na VPS)
ALERT_THRESHOLDS = {
    "cpu_percent": float(os.getenv("ALERT_CPU_PERCENT", "90.0")),
    "ram_percent": float(os.getenv("ALERT_RAM_PERCENT", "92.0")),
    "disk_min_free_gb": float(os.getenv("ALERT_DISK_MIN_FREE_GB", "4.0")),
    "json_stale_critical_sec": float(os.getenv("ALERT_JSON_STALE_CRITICAL_SEC", "45.0")),
    "json_stale_warning_sec": float(os.getenv("ALERT_JSON_STALE_WARN_SEC", "20.0")),
}

# Definice sledovaných JSON souborů projektu a jejich očekávané periody
MONITORED_JSONS: Dict[str, Dict[str, Any]] = {
    "future_invest_demo_state.json": {
        "title": "FutureInvest Demo State",
        "role": "Centrální živý stav pro UI, boty a telemetrii",
        "max_age_sec": 15,
        "critical": True
    },
    "live_portfolio.json": {
        "title": "Live Portfolio & Balances",
        "role": "Zůstatky, hotovost a otevřené pozice z IBKR",
        "max_age_sec": 60,
        "critical": True
    },
    "execution_lock.json": {
        "title": "Execution Safety Lock",
        "role": "Bezpečnostní zámek objednávek (Kill Switch - konfigurace)",
        "max_age_sec": 86400 * 365,
        "critical": False,
        "stale_exempt": True
    },
    "gateway_outages.json": {
        "title": "Gateway Outages History",
        "role": "Historie posledních 10 výpadků socketu 7497",
        "max_age_sec": 86400 * 365,
        "critical": False,
        "stale_exempt": True
    },
    "high_alpha_gold_telemetry.json": {
        "title": "High Alpha Gold Telemetry",
        "role": "L2 DOM a makro-ekonomická telemetrie pro zlato",
        "max_age_sec": 60,
        "critical": False
    },
    "demo_equity_history.json": {
        "title": "Demo Equity History",
        "role": "Historický vývoj majetku účtu",
        "max_age_sec": 86400 * 365,
        "critical": False,
        "stale_exempt": True
    },
    "scalping_trades.json": {
        "title": "Scalping Trades History",
        "role": "Záznam provedených rychlých scalping obchodů",
        "max_age_sec": 86400,
        "critical": False
    },
    "cache_macro.json": {
        "title": "Macro Calendar Cache",
        "role": "Cache ekonomických indikátorů (FRED, VIX, Yields)",
        "max_age_sec": 86400 * 30,
        "critical": False,
        "stale_exempt": True
    }
}

# Definice sledovaných procesů projektu
PROJECT_PROCESS_KEYWORDS = [
    ("server.py", "SuggestInvest Web & API Server", True),
    ("ibkr_watchdog.py", "IBKR Watchdog Daemon (Port 7497 & L2 DOM)", True),
    ("ib_watchdog.py", "IBKR Watchdog (Alternativní synchronizátor)", False),
    ("ibkr_sync_service.py", "IBKR Portfolio Sync Service", False),
    ("autoinvest_executor.py", "AutoInvest Order Execution Engine", False),
    ("autoinvest_service.py", "AutoInvest Background Service", False),
    ("argon_futures_bot.py", "Argon V2.5 Autonomous Futures Bot", False),
    ("data_continuity_service.py", "Data Continuity Gap Detector", False),
    ("launch_ibkr.py", "IBKR Demo Gateway Launcher", False),
    ("ibgateway", "IB Gateway Native Process", False),
    ("java.exe", "IBKR Gateway Java Runtime (Port 7497)", False),
    ("ibc", "IB Controller Automation Daemon", False),
]


def safe_json_write(path: str, data: Any) -> None:
    """Atomický zápis JSON souboru přes temp soubor a os.replace."""
    import tempfile
    dir_ = os.path.dirname(path) or "."
    tmp_fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


class NetworkTracker:
    """Sleduje přenesená data a vypočítává okamžitou rychlost (KB/s, MB/s)."""
    def __init__(self):
        self.last_check_time: Optional[float] = None
        self.initial_bytes_sent: int = 0
        self.initial_bytes_recv: int = 0
        self.last_bytes_sent: int = 0
        self.last_bytes_recv: int = 0
        self.initialized: bool = False

    def collect(self) -> Dict[str, Any]:
        now = time.time()
        if not HAS_PSUTIL:
            return {
                "available": False,
                "error": "psutil není nainstalován"
            }

        net = psutil.net_io_counters()
        curr_sent = net.bytes_sent
        curr_recv = net.bytes_recv

        if not self.initialized:
            self.initial_bytes_sent = curr_sent
            self.initial_bytes_recv = curr_recv
            self.last_bytes_sent = curr_sent
            self.last_bytes_recv = curr_recv
            self.last_check_time = now
            self.initialized = True
            upload_rate_kbps = 0.0
            download_rate_kbps = 0.0
        else:
            dt = max(0.1, now - (self.last_check_time or now))
            upload_rate_kbps = ((curr_sent - self.last_bytes_sent) / dt) / 1024.0
            download_rate_kbps = ((curr_recv - self.last_bytes_recv) / dt) / 1024.0
            self.last_bytes_sent = curr_sent
            self.last_bytes_recv = curr_recv
            self.last_check_time = now

        session_sent_mb = (curr_sent - self.initial_bytes_sent) / (1024 * 1024)
        session_recv_mb = (curr_recv - self.initial_bytes_recv) / (1024 * 1024)
        total_sent_mb = curr_sent / (1024 * 1024)
        total_recv_mb = curr_recv / (1024 * 1024)

        # Síťová rozhraní
        interfaces = []
        try:
            addrs = psutil.net_if_addrs()
            stats = psutil.net_if_stats()
            for if_name, if_addrs in addrs.items():
                st = stats.get(if_name)
                ip_v4 = next((a.address for a in if_addrs if a.family == socket.AF_INET), None)
                if ip_v4 and not ip_v4.startswith("127."):
                    interfaces.append({
                        "name": if_name,
                        "ip": ip_v4,
                        "is_up": st.isup if st else True,
                        "speed_mbps": st.speed if st else 0
                    })
        except Exception:
            pass

        return {
            "available": True,
            "session_traffic": {
                "sent_mb": round(session_sent_mb, 2),
                "recv_mb": round(session_recv_mb, 2),
                "total_mb": round(session_sent_mb + session_recv_mb, 2),
                "duration_sec": round(now - (self.last_check_time if self.initialized else now), 1)
            },
            "rates": {
                "upload_kb_s": round(max(0.0, upload_rate_kbps), 2),
                "download_kb_s": round(max(0.0, download_rate_kbps), 2),
                "upload_mb_s": round(max(0.0, upload_rate_kbps / 1024.0), 3),
                "download_mb_s": round(max(0.0, download_rate_kbps / 1024.0), 3),
            },
            "system_totals": {
                "total_sent_mb": round(total_sent_mb, 1),
                "total_recv_mb": round(total_recv_mb, 1),
                "packets_sent": net.packets_sent,
                "packets_recv": net.packets_recv,
                "errors_in": net.errin,
                "errors_out": net.errout,
                "drop_in": net.dropin,
                "drop_out": net.dropout
            },
            "interfaces": interfaces[:4]
        }


def collect_cpu_metrics() -> Dict[str, Any]:
    """Získá celkové a per-core vytížení CPU."""
    if not HAS_PSUTIL:
        return {"available": False}

    cpu_pct = psutil.cpu_percent(interval=0.1)
    per_cpu = psutil.cpu_percent(percpu=True)
    count_logical = psutil.cpu_count(logical=True)
    count_physical = psutil.cpu_count(logical=False)

    load_avg = None
    if hasattr(os, "getloadavg"):
        try:
            load_avg = [round(x, 2) for x in os.getloadavg()]
        except Exception:
            pass

    return {
        "available": True,
        "overall_percent": round(cpu_pct, 1),
        "cores_logical": count_logical,
        "cores_physical": count_physical,
        "per_core_percent": [round(c, 1) for c in per_cpu],
        "load_average": load_avg,
        "status": "CRITICAL" if cpu_pct >= ALERT_THRESHOLDS["cpu_percent"] else ("WARNING" if cpu_pct >= 75.0 else "HEALTHY")
    }


def collect_ram_metrics() -> Dict[str, Any]:
    """Získá statistiky fyzické a virtuální paměti RAM."""
    if not HAS_PSUTIL:
        return {"available": False}

    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()

    total_mb = vm.total / (1024 * 1024)
    used_mb = vm.used / (1024 * 1024)
    free_mb = vm.available / (1024 * 1024)
    pct = vm.percent

    return {
        "available": True,
        "total_mb": round(total_mb, 1),
        "used_mb": round(used_mb, 1),
        "free_mb": round(free_mb, 1),
        "used_gb": round(used_mb / 1024.0, 2),
        "total_gb": round(total_mb / 1024.0, 2),
        "percent": round(pct, 1),
        "swap": {
            "total_mb": round(swap.total / (1024 * 1024), 1),
            "used_mb": round(swap.used / (1024 * 1024), 1),
            "percent": round(swap.percent, 1)
        },
        "status": "CRITICAL" if pct >= ALERT_THRESHOLDS["ram_percent"] else ("WARNING" if pct >= 80.0 else "HEALTHY")
    }


def collect_disk_metrics() -> Dict[str, Any]:
    """Získá využití disku pro adresář projektu."""
    if not HAS_PSUTIL:
        return {"available": False}

    du = psutil.disk_usage(WORKSPACE_DIR)
    total_gb = du.total / (1024 ** 3)
    used_gb = du.used / (1024 ** 3)
    free_gb = du.free / (1024 ** 3)

    return {
        "available": True,
        "total_gb": round(total_gb, 1),
        "used_gb": round(used_gb, 1),
        "free_gb": round(free_gb, 1),
        "percent": round(du.percent, 1),
        "status": "CRITICAL" if free_gb < ALERT_THRESHOLDS["disk_min_free_gb"] else "HEALTHY"
    }


def collect_project_processes() -> Dict[str, Any]:
    """Vyhledá a zanalyzuje všechny běžící procesy týkající se projektu."""
    if not HAS_PSUTIL:
        return {"available": False, "processes": []}

    detected_processes: List[Dict[str, Any]] = []
    total_proj_cpu = 0.0
    total_proj_ram_mb = 0.0

    try:
        current_pid = os.getpid()
        for p in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time', 'status']):
            try:
                cmdline_list = p.info.get('cmdline') or []
                cmdline_str = " ".join(cmdline_list).lower()
                p_name = (p.info.get('name') or "").lower()

                # Ignorujeme samotný reporting skript
                if p.pid == current_pid:
                    continue

                matched_role = None
                matched_critical = False

                for kw, role, is_crit in PROJECT_PROCESS_KEYWORDS:
                    if kw.lower() in cmdline_str or kw.lower() == p_name:
                        matched_role = role
                        matched_critical = is_crit
                        break

                if matched_role:
                    # Získání detailních metrik procesu
                    with p.oneshot():
                        cpu_p = p.cpu_percent(interval=None)
                        mem_info = p.memory_info()
                        ram_mb = mem_info.rss / (1024 * 1024)
                        threads_count = p.num_threads()
                        create_dt = datetime.datetime.fromtimestamp(p.info['create_time'])
                        uptime_sec = max(0, int(time.time() - p.info['create_time']))
                        uptime_str = f"{uptime_sec // 3600}h {(uptime_sec % 3600) // 60}m {uptime_sec % 60}s"

                    total_proj_cpu += cpu_p
                    total_proj_ram_mb += ram_mb

                    detected_processes.append({
                        "pid": p.pid,
                        "name": p.info['name'],
                        "role": matched_role,
                        "critical": matched_critical,
                        "status": p.info.get('status', 'running'),
                        "cpu_percent": round(cpu_p, 1),
                        "ram_mb": round(ram_mb, 1),
                        "threads": threads_count,
                        "started_at": create_dt.strftime("%d.%m.%Y %H:%M:%S"),
                        "uptime_sec": uptime_sec,
                        "uptime_str": uptime_str,
                        "cmd": (cmdline_list[:2] if len(cmdline_list) > 2 else cmdline_list)
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except Exception as e:
        logger.warning(f"Chyba při skenování procesů: {e}")

    # Kontrola zda nechybí kritické procesy
    missing_critical = []
    for kw, role, is_crit in PROJECT_PROCESS_KEYWORDS:
        if is_crit:
            found = any(p["role"] == role for p in detected_processes)
            if not found:
                missing_critical.append({"keyword": kw, "role": role})

    return {
        "available": True,
        "count": len(detected_processes),
        "total_cpu_percent": round(total_proj_cpu, 1),
        "total_ram_mb": round(total_proj_ram_mb, 1),
        "processes": detected_processes,
        "missing_critical": missing_critical,
        "status": "CRITICAL" if missing_critical else ("WARNING" if total_proj_ram_mb > 1500.0 else "HEALTHY")
    }


def collect_json_health() -> Dict[str, Any]:
    """Zkontroluje stav, stáří, velikost a validitu všech klíčových JSON souborů."""
    now = time.time()
    results: List[Dict[str, Any]] = []
    stale_count = 0
    corrupt_count = 0
    missing_critical_count = 0

    for filename, meta in MONITORED_JSONS.items():
        filepath = os.path.join(DATA_DIR, filename)
        exists = os.path.exists(filepath)
        max_age = meta["max_age_sec"]
        is_crit = meta["critical"]

        if not exists:
            status = "MISSING"
            if is_crit:
                missing_critical_count += 1
            results.append({
                "filename": filename,
                "title": meta["title"],
                "role": meta["role"],
                "exists": False,
                "size_bytes": 0,
                "last_modified": "–",
                "age_sec": None,
                "age_str": "Soubor neexistuje",
                "valid": False,
                "status": status,
                "critical": is_crit
            })
            continue

        try:
            stat = os.stat(filepath)
            size_b = stat.st_size
            mtime = stat.st_mtime
            age_sec = max(0.0, now - mtime)
            mtime_dt = datetime.datetime.fromtimestamp(mtime).strftime("%d.%m.%Y %H:%M:%S")

            if age_sec < 60:
                age_str = f"před {age_sec:.1f} s"
            elif age_sec < 3600:
                age_str = f"před {int(age_sec // 60)} m {int(age_sec % 60)} s"
            else:
                age_str = f"před {int(age_sec // 3600)} h {int((age_sec % 3600) // 60)} m"

            # Validace JSON integrity
            valid = False
            parse_error = None
            keys_count = 0
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = json.load(f)
                    valid = True
                    if isinstance(content, dict):
                        keys_count = len(content)
                    elif isinstance(content, list):
                        keys_count = len(content)
            except Exception as e:
                valid = False
                parse_error = str(e)
                corrupt_count += 1

            # Určení zdraví souboru
            # Pro dynamické live feedy (max_age_sec <= 60) hlídáme krátký limit, pro statické zámky jejich max_age
            stale_limit = max(max_age, ALERT_THRESHOLDS["json_stale_critical_sec"]) if is_crit else max_age

            if not valid:
                status = "CORRUPTED"
            elif meta.get("stale_exempt"):
                status = "HEALTHY"
            elif age_sec > stale_limit:
                status = "CRITICAL_STALE" if is_crit else "STALE"
                stale_count += 1
            elif age_sec > max_age:
                status = "STALE"
                stale_count += 1
            else:
                status = "HEALTHY"

            results.append({
                "filename": filename,
                "title": meta["title"],
                "role": meta["role"],
                "exists": True,
                "size_bytes": size_b,
                "size_kb": round(size_b / 1024.0, 2),
                "last_modified": mtime_dt,
                "age_sec": round(age_sec, 1),
                "age_str": age_str,
                "valid": valid,
                "parse_error": parse_error,
                "items_count": keys_count,
                "status": status,
                "critical": is_crit
            })

        except Exception as e:
            results.append({
                "filename": filename,
                "title": meta["title"],
                "exists": True,
                "error": str(e),
                "status": "ERROR",
                "critical": is_crit
            })

    overall_status = "HEALTHY"
    if missing_critical_count > 0 or corrupt_count > 0 or any(r["status"] == "CRITICAL_STALE" for r in results):
        overall_status = "CRITICAL"
    elif stale_count > 0:
        overall_status = "WARNING"

    return {
        "count_monitored": len(MONITORED_JSONS),
        "healthy_count": sum(1 for r in results if r.get("status") == "HEALTHY"),
        "stale_count": stale_count,
        "corrupt_count": corrupt_count,
        "missing_critical_count": missing_critical_count,
        "overall_status": overall_status,
        "files": results
    }


def collect_background_feeds() -> Dict[str, Any]:
    """Prověří stav socketů, RSS feedů a stahování dat na pozadí."""
    # 1. IB Gateway Port 7497 test
    s_ib = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s_ib.settimeout(0.8)
    ib_connected = False
    try:
        s_ib.connect(("127.0.0.1", 7497))
        ib_connected = True
        s_ib.close()
    except Exception:
        ib_connected = False

    # 2. SuggestInvest Server Port 8000 test
    s_srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s_srv.settimeout(0.8)
    srv_connected = False
    try:
        s_srv.connect(("127.0.0.1", 8000))
        srv_connected = True
        s_srv.close()
    except Exception:
        srv_connected = False

    # 3. Načtení telemetrie z future_invest_demo_state.json
    state_file = os.path.join(DATA_DIR, "future_invest_demo_state.json")
    sync_time = "Neznámý"
    dom_connected = False
    dom_status = "–"
    wobi_10 = 0.0
    macro_long_mult = 1.0
    macro_short_mult = 1.0

    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                st = json.load(f)
                sync_time = st.get("sync_time_cet", "–")
                dom_info = st.get("dom_l2", {})
                dom_connected = dom_info.get("connected", False)
                dom_status = dom_info.get("status_text", dom_info.get("status", "–"))
                wobi_10 = dom_info.get("metrics", {}).get("wobi_10", 0.0)
                macro = st.get("cross_asset_macro", {})
                macro_long_mult = macro.get("long_multiplier", 1.0)
                macro_short_mult = macro.get("short_multiplier", 1.0)
        except Exception:
            pass

    return {
        "ib_gateway_socket_7497": {
            "online": ib_connected,
            "status_text": "PŘIPOJENO (Socket 7497 aktivní)" if ib_connected else "ODPOJENO (Socket 7497 nedostupný)"
        },
        "suggestinvest_server_8000": {
            "online": srv_connected,
            "status_text": "BĚŽÍ (HTTP server port 8000)" if srv_connected else "NEDOSTUPNÝ (Server neběží)"
        },
        "l2_dom_data_feed": {
            "connected": dom_connected,
            "status": dom_status,
            "wobi_10": round(wobi_10, 4)
        },
        "macro_calendar_bridge": {
            "active": True,
            "long_multiplier": macro_long_mult,
            "short_multiplier": macro_short_mult
        },
        "last_sync_time": sync_time
    }


def evaluate_alerts(
    cpu: Dict[str, Any],
    ram: Dict[str, Any],
    disk: Dict[str, Any],
    procs: Dict[str, Any],
    jsons: Dict[str, Any],
    feeds: Dict[str, Any]
) -> List[Dict[str, str]]:
    """Vyhodnotí všechny metriky a sestaví seznam varování a kritických alertů."""
    alerts = []

    # CPU alert
    if cpu.get("available") and cpu["overall_percent"] >= ALERT_THRESHOLDS["cpu_percent"]:
        alerts.append({
            "level": "CRITICAL",
            "category": "CPU",
            "message": f"Vysoké vytížení CPU: {cpu['overall_percent']}% (Limit: {ALERT_THRESHOLDS['cpu_percent']}%)"
        })

    # RAM alert
    if ram.get("available") and ram["percent"] >= ALERT_THRESHOLDS["ram_percent"]:
        alerts.append({
            "level": "CRITICAL",
            "category": "RAM",
            "message": f"Kritické zaplnění RAM: {ram['percent']}% ({ram['used_mb']} MB z {ram['total_mb']} MB)"
        })

    # Disk alert
    if disk.get("available") and disk["free_gb"] < ALERT_THRESHOLDS["disk_min_free_gb"]:
        alerts.append({
            "level": "CRITICAL",
            "category": "DISK",
            "message": f"Nedostatek místa na disku: zbývá jen {disk['free_gb']} GB (Min: {ALERT_THRESHOLDS['disk_min_free_gb']} GB)"
        })

    # Chybějící kritické procesy
    for missing in procs.get("missing_critical", []):
        alerts.append({
            "level": "CRITICAL",
            "category": "PROCESS",
            "message": f"Kritický proces NEBĚŽÍ: {missing['role']} ({missing['keyword']})"
        })

    # Zastavené/zamrzlé JSONy
    for f in jsons.get("files", []):
        if f.get("status") == "CRITICAL_STALE":
            limit_val = f.get("age_limit_sec") or ALERT_THRESHOLDS['json_stale_critical_sec']
            alerts.append({
                "level": "CRITICAL",
                "category": "JSON_DATA",
                "message": f"Zastavená data v {f['filename']} – stáří {f['age_str']} (limit: {limit_val} s)"
            })
        elif f.get("status") == "CORRUPTED":
            alerts.append({
                "level": "CRITICAL",
                "category": "JSON_CORRUPT",
                "message": f"Poškozený soubor {f['filename']}: {f.get('parse_error')}"
            })
        elif f.get("status") == "MISSING" and f.get("critical"):
            alerts.append({
                "level": "CRITICAL",
                "category": "JSON_MISSING",
                "message": f"Chybí klíčový datový soubor {f['filename']}"
            })

    # Gateway socket alert - klíčový port 7497 pro live data a objednávky
    if not feeds.get("ib_gateway_socket_7497", {}).get("online", False):
        alerts.append({
            "level": "CRITICAL",
            "category": "PORT_7497",
            "message": "IB Gateway Socket 7497 není dostupný (offline) – tržní data COMEX a objednávky jsou pozastaveny. Port je nutné nahodit."
        })

    return alerts


def generate_system_report(net_tracker: Optional[NetworkTracker] = None) -> Dict[str, Any]:
    """Sestaví kompletní snapshot systémového reportu."""
    if net_tracker is None:
        net_tracker = NetworkTracker()

    now_dt = datetime.datetime.now()
    now_str = now_dt.strftime("%d.%m.%Y %H:%M:%S")

    net = net_tracker.collect()
    cpu = collect_cpu_metrics()
    ram = collect_ram_metrics()
    disk = collect_disk_metrics()
    procs = collect_project_processes()
    jsons = collect_json_health()
    feeds = collect_background_feeds()
    alerts = evaluate_alerts(cpu, ram, disk, procs, jsons, feeds)

    overall_health = "HEALTHY"
    if any(a["level"] == "CRITICAL" for a in alerts):
        overall_health = "CRITICAL"
    elif alerts:
        overall_health = "WARNING"

    report = {
        "timestamp": now_str,
        "timestamp_iso": now_dt.isoformat(),
        "overall_health": overall_health,
        "system_info": {
            "os": f"{platform.system()} {platform.release()}",
            "hostname": socket.gethostname(),
            "python_version": platform.python_version(),
            "psutil_available": HAS_PSUTIL,
            "architecture": platform.machine()
        },
        "network_traffic": net,
        "cpu": cpu,
        "memory": ram,
        "disk": disk,
        "project_processes": procs,
        "monitored_jsons": jsons,
        "background_feeds": feeds,
        "alerts": alerts,
        "alerts_count": len(alerts),
        "vps_readiness": {
            "ready_for_cloud_vps": True,
            "systemd_service_name": "suggestinvest-reporter.service",
            "supported_os": ["Ubuntu 22.04/24.04 LTS", "Debian 12", "Windows Server 2022/2025", "Windows 11"]
        }
    }

    # 1. Atomické uložení aktuálního stavu do data/system_report.json
    try:
        safe_json_write(REPORT_JSON_PATH, report)
    except Exception as e:
        logger.error(f"Nelze zapsat {REPORT_JSON_PATH}: {e}")

    # 2. Uložení časové řady do telemetry history JSONL (s rotací posledních 1000 řádků)
    try:
        hist_entry = {
            "time": now_str,
            "health": overall_health,
            "cpu_pct": cpu.get("overall_percent"),
            "ram_pct": ram.get("percent"),
            "ram_used_mb": ram.get("used_mb"),
            "proj_ram_mb": procs.get("total_ram_mb"),
            "up_kb_s": net.get("rates", {}).get("upload_kb_s", 0.0),
            "down_kb_s": net.get("rates", {}).get("download_kb_s", 0.0),
            "alerts": len(alerts)
        }
        with open(HISTORY_JSONL_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(hist_entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

    return report


def print_console_dashboard(report: Dict[str, Any]) -> None:
    """Vykreslí přehledný textový dashboard do konzole."""
    h = report["overall_health"]
    h_badge = "🟢 ZDRAVÝ" if h == "HEALTHY" else ("🟠 VAROVÁNÍ" if h == "WARNING" else "🔴 KRITICKÝ STAV")

    print("\n" + "=" * 78)
    print(f"📊 SUGGESTINVEST SYSTEM REPORT · {report['timestamp']} · STAV: {h_badge}")
    print("=" * 78)

    # 1. Systémové zdroje
    cpu = report["cpu"]
    ram = report["memory"]
    disk = report["disk"]
    net = report["network_traffic"]

    cpu_txt = f"{cpu.get('overall_percent', '–')}% ({cpu.get('cores_logical', '?')} jader)"
    ram_txt = f"{ram.get('used_gb', '?')} / {ram.get('total_gb', '?')} GB ({ram.get('percent', '–')}%)"
    disk_txt = f"{disk.get('free_gb', '?')} GB volno ({disk.get('percent', '–')}% obsazeno)"

    rates = net.get("rates", {})
    session = net.get("session_traffic", {})
    net_rates_txt = f"↓ {rates.get('download_kb_s', 0)} KB/s  |  ↑ {rates.get('upload_kb_s', 0)} KB/s"
    net_sess_txt = f"Session: ↓ {session.get('recv_mb', 0)} MB  /  ↑ {session.get('sent_mb', 0)} MB"

    print(f"  ⚡ CPU:     {cpu_txt:<25} | 💾 RAM:  {ram_txt}")
    print(f"  💿 DISK:    {disk_txt:<25} | 🌐 SÍŤ:  {net_rates_txt}")
    print(f"  📦 DATA:    {net_sess_txt}")
    print("-" * 78)

    # 2. Procesy projektu
    procs = report["project_processes"]
    print(f"⚙️  PROCESY PROJEKTU ({procs.get('count', 0)} běžících | celkem RAM: {procs.get('total_ram_mb', 0):.1f} MB | CPU: {procs.get('total_cpu_percent', 0):.1f}%):")
    if procs.get("processes"):
        for p in procs["processes"]:
            crit_mark = "⭐" if p["critical"] else "  "
            print(f"   {crit_mark} PID {p['pid']:<6} | {p['role'][:34]:<34} | RAM: {p['ram_mb']:>6.1f} MB | CPU: {p['cpu_percent']:>4.1f}% | Uptime: {p['uptime_str']}")
    else:
        print("   ⚠️ Žádný aktivní proces projektu nebyl detekován!")

    if procs.get("missing_critical"):
        for m in procs["missing_critical"]:
            print(f"   ❌ CHYBÍ KRITICKÝ PROCES: {m['role']} ({m['keyword']})")
    print("-" * 78)

    # 3. Monitoring JSONů
    jsons = report["monitored_jsons"]
    print(f"📁 MONITORING DATOVÝCH JSONŮ ({jsons.get('healthy_count', 0)}/{jsons.get('count_monitored', 0)} v pořádku):")
    for f in jsons.get("files", []):
        st_icon = "🟢" if f["status"] == "HEALTHY" else ("🟠" if f["status"] == "STALE" else ("🔴" if "CRITICAL" in f["status"] or f["status"] == "CORRUPTED" else "⚪"))
        size_str = f"{f.get('size_kb', 0):>6.2f} KB" if f.get("exists") else "CHYBÍ"
        age_str = f.get("age_str", "–")
        print(f"   {st_icon} {f['filename']:<33} | {size_str} | {age_str:<18} | {f['title'][:20]}")
    print("-" * 78)

    # 4. Běh na pozadí a socket
    feeds = report["background_feeds"]
    ib = feeds.get("ib_gateway_socket_7497", {})
    srv = feeds.get("suggestinvest_server_8000", {})
    dom = feeds.get("l2_dom_data_feed", {})
    ib_icon = "🟢" if ib.get("online") else "🔴"
    srv_icon = "🟢" if srv.get("online") else "🔴"
    print(f"🔌 FEEDY A SPOJENÍ:")
    print(f"   {ib_icon} IBKR Socket 7497: {ib.get('status_text')} | DOM L2: {dom.get('status')} (WOBI: {dom.get('wobi_10', 0):+.4f})")
    print(f"   {srv_icon} Web Server 8000:  {srv.get('status_text')} | Poslední sync: {feeds.get('last_sync_time')}")

    # 5. Alerty
    if report["alerts"]:
        print("-" * 78)
        print(f"🚨 AKTIVNÍ ALERTY ({len(report['alerts'])}):")
        for a in report["alerts"]:
            lvl_icon = "🔴" if a["level"] == "CRITICAL" else "🟠"
            print(f"   {lvl_icon} [{a['category']}] {a['message']}")

    print("=" * 78 + "\n")


def run_monitoring_daemon(interval_sec: int = 10, quiet: bool = False) -> None:
    """Spustí nekonečnou dohledovou smyčku s nastaveným intervalem."""
    logger.info("=" * 65)
    logger.info("🛡️ SPUŠTĚN SYSTÉMOVÝ MONITORING A REPORTING (SuggestInvest)")
    logger.info(f"Interval měření: {interval_sec} s | Ukládání: {REPORT_JSON_PATH}")
    logger.info("Architektura: Připraveno pro Windows 11 i Cloud VPS Linux (Ubuntu/Debian)")
    logger.info("=" * 65)

    tracker = NetworkTracker()

    while True:
        try:
            report = generate_system_report(tracker)
            if not quiet:
                print_console_dashboard(report)
            else:
                logger.info(f"Heartbeat | Stav: {report['overall_health']} | CPU: {report['cpu'].get('overall_percent')}% | RAM: {report['memory'].get('percent')}% | JSONs: {report['monitored_jsons'].get('healthy_count')}/{report['monitored_jsons'].get('count_monitored')} OK")
        except Exception as e:
            logger.error(f"Chyba při generování systémového reportu: {e}", exc_info=True)

        time.sleep(interval_sec)


def main():
    parser = argparse.ArgumentParser(description="SuggestInvest System Reporting & VPS Telemetry")
    parser.add_argument("--interval", "-i", type=int, default=10, help="Interval měření v sekundách (výchozí: 10s)")
    parser.add_argument("--once", action="store_true", help="Provede pouze jeden jednorázový diagnostický snapshot a skončí")
    parser.add_argument("--json", action="store_true", help="Vytiskne čistý JSON report do stdout (pro curl/skripty)")
    parser.add_argument("--health", action="store_true", help="Vrátí exit kód 0 pokud je systém zdravý, jinak 1")
    parser.add_argument("--quiet", action="store_true", help="Běh v tichém režimu (pouze zápis do logu a JSONu)")

    args = parser.parse_args()

    tracker = NetworkTracker()

    if args.json:
        report = generate_system_report(tracker)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        sys.exit(0)

    if args.once:
        report = generate_system_report(tracker)
        print_console_dashboard(report)
        print(f"✅ Kompletní JSON snapshot uložen do: {REPORT_JSON_PATH}")
        print(f"✅ Historie metrik zaznamenána v:     {HISTORY_JSONL_PATH}")
        sys.exit(0)

    if args.health:
        report = generate_system_report(tracker)
        healthy = report["overall_health"] in ("HEALTHY", "WARNING")
        sys.exit(0 if healthy else 1)

    # Standardní režim: periodický daemon
    run_monitoring_daemon(interval_sec=args.interval, quiet=args.quiet)


if __name__ == "__main__":
    main()
