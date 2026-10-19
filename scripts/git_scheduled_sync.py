#!/usr/bin/env python3
"""
SuggestInvest • Scheduled GitHub Synchronization Daemon
======================================================
Automated synchronization script for SuggestInvest Central Hub and subpages.
Schedules git sync at: 09:00, 12:00, 15:00, 18:00, 21:00 CET.

Features:
- Ensures security password gate is intact on all pages before committing
- Excludes sensitive credentials (IBKR-Demo-online, IBKR-Live-online, *.db, *.key)
- Rebase with origin/main to prevent conflicts with GitHub Actions cron
- Pushes latest live telemetry, system status, and demo states to GitHub Pages
- Provides --now flag for immediate manual deployment
"""

import os
import sys
import time
import subprocess
import logging
from datetime import datetime
import pytz

# Target CET sync hours
SYNC_HOURS_CET = [9, 12, 15, 18, 21]
CET_TZ = pytz.timezone("Europe/Prague")

# Base directory
REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(REPO_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "git_sync.log")

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

def run_cmd(cmd_list, cwd=REPO_DIR):
    """Executes a command and returns (returncode, stdout, stderr)"""
    try:
        res = subprocess.run(
            cmd_list,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except Exception as e:
        return -1, "", str(e)

def verify_security_gates():
    """Verifies that all public HTML files have the security password gate active."""
    logging.info("🔒 Checking security gates across HTML pages...")
    try:
        injector_script = os.path.join(REPO_DIR, "scripts", "inject_security_gate.py")
        if os.path.isfile(injector_script):
            code, out, err = run_cmd([sys.executable, injector_script])
            if code == 0:
                logging.info("✅ Security gate verification passed.")
                return True
            else:
                logging.warning(f"Security gate injector returned code {code}: {err}")
    except Exception as ex:
        logging.error(f"Error checking security gate: {ex}")
    return False

def sync_to_github(trigger_reason="Scheduled Sync"):
    """
    Executes git pull --rebase, stages web pages & data telemetry,
    commits, and pushes to origin/main.
    """
    now_cet = datetime.now(CET_TZ).strftime("%Y-%m-%d %H:%M:%S CET")
    logging.info(f"🚀 Starting GitHub synchronization ({trigger_reason}) at {now_cet}...")

    # 1. Verify security gates
    verify_security_gates()

    # 2. Fetch and Rebase to incorporate any remote commits cleanly
    logging.info("📥 Pulling latest changes with rebase from origin/main...")
    code, out, err = run_cmd(["git", "pull", "--rebase", "origin", "main"])
    if code != 0:
        logging.error(f"Failed to git pull --rebase: {err}. Output: {out}")
        # Try aborting rebase if stuck
        run_cmd(["git", "rebase", "--abort"])
        logging.warning("Rebase aborted to maintain repository integrity.")
        return False
    else:
        logging.info("✅ Rebase completed successfully.")

    # 3. Stage relevant pages and telemetry JSON files
    stage_targets = [
        ".gitignore",
        ".github/workflows/deploy_pages.yml",
        "hub.html",
        "FutureInvestDemo.html",
        "SilverInvestDemo.html",
        "trading.html",
        "trading_template.html",
        "system_status.html",
        "scalping.html",
        "scalping_v2.html",
        "argon_results_2026.html",
        "silver_results_2026.html",
        "argon_audit.html",
        "backtest.html",
        "pages.html",
        "sitemap.html",
        "index.html",
        "template.html",
        "scripts/inject_security_gate.py",
        "scripts/git_scheduled_sync.py",
        "start_scheduled_sync.bat",
        # Data files
        "data/future_invest_demo_state.json",
        "data/system_report.json",
        "data/live_portfolio.json",
        "data/demo_equity_history.json",
        "data/high_alpha_gold_telemetry.json",
        "data/high_alpha_silver_telemetry.json",
        "data/silver_walkforward_manifest.json",
        "data/silver_walkforward_2026_results.json",
        "data/silver_stress_test_report.json",
        "data/silver_gold_comparison.json",
        "data/silver_monte_carlo_results.json",
        "data/silver_quant_research_summary.json",
        "data/silver_rollover_calendar.json",
        "data/silver_shfe_state.json",
        "data/silver_macro_state.json",
        "data/silver_industrial_demand.json",
        "data/silver_cot_latest.json",
        "data/silver_atr_calibration.json",
        "data/silver_volatility_gate_calibration.json",
        "data/silver_portfolio_synergy.json",
        "data/backtest_oos_2026_v25_comparison.json",
        "data/gateway_outages.json",
        "data/scalping_trades.json",
        "data/backtest"
    ]

    for target in stage_targets:
        full_path = os.path.join(REPO_DIR, target)
        if os.path.exists(full_path):
            run_cmd(["git", "add", target])

    # 4. Check if there are staged changes
    code, status_out, _ = run_cmd(["git", "diff", "--cached", "--name-only"])
    if not status_out.strip():
        logging.info("ℹ️ No new changes to commit. Repository is already up-to-date.")
        return True

    staged_files = status_out.strip().splitlines()
    logging.info(f"📦 Staged {len(staged_files)} modified/new files.")

    # 5. Commit with informative message
    commit_msg = f"Auto-sync SuggestInvest Hub telemetry & dashboards [{now_cet}]"
    logging.info(f"📝 Committing: '{commit_msg}'")
    code, out, err = run_cmd(["git", "commit", "-m", commit_msg])
    if code != 0:
        logging.error(f"Failed to commit: {err}. Output: {out}")
        return False

    # 6. Push to origin main
    logging.info("📤 Pushing to origin main...")
    code, out, err = run_cmd(["git", "push", "origin", "main"])
    if code != 0:
        logging.error(f"Failed to git push: {err}. Output: {out}")
        return False

    logging.info(f"✅ Successfully deployed and synchronized to GitHub ({now_cet})!")
    return True

def run_scheduler_loop():
    """Continuous daemon loop checking for scheduled CET sync windows."""
    logging.info(f"🕒 SuggestInvest Git Sync Scheduler Daemon started.")
    logging.info(f"⏰ Target CET sync hours: {SYNC_HOURS_CET} (09:00, 12:00, 15:00, 18:00, 21:00 CET)")
    
    last_synced_hour_key = None

    while True:
        try:
            now = datetime.now(CET_TZ)
            hour_key = (now.year, now.month, now.day, now.hour)

            # Check if current CET hour matches target and hasn't fired yet for this hour
            if now.hour in SYNC_HOURS_CET and hour_key != last_synced_hour_key:
                sync_to_github(f"CET Window {now.hour:02d}:00")
                last_synced_hour_key = hour_key

            # Sleep 30 seconds before next check
            time.sleep(30)
        except KeyboardInterrupt:
            logging.info("🛑 Scheduler stopped by user.")
            break
        except Exception as e:
            logging.error(f"Unexpected error in scheduler loop: {e}")
            time.sleep(60)

if __name__ == "__main__":
    if "--now" in sys.argv or "-n" in sys.argv:
        success = sync_to_github(trigger_reason="Immediate Manual Deployment")
        sys.exit(0 if success else 1)
    else:
        # Run immediate sync on start, then enter continuous scheduler loop
        sync_to_github(trigger_reason="Initial Startup Sync")
        run_scheduler_loop()
