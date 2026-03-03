"""
File downloading from Google Drive.
Extracted from sync_drive.py — download, export, retry logic.
"""

import io
import hashlib
import time
from pathlib import Path

from googleapiclient.http import MediaIoBaseDownload

from drive_scanner.scanner import _sanitize_name

# ──────────────────────────────────────────────────────────
# MIME type mappings
# ──────────────────────────────────────────────────────────

EXPORT_MIMES = {
    "application/vnd.google-apps.document":
        ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"),
    "application/vnd.google-apps.spreadsheet":
        ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".xlsx"),
    "application/vnd.google-apps.presentation":
        ("application/vnd.openxmlformats-officedocument.presentationml.presentation", ".pptx"),
}

SKIP_MIMES = {
    "application/vnd.google-apps.shortcut",
    "application/vnd.google-apps.folder",
    "application/vnd.google-apps.form",
    "application/vnd.google-apps.map",
    "application/vnd.google-apps.site",
}


# ──────────────────────────────────────────────────────────
# Path helpers
# ──────────────────────────────────────────────────────────

def expected_local_path(download_dir, term_key, file_meta):
    """Compute where a Drive file should be on the local filesystem."""
    name = file_meta["name"]
    mime = file_meta.get("mime_type", "")
    folder_path = file_meta.get("folder_path", "")

    if mime in EXPORT_MIMES:
        _, ext = EXPORT_MIMES[mime]
        if not name.endswith(ext):
            name = name + ext

    name = _sanitize_name(name)
    segments = [_sanitize_name(s) for s in folder_path.split("/") if s]

    base = Path(download_dir) / term_key
    if segments:
        return base / Path(*segments) / name
    return base / name


# ──────────────────────────────────────────────────────────
# Download logic
# ──────────────────────────────────────────────────────────

def _direct_export(creds, file_id, mime, dest_path):
    """Export native Google file via direct URL — bypasses 10MB API limit."""
    from google.auth.transport.requests import AuthorizedSession

    url_map = {
        "application/vnd.google-apps.presentation":
            f"https://docs.google.com/presentation/d/{file_id}/export/pptx",
        "application/vnd.google-apps.document":
            f"https://docs.google.com/document/d/{file_id}/export?format=docx",
        "application/vnd.google-apps.spreadsheet":
            f"https://docs.google.com/spreadsheets/d/{file_id}/export?format=xlsx",
    }
    url = url_map.get(mime)
    if not url:
        raise ValueError(f"No direct export URL for MIME type: {mime}")

    session = AuthorizedSession(creds)
    resp = session.get(url)
    resp.raise_for_status()

    if len(resp.content) == 0:
        raise ValueError(f"Direct export returned empty content for {file_id}")

    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(resp.content)

    local_md5 = hashlib.md5(resp.content).hexdigest()
    return str(dest_path), local_md5


def _is_transient_error(e):
    """Check if an exception is a transient/retryable error."""
    err_str = str(e)
    for marker in ("429", "500", "502", "503", "504", "timed out",
                    "Connection reset", "Connection aborted", "RemoteDisconnected"):
        if marker in err_str:
            return True
    return False


def download_file(service, file_meta, dest_path, creds=None):
    """Download a file from Drive to dest_path. Retries on failure.

    Returns:
        (local_path, local_md5) or (None, None) for skipped types.
    Raises:
        RuntimeError with full context on all failures.
    """
    fid = file_meta["id"]
    name = file_meta["name"]
    mime = file_meta["mime_type"]

    if mime in SKIP_MIMES:
        return None, None

    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    if mime in EXPORT_MIMES:
        export_mime, ext = EXPORT_MIMES[mime]
        request = service.files().export_media(fileId=fid, mimeType=export_mime)
    else:
        request = service.files().get_media(fileId=fid)

    # Attempt 1: Standard API download/export
    last_error = None
    try:
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        content = fh.getvalue()
        if len(content) == 0:
            raise ValueError("API returned empty content (0 bytes)")

        with open(dest_path, "wb") as f:
            f.write(content)

        return str(dest_path), hashlib.md5(content).hexdigest()

    except Exception as e:
        last_error = e

        # Attempt 2: Direct URL export (for exportSizeLimitExceeded)
        if "exportSizeLimitExceeded" in str(e) and mime in EXPORT_MIMES and creds:
            print(f"    API export too large for {name} — trying direct URL export...")
            try:
                return _direct_export(creds, fid, mime, dest_path)
            except Exception as e2:
                last_error = e2

        # Attempt 3: Retry once on transient errors
        if _is_transient_error(last_error):
            print(f"    Transient error for {name} — retrying in 2s...")
            time.sleep(2)
            try:
                if mime in EXPORT_MIMES:
                    export_mime, _ = EXPORT_MIMES[mime]
                    request = service.files().export_media(fileId=fid, mimeType=export_mime)
                else:
                    request = service.files().get_media(fileId=fid)

                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()

                content = fh.getvalue()
                if len(content) == 0:
                    raise ValueError("Retry returned empty content (0 bytes)")

                with open(dest_path, "wb") as f:
                    f.write(content)

                return str(dest_path), hashlib.md5(content).hexdigest()

            except Exception as e3:
                last_error = e3

    folder_path = file_meta.get("folder_path", "")
    size_mb = file_meta.get("size", 0) / (1024 * 1024)
    drive_link = file_meta.get("web_link", "")
    raise RuntimeError(
        f"Download failed for '{name}' (id={fid}, {size_mb:.1f}MB, {mime})\n"
        f"  Path: {folder_path}\n"
        f"  Drive: {drive_link}\n"
        f"  Error: {last_error}"
    )


# ──────────────────────────────────────────────────────────
# Batch download
# ──────────────────────────────────────────────────────────

def download_changes(service, creds, term_key, changes, download_dir, download_all=False):
    """Download changed files for a term.

    Args:
        service: Drive API service.
        creds: OAuth credentials (for direct export fallback).
        term_key: e.g. "term1".
        changes: list of change dicts from detect_changes().
        download_dir: root directory for downloads.
        download_all: if True, download ALL files (not just changed ones).

    Returns:
        dict with keys: downloaded, errors, skipped
    """
    result = {"downloaded": [], "errors": [], "skipped": 0}

    for change in changes:
        ct = change.get("change_type", "UNCHANGED")
        mime = change.get("mime_type", "")

        if mime in SKIP_MIMES or ct == "DELETED":
            result["skipped"] += 1
            continue

        should_download = download_all or ct in ("NEW", "MODIFIED", "RENAMED")
        if not should_download:
            result["skipped"] += 1
            continue

        local_path = expected_local_path(download_dir, term_key, change)
        label = ct if ct != "UNCHANGED" else "SYNC"
        fp = change.get("folder_path", "")
        display = f"{fp}/{change['name']}" if fp else change["name"]
        print(f"  [{label}] Downloading: {display}")

        try:
            path, md5 = download_file(service, change, local_path, creds=creds)
            if path:
                result["downloaded"].append({
                    "name": change["name"],
                    "file_id": change.get("id", ""),
                    "local_path": str(path),
                    "local_md5": md5,
                    "change_type": ct,
                })
        except Exception as e:
            print(f"    FAILED: {change['name']}: {e}")
            result["errors"].append({
                "name": change["name"],
                "file_id": change.get("id", ""),
                "error": str(e)[:300],
                "change_type": ct,
            })

    return result
