"""
Martin Capital Partners — Tamarac File Watcher
watch_tamarac.py

Runs silently in the background. Polls the data/ folder every 60 seconds.
When Tamarac_Holdings.xlsx changes (new modification time), auto-commits
and pushes to GitHub so Streamlit Cloud picks up the update.

Setup:
  1. Place this file in the Portfolio Dashboard project root
  2. Add the .vbs launcher to shell:startup (see instructions below)
  3. It starts automatically at login and survives screen locks

Logs to watch_tamarac.log in the project root for troubleshooting.
"""

import os
import sys
import time
import subprocess
import logging
from pathlib import Path
from datetime import datetime

# ── Configuration ──────────────────────────────────────────────────────────

DASHBOARD_DIR = Path(
    r"C:\Users\RyanAdair\Martin Capital Partners LLC"
    r"\Eugene - Documents\Operations\Scripts\Portfolio Dashboard"
)
WATCH_FILE = DASHBOARD_DIR / "data" / "Tamarac_Holdings.xlsx"
POLL_INTERVAL = 60  # seconds between checks
LOG_FILE = DASHBOARD_DIR / "watch_tamarac.log"

# ── Logging setup ──────────────────────────────────────────────────────────

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("watch_tamarac")


def _git(args):
    """Run a git command in the dashboard directory. Returns True on success."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(DASHBOARD_DIR),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            log.warning(f"git {' '.join(args)} failed: {result.stderr.strip()}")
            return False
        return True
    except subprocess.TimeoutExpired:
        log.error(f"git {' '.join(args)} timed out")
        return False
    except FileNotFoundError:
        log.error("git not found on PATH")
        return False


def _push_tamarac():
    """Stage, commit, and push the Tamarac file."""
    log.info("Change detected — pushing to GitHub...")

    if not _git(["add", "data/Tamarac_Holdings.xlsx"]):
        return False

    commit_msg = f"Update Tamarac holdings {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    if not _git(["commit", "-m", commit_msg]):
        # Could mean nothing to commit (no actual content change)
        log.info("Nothing to commit (file may be identical to last push)")
        return False

    if not _git(["push"]):
        log.error("Push failed — will retry on next cycle")
        return False

    log.info("Push complete — Streamlit Cloud will redeploy shortly")
    return True


def main():
    log.info("=" * 50)
    log.info("Tamarac file watcher started")
    log.info(f"Watching: {WATCH_FILE}")
    log.info(f"Poll interval: {POLL_INTERVAL}s")

    if not WATCH_FILE.exists():
        log.warning(f"File not found at startup: {WATCH_FILE}")
        log.info("Will keep checking until the file appears...")

    last_mtime = None

    # Initialize with current mtime so we don't push on first launch
    if WATCH_FILE.exists():
        last_mtime = os.path.getmtime(str(WATCH_FILE))
        log.info(f"Initial mtime: {datetime.fromtimestamp(last_mtime).strftime('%Y-%m-%d %H:%M:%S')}")

    while True:
        try:
            time.sleep(POLL_INTERVAL)

            if not WATCH_FILE.exists():
                continue

            current_mtime = os.path.getmtime(str(WATCH_FILE))

            # First time seeing the file (it appeared after startup)
            if last_mtime is None:
                last_mtime = current_mtime
                log.info(f"File appeared — mtime: {datetime.fromtimestamp(current_mtime).strftime('%Y-%m-%d %H:%M:%S')}")
                _push_tamarac()
                continue

            # File changed
            if current_mtime != last_mtime:
                old_dt = datetime.fromtimestamp(last_mtime).strftime('%Y-%m-%d %H:%M:%S')
                new_dt = datetime.fromtimestamp(current_mtime).strftime('%Y-%m-%d %H:%M:%S')
                log.info(f"File changed: {old_dt} → {new_dt}")
                last_mtime = current_mtime

                # Brief delay — let the file finish writing
                time.sleep(3)

                _push_tamarac()

        except KeyboardInterrupt:
            log.info("Watcher stopped by user")
            break
        except Exception as e:
            log.error(f"Unexpected error: {e}")
            time.sleep(POLL_INTERVAL)  # Don't spin on repeated errors


if __name__ == "__main__":
    main()