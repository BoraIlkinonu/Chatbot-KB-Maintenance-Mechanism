"""
Webhook payload builder and HTTP POST dispatcher.
Builds the v1.0 schema payload and delivers it to the external webhook URL.
"""

import json
import urllib.request
from datetime import datetime, timezone

from drive_scanner.config import EXTERNAL_WEBHOOK_URL
from drive_scanner.lessons import extract_lesson_range

SCHEMA_VERSION = "1.0"


def build_payload(scan_results, activity_by_term, revision_data):
    """Build the webhook payload from scan results.

    Args:
        scan_results: dict with keys {scan_timestamp, terms: {term_key: {files, changes}}}
        activity_by_term: dict {term_key: [activity_records]}
        revision_data: dict {file_id: {file_name, term, folder_path, revisions}}

    Returns:
        dict matching the v1.0 webhook payload schema.
    """
    scan_timestamp = scan_results.get("scan_timestamp", datetime.now(timezone.utc).isoformat())

    # Collect all non-UNCHANGED changes grouped by term
    changes_by_term = {}
    summary_counts = {
        "total_files_scanned": 0,
        "total_changed": 0,
        "new": 0,
        "modified": 0,
        "deleted": 0,
        "renamed": 0,
        "metadata_changed": 0,
    }

    for term_key, term_data in scan_results.get("terms", {}).items():
        term_changes = []
        for change in term_data.get("changes", []):
            ct = change.get("change_type", "UNCHANGED")
            summary_counts["total_files_scanned"] += 1

            if ct == "UNCHANGED":
                continue

            summary_counts["total_changed"] += 1
            count_key = ct.lower()
            if count_key in summary_counts:
                summary_counts[count_key] += 1

            entry = _build_change_entry(change)
            term_changes.append(entry)

        if term_changes:
            changes_by_term[term_key] = term_changes

    has_changes = summary_counts["total_changed"] > 0

    # Build revisions section keyed by file_id
    revisions_section = {}
    for file_id, info in revision_data.items():
        revisions_section[file_id] = {
            "file_name": info.get("name", ""),
            "term": info.get("term", ""),
            "folder_path": info.get("folder_path", ""),
            "revisions": info.get("revisions", []),
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "event_type": "drive_scan_complete",
        "scan_timestamp": scan_timestamp,
        "has_changes": has_changes,
        "summary": summary_counts,
        "changes": changes_by_term,
        "activity": {k: v for k, v in activity_by_term.items() if v},
        "revisions": revisions_section,
    }


def _build_change_entry(change):
    """Build a single change entry for the payload."""
    entry = {
        "file_id": change.get("id", ""),
        "file_name": change.get("name", ""),
        "mime_type": change.get("mime_type", ""),
        "change_type": change.get("change_type", ""),
        "folder_path": change.get("folder_path", ""),
        "modified_time": change.get("modified_time", ""),
        "web_link": change.get("web_link", ""),
        "size_bytes": change.get("size", 0),
        "md5": change.get("md5", ""),
        "is_native_google": change.get("is_native_google", False),
        "native_type": change.get("native_type"),
        "owner": change.get("owner_name", ""),
        "last_modifier": change.get("last_modifier_name", ""),
        "version": change.get("version", ""),
        "head_revision_id": change.get("head_revision_id", ""),
        "lessons": extract_lesson_range(
            change.get("folder_path", "") + "/" + change.get("name", "")
        ),
    }

    # Add change-type-specific fields
    if change.get("previous_md5"):
        entry["previous_md5"] = change["previous_md5"]
    if change.get("previous_name"):
        entry["previous_name"] = change["previous_name"]

    return entry


def deliver_webhook(payload, webhook_url=None):
    """POST the payload to the external webhook URL.

    Args:
        payload: dict to serialize as JSON.
        webhook_url: Override URL. Falls back to EXTERNAL_WEBHOOK_URL env var.

    Returns:
        (success: bool, status_code: int | None, error: str | None)
    """
    url = webhook_url or EXTERNAL_WEBHOOK_URL
    if not url:
        print("[Webhook] Delivery disabled (no EXTERNAL_WEBHOOK_URL set)")
        return False, None, "No webhook URL configured"

    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "drive-scanner/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status == 200, resp.status, None
    except Exception as e:
        print(f"[Webhook] Delivery failed: {e}")
        return False, None, str(e)
