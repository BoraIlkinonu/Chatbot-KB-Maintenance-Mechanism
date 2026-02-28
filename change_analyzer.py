"""
Change Analyzer
Reads sync results and determines if there are changes to process.
Returns a simple list of changed files with term info.
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")

from config import LOGS_DIR, CHANGE_MANIFEST_FILE


def analyze_changes(sync_result):
    """
    Analyze all changes from a sync result.
    Returns: dict with has_changes (bool) and list of changed files.
    """
    change_details = []
    has_changes = False

    for term_key, term_data in sync_result.get("terms", {}).items():
        for change in term_data.get("files", []):
            ct = change["change_type"]
            if ct == "UNCHANGED":
                continue

            has_changes = True
            change_details.append({
                "file": change.get("name", ""),
                "term": term_key,
                "change_type": ct,
            })

    return {
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "has_changes": has_changes,
        "change_details": change_details,
        "summary": {
            "total_changes": len(change_details),
        },
    }


def write_change_manifest(sync_result):
    """Write a structured change manifest for downstream consumers.

    Groups files by change type: added, modified, deleted, renamed.
    Written to state/change_manifest.json for the local pipeline to read.
    """
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "added": [],
        "modified": [],
        "deleted": [],
        "renamed": [],
    }

    for term_key, term_data in sync_result.get("terms", {}).items():
        for change in term_data.get("files", []):
            ct = change["change_type"]
            if ct == "UNCHANGED" or ct == "METADATA_CHANGED":
                continue

            entry = {
                "file": change.get("name", ""),
                "term": term_key,
                "folder_path": change.get("folder_path", ""),
            }

            if ct == "NEW":
                manifest["added"].append(entry)
            elif ct == "MODIFIED":
                manifest["modified"].append(entry)
            elif ct == "DELETED":
                manifest["deleted"].append(entry)
            elif ct == "RENAMED":
                entry["previous_name"] = change.get("previous_name", "")
                manifest["renamed"].append(entry)

    manifest["summary"] = {
        "total_added": len(manifest["added"]),
        "total_modified": len(manifest["modified"]),
        "total_deleted": len(manifest["deleted"]),
        "total_renamed": len(manifest["renamed"]),
    }

    CHANGE_MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CHANGE_MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"  Change manifest: {CHANGE_MANIFEST_FILE}")
    return manifest


def run_analysis(sync_log_path=None):
    """Run analysis from a sync log file or the latest one."""
    print("=" * 60)
    print("  Change Analyzer")
    print("=" * 60)
    print()

    # Find the sync log
    if sync_log_path:
        log_path = Path(sync_log_path)
    else:
        log_files = sorted(LOGS_DIR.glob("sync_*.json"), reverse=True)
        if not log_files:
            print("No sync logs found. Run sync_drive.py first.")
            return None
        log_path = log_files[0]

    print(f"Reading: {log_path}")
    with open(log_path, "r", encoding="utf-8") as f:
        sync_result = json.load(f)

    analysis = analyze_changes(sync_result)

    # Save analysis
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = LOGS_DIR / f"analysis_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False)

    s = analysis["summary"]
    print(f"\n  Total changes: {s['total_changes']}")
    if not analysis["has_changes"]:
        print("\n  No changes detected. Pipeline stages will be skipped.")
    print(f"\n  Analysis saved: {output_path}")
    print("=" * 60)

    return analysis


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else None
    run_analysis(path)
