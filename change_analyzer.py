"""
Smart Change Analyzer
Reads sync results and determines which pipeline stages need to re-run.
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")

from config import (
    CHANGE_STAGE_MAP, IMAGE_BEARING_EXTENSIONS, CONVERTIBLE_EXTENSIONS,
    NATIVE_GOOGLE_MIMES, LOGS_DIR,
)


def classify_change(change):
    """
    Classify a single file change into a change category.
    Returns: (category, needs_admin_flag)
    """
    ct = change["change_type"]
    name = change.get("name", "")
    ext = ("." + change.get("extension", "")).lower() if change.get("extension") else ""
    mime = change.get("mime_type", "")

    if ct == "UNCHANGED":
        return None, False

    if ct == "DELETED":
        return "deleted_file", False

    if ct == "RENAMED":
        return "renamed_file", False

    if ct == "METADATA_CHANGED":
        return "metadata_only", False

    # NEW or MODIFIED
    is_native = change.get("is_native_google", False)
    is_native_presentation = mime == "application/vnd.google-apps.presentation"

    if ct == "NEW":
        if ext in IMAGE_BEARING_EXTENSIONS or is_native_presentation:
            return "new_images", True   # Flag admin for image analysis
        return "new_file", False

    # MODIFIED
    if ext in IMAGE_BEARING_EXTENSIONS or is_native_presentation:
        # PPTX or native presentation modified — might have new images
        return "new_images", True
    elif ext in CONVERTIBLE_EXTENSIONS or is_native:
        return "text_only", False
    else:
        return "structural", False


def analyze_changes(sync_result):
    """
    Analyze all changes from a sync result.
    Returns: dict with stages_to_run, change_details, admin_flags
    """
    all_stages = set()
    admin_flags = []
    change_details = []
    has_changes = False

    for term_key, term_data in sync_result.get("terms", {}).items():
        for change in term_data.get("files", []):
            ct = change["change_type"]
            if ct == "UNCHANGED":
                continue

            has_changes = True
            category, needs_admin = classify_change(change)

            if category is None:
                continue

            stages = CHANGE_STAGE_MAP.get(category, [])
            all_stages.update(stages)

            if needs_admin:
                is_native_pres = change.get("mime_type") == "application/vnd.google-apps.presentation"
                admin_flags.append({
                    "file": change.get("name", ""),
                    "folder_path": change.get("folder_path", ""),
                    "term": term_key,
                    "change_type": ct,
                    "source_type": "native_slides" if is_native_pres else "pptx",
                    "reason": (
                        "New/modified native Google Slides may contain new images requiring analysis (Stage 4)"
                        if is_native_pres else
                        "New/modified PPTX may contain new images requiring Claude analysis (Stage 4)"
                    ),
                })

            change_details.append({
                "file": change.get("name", ""),
                "file_id": change.get("id", ""),
                "term": term_key,
                "change_type": ct,
                "category": category,
                "stages_triggered": stages,
            })

    analysis = {
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "has_changes": has_changes,
        "stages_to_run": sorted(all_stages),
        "admin_flags": admin_flags,
        "change_details": change_details,
        "summary": {
            "total_changes": len(change_details),
            "categories": {},
            "stages_to_run": sorted(all_stages),
            "needs_admin_review": len(admin_flags) > 0,
        },
    }

    # Count by category
    for detail in change_details:
        cat = detail["category"]
        analysis["summary"]["categories"][cat] = (
            analysis["summary"]["categories"].get(cat, 0) + 1
        )

    return analysis


def run_analysis(sync_log_path=None):
    """Run analysis from a sync log file or the latest one."""
    print("=" * 60)
    print("  Smart Change Analyzer")
    print("=" * 60)
    print()

    # Find the sync log
    if sync_log_path:
        log_path = Path(sync_log_path)
    else:
        # Find most recent sync log
        log_files = sorted(LOGS_DIR.glob("sync_*.json"), reverse=True)
        if not log_files:
            print("No sync logs found. Run sync_drive.py first.")
            return None
        log_path = log_files[0]

    print(f"Reading: {log_path}")
    with open(log_path, "r", encoding="utf-8") as f:
        sync_result = json.load(f)

    # Analyze
    analysis = analyze_changes(sync_result)

    # Save analysis
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = LOGS_DIR / f"analysis_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, indent=2, ensure_ascii=False)

    # Print summary
    s = analysis["summary"]
    print(f"\n  Total changes: {s['total_changes']}")
    print(f"  Categories:")
    for cat, count in s["categories"].items():
        print(f"    {cat}: {count}")
    print(f"\n  Stages to run: {s['stages_to_run']}")
    print(f"  Needs admin review: {s['needs_admin_review']}")

    if analysis["admin_flags"]:
        print(f"\n  Admin flags:")
        for flag in analysis["admin_flags"]:
            print(f"    - {flag['file']} ({flag['reason'][:60]}...)")

    if not analysis["has_changes"]:
        print("\n  No changes detected. Pipeline stages will be skipped.")

    print(f"\n  Analysis saved: {output_path}")
    print("=" * 60)

    return analysis


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else None
    run_analysis(path)
