"""
State persistence for the Drive Scanner.
Loads/saves previous_scan.json and revision_history.json independently from the main pipeline.
"""

import json
from datetime import datetime, timezone

from drive_scanner.config import PREVIOUS_SCAN_FILE, REVISION_HISTORY_FILE


def load_previous_scan():
    """Load previous scan results for comparison."""
    if PREVIOUS_SCAN_FILE.exists():
        try:
            with open(PREVIOUS_SCAN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_previous_scan(scan_data):
    """Save current scan as baseline for next run."""
    PREVIOUS_SCAN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PREVIOUS_SCAN_FILE, "w", encoding="utf-8") as f:
        json.dump(scan_data, f, indent=2, ensure_ascii=False)


def load_revision_history():
    """Load cumulative revision history from state file."""
    if REVISION_HISTORY_FILE.exists():
        try:
            with open(REVISION_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_updated": "", "files": {}}


def save_revision_history(history):
    """Save cumulative revision history to state file."""
    REVISION_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    history["last_updated"] = datetime.now(timezone.utc).isoformat()
    with open(REVISION_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
