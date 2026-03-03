"""
Drive Scanner — Standalone Google Drive change detection webhook service.

Scans Google Drive term folders, detects file changes (NEW/MODIFIED/DELETED/RENAMED),
and delivers structured JSON payloads to external webhook endpoints.
"""

__version__ = "1.0.0"
