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
        print("[Slack] Notifications disabled (no SLACK_WEBHOOK_URL set)")
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
        print(f"[Slack] Could not deliver notification: {e} — pipeline results are unaffected")
        return False


# ──────────────────────────────────────────────────────────
# Notification templates
# ──────────────────────────────────────────────────────────

def notify_sync_complete(sync_summary, revision_count=0, download_errors=None):
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

    if revision_count > 0:
        msg += f"\nRevision data fetched for {revision_count} changed files"

    if s["errors"] > 0 and download_errors:
        # Classify errors
        export_too_large = []
        other_errors = []
        for err in download_errors:
            error_msg = err.get("error", "")
            if "exportSizeLimitExceeded" in error_msg or ("403" in error_msg and "export" in error_msg.lower()):
                export_too_large.append(err)
            else:
                other_errors.append(err)

        if export_too_large:
            msg += (
                f"\n:warning: *{len(export_too_large)} native Google Slides too large to export via API*\n"
                f"_Apps Script pre-export was also not found for these files._\n"
                f"_Action: run `exportAllLargeSlides()` in Apps Script, then re-run pipeline._\n"
            )
            for err in export_too_large[:15]:
                term_label = _term_label(err.get("term", ""))
                fp = err.get("folder_path", "")
                display = f"{fp}/{err['file']}" if fp else err["file"]
                msg += f"  • `{display}` [{term_label}]\n"
            if len(export_too_large) > 15:
                msg += f"  _... +{len(export_too_large) - 15} more_\n"

        if other_errors:
            msg += f"\n:rotating_light: *{len(other_errors)} unexpected download failure(s):*\n"
            for err in other_errors[:10]:
                term_label = _term_label(err.get("term", ""))
                fp = err.get("folder_path", "")
                display = f"{fp}/{err['file']}" if fp else err["file"]
                msg += f"  • `{display}` [{term_label}] — {err.get('error', '')[:150]}\n"
    elif s["errors"] > 0:
        msg += "\n:rotating_light: *Errors occurred during sync — see sync log JSON for error details (likely export-size-limit or permission issues)*"

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

    # Group by term for clearer display
    by_term = {}
    for flag in admin_flags:
        term = flag.get("term", "unknown")
        by_term.setdefault(term, []).append(flag)

    msg = (
        f":frame_with_picture: *New Images Detected — Admin Review Needed*\n"
        f"{len(admin_flags)} file(s) with new/modified images:\n"
    )
    for term_key in sorted(by_term):
        term_label = _term_label(term_key)
        msg += f"\n*{term_label}:* `sources/{term_key}/`\n"
        for flag in by_term[term_key][:10]:
            fp = flag.get("folder_path", "")
            display = f"{fp}/{flag.get('file', '')}" if fp else flag.get("file", "")
            msg += f"  • `{display}` ({flag.get('change_type', '')})\n"

    msg += "\n_Run Stage 4 (Claude image analysis) when ready._"

    return send_slack(msg)


def notify_no_changes():
    """Notify that sync found no changes."""
    msg = ":zzz: *KB Sync: No changes detected*\nAll files are up to date."
    return send_slack(msg)


def notify_pptx_integrity(integrity_results):
    """Notify about PPTX integrity check results."""
    if not integrity_results:
        return False

    total = integrity_results.get("total", 0)
    valid = integrity_results.get("valid", 0)
    errors = integrity_results.get("errors", [])
    warnings = integrity_results.get("warnings", [])

    if not errors and not warnings:
        return False  # All good, no need to notify

    if errors:
        emoji = ":rotating_light:"
        headline = "PPTX INTEGRITY ERRORS"
    else:
        emoji = ":warning:"
        headline = "PPTX Integrity Warnings"

    msg = (
        f"{emoji} *{headline}*\n"
        f"Checked: {total} | Valid: {valid} | "
        f"Errors: {len(errors)} | Warnings: {len(warnings)}\n"
    )

    for err in errors[:5]:
        msg += f"\n:x: `{err['file']}`: {err['error'][:100]}"

    for warn in warnings[:5]:
        msg += f"\n:warning: `{warn['file']}`: {warn['warning']}"

    if len(errors) > 5:
        msg += f"\n_... and {len(errors) - 5} more errors_"
    if len(warnings) > 5:
        msg += f"\n_... and {len(warnings) - 5} more warnings_"

    return send_slack(msg)


def notify_error(stage, error_msg):
    """Notify about a pipeline error."""
    msg = (
        f":rotating_light: *Pipeline Error — {stage}*\n"
        f"```{error_msg[:500]}```"
    )
    return send_slack(msg)


def notify_activity_summary(activities_by_term):
    """Notify about recent Drive activity across all terms, grouped by user."""
    total = sum(len(v) for v in activities_by_term.values())
    if total == 0:
        return False

    # Group activities by user across all terms with details
    user_events = {}  # {user_name: [{action, target, term, time}, ...]}
    for term, activities in activities_by_term.items():
        for a in activities:
            timestamp = a.get("timestamp", "")
            for actor in a.get("actors", []):
                user = actor.get("person_name", "unknown")
                if user not in user_events:
                    user_events[user] = []
                for action in a.get("actions", []):
                    for target in a.get("targets", []):
                        user_events[user].append({
                            "action": action.get("type", "unknown"),
                            "target": target.get("title", "?"),
                            "term": term,
                            "time": timestamp,
                        })

    msg = f":eyes: *Drive Activity Summary* ({total} events)\n"

    # Per-user: action details with timestamps and term
    for user, events in sorted(user_events.items()):
        # Sort by time descending (most recent first)
        events.sort(key=lambda e: e.get("time", ""), reverse=True)

        # Count actions
        action_counts = {}
        for e in events:
            action_counts[e["action"]] = action_counts.get(e["action"], 0) + 1
        counts_str = ", ".join(f"{c} {a}" for a, c in sorted(action_counts.items()))

        msg += f"\n*{user}* ({counts_str}):\n"
        for e in events[:5]:  # Show up to 5 most recent per user
            time_str = _format_timestamp(e["time"])
            term_str = _term_label(e["term"])
            msg += f"  • {e['action']} → `{e['target']}` [{term_str}] — {time_str}\n"
        if len(events) > 5:
            msg += f"  _... and {len(events) - 5} more events_\n"

    return send_slack(msg)


def notify_dry_run_summary(sync_result):
    """Notify about dry-run scan results — what WOULD happen."""
    s = sync_result.get("summary", {})

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Dry Run — Changes Detected"}
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":mag: *File changes:*\n"
                    f"  New: {s.get('new', 0)} | Modified: {s.get('modified', 0)} | "
                    f"Deleted: {s.get('deleted', 0)} | Renamed: {s.get('renamed', 0)} | "
                    f"Unchanged: {s.get('unchanged', 0)}"
                ),
            },
        },
    ]

    # Activity summary section
    activity_log = sync_result.get("activity_log", {})
    total_activity = sum(len(v) for v in activity_log.values())
    if total_activity > 0:
        activity_text = f":eyes: *Activity:* {total_activity} events across {len(activity_log)} terms"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": activity_text},
        })

    # Stages that would run
    has_changes = s.get("new", 0) + s.get("modified", 0) + s.get("deleted", 0) + s.get("renamed", 0) > 0
    if has_changes:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":gear: *Stages that would run:* 1 (Extract) → 2 (Convert) → 3 (Native) → 5 (Consolidate) → 6 (Build) → 7 (Validate)",
            },
        })

    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": "_Run without `--dry-run` to apply changes_"}],
    })

    msg = (
        f":mag: *Dry Run Complete* — "
        f"{s.get('new', 0)} new, {s.get('modified', 0)} modified, "
        f"{s.get('deleted', 0)} deleted files detected"
    )

    return send_slack(msg, blocks=blocks)


def _format_timestamp(iso_str):
    """Format ISO8601 timestamp to readable 'YYYY-MM-DD HH:MM UTC'."""
    if not iso_str:
        return "unknown time"
    try:
        # Handle various ISO formats
        clean = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return iso_str[:16] if len(iso_str) >= 16 else iso_str


def _term_label(term_key):
    """Convert term key like 'term1' to 'Term 1'."""
    if not term_key:
        return ""
    import re
    m = re.match(r"term\s*(\d+)", str(term_key), re.IGNORECASE)
    return f"Term {m.group(1)}" if m else str(term_key)


def notify_revision_summary(revision_data):
    """Notify about revision history for changed files."""
    if not revision_data:
        return False

    # Group revisions by user with timestamps and file details
    user_details = {}  # {user_name: [{file, term, time}, ...]}
    for file_id, file_info in revision_data.items():
        file_name = file_info.get("name", "unknown")
        folder_path = file_info.get("folder_path", "")
        term = file_info.get("term", "")
        for rev in file_info.get("revisions", []):
            user = rev.get("user_name") or rev.get("user_email") or "(Google system operation)"
            if user not in user_details:
                user_details[user] = []
            user_details[user].append({
                "file": file_name,
                "folder_path": folder_path,
                "term": term,
                "time": rev.get("time", ""),
            })

    if not user_details:
        return False

    msg = f":scroll: *Revision History* ({len(revision_data)} files)\n"

    # Group by term first, then by user within each term
    term_users = {}  # {term: {user: {file: info}}}
    for user, entries in user_details.items():
        for e in entries:
            term = e.get("term", "unknown")
            term_users.setdefault(term, {}).setdefault(user, {})
            key = e["file"]
            if key not in term_users[term][user] or e["time"] > term_users[term][user][key]["time"]:
                term_users[term][user][key] = e

    for term_key in sorted(term_users):
        term_label = _term_label(term_key)
        msg += f"\n*{term_label}:* `sources/{term_key}/`\n"
        for user, file_latest in sorted(term_users[term_key].items()):
            msg += f"  *{user}:*\n"
            for fname, info in sorted(file_latest.items()):
                time_str = _format_timestamp(info["time"])
                fp = info.get("folder_path", "")
                display = f"{fp}/{fname}" if fp else fname
                msg += f"    • `{display}` — {time_str}\n"

    return send_slack(msg)
