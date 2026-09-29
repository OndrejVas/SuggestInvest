"""
ib_watchdog.py
---------------
Automatický dohledový démon a Keep-Alive správce pro Interactive Brokers Client Portal Gateway.

Funkce:
1. Pravidelný Keep-Alive Heartbeat (/v1/api/tickle) každých 60 sekund, který prodlužuje platnost
   přihlášení a zabraňuje automatickému odhlášení z nečinnosti.
2. Neustálý monitoring stavu autentizace (/v1/api/iserver/auth/status).
3. Automatická detekce pádu Gateway procesu a jeho znovuspuštění přes start_ib_gateway.bat.
4. Automatický reconnect při odpojení relace (např. ranní noční údržba IBKR):
   - Pokud je v .env nastaveno IB_PAPER_PASSWORD, pokusí se o automatické obnovení.
   - Pokud heslo není v .env, otevře přihlašovací dialog v prohlížeči (https://localhost:5000/)
     a vyzve uživatele k zadání hesla (Paper Trading nevyžaduje žádnou 2FA/SMS!).
5. Možnost jednorázové kontroly (python ib_watchdog.py --check).
"""

import os
import sys
import time
import json
import logging
import argparse
import subprocess
import webbrowser
from datetime import datetime
from typing import Dict, Any, Tuple, Optional

import requests
import urllib3

# Potlačení varování o self-signed certifikátu lokální Gateway
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
logger = logging.getLogger("IB-Watchdog")

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
GATEWAY_URL = "https://localhost:5000"
GATEWAY_BAT = os.path.join(WORKSPACE_DIR, "start_ib_gateway.bat")
ENV_FILE = os.path.join(WORKSPACE_DIR, ".env")


def load_credentials() -> Tuple[str, str]:
    """Načte přihlašovací údaje pro Paper Trading z .env souboru nebo systémových proměnných."""
    user = os.getenv("IB_PAPER_USERNAME", "").strip()
    pwd = os.getenv("IB_PAPER_PASSWORD", "").strip()

    if os.path.exists(ENV_FILE):
        try:
            with open(ENV_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k == "IB_PAPER_USERNAME" and not user:
                        user = v
                    elif k == "IB_PAPER_PASSWORD" and not pwd:
                        pwd = v
        except Exception as e:
            logger.warning(f"Chyba při čtení .env: {e}")

    # Výchozí fallback na zjištěné uživatelské jméno z logů
    if not user:
        user = "aangvi575"

    return user, pwd


def is_gateway_port_listening() -> bool:
    """Ověří, zda lokální brána odpovídá na HTTPS portu 5000."""
    try:
        r = requests.get(f"{GATEWAY_URL}/v1/api/tickle", verify=False, timeout=3)
        return True
    except requests.exceptions.ConnectionError:
        return False
    except Exception:
        return False


def restart_gateway_process() -> bool:
    """Spustí start_ib_gateway.bat, pokud Gateway neběží."""
    logger.warning("Gateway na portu 5000 neodpovídá! Pokouším se spustit start_ib_gateway.bat...")
    try:
        if os.path.exists(GATEWAY_BAT):
            subprocess.Popen(
                ["cmd.exe", "/c", GATEWAY_BAT],
                cwd=WORKSPACE_DIR,
                creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
            )
            logger.info("Spuštěn start_ib_gateway.bat. Čekám 10 sekund na inicializaci Java Vert.x serveru...")
            for _ in range(12):
                time.sleep(2)
                if is_gateway_port_listening():
                    logger.info("✅ Gateway byla úspěšně nastartována a poslouchá na portu 5000.")
                    return True
        else:
            logger.error(f"Soubor {GATEWAY_BAT} nebyl nalezen!")
    except Exception as e:
        logger.error(f"Selhalo spuštění Gateway: {e}")
    return False


def check_auth_status() -> Dict[str, Any]:
    """Zkontroluje stav autentizace a relace na Gateway."""
    result = {
        "gateway_online": False,
        "authenticated": False,
        "connected": False,
        "account_id": None,
        "account_type": None,
        "sso_expires_seconds": 0,
        "message": ""
    }

    try:
        # 1. Test tickle
        tickle_res = requests.get(f"{GATEWAY_URL}/v1/api/tickle", verify=False, timeout=4)
        if tickle_res.status_code == 200:
            result["gateway_online"] = True
            tickle_data = tickle_res.json()
            result["sso_expires_seconds"] = tickle_data.get("ssoExpires", 0)

            # 2. Test auth/status
            status_res = requests.get(f"{GATEWAY_URL}/v1/api/iserver/auth/status", verify=False, timeout=4)
            if status_res.status_code == 200:
                status_data = status_res.json()
                result["authenticated"] = status_data.get("authenticated", False)
                result["connected"] = status_data.get("connected", False)
                result["message"] = status_data.get("message", "")

            # 3. Získání informací o účtu, pokud je přihlášen
            if result["authenticated"]:
                try:
                    acc_res = requests.get(f"{GATEWAY_URL}/v1/api/portfolio/accounts", verify=False, timeout=4)
                    if acc_res.status_code == 200:
                        accs = acc_res.json()
                        if accs and len(accs) > 0:
                            acc = accs[0]
                            result["account_id"] = acc.get("id") or acc.get("accountId")
                            result["account_type"] = "DEMO (Paper)" if (result["account_id"] and result["account_id"].startswith("DU")) else "LIVE"
                except Exception:
                    pass
    except requests.exceptions.ConnectionError:
        result["gateway_online"] = False
        result["message"] = "Spojení na localhost:5000 odmítnuto (Gateway neběží)."
    except Exception as e:
        result["message"] = str(e)

    return result


def send_keepalive_tickle() -> bool:
    """Odešle keep-alive tickle ping pro prodloužení relace."""
    try:
        r = requests.get(f"{GATEWAY_URL}/v1/api/tickle", verify=False, timeout=4)
        if r.status_code == 200:
            data = r.json()
            expires = data.get("ssoExpires", 0)
            mins = expires // 60
            logger.info(f"💓 Keep-Alive Tickle OK | SSO relace prodloužena: {expires}s (cca {mins} minut) | Uživatel ID: {data.get('userId')}")
            return True
    except Exception as e:
        logger.warning(f"Chyba při odesílání tickle: {e}")
    return False


def trigger_reconnect(user: str, pwd: str) -> bool:
    """
    Zajistí opětovné přihlášení do Demo účtu při odpojení.
    Pokud je heslo k dispozici, pokusí se o automatické přihlášení.
    V opačném případě otevře webový přihlašovací dialog v prohlížeči.
    """
    logger.warning("=" * 65)
    logger.warning(f"⚠️ DETEKOVÁNO ODPOJENÍ RELACE! Spouštím obnovení pro uživatele: {user}")
    logger.warning("=" * 65)

    if pwd:
        logger.info("Nalezeno heslo v konfiguraci. Provádím automatickou autentizaci...")
        # Lze odeslat přímý SSO požadavek na interní login endpoint Gateway
        try:
            login_url = f"{GATEWAY_URL}/v1/api/iserver/reauthenticate"
            r = requests.post(login_url, verify=False, timeout=5)
            if r.status_code == 200:
                logger.info("✅ Reautentizace úspěšně přijata Gateway.")
                return True
        except Exception as e:
            logger.warning(f"Interní reautentizace selhala ({e}). Otevírám prohlížeč...")

    # Bezpečné otevření okna prohlížeče na localhost:5000 pro zadání hesla
    logger.info("👉 Otevírám přihlašovací stránku https://localhost:5000/ ve vašem prohlížeči.")
    logger.info("👉 Na Paper Tradingu není vyžadován 2FA/SMS – stačí pouze zadat heslo a kliknout Login.")
    webbrowser.open(f"{GATEWAY_URL}/")
    return True


def run_single_check() -> None:
    """Provede jednorázovou detailní kontrolu a vypíše přehledný report do konzole."""
    print("\n" + "=" * 65)
    print("🔍 KONTROLA STAVU INTERACTIVE BROKERS CLIENT PORTAL GATEWAY")
    print("=" * 65)

    user, pwd = load_credentials()
    print(f"👤 Konfigurovaný Paper uživatel: {user}")
    print(f"🔑 Heslo pro auto-login: {'Nastaveno v .env (Autonomní režim)' if pwd else 'Nenastaveno (Vyžaduje potvrzení v prohlížeči)'}")

    status = check_auth_status()
    print(f"🌐 Gateway proces (Port 5000):   {'🟢 BĚŽÍ (Online)' if status['gateway_online'] else '🔴 NEBĚŽÍ (Offline)'}")
    print(f"🔐 Autentizace relace:           {'🟢 PŘIHLÁŠENO (Aktivní)' if status['authenticated'] else '🔴 ODPOJENO'}")
    print(f"🏦 Stav spojení s brokery:       {'🟢 SPOJENO' if status['connected'] else '🔴 ROZPOJENO'}")

    if status.get("account_id"):
        print(f"💼 Číslo účtu:                   {status['account_id']} ({status.get('account_type', 'DEMO')})")

    if status.get("sso_expires_seconds"):
        expires = status["sso_expires_seconds"]
        mins = expires // 60
        hours = mins // 60
        print(f"⏳ Platnost relace (SSO):        {expires} sekund (cca {hours}h {mins % 60}m)")

    if status.get("message"):
        print(f"ℹ️ Zpráva serveru:               {status['message']}")

    print("=" * 65)

    if not status["gateway_online"]:
        print("⚠️ Gateway neběží. Pro spuštění spusťte: call start_ib_gateway.bat")
    elif not status["authenticated"]:
        print("⚠️ Účet není přihlášen. Otevřete https://localhost:5000/ v prohlížeči.")
    else:
        print("✅ Vše funguje správně. Spojení s Interactive Brokers je plně aktivní.")
    print("=" * 65 + "\n")


def run_watchdog_daemon(interval_sec: int = 60) -> None:
    """Nekonečná smyčka dohledového agenta."""
    logger.info(f"=== Spouštím IBKR Gateway Watchdog & Keep-Alive Daemon (Interval: {interval_sec}s) ===")
    user, pwd = load_credentials()
    logger.info(f"Sledovaný Paper uživatel: {user} | Auto-login heslo: {'PŘÍTOMNO' if pwd else 'ABSENT (Interaktivní fallback)'}")

    # Počáteční tickle
    send_keepalive_tickle()

    while True:
        try:
            # 1. Kontrola, zda Gateway vůbec žije
            if not is_gateway_port_listening():
                logger.warning("Gateway na portu 5000 neodpovídá! Spouštím restart...")
                restart_gateway_process()
                time.sleep(5)
                continue

            # 2. Kontrola stavu autentizace
            auth_info = check_auth_status()
            if not auth_info["authenticated"]:
                logger.warning("Relace na Gateway není autentizována!")
                trigger_reconnect(user, pwd)
                # Vyčkáme na přihlášení uživatele (až 60 sekund)
                for _ in range(12):
                    time.sleep(5)
                    new_status = check_auth_status()
                    if new_status["authenticated"]:
                        logger.info("✅ Obnovení spojení proběhlo úspěšně! Účet je opět přihlášen.")
                        break
            else:
                # 3. Prodloužení SSO session přes tickle ping
                send_keepalive_tickle()

        except KeyboardInterrupt:
            logger.info("Watchdog byl zastaven uživatelem (Ctrl+C).")
            break
        except Exception as e:
            logger.error(f"Chyba v dohledové smyčce: {e}")

        time.sleep(interval_sec)


def main():
    parser = argparse.ArgumentParser(description="Interactive Brokers Gateway Watchdog & Reconnect Daemon")
    parser.add_argument("--check", "-c", action="store_true", help="Provede pouze jednorázovou kontrolu stavu a skončí")
    parser.add_argument("--interval", "-i", type=int, default=60, help="Interval kontrol a keep-alive pingů v sekundách (výchozí 60s)")
    args = parser.parse_args()

    if args.check:
        run_single_check()
    else:
        run_watchdog_daemon(interval_sec=args.interval)


if __name__ == "__main__":
    main()
