"""
Minimal configuration for the Drive Scanner webhook service.
Folder IDs, scopes, and env-var-based settings only.
"""

import os
from pathlib import Path

# ──────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────
BASE_DIR = Path(os.environ.get("SCANNER_BASE_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
STATE_DIR = BASE_DIR / "drive_scanner" / "state"

# State files (independent from main pipeline)
PREVIOUS_SCAN_FILE = STATE_DIR / "previous_scan.json"
REVISION_HISTORY_FILE = STATE_DIR / "revision_history.json"

# ──────────────────────────────────────────────────────────
# Google Drive target folders
# ──────────────────────────────────────────────────────────
TARGET_FOLDERS = {
    "term1": {
        "id": "17s13FlHGkaNPPlf3jAUY0tSza2yxHqPe",
        "name": "Term 1 - Foundations",
    },
    "term2": {
        "id": "16UgEwue1ROxFJyPTrowIqTQyduoNEIUb",
        "name": "Term 2 - Accelerator",
    },
    "term3": {
        "id": "1T6zzl0oqltIGcl8M4wAg2xy-z2HDZuxi",
        "name": "Term 3 - Mastery",
    },
}

# ──────────────────────────────────────────────────────────
# Google OAuth (read-only scopes)
# ──────────────────────────────────────────────────────────
SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.activity.readonly",
]

CLIENT_SECRET_FILE = BASE_DIR / (
    "client_secret_2_509243096178-6836hetgaplnd64sjh004f0c2471uvbo"
    ".apps.googleusercontent.com.json"
)
TOKEN_FILE = BASE_DIR / "token.json"

# Native Google MIME types
NATIVE_GOOGLE_MIMES = {
    "application/vnd.google-apps.document":     "google_doc",
    "application/vnd.google-apps.spreadsheet":  "google_sheet",
    "application/vnd.google-apps.presentation": "google_slides",
}

# ──────────────────────────────────────────────────────────
# Webhook & Slack (from environment / GitHub secrets)
# ──────────────────────────────────────────────────────────
EXTERNAL_WEBHOOK_URL = os.environ.get("EXTERNAL_WEBHOOK_URL", "")
SLACK_WEBHOOK_EXTERNAL = os.environ.get("SLACK_WEBHOOK_EXTERNAL", "")
