"""
Drive folder scanning and change detection.
Extracted from sync_drive.py — scan_folder() and detect_changes().
"""

import re

from drive_scanner.config import NATIVE_GOOGLE_MIMES

# ──────────────────────────────────────────────────────────
# Path sanitization (Windows-safe file/folder names)
# ──────────────────────────────────────────────────────────

_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*]')


def _sanitize_name(name):
    """Replace characters illegal in Windows file/folder names."""
    sanitized = _ILLEGAL_CHARS.sub('_', name)
    sanitized = sanitized.rstrip('. ')
    return sanitized or '_unnamed'


# ──────────────────────────────────────────────────────────
# Drive scanning
# ──────────────────────────────────────────────────────────

def scan_folder(service, folder_id, depth=0, folder_path=""):
    """Recursively scan a Drive folder. Returns list of file metadata dicts.
    Tracks the full folder path so hierarchy is preserved."""
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
                subfolder_name = item.get("name", "")
                safe_name = _sanitize_name(subfolder_name)
                subfolder_path = f"{folder_path}/{safe_name}" if folder_path else safe_name
                children = scan_folder(service, item["id"], depth + 1, subfolder_path)
                files.extend(children)
            elif mime == "application/vnd.google-apps.shortcut":
                print(f"  Skipping shortcut: {item.get('name', '')}")
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
