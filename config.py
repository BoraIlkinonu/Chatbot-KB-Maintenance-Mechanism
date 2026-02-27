"""
Central Configuration for KB Maintenance Pipeline
All constants, paths, API settings, and pipeline parameters.
"""

import os
import re
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

# Folder where Apps Script exports large native Slides as PPTX
# (bypasses the 10MB API export limit). Set to "" to disable.
# See scripts/export_large_slides.js for setup instructions.
EXPORTS_FOLDER_ID = os.environ.get("EXPORTS_FOLDER_ID", "1YOBetrxAjn5LBmcU9YzFNNOUQDrCEXcz")

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
    # Stage 4 (Image Analysis) is manual — requires Claude Code agents
    5: {"name": "Consolidation",            "script": "consolidate.py"},
    6: {"name": "KB Build",                 "script": "build_kb.py"},
    7: {"name": "Validation",               "script": "validate_kb.py"},
}

# Change type → stages to re-run
CHANGE_STAGE_MAP = {
    "text_only":       [2, 3, 5, 6, 7],
    "new_images":      [1, 2, 3, 5, 6, 7],  # + flag admin for Stage 4
    "new_file":        [1, 2, 3, 5, 6, 7],
    "structural":      [1, 2, 3, 5, 6, 7],  # full rebuild
    "deleted_file":    [5, 6, 7],
    "renamed_file":    [5, 6, 7],
    "metadata_only":   [6, 7],               # re-build KB with updated metadata
}

# File extensions that may contain images
IMAGE_BEARING_EXTENSIONS = {".pptx"}

# Video file extensions
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".webm"}

# Endstar platform tool keywords → canonical tool name
ENDSTAR_TOOLS = {
    "triggers": "Triggers",
    "npcs": "NPCs",
    "npc": "NPCs",
    "interactions": "Interactions",
    "mechanics tool": "Mechanics",
    "mechanics system": "Mechanics",
    "connections": "Connections",
    "props": "Props",
    "rule block": "Rule Blocks",
    "rule blocks": "Rule Blocks",
    "visuals tool": "Visuals",
    "visual tool": "Visuals",
    "sound tool": "Sound",
    "sound effect": "Sound",
    "sound engine": "Sound",
    "npc dialogue": "NPC dialogue",
    "level flow": "Level flow",
    "prototype": "Prototyping tools",
    "prototyping": "Prototyping tools",
}

# Single-word Endstar tool keywords that are ambiguous and need context
# These only match when co-occurring with Endstar-related terms nearby
ENDSTAR_AMBIGUOUS_TOOLS = {
    "sound": "Sound",
    "mechanics": "Mechanics",
    "visuals": "Visuals",
    "logic": "Logic",
}

# URL patterns for video services
VIDEO_URL_PATTERNS = [
    re.compile(r"(?:https?://)?(?:www\.)?youtube\.com/watch\?v=[\w\-]+", re.IGNORECASE),
    re.compile(r"(?:https?://)?youtu\.be/[\w\-]+", re.IGNORECASE),
    re.compile(r"(?:https?://)?(?:www\.)?vimeo\.com/\d+", re.IGNORECASE),
    # Note: drive.google.com/file/d/ removed — it matched ALL Drive files (PDFs, images, etc.)
    # Drive video files are captured by the video file scanner via actual file extensions
]

# Supported file types for conversion
CONVERTIBLE_EXTENSIONS = {".pptx", ".docx", ".xlsx", ".pdf"}

# Native Google MIME types for API extraction
NATIVE_GOOGLE_MIMES = {
    "application/vnd.google-apps.document":     "google_doc",
    "application/vnd.google-apps.spreadsheet":  "google_sheet",
    "application/vnd.google-apps.presentation": "google_slides",
}

# ──────────────────────────────────────────────────────────
# Validation (5-signal consensus)
# ──────────────────────────────────────────────────────────
SIGNAL_WEIGHTS = {
    "path_pattern":      1.0,
    "video_parent":      1.0,
    "metadata_crossref": 0.95,
    "semantic_align":    0.8,
    "keyword_match":     0.7,
    "volume_check":      0.5,
}

# Anomaly severity thresholds
VALIDATION_THRESHOLDS = {
    "misaligned_confidence": 60,    # Below this → MISALIGNED
    "volume_outlier_zscore": 2.0,   # Above this → VOLUME_OUTLIER
}

# ERROR-severity anomalies block KB publishing
BLOCK_ON_ERROR = True

# ──────────────────────────────────────────────────────────
# Week ↔ Lesson mapping (UAE curriculum)
# ──────────────────────────────────────────────────────────
WEEK_LESSON_MAP = {
    1: [1, 2],
    2: [3, 4],
    3: [5, 6],
    4: [7, 8],
    5: [9, 10],
    6: [11, 12],
}

# ──────────────────────────────────────────────────────────
# Duplicate Detection
# ──────────────────────────────────────────────────────────
FUZZY_NAME_THRESHOLD = 0.85  # Levenshtein similarity

# ──────────────────────────────────────────────────────────
# Consolidation
# ──────────────────────────────────────────────────────────
CONSOLIDATE_COMBINED = False  # Write combined file alongside per-term files

# ──────────────────────────────────────────────────────────
# Slack Notifications
# ──────────────────────────────────────────────────────────
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")

# ──────────────────────────────────────────────────────────
# Cross-Validation (Stage 8)
# ──────────────────────────────────────────────────────────
CROSS_VALIDATION_DIR = VALIDATION_DIR
JUDGE_MODEL = "opus"                      # Claude CLI model alias
CROSS_VALIDATION_SAMPLE_RATE = 0.5        # Fraction of passing lessons to verify

# ──────────────────────────────────────────────────────────
# QA System (Layered Validation)
# ──────────────────────────────────────────────────────────
QA_PREVIOUS_BUILDS_DIR = VALIDATION_DIR / "previous_builds"

# ──────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────
LOG_EVERYTHING = True   # Log UNCHANGED files too
LOG_ENCODING = "utf-8"
