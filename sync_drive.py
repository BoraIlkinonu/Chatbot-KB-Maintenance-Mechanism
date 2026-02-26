"""
Google Drive Sync Script
Scans target folders, detects changes since last sync, downloads changed files,
logs EVERYTHING (including UNCHANGED), and captures Drive Activity data.
"""

import sys
import os
import json
import hashlib
import io
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from googleapiclient.http import MediaIoBaseDownload

from config import (
    TARGET_FOLDERS, SOURCES_DIR, LOGS_DIR, PREVIOUS_SCAN_FILE,
    NATIVE_GOOGLE_MIMES, LOG_EVERYTHING,
)
from auth import authenticate, get_drive_service, get_activity_service


# ──────────────────────────────────────────────────────────
# Drive scanning
# ──────────────────────────────────────────────────────────

def scan_folder(service, folder_id, depth=0, folder_path=""):
    """Recursively scan a Drive folder. Returns list of file metadata dicts.
    Tracks the full folder path so downloaded files preserve hierarchy."""
    files = []
    page_token = None

    while True:
        resp = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            fields=(
                "nextPageToken,files(id,name,mimeType,size,md5Checksum,"
                "createdTime,modifiedTime,lastModifyingUser,owners,"
                "webViewLink,fileExtension,version,headRevisionId,"
                "parents,shared,description)"
            ),
            pageSize=1000,
            pageToken=page_token,
            orderBy="folder,name",
        ).execute()

        for item in resp.get("files", []):
            mime = item.get("mimeType", "")

            if mime == "application/vnd.google-apps.folder":
                # Recurse into subfolder, tracking path
                subfolder_name = item.get("name", "")
                subfolder_path = f"{folder_path}/{subfolder_name}" if folder_path else subfolder_name
                children = scan_folder(service, item["id"], depth + 1, subfolder_path)
                files.extend(children)
            else:
                last_mod = item.get("lastModifyingUser", {})
                owners = item.get("owners", [])

                files.append({
                    "id": item["id"],
                    "name": item.get("name", ""),
                    "mime_type": mime,
                    "size": int(item.get("size", 0) or 0),
                    "md5": item.get("md5Checksum", ""),
                    "created_time": item.get("createdTime", ""),
                    "modified_time": item.get("modifiedTime", ""),
                    "version": item.get("version", ""),
                    "head_revision_id": item.get("headRevisionId", ""),
                    "web_link": item.get("webViewLink", ""),
                    "extension": item.get("fileExtension", ""),
                    "parent_id": folder_id,
                    "folder_path": folder_path,
                    "shared": item.get("shared", False),
                    "description": item.get("description", ""),
                    "last_modifier_email": last_mod.get("emailAddress", ""),
                    "last_modifier_name": last_mod.get("displayName", ""),
                    "owner_email": owners[0].get("emailAddress", "") if owners else "",
                    "owner_name": owners[0].get("displayName", "") if owners else "",
                    "is_native_google": mime.startswith("application/vnd.google-apps."),
                    "native_type": NATIVE_GOOGLE_MIMES.get(mime),
                })

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return files


# ──────────────────────────────────────────────────────────
# Change detection
# ──────────────────────────────────────────────────────────

def load_previous_scan():
    """Load previous scan results for comparison."""
    if PREVIOUS_SCAN_FILE.exists():
        with open(PREVIOUS_SCAN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def detect_changes(current_files, previous_files_by_id):
    """
    Compare current scan against previous scan.
    Returns a list of change records for EVERY file (including UNCHANGED).
    """
    changes = []
    current_ids = set()

    for f in current_files:
        fid = f["id"]
        current_ids.add(fid)
        prev = previous_files_by_id.get(fid)

        if prev is None:
            changes.append({**f, "change_type": "NEW"})
        elif f["md5"] and prev.get("md5") and f["md5"] != prev["md5"]:
            changes.append({**f, "change_type": "MODIFIED", "previous_md5": prev["md5"]})
        elif f["modified_time"] != prev.get("modified_time"):
            # Modified time changed but md5 same or unavailable (native Google files)
            if f["is_native_google"]:
                changes.append({**f, "change_type": "MODIFIED"})
            else:
                changes.append({**f, "change_type": "METADATA_CHANGED"})
        elif f["name"] != prev.get("name"):
            changes.append({
                **f,
                "change_type": "RENAMED",
                "previous_name": prev["name"],
            })
        else:
            changes.append({**f, "change_type": "UNCHANGED"})

    # Detect deletions
    for fid, prev in previous_files_by_id.items():
        if fid not in current_ids:
            changes.append({**prev, "change_type": "DELETED"})

    return changes


# ──────────────────────────────────────────────────────────
# Drive Activity API
# ──────────────────────────────────────────────────────────

def fetch_recent_activity(activity_service, folder_id):
    """Fetch recent activity for a folder from Drive Activity API."""
    activities = []
    try:
        body = {
            "ancestorName": f"items/{folder_id}",
            "pageSize": 100,
            "filter": "time >= '2020-01-01T00:00:00Z'",
        }
        page_token = None

        while True:
            if page_token:
                body["pageToken"] = page_token

            resp = activity_service.activity().query(body=body).execute()

            for activity in resp.get("activities", []):
                timestamp = activity.get("timestamp") or ""
                if not timestamp:
                    ts_range = activity.get("timeRange", {})
                    timestamp = ts_range.get("endTime") or ts_range.get("startTime", "")

                actors = []
                for actor in activity.get("actors", []):
                    user = actor.get("user", {})
                    known_user = user.get("knownUser", {})
                    actors.append({
                        "person_name": known_user.get("personName", ""),
                        "is_current_user": known_user.get("isCurrentUser", False),
                    })

                actions = []
                for action in activity.get("actions", []):
                    detail = action.get("detail", {})
                    action_type = next(iter(detail.keys()), "unknown") if detail else "unknown"
                    actions.append({
                        "type": action_type,
                        "detail": detail.get(action_type, {}),
                    })

                targets = []
                for target in activity.get("targets", []):
                    drive_item = target.get("driveItem", {})
                    targets.append({
                        "title": drive_item.get("title", ""),
                        "name": drive_item.get("name", ""),
                        "mime_type": drive_item.get("mimeType", ""),
                        "file_id": drive_item.get("name", "").replace("items/", ""),
                    })

                activities.append({
                    "timestamp": timestamp,
                    "actors": actors,
                    "actions": actions,
                    "targets": targets,
                })

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

    except Exception as e:
        print(f"  Warning: Could not fetch activity for folder {folder_id}: {e}")

    return activities


# ──────────────────────────────────────────────────────────
# File downloading
# ──────────────────────────────────────────────────────────

EXPORT_MIMES = {
    "application/vnd.google-apps.document":
        ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "application/vnd.google-apps.spreadsheet":
        ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "application/vnd.google-apps.presentation":
        ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
}


def download_file(service, file_meta, dest_dir):
    """Download a file from Drive. Exports native Google formats to Office equivalents."""
    fid = file_meta["id"]
    name = file_meta["name"]
    mime = file_meta["mime_type"]

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # For native Google files, export to Office format
    if mime in EXPORT_MIMES:
        export_mime, ext = EXPORT_MIMES[mime]
        if not name.endswith(ext):
            name = name + ext
        request = service.files().export_media(fileId=fid, mimeType=export_mime)
    else:
        request = service.files().get_media(fileId=fid)

    dest_path = dest_dir / name
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    with open(dest_path, "wb") as f:
        f.write(fh.getvalue())

    # Compute local MD5
    local_md5 = hashlib.md5(fh.getvalue()).hexdigest()

    return str(dest_path), local_md5


# ──────────────────────────────────────────────────────────
# Main sync
# ──────────────────────────────────────────────────────────

def run_sync():
    """Execute full sync: scan → detect changes → download → log."""
    print("=" * 60)
    print("  KB Maintenance Pipeline — Drive Sync")
    print("=" * 60)
    print()

    # Ensure directories
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    PREVIOUS_SCAN_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Authenticate
    creds = authenticate()
    drive_service = get_drive_service(creds)
    activity_service = get_activity_service(creds)
    print("Authenticated.\n")

    # Load previous scan
    prev_scan = load_previous_scan()
    prev_files_by_id = {}
    for term_data in prev_scan.get("terms", {}).values():
        for f in term_data.get("files", []):
            prev_files_by_id[f["id"]] = f

    # Scan all target folders
    sync_result = {
        "sync_timestamp": datetime.now(timezone.utc).isoformat(),
        "terms": {},
        "summary": {
            "total_files": 0,
            "new": 0,
            "modified": 0,
            "deleted": 0,
            "renamed": 0,
            "metadata_changed": 0,
            "unchanged": 0,
            "downloaded": 0,
            "errors": 0,
        },
        "activity_log": {},
    }

    all_current_files = {}  # For saving as next "previous scan"

    for term_key, folder_info in TARGET_FOLDERS.items():
        folder_id = folder_info["id"]
        folder_name = folder_info["name"]
        print(f"--- Scanning: {folder_name} ({term_key}) ---")

        # Scan
        current_files = scan_folder(drive_service, folder_id)
        print(f"  Found {len(current_files)} files")

        # Detect changes
        term_prev = {
            f["id"]: f
            for f in prev_scan.get("terms", {}).get(term_key, {}).get("files", [])
        }
        changes = detect_changes(current_files, term_prev)

        # Fetch activity
        print(f"  Fetching activity log...")
        activities = fetch_recent_activity(activity_service, folder_id)
        sync_result["activity_log"][term_key] = activities
        print(f"  {len(activities)} activity records")

        # Download changed files
        term_sources = SOURCES_DIR / term_key
        downloaded = []
        errors = []

        for change in changes:
            ct = change["change_type"]
            sync_result["summary"]["total_files"] += 1

            if ct == "UNCHANGED":
                sync_result["summary"]["unchanged"] += 1
            elif ct == "NEW":
                sync_result["summary"]["new"] += 1
            elif ct == "MODIFIED":
                sync_result["summary"]["modified"] += 1
            elif ct == "DELETED":
                sync_result["summary"]["deleted"] += 1
            elif ct == "RENAMED":
                sync_result["summary"]["renamed"] += 1
            elif ct == "METADATA_CHANGED":
                sync_result["summary"]["metadata_changed"] += 1

            # Download NEW, MODIFIED, RENAMED files
            if ct in ("NEW", "MODIFIED", "RENAMED"):
                try:
                    # Preserve folder hierarchy from Drive
                    fp = change.get("folder_path", "")
                    dest_dir = term_sources / fp if fp else term_sources
                    print(f"  [{ct}] Downloading: {fp}/{change['name']}" if fp else f"  [{ct}] Downloading: {change['name']}")
                    local_path, local_md5 = download_file(
                        drive_service, change, dest_dir
                    )
                    change["local_path"] = local_path
                    change["local_md5"] = local_md5
                    downloaded.append(change["name"])
                    sync_result["summary"]["downloaded"] += 1
                except Exception as e:
                    print(f"    ERROR downloading {change['name']}: {e}")
                    change["download_error"] = str(e)
                    errors.append({"file": change["name"], "error": str(e)})
                    sync_result["summary"]["errors"] += 1

        # Store term results
        sync_result["terms"][term_key] = {
            "folder_id": folder_id,
            "folder_name": folder_name,
            "files": changes,
            "downloaded": downloaded,
            "errors": errors,
        }

        # Save for next comparison
        all_current_files[term_key] = {
            "files": current_files,
        }

        print(f"  Downloaded: {len(downloaded)} files")
        if errors:
            print(f"  Errors: {len(errors)}")
        print()

    # Save current scan as "previous" for next run
    with open(PREVIOUS_SCAN_FILE, "w", encoding="utf-8") as f:
        json.dump(
            {"scan_timestamp": sync_result["sync_timestamp"], "terms": all_current_files},
            f, indent=2, ensure_ascii=False,
        )

    # Write comprehensive sync log (append-style: one entry per sync)
    log_entry = sync_result
    log_file = LOGS_DIR / f"sync_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(log_entry, f, indent=2, ensure_ascii=False)

    # Summary
    s = sync_result["summary"]
    print("=" * 60)
    print("  Sync Complete")
    print("=" * 60)
    print(f"  Total files scanned : {s['total_files']}")
    print(f"  New                 : {s['new']}")
    print(f"  Modified            : {s['modified']}")
    print(f"  Deleted             : {s['deleted']}")
    print(f"  Renamed             : {s['renamed']}")
    print(f"  Metadata changed    : {s['metadata_changed']}")
    print(f"  Unchanged           : {s['unchanged']}")
    print(f"  Downloaded          : {s['downloaded']}")
    print(f"  Errors              : {s['errors']}")
    print(f"\n  Log saved: {log_file}")
    print("=" * 60)

    return sync_result


if __name__ == "__main__":
    run_sync()
