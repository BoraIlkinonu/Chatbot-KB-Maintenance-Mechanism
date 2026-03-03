"""
Drive Activity API and file revision history fetching.
Extracted from sync_drive.py — activity parsing + revision queries.
"""

import time


# ──────────────────────────────────────────────────────────
# Activity API parsing
# ──────────────────────────────────────────────────────────

def _parse_activity_response(resp):
    """Parse activity API response into structured records."""
    records = []
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

        records.append({
            "timestamp": timestamp,
            "actors": actors,
            "actions": actions,
            "targets": targets,
        })
    return records


# ──────────────────────────────────────────────────────────
# Activity fetching strategies
# ──────────────────────────────────────────────────────────

def fetch_recent_activity(activity_service, folder_id, since_timestamp=None,
                          file_ids=None):
    """Fetch recent activity from Drive Activity API.

    First tries folder-level query (ancestorName). If that fails (e.g. no ownership),
    falls back to per-file queries (itemName) for changed files.

    Args:
        since_timestamp: ISO8601 timestamp to filter events from. If None, fetches from 2020.
        file_ids: List of (file_id, file_name) tuples for per-file fallback.
    """
    time_filter = f"time >= '{since_timestamp}'" if since_timestamp else "time >= '2020-01-01T00:00:00Z'"

    # Strategy 1: Folder-level query (requires folder ownership)
    activities = _fetch_activity_by_ancestor(activity_service, folder_id, time_filter)
    if activities is not None:
        return activities

    # Strategy 2: Per-file queries (same data quality, works with any access level)
    if file_ids:
        print(f"    Using per-file activity queries ({len(file_ids)} files)...")
        return _fetch_activity_by_files(activity_service, file_ids, time_filter)

    return []


def _fetch_activity_by_ancestor(activity_service, folder_id, time_filter):
    """Try folder-level activity query. Returns None if folder not owned."""
    activities = []
    try:
        body = {
            "ancestorName": f"items/{folder_id}",
            "pageSize": 100,
            "filter": time_filter,
        }
        page_token = None

        while True:
            if page_token:
                body["pageToken"] = page_token
            resp = activity_service.activity().query(body=body).execute()
            activities.extend(_parse_activity_response(resp))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        return activities

    except Exception:
        print(f"    Folder not owned — using per-file activity queries instead")
        return None


def _fetch_activity_by_files(activity_service, file_ids, time_filter):
    """Query activity per-file using itemName. Works with read-only access."""
    all_activities = []
    seen_timestamps = set()

    for file_id, file_name in file_ids:
        try:
            body = {
                "itemName": f"items/{file_id}",
                "pageSize": 50,
                "filter": time_filter,
            }
            resp = activity_service.activity().query(body=body).execute()
            records = _parse_activity_response(resp)

            for record in records:
                dedup_key = record["timestamp"] + str(record.get("targets", [{}])[0].get("file_id", ""))
                if dedup_key not in seen_timestamps:
                    seen_timestamps.add(dedup_key)
                    all_activities.append(record)

            time.sleep(0.05)

        except Exception:
            pass

    all_activities.sort(key=lambda a: a.get("timestamp", ""), reverse=True)
    return all_activities


# ──────────────────────────────────────────────────────────
# Revision History
# ──────────────────────────────────────────────────────────

def fetch_file_revisions(drive_service, file_id, file_name):
    """Fetch full revision history for a file.
    Returns list of {id, time, user_email, user_name, size}."""
    revisions = []
    try:
        page_token = None
        while True:
            resp = drive_service.revisions().list(
                fileId=file_id,
                fields="nextPageToken,revisions(id,modifiedTime,lastModifyingUser,size)",
                pageSize=1000,
                pageToken=page_token,
            ).execute()

            for rev in resp.get("revisions", []):
                user = rev.get("lastModifyingUser", {})
                user_name = user.get("displayName", "")
                user_email = user.get("emailAddress", "")
                if not user_name and not user_email:
                    user_name = "(Google system operation)"
                revisions.append({
                    "id": rev.get("id", ""),
                    "time": rev.get("modifiedTime", ""),
                    "user_email": user_email,
                    "user_name": user_name,
                    "size": int(rev.get("size", 0) or 0),
                })

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

    except Exception as e:
        print(f"    Skipping revision history for {file_name} (access limited)")

    return revisions
