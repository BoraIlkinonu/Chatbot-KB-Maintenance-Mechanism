"""
Pipeline Orchestrator
Main entry point that runs: sync → analyze → stages → validate → notify.
Reads change analyzer output to determine which stages to execute.
"""

import sys
import json
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from config import STAGES, LOGS_DIR, OUTPUT_DIR
from sync_drive import run_sync
from change_analyzer import analyze_changes
from notify_slack import (
    notify_sync_complete, notify_build_complete, notify_validation_result,
    notify_new_images, notify_no_changes, notify_error, notify_activity_summary,
    notify_dry_run_summary, notify_revision_summary, notify_pptx_integrity,
)


def run_stage(stage_num, sync_result=None):
    """Run a single pipeline stage by number."""
    if stage_num == 1:
        from extract_media import run_extraction
        return run_extraction()
    elif stage_num == 2:
        from convert_docs import run_conversion
        return run_conversion()
    elif stage_num == 3:
        from extract_native_google import run_native_extraction
        return run_native_extraction(sync_result)
    elif stage_num == 5:
        from consolidate import run_consolidation
        return run_consolidation()
    elif stage_num == 6:
        from build_kb import run_build
        result = run_build()
        # Also build templates after the main KB
        from build_templates import run_build_templates
        run_build_templates()
        return result
    elif stage_num == 7:
        from qa.runner import run_qa
        report = run_qa(layers=[1, 3, 4])
        return {"verdict": report.compute_verdict(), "exit_code": report.exit_code()}
    else:
        print(f"Stage {stage_num} not implemented (Stage 4 is manual).")
        return None


def run_pipeline(skip_sync=False, force_full=False, cross_validate=False,
                  dry_run=False, download_all=False):
    """
    Execute the full pipeline.

    Args:
        skip_sync: If True, skip Drive sync and use latest sync log
        force_full: If True, run all stages regardless of changes
        cross_validate: If True, run Stage 8 cross-validation after build
        dry_run: If True, scan Drive and report changes without downloading or running stages
        download_all: If True, download ALL files from Drive (not just changed ones)
    """
    print()
    print("=" * 60)
    print("  Curriculum KB Maintenance Pipeline")
    print(f"  {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)
    print()

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    pipeline_log = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "stages_run": [],
        "errors": [],
        "status": "running",
    }

    sync_result = None

    try:
        # ─── Step 1: Sync ────────────────────────────────
        if dry_run:
            print("\n>>> STEP 1: Drive Sync (DRY RUN)\n")
            sync_result = run_sync(dry_run=True)
            notify_dry_run_summary(sync_result)
            notify_revision_summary(sync_result.get("revision_history", {}))
            notify_activity_summary(sync_result.get("activity_log", {}))
            pipeline_log["status"] = "dry_run"
            pipeline_log["completed_at"] = datetime.now(timezone.utc).isoformat()
            # Save pipeline log and exit early
            log_path = LOGS_DIR / f"pipeline_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
            with open(log_path, "w", encoding="utf-8") as f:
                json.dump(pipeline_log, f, indent=2, ensure_ascii=False)
            print(f"\n{'=' * 60}")
            print(f"  Dry run complete — no stages executed")
            print(f"  Log: {log_path}")
            print(f"{'=' * 60}\n")
            return pipeline_log
        elif not skip_sync:
            print("\n>>> STEP 1: Drive Sync\n")
            sync_result = run_sync(download_all=download_all)
            notify_sync_complete(sync_result["summary"], download_errors=sync_result.get("download_errors", []))
            notify_revision_summary(sync_result.get("revision_history", {}))

            # Notify about activity
            notify_activity_summary(sync_result.get("activity_log", {}))

            # Notify about PPTX integrity issues (errors/warnings only)
            notify_pptx_integrity(sync_result.get("integrity", {}))
        else:
            print("\n>>> STEP 1: Sync skipped (using latest log)\n")
            logs = sorted(LOGS_DIR.glob("sync_*.json"), reverse=True)
            if logs:
                with open(logs[0], "r", encoding="utf-8") as f:
                    sync_result = json.load(f)

        # ─── Step 2: Analyze Changes ─────────────────────
        print("\n>>> STEP 2: Change Analysis\n")
        if sync_result:
            analysis = analyze_changes(sync_result)
        else:
            analysis = {"has_changes": False, "stages_to_run": [], "admin_flags": []}

        if not analysis["has_changes"] and not force_full:
            print("No changes detected. Skipping pipeline stages.")
            notify_no_changes()
            pipeline_log["status"] = "no_changes"
            return pipeline_log

        # ─── Step 3: Run Pipeline Stages ─────────────────
        if force_full:
            stages_to_run = [1, 2, 3, 5, 6, 7]
            print(f"\nForce full rebuild: running stages {stages_to_run}\n")
        else:
            stages_to_run = analysis["stages_to_run"]
            print(f"\nStages to run based on changes: {stages_to_run}\n")

        for stage_num in stages_to_run:
            stage_info = STAGES.get(stage_num, {})
            stage_name = stage_info.get("name", f"Stage {stage_num}")

            print(f"\n>>> Running Stage {stage_num}: {stage_name}\n")
            try:
                result = run_stage(stage_num, sync_result)
                pipeline_log["stages_run"].append({
                    "stage": stage_num,
                    "name": stage_name,
                    "status": "success",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as e:
                error_msg = f"Stage {stage_num} ({stage_name}) failed: {e}"
                print(f"\nERROR: {error_msg}")
                traceback.print_exc()
                pipeline_log["errors"].append(error_msg)
                pipeline_log["stages_run"].append({
                    "stage": stage_num,
                    "name": stage_name,
                    "status": "failed",
                    "error": str(e),
                })
                notify_error(stage_name, str(e))
                # Continue with remaining stages unless it's a critical failure
                if stage_num in (5, 6):  # Consolidation or build failure is critical
                    print("Critical stage failed. Stopping pipeline.")
                    break

        # ─── Step 4: Handle Admin Flags ──────────────────
        if analysis.get("admin_flags"):
            print(f"\n>>> Admin Flags: {len(analysis['admin_flags'])} files need image analysis")
            notify_new_images(analysis["admin_flags"])

        # ─── Step 5: Report Results ──────────────────────
        # Check validation results
        if 7 in stages_to_run:
            from config import VALIDATION_DIR
            val_reports = list(VALIDATION_DIR.glob("validation_report_term*.json"))
            for vr in val_reports:
                with open(vr, "r", encoding="utf-8") as f:
                    report = json.load(f)
                notify_validation_result(report)

                # Notify build complete
                term = vr.stem.replace("validation_report_term", "")
                kb_path = OUTPUT_DIR / f"Term {term} - Lesson Based Structure.json"
                if kb_path.exists():
                    with open(kb_path, "r", encoding="utf-8") as f:
                        kb = json.load(f)
                    notify_build_complete(term, kb.get("total_lessons", 0), str(kb_path))

        # ─── Step 6: Cross-Validation (optional) ──────────
        if cross_validate:
            print("\n>>> Running Stage 8: Cross-Validation Expert Agent\n")
            try:
                from cross_validate_kb import run_cross_validation
                cv_result = run_cross_validation()
                pipeline_log["stages_run"].append({
                    "stage": 8,
                    "name": "Cross-Validation",
                    "status": "success",
                    "overall_confidence": cv_result.get("overall_confidence"),
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                })
            except Exception as e:
                error_msg = f"Stage 8 (Cross-Validation) failed: {e}"
                print(f"\nERROR: {error_msg}")
                traceback.print_exc()
                pipeline_log["errors"].append(error_msg)
                pipeline_log["stages_run"].append({
                    "stage": 8,
                    "name": "Cross-Validation",
                    "status": "failed",
                    "error": str(e),
                })

        pipeline_log["status"] = "completed"
        pipeline_log["completed_at"] = datetime.now(timezone.utc).isoformat()

    except Exception as e:
        error_msg = f"Pipeline failed: {e}"
        print(f"\nFATAL ERROR: {error_msg}")
        traceback.print_exc()
        pipeline_log["errors"].append(error_msg)
        pipeline_log["status"] = "failed"
        notify_error("Pipeline", str(e))

    # Save pipeline log
    log_path = LOGS_DIR / f"pipeline_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(pipeline_log, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 60}")
    print(f"  Pipeline {pipeline_log['status'].upper()}")
    print(f"  Stages run: {len(pipeline_log['stages_run'])}")
    print(f"  Errors: {len(pipeline_log['errors'])}")
    print(f"  Log: {log_path}")
    print(f"{'=' * 60}\n")

    return pipeline_log


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="KB Maintenance Pipeline")
    parser.add_argument("--skip-sync", action="store_true", help="Skip Drive sync")
    parser.add_argument("--force-full", action="store_true", help="Force full rebuild")
    parser.add_argument("--cross-validate", action="store_true",
                        help="Run Stage 8 cross-validation (requires claude CLI)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Scan and report changes without downloading or running stages")
    parser.add_argument("--download-all", action="store_true",
                        help="Download ALL files from Drive (not just changed). Use in CI.")
    args = parser.parse_args()

    run_pipeline(skip_sync=args.skip_sync, force_full=args.force_full,
                 cross_validate=args.cross_validate, dry_run=args.dry_run,
                 download_all=args.download_all)
