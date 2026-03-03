"""
Slack notifications for the Drive Scanner webhook service.
Uses SLACK_WEBHOOK_EXTERNAL — completely separate from the main pipeline's Slack app.
"""

import json
import re
import urllib.request
from datetime import datetime

from drive_scanner.config import SLACK_WEBHOOK_EXTERNAL

DASHBOARD_URL = "https://drive-scanner-hook.tilkinonu.workers.dev"


def send_slack(message, blocks=None):
    """Send a message to the external Slack app via webhook."""
    webhook = SLACK_WEBHOOK_EXTERNAL
    if not webhook:
        print("[Slack] External notifications disabled (no SLACK_WEBHOOK_EXTERNAL set)")
        return False

    try:
        payload = {"text": message}
        if blocks:
            payload["blocks"] = blocks

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[Slack] Could not deliver notification: {e}")
        return False


# ──────────────────────────────────────────────────────────
# Notification templates
# ──────────────────────────────────────────────────────────

def notify_scan_changes(payload):
    """Notify about scan results with changes grouped by term."""
    summary = payload.get("summary", {})
    changes = payload.get("changes", {})
    has_changes = payload.get("has_changes", False)

    if not has_changes:
        return send_slack(
            ":zzz: *Drive Scan: No changes detected*\n"
            f"Scanned {summary.get('total_files_scanned', 0)} files — all up to date.\n"
            f"<{DASHBOARD_URL}|:mag: Dashboard>"
        )

    # Build change summary
    parts = []
    for key in ("new", "modified", "deleted", "renamed", "metadata_changed"):
        count = summary.get(key, 0)
        if count > 0:
            parts.append(f"{count} {key}")

    header = (
        f":bell: *Drive Changes Detected* — {summary.get('total_changed', 0)} file(s) changed\n"
        f"({', '.join(parts)})\n"
    )

    sections = [header]

    for term_key in sorted(changes):
        term_label = _term_label(term_key)
        term_changes = changes[term_key]
        sections.append(f"*{term_label}:*")
        for item in term_changes[:10]:
            ct = item.get("change_type", "?")
            name = item.get("file_name", "?")
            sections.append(f"  :small_blue_diamond: `{name}` — {ct}")
        if len(term_changes) > 10:
            sections.append(f"  _... +{len(term_changes) - 10} more_")

    sections.append(f"\n<{DASHBOARD_URL}|:mag: View full details on Dashboard>")

    return send_slack("\n".join(sections))


def notify_scan_error(error_msg):
    """Notify about a scan error."""
    msg = (
        f":rotating_light: *Drive Scanner Error*\n"
        f"```{error_msg[:500]}```"
    )
    return send_slack(msg)


def notify_webhook_delivery(success, status_code, error):
    """Notify about webhook delivery result (only on failure)."""
    if success:
        return False  # Don't notify on success

    msg = (
        f":warning: *Webhook Delivery Failed*\n"
        f"Status: {status_code or 'N/A'}\n"
        f"Error: {error or 'unknown'}"
    )
    return send_slack(msg)


# ──────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────

def _term_label(term_key):
    """Convert term key like 'term1' to 'Term 1'."""
    if not term_key:
        return ""
    m = re.match(r"term\s*(\d+)", str(term_key), re.IGNORECASE)
    return f"Term {m.group(1)}" if m else str(term_key)


def _format_timestamp(iso_str):
    """Format ISO8601 timestamp to readable 'YYYY-MM-DD HH:MM UTC'."""
    if not iso_str:
        return "unknown time"
    try:
        clean = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return iso_str[:16] if len(iso_str) >= 16 else iso_str
