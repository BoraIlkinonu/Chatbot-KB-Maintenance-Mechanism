"""
Pipeline Orchestrator

Two modes:
  --mode ci:    Sync Drive -> detect changes -> Slack notify -> done
  --mode local: Sync (optional) -> convert -> native extract -> LLM consolidate
                -> LLM KB build -> LLM templates -> LLM validation

CI has no ANTHROPIC_API_KEY. CI only syncs and notifies admin.
Full pipeline (LLM steps) runs locally.
"""

import sys
import json
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from config import LOGS_DIR, OUTPUT_DIR, CHANGE_MANIFEST_FILE, SOURCES_DIR, CONVERTED_DIR
from sync_drive import run_sync
from notify_slack import notify_no_changes, notify_error, notify_changes_detected


def _write_sync_github_summary(summary, download_errors, verification=None):
    """Write sync results to GitHub step summary (CI only)."""
    import os
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    lines = ["## Sync Results\n"]
    lines.append("| Metric | Count |")
    lines.append("|--------|-------|")
    lines.append(f"| Files scanned | {summary['total_files']} |")
    lines.append(f"| New | {summary['new']} |")
    lines.append(f"| Modified | {summary['modified']} |")
    lines.append(f"| Downloaded | {summary['downloaded']} |")
    recovered = summary.get('recovered', 0)
    if recovered:
        lines.append(f"| Recovered | {recovered} |")
    lines.append(f"| Errors | {summary['errors']} |")
    lines.append("")

    # Verification results — the definitive file check
    if verification:
        expected = verification.get("expected_files", 0)
        if verification.get("all_present"):
            lines.append(f"### File Verification: PASS")
            lines.append(f"> All {expected} files verified on disk.\n")
        else:
            missing = verification.get("missing", [])
            zero_byte = verification.get("zero_byte", [])
            total_problems = len(missing) + len(zero_byte)
            lines.append(f"### File Verification: FAIL — {total_problems} of {expected} files missing\n")
            for m in missing + zero_byte:
                fp = m.get("folder_path", "")
                display = f"{fp}/{m['file']}" if fp else m["file"]
                drive_link = m.get("drive_link", "")
                link_md = f" — [Drive link]({drive_link})" if drive_link else ""
                lines.append(f"- `{display}` [{m.get('term', '')}] — {m.get('reason', 'unknown')[:150]}{link_md}")
            lines.append("")

    if download_errors and not verification:
        for err in download_errors[:15]:
            fp = err.get("folder_path", "")
            display = f"{fp}/{err['file']}" if fp else err["file"]
            lines.append(f"- `{display}` [{err.get('term', '')}] — {err.get('error', '')[:150]}")
        lines.append("")

    with open(summary_path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ──────────────────────────────────────────────────────────
# CI Mode: Sync + Notify Only
# ──────────────────────────────────────────────────────────

def run_ci_pipeline(dry_run=False, download="none"):
    """CI pipeline: sync Drive -> detect changes -> write manifest -> Slack notify -> done.

    Args:
        dry_run: Scan only, no state update, no downloads.
        download: Download mode — "none" (metadata scan only), "diff" (changed files),
                  "all" (everything).
    """
    print()
    print("=" * 60)
    print("  KB Pipeline — CI Mode (Sync + Notify)")
    print(f"  Download mode: {download}")
    print(f"  {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)
    print()

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    pipeline_log = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "mode": "ci",
        "download": download,
        "steps_run": [],
        "errors": [],
        "status": "running",
    }

    try:
        # Sync Drive
        if dry_run:
            print("\n>>> Sync (DRY RUN)\n")
            sync_result = run_sync(dry_run=True)
            from notify_slack import notify_dry_run_summary
            notify_dry_run_summary(sync_result)
            pipeline_log["status"] = "dry_run"
            _save_pipeline_log(pipeline_log)
            return pipeline_log

        print(f"\n>>> Sync Drive (download={download})\n")
        if download == "none":
            sync_result = run_sync(skip_downloads=True)
        elif download == "diff":
            sync_result = run_sync(download_all=False)
        elif download == "all":
            sync_result = run_sync(download_all=True)
        else:
            sync_result = run_sync(skip_downloads=True)

        _write_sync_github_summary(
            sync_result["summary"],
            sync_result.get("download_errors", []),
            verification=sync_result.get("verification"),
        )
        pipeline_log["steps_run"].append({
            "step": "sync", "status": "success",
        })

        # Detect changes + write manifest
        from change_analyzer import analyze_changes, write_change_manifest
        analysis = analyze_changes(sync_result)
        manifest = write_change_manifest(sync_result)
        pipeline_log["steps_run"].append({
            "step": "manifest", "status": "success",
        })

        if not analysis["has_changes"]:
            print("No changes detected.")
            notify_no_changes()
            pipeline_log["status"] = "no_changes"
            _save_pipeline_log(pipeline_log)
            return pipeline_log

        # Notify admin about changes
        notify_changes_detected(
            analysis["change_details"],
            verification=sync_result.get("verification"),
        )
        pipeline_log["status"] = "synced"
        pipeline_log["changes"] = analysis["summary"]
        pipeline_log["manifest_summary"] = manifest.get("summary", {})

    except Exception as e:
        error_msg = f"CI pipeline failed: {e}"
        print(f"\nFATAL ERROR: {error_msg}")
        traceback.print_exc()
        pipeline_log["errors"].append(error_msg)
        pipeline_log["status"] = "failed"
        notify_error("CI Sync", str(e))

    _save_pipeline_log(pipeline_log)
    print(f"\n{'=' * 60}")
    print(f"  CI Pipeline {pipeline_log['status'].upper()}")
    print(f"{'=' * 60}\n")
    return pipeline_log


# ──────────────────────────────────────────────────────────
# Local Mode: Full LLM Pipeline
# ──────────────────────────────────────────────────────────

def _cleanup_deleted_files(deleted_entries):
    """Remove deleted files from sources/ and converted/ so they're excluded from LLM extraction."""
    for entry in deleted_entries:
        term = entry["term"]
        fname = entry["file"]
        fp = entry.get("folder_path", "")

        # Remove from sources/
        source_path = SOURCES_DIR / term / fp / fname if fp else SOURCES_DIR / term / fname
        if source_path.exists():
            source_path.unlink()
            print(f"    Removed source: {source_path.relative_to(SOURCES_DIR)}")

        # Remove corresponding converted files (.md, etc.)
        stem = Path(fname).stem
        converted_term = CONVERTED_DIR / term
        if converted_term.exists():
            for converted in converted_term.rglob(f"{stem}.*"):
                converted.unlink()
                print(f"    Removed converted: {converted.relative_to(CONVERTED_DIR)}")


def run_local_pipeline(skip_sync=False, force_full=False, analyze_images=False,
                       backend="cli"):
    """Local pipeline: sync -> convert -> native -> LLM consolidate -> LLM build -> LLM templates -> LLM validate."""
    print()
    print("=" * 60)
    print("  KB Pipeline — Local Mode (Full LLM)")
    print(f"  {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)
    print()

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    pipeline_log = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "mode": "local",
        "steps_run": [],
        "errors": [],
        "status": "running",
    }
    pipeline_results = {}
    sync_result = None

    try:
        # ─── Step 1: Sync (optional) ────────────────────────
        if not skip_sync:
            print("\n>>> STEP 1: Drive Sync\n")
            sync_result = run_sync()
            pipeline_results["sync_summary"] = sync_result["summary"]
            if "verification" in sync_result:
                pipeline_results["verification"] = sync_result["verification"]
            pipeline_log["steps_run"].append({"step": 1, "name": "Sync", "status": "success"})
        else:
            print("\n>>> STEP 1: Sync skipped\n")
            logs = sorted(LOGS_DIR.glob("sync_*.json"), reverse=True)
            if logs:
                with open(logs[0], "r", encoding="utf-8") as f:
                    sync_result = json.load(f)

        # Check for changes
        if not force_full and sync_result:
            from change_analyzer import analyze_changes
            analysis = analyze_changes(sync_result)
            if not analysis["has_changes"]:
                print("No changes detected. Pipeline skipped.")
                notify_no_changes()
                pipeline_log["status"] = "no_changes"
                _save_pipeline_log(pipeline_log)
                return pipeline_log

        # Clean up deleted files from change manifest (written by CI)
        if CHANGE_MANIFEST_FILE.exists():
            with open(CHANGE_MANIFEST_FILE, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            deleted = manifest.get("deleted", [])
            if deleted:
                print(f"  Change manifest: {len(deleted)} deleted file(s) to clean up")
                _cleanup_deleted_files(deleted)

        # ─── Step 2: Convert to text ────────────────────────
        print("\n>>> STEP 2: Convert to Text\n")

        print("  2a. Media extraction (hyperlinks + images)...")
        from extract_media import run_extraction as run_media
        run_media()

        print("  2b. Document conversion (PPTX/DOCX/PDF → markdown)...")
        from convert_docs import run_conversion
        run_conversion()

        print("  2c. Native Google extraction (Docs/Slides API)...")
        from extract_native_google import run_native_extraction
        run_native_extraction(sync_result)

        pipeline_log["steps_run"].append({"step": 2, "name": "Convert", "status": "success"})

        # ─── Step 2.5: Image Analysis (optional) ─────────
        if analyze_images:
            print("\n>>> STEP 2.5: Image Analysis (optional)\n")
            try:
                from analyze_images import run_analysis
                img_result = run_analysis(backend=backend)
                pipeline_results["image_analysis"] = img_result
                pipeline_log["steps_run"].append({"step": 2.5, "name": "Image Analysis", "status": "success"})
            except Exception as e:
                print(f"  Image analysis failed (non-critical): {e}")
                pipeline_log["steps_run"].append({"step": 2.5, "name": "Image Analysis", "status": "failed", "error": str(e)})

        # ─── Step 3: LLM Consolidation ──────────────────────
        print("\n>>> STEP 3: LLM Consolidation\n")
        from consolidate import run_consolidation
        run_consolidation(backend=backend)
        pipeline_log["steps_run"].append({"step": 3, "name": "Consolidation", "status": "success"})

        # ─── Step 4: LLM KB Build ───────────────────────────
        print("\n>>> STEP 4: LLM KB Build\n")
        from build_kb import run_build
        run_build(backend=backend)
        pipeline_log["steps_run"].append({"step": 4, "name": "KB Build", "status": "success"})

        # Also build templates
        try:
            print("\n>>> STEP 4b: LLM Templates Build\n")
            from build_templates import run_build_templates
            run_build_templates(backend=backend)
            pipeline_log["steps_run"].append({"step": "4b", "name": "Templates", "status": "success"})
        except Exception as e:
            print(f"  Template build failed (non-critical): {e}")

        # ─── Step 5: Dual-Judge Validation ───────────────────
        print("\n>>> STEP 5: Dual-Judge Validation\n")
        try:
            from validation.dual_judge.evaluator import run_dual_judge_validation
            report = run_dual_judge_validation(backend=backend, verbose=True)
            pipeline_results["dual_judge"] = {
                "scores": report.compute_scores(),
                "verdict": report.compute_verdict(),
                "sampled": report.sampled_count,
                "calls_made": report.calls_made,
            }
            pipeline_log["steps_run"].append({"step": 5, "name": "Dual-Judge", "status": "success"})
        except Exception as e:
            print(f"  Dual-judge failed: {e}")
            pipeline_log["steps_run"].append({"step": 5, "name": "Dual-Judge", "status": "failed", "error": str(e)})

        # Collect KB build info
        builds = []
        for kb_file in sorted(OUTPUT_DIR.glob("Term * - Lesson Based Structure.json")):
            try:
                with open(kb_file, "r", encoding="utf-8") as f:
                    kb = json.load(f)
                term_str = kb_file.stem.split(" - ")[0].replace("Term ", "")
                builds.append({"term": term_str, "lessons": kb.get("total_lessons", 0)})
            except Exception:
                pass
        pipeline_results["builds"] = builds
        pipeline_log["status"] = "completed"
        pipeline_log["completed_at"] = datetime.now(timezone.utc).isoformat()

    except Exception as e:
        error_msg = f"Pipeline failed: {e}"
        print(f"\nFATAL ERROR: {error_msg}")
        traceback.print_exc()
        pipeline_log["errors"].append(error_msg)
        pipeline_log["status"] = "failed"
        pipeline_results["fatal_error"] = str(e)

    _save_pipeline_log(pipeline_log)

    # Send notification
    pipeline_results["status"] = pipeline_log["status"]
    pipeline_results["steps_run"] = pipeline_log["steps_run"]
    pipeline_results["completed_at"] = pipeline_log.get("completed_at", "")
    pipeline_results["step_errors"] = [
        f"Step {sr['step']} ({sr['name']}): {sr.get('error', '')[:200]}"
        for sr in pipeline_log["steps_run"]
        if sr.get("status") == "failed"
    ]

    try:
        from notify_slack import notify_llm_pipeline_complete
        notify_llm_pipeline_complete(pipeline_results)
    except Exception:
        if pipeline_results.get("fatal_error"):
            notify_error("Pipeline", pipeline_results["fatal_error"])

    print(f"\n{'=' * 60}")
    print(f"  Pipeline {pipeline_log['status'].upper()}")
    print(f"  Steps run: {len(pipeline_log['steps_run'])}")
    print(f"  Errors: {len(pipeline_log['errors'])}")
    print(f"{'=' * 60}\n")

    return pipeline_log


def _save_pipeline_log(pipeline_log):
    """Save pipeline log to disk."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"pipeline_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(pipeline_log, f, indent=2, ensure_ascii=False)
    print(f"  Log: {log_path}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="KB Maintenance Pipeline")
    parser.add_argument("--mode", choices=["ci", "local"], default="local",
                        help="Pipeline mode: ci (sync+notify) or local (full LLM)")
    parser.add_argument("--skip-sync", action="store_true", help="Skip Drive sync (local mode)")
    parser.add_argument("--force-full", action="store_true", help="Force full rebuild (local mode)")
    parser.add_argument("--analyze-images", action="store_true",
                        help="Run optional image analysis step (local mode)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Scan and report changes without processing")
    parser.add_argument("--download", choices=["none", "diff", "all"], default="none",
                        help="Download mode: none (metadata only), diff (changed files), all (everything)")
    parser.add_argument("--backend", choices=["cli", "sdk", "auto"], default="cli",
                        help="LLM backend for local mode (default: cli)")
    args = parser.parse_args()

    if args.mode == "ci":
        run_ci_pipeline(dry_run=args.dry_run, download=args.download)
    else:
        run_local_pipeline(
            skip_sync=args.skip_sync,
            force_full=args.force_full,
            analyze_images=args.analyze_images,
            backend=args.backend,
        )
