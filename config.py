"""
Central Configuration for KB Maintenance Pipeline
All constants, paths, API settings, and pipeline parameters.
"""

import os
from pathlib import Path

# ──────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────
BASE_DIR = Path(os.environ.get("PIPELINE_BASE_DIR", os.path.dirname(os.path.abspath(__file__))))
SOURCES_DIR = BASE_DIR / "sources"          # Downloaded Drive files
CONVERTED_DIR = BASE_DIR / "converted"       # Markdown/CSV output from Stage 2
MEDIA_DIR = BASE_DIR / "media"               # Extracted images from Stage 1
NATIVE_DIR = BASE_DIR / "native_extracts"    # Google API extracts from Stage 3
CONSOLIDATED_DIR = BASE_DIR / "consolidated" # Merged content from Stage 5
OUTPUT_DIR = BASE_DIR / "output"             # Final KB JSON from Stage 6
LOGS_DIR = BASE_DIR / "logs"                 # All log files
VALIDATION_DIR = BASE_DIR / "validation"     # Validation results from Stage 7

# State files
PREVIOUS_SCAN_FILE = BASE_DIR / "state" / "previous_scan.json"
CHANGE_MANIFEST_FILE = BASE_DIR / "state" / "change_manifest.json"
SYNC_LOG_FILE = LOGS_DIR / "sync_log.json"
BUILD_LOG_FILE = LOGS_DIR / "build_log.json"

# ──────────────────────────────────────────────────────────
# Google Drive
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
# Google OAuth
# ──────────────────────────────────────────────────────────
SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.activity.readonly",
    "https://www.googleapis.com/auth/presentations.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/directory.readonly",
]

CLIENT_SECRET_FILE = BASE_DIR / (
    "client_secret_2_509243096178-6836hetgaplnd64sjh004f0c2471uvbo"
    ".apps.googleusercontent.com.json"
)
TOKEN_FILE = BASE_DIR / "token.json"

# ──────────────────────────────────────────────────────────
# Pipeline Stages
# ──────────────────────────────────────────────────────────
STAGES = {
    1: {"name": "Media Extraction",         "script": "extract_media.py"},
    2: {"name": "Document Conversion",      "script": "convert_docs.py"},
    3: {"name": "Native Google Extraction",  "script": "extract_native_google.py"},
    5: {"name": "Consolidation",            "script": "consolidate.py"},
    6: {"name": "KB Build",                 "script": "build_kb.py"},
    7: {"name": "Validation",               "script": "validate_kb_judge.py"},
}

# Supported file types for conversion
CONVERTIBLE_EXTENSIONS = {".pptx", ".docx", ".xlsx", ".pdf"}

# Native Google MIME types for API extraction
NATIVE_GOOGLE_MIMES = {
    "application/vnd.google-apps.document":     "google_doc",
    "application/vnd.google-apps.spreadsheet":  "google_sheet",
    "application/vnd.google-apps.presentation": "google_slides",
}

# ──────────────────────────────────────────────────────────
# Slack Notifications
# ──────────────────────────────────────────────────────────
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

# ──────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────
LOG_EVERYTHING = True   # Log UNCHANGED files too
LOG_ENCODING = "utf-8"
