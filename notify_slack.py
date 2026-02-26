"""
Slack Notification Module
Sends formatted messages for sync alerts, build results, validation results,
error warnings, new image alerts, and parent folder activity.
"""

import sys
import json
import os
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")

from config import SLACK_WEBHOOK_URL


def send_slack(message, blocks=None):
    """Send a message to Slack via webhook."""
    webhook = SLACK_WEBHOOK_URL or os.environ.get("SLACK_WEBHOOK_URL", "")
    if not webhook:
        print("[Slack] No webhook URL configured. Skipping notification.")
        return False

    try:
        import urllib.request
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
        print(f"[Slack] Error sending notification: {e}")
        return False


# ──────────────────────────────────────────────────────────
# Notification templates
# ──────────────────────────────────────────────────────────

def notify_sync_complete(sync_summary):
    """Notify team about sync results."""
    s = sync_summary
    emoji = ":white_check_mark:" if s["errors"] == 0 else ":warning:"

    msg = (
        f"{emoji} *KB Sync Complete*\n"
        f"Files scanned: {s['total_files']} | "
        f"New: {s['new']} | Modified: {s['modified']} | "
        f"Deleted: {s['deleted']} | Unchanged: {s['unchanged']}\n"
        f"Downloaded: {s['downloaded']} | Errors: {s['errors']}"
    )

    if s["errors"] > 0:
        msg += "\n:rotating_light: *Errors occurred during sync — check logs*"

    return send_slack(msg)


def notify_build_complete(term, lesson_count, output_path):
    """Notify team about KB build results."""
    msg = (
        f":hammer_and_wrench: *KB Build Complete — Term {term}*\n"
        f"Lessons built: {lesson_count}\n"
        f"Output: `{output_path}`"
    )
    return send_slack(msg)


def notify_validation_result(report):
    """Notify team about validation results."""
    status = report.get("status", "UNKNOWN")
    confidence = report.get("overall_confidence", 0)
    errors = report.get("summary", {}).get("errors", 0)
    warnings = report.get("summary", {}).get("warnings", 0)
    blocked = report.get("publish_blocked", False)

    if blocked:
        emoji = ":no_entry:"
        headline = "PUBLISHING BLOCKED"
    elif status == "VALID":
        emoji = ":white_check_mark:"
        headline = "VALID"
    elif status == "VALID_WITH_WARNINGS":
        emoji = ":large_yellow_circle:"
        headline = "VALID WITH WARNINGS"
    else:
        emoji = ":warning:"
        headline = status

    msg = (
        f"{emoji} *Validation: {headline}*\n"
        f"Confidence: {confidence}% | "
        f"Errors: {errors} | Warnings: {warnings}"
    )

    if blocked:
        msg += "\n:rotating_light: *Fix ERROR-level anomalies before KB can be published*"
        # List errors
        for a in report.get("anomalies_by_severity", {}).get("ERROR", [])[:5]:
            msg += f"\n  • {a.get('message', '')}"

    return send_slack(msg)


def notify_new_images(admin_flags):
    """Alert admin about new images needing Claude analysis (Stage 4)."""
    if not admin_flags:
        return False

    msg = (
        f":frame_with_picture: *New Images Detected — Admin Review Needed*\n"
        f"{len(admin_flags)} file(s) with new/modified images:\n"
    )
    for flag in admin_flags[:10]:
        msg += f"  • `{flag.get('file', '')}` ({flag.get('change_type', '')})\n"

    msg += "\n_Run Stage 4 (Claude image analysis) when ready._"

    return send_slack(msg)


def notify_no_changes():
    """Notify that sync found no changes."""
    msg = ":zzz: *KB Sync: No changes detected*\nAll files are up to date."
    return send_slack(msg)


def notify_error(stage, error_msg):
    """Notify about a pipeline error."""
    msg = (
        f":rotating_light: *Pipeline Error — {stage}*\n"
        f"```{error_msg[:500]}```"
    )
    return send_slack(msg)


def notify_activity_summary(activities_by_term):
    """Notify about recent Drive activity across all terms."""
    total = sum(len(v) for v in activities_by_term.values())
    if total == 0:
        return False

    msg = f":eyes: *Drive Activity Summary* ({total} events)\n"
    for term, activities in activities_by_term.items():
        if activities:
            msg += f"\n*{term}*: {len(activities)} events"
            # Show latest 3
            for a in activities[:3]:
                actors = ", ".join(
                    act.get("person_name", "unknown") for act in a.get("actors", [])
                )
                actions = ", ".join(
                    act.get("type", "?") for act in a.get("actions", [])
                )
                targets = ", ".join(
                    t.get("title", "?") for t in a.get("targets", [])
                )
                msg += f"\n  • {actors}: {actions} → _{targets}_"

    return send_slack(msg)
