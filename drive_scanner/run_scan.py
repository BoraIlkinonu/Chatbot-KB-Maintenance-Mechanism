"""
Drive Scanner — CLI entry point.

Usage:
    python -m drive_scanner [--dry-run] [--download] [--full-sync] [--output FILE]

Modes:
    (default)    Scan + detect changes + webhook + Slack notification
    --download   Also download changed files (NEW/MODIFIED/RENAMED)
    --full-sync  Delete cached state + download ALL files from scratch
    --dry-run    Scan only, no webhook/downloads/state update
"""

import sys
import os
import json
import shutil
import time
import argparse
from datetime import datetime, timezone
from pathlib import Path

from drive_scanner.config import TARGET_FOLDERS, STATE_DIR, BASE_DIR
from drive_scanner.auth import authenticate, get_drive_service, get_activity_service
from drive_scanner.scanner import scan_folder, detect_changes
from drive_scanner.activity import fetch_recent_activity, fetch_file_revisions
from drive_scanner.state import (
    load_previous_scan, save_previous_scan,
    load_revision_history, save_revision_history,
)
from drive_scanner.webhook import build_payload, deliver_webhook
from drive_scanner.slack_notify import (
    notify_scan_changes, notify_scan_error, notify_webhook_delivery,
)

DOWNLOAD_DIR = Path(os.environ.get("SCANNER_DOWNLOAD_DIR", str(BASE_DIR / "downloads")))


def _clear_state():
    """Delete cached state files so next scan treats everything as NEW."""
    for f in STATE_DIR.glob("*.json"):
        f.unlink()
        print(f"  Deleted: {f}")


def _clear_downloads():
    """Delete all previously downloaded files."""
    if DOWNLOAD_DIR.exists():
        shutil.rmtree(DOWNLOAD_DIR)
        print(f"  Deleted: {DOWNLOAD_DIR}")


def run_scan(dry_run=False, download=False, full_sync=False, output_file=None):
    """Execute full scan: authenticate -> scan -> diff -> download -> webhook -> Slack -> state save.

    Args:
        dry_run: Scan only, no side effects.
        download: Download changed files after scanning.
        full_sync: Clear all cached state + downloads, then download everything.
        output_file: Path to write scan result JSON.
    """
    # full_sync implies download
    if full_sync:
        download = True

    mode_parts = []
    if dry_run:
        mode_parts.append("DRY RUN")
    if full_sync:
        mode_parts.append("FULL SYNC")
    elif download:
        mode_parts.append("DOWNLOAD")
    mode_label = f" ({' + '.join(mode_parts)})" if mode_parts else ""

    print("=" * 60)
    print("  Drive Scanner — Change Detection Webhook" + mode_label)
    print("=" * 60)
    print()

    # Full sync: wipe state and downloads first
    if full_sync and not dry_run:
        print("Clearing cached state and downloads...")
        _clear_state()
        _clear_downloads()
        print()

    # Authenticate
    creds = authenticate()
    drive_service = get_drive_service(creds)
    activity_service = get_activity_service(creds)
    print("Authenticated.\n")

    # Load previous scan baseline (empty after full_sync clear)
    prev_scan = load_previous_scan()
    last_sync_timestamp = prev_scan.get("scan_timestamp")

    # Load cumulative revision history
    revision_history = load_revision_history()

    scan_timestamp = datetime.now(timezone.utc).isoformat()

    scan_results = {
        "scan_timestamp": scan_timestamp,
        "terms": {},
    }
    activity_by_term = {}
    revision_data = {}
    all_current_files = {}
    download_summary = {"total_downloaded": 0, "total_errors": 0, "by_term": {}}

    for term_key, folder_info in TARGET_FOLDERS.items():
        folder_id = folder_info["id"]
        folder_name = folder_info["name"]
        print(f"--- Scanning: {folder_name} ({term_key}) ---")

        # Scan folder
        current_files = scan_folder(drive_service, folder_id)
        print(f"  Found {len(current_files)} files")

        # Build previous files lookup for this term
        term_prev = {
            f["id"]: f
            for f in prev_scan.get("terms", {}).get(term_key, {}).get("files", [])
        }

        # Detect changes
        changes = detect_changes(current_files, term_prev)

        # Count changes
        changed_count = sum(1 for c in changes if c["change_type"] != "UNCHANGED")
        print(f"  Changes: {changed_count} ({len(changes)} total including unchanged)")

        # Fetch activity for changed files
        print(f"  Fetching activity log...")
        changed_ids = [
            (c["id"], c["name"]) for c in changes
            if c["change_type"] in ("NEW", "MODIFIED", "METADATA_CHANGED", "RENAMED")
        ]
        activities = fetch_recent_activity(
            activity_service, folder_id,
            since_timestamp=last_sync_timestamp,
            file_ids=changed_ids if changed_ids else None,
        )
        activity_by_term[term_key] = activities
        print(f"  {len(activities)} activity records")

        # Fetch revision history for changed files
        changed_files = [
            c for c in changes
            if c["change_type"] in ("NEW", "MODIFIED", "METADATA_CHANGED")
        ]
        if changed_files:
            print(f"  Fetching revision history for {len(changed_files)} changed files...")
            for cf in changed_files:
                revisions = fetch_file_revisions(drive_service, cf["id"], cf["name"])
                if revisions:
                    file_id = cf["id"]
                    revision_data[file_id] = {
                        "name": cf["name"],
                        "folder_path": cf.get("folder_path", ""),
                        "term": term_key,
                        "revisions": revisions,
                    }
                    revision_history["files"][file_id] = {
                        "name": cf["name"],
                        "folder_path": cf.get("folder_path", ""),
                        "term": term_key,
                        "revisions": revisions,
                    }
                time.sleep(0.1)

        # Download files if requested
        if download and not dry_run:
            from drive_scanner.download import download_changes
            print(f"  Downloading files...")
            dl_result = download_changes(
                drive_service, creds, term_key, changes,
                str(DOWNLOAD_DIR), download_all=full_sync,
            )
            download_summary["by_term"][term_key] = dl_result
            download_summary["total_downloaded"] += len(dl_result["downloaded"])
            download_summary["total_errors"] += len(dl_result["errors"])
            print(f"  Downloaded: {len(dl_result['downloaded'])} | "
                  f"Errors: {len(dl_result['errors'])} | "
                  f"Skipped: {dl_result['skipped']}")

        # Store results
        scan_results["terms"][term_key] = {
            "folder_id": folder_id,
            "folder_name": folder_name,
            "files": current_files,
            "changes": changes,
        }

        all_current_files[term_key] = {"files": current_files}
        print()

    # Build webhook payload
    payload = build_payload(scan_results, activity_by_term, revision_data)

    # Add download info to payload if downloads happened
    if download and not dry_run:
        payload["downloads"] = download_summary

    # Summary
    summary = payload["summary"]
    print("=" * 60)
    print("  Scan Complete" + mode_label)
    print("=" * 60)
    print(f"  Total files scanned : {summary['total_files_scanned']}")
    print(f"  Total changed       : {summary['total_changed']}")
    print(f"  New                 : {summary['new']}")
    print(f"  Modified            : {summary['modified']}")
    print(f"  Deleted             : {summary['deleted']}")
    print(f"  Renamed             : {summary['renamed']}")
    print(f"  Metadata changed    : {summary['metadata_changed']}")
    print(f"  Has changes         : {payload['has_changes']}")
    if download and not dry_run:
        print(f"  Files downloaded    : {download_summary['total_downloaded']}")
        print(f"  Download errors     : {download_summary['total_errors']}")
        print(f"  Download dir        : {DOWNLOAD_DIR}")

    # Write payload to output file
    if output_file:
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"\n  Payload written to: {output_file}")

    # Always deliver webhook so dashboard shows results for every scan
    print(f"\n  Delivering webhook...")
    success, status_code, error = deliver_webhook(payload)
    if success:
        print(f"  Webhook delivered successfully (HTTP {status_code})")
    else:
        print(f"  Webhook delivery failed: {error}")
        if not dry_run:
            notify_webhook_delivery(success, status_code, error)

    if dry_run:
        print(f"\n  ** DRY RUN — no state update **")
    else:
        # Send Slack notification
        notify_scan_changes(payload)

        # Save state
        save_previous_scan({
            "scan_timestamp": scan_timestamp,
            "terms": all_current_files,
        })
        save_revision_history(revision_history)
        print(f"\n  State saved.")

    print("=" * 60)
    return payload


def main():
    parser = argparse.ArgumentParser(
        description="Drive Scanner — Google Drive change detection webhook"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Scan and print payload but don't deliver webhook or update state"
    )
    parser.add_argument(
        "--download", action="store_true",
        help="Download changed files (NEW/MODIFIED/RENAMED) after scanning"
    )
    parser.add_argument(
        "--full-sync", action="store_true",
        help="Delete all cached state and downloads, then re-download everything"
    )
    parser.add_argument(
        "--output", "-o", type=str, default=None,
        help="Write scan result JSON to this file path"
    )
    args = parser.parse_args()

    try:
        run_scan(
            dry_run=args.dry_run,
            download=args.download,
            full_sync=args.full_sync,
            output_file=args.output,
        )
    except Exception as e:
        print(f"\nFATAL ERROR: {e}")
        notify_scan_error(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
