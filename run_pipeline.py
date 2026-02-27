"""
Pipeline Orchestrator (LLM-based)

5-step pipeline:
  1. Sync Drive — download source files
  2. Convert to text — PPTX/DOCX/PDF/XLSX → markdown, Google Docs/Slides → text
  2.5 Analyze images (optional) — Claude describes extracted images
  3. LLM Extract — Claude extracts all KB fields as JSON
  4. Build KB — assemble LLM JSON into final KB schema
  5. Dual-Judge — two independent Claude judges score KB against source

Fallback mode: if no LLM backend is available, uploads converted sources
as artifact and notifies Slack for local processing.
"""

import sys
import json
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from config import LOGS_DIR, OUTPUT_DIR
from sync_drive import run_sync
from notify_slack import (
    notify_no_changes, notify_error,
    notify_llm_pipeline_complete, notify_sources_ready,
)


def _write_sync_github_summary(summary, download_errors):
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
    lines.append(f"| Errors | {summary['errors']} |")
    lines.append("")

    if download_errors:
        export_errors = [e for e in download_errors
                         if "exportSizeLimitExceeded" in e.get("error", "") or "403" in e.get("error", "")]
        other_errors = [e for e in download_errors if e not in export_errors]

        if export_errors:
            lines.append(f"### Large Google Slides — PPTX export skipped ({len(export_errors)} files)")
            lines.append("> Text extracted via native Slides API — no content loss.\n")
            for err in export_errors:
                lines.append(f"- `{err['file']}` [{err.get('term', '')}]")
            lines.append("")

        if other_errors:
            lines.append(f"### Unexpected download failures ({len(other_errors)} files)")
            for err in other_errors:
                lines.append(f"- `{err['file']}` [{err.get('term', '')}] — {err.get('error', '')[:150]}")
            lines.append("")

    with open(summary_path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def run_pipeline(skip_sync=False, force_full=False, analyze_images=False,
                 dry_run=False, download_all=False, force_extract=False):
    """
    Execute the LLM-based pipeline.

    Args:
        skip_sync: Skip Drive sync, use latest sync log
        force_full: Force full rebuild regardless of changes
        analyze_images: Run optional image analysis step
        dry_run: Scan Drive and report changes without processing
        download_all: Download ALL files from Drive (for CI)
        force_extract: Force re-extraction even if LLM cache is valid
    """
    print()
    print("=" * 60)
    print("  Curriculum KB Maintenance Pipeline (LLM)")
    print(f"  {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)
    print()

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    pipeline_log = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "steps_run": [],
        "errors": [],
        "status": "running",
    }

    pipeline_results = {}
    sync_result = None

    try:
        # ─── Step 1: Sync ────────────────────────────────
        if dry_run:
            print("\n>>> STEP 1: Drive Sync (DRY RUN)\n")
            sync_result = run_sync(dry_run=True)
            from notify_slack import notify_dry_run_summary
            notify_dry_run_summary(sync_result)
            pipeline_log["status"] = "dry_run"
            pipeline_log["completed_at"] = datetime.now(timezone.utc).isoformat()
            _save_pipeline_log(pipeline_log)
            return pipeline_log
        elif not skip_sync:
            print("\n>>> STEP 1: Drive Sync\n")
            sync_result = run_sync(download_all=download_all)
            pipeline_results["sync_summary"] = sync_result["summary"]
            pipeline_results["download_errors"] = sync_result.get("download_errors", [])
            _write_sync_github_summary(sync_result["summary"],
                                       sync_result.get("download_errors", []))
            pipeline_log["steps_run"].append({
                "step": 1, "name": "Sync", "status": "success",
            })
        else:
            print("\n>>> STEP 1: Sync skipped\n")
            logs = sorted(LOGS_DIR.glob("sync_*.json"), reverse=True)
            if logs:
                with open(logs[0], "r", encoding="utf-8") as f:
                    sync_result = json.load(f)

        # ─── Check for changes ────────────────────────────
        if not force_full and sync_result:
            from change_analyzer import analyze_changes
            analysis = analyze_changes(sync_result)
            if not analysis["has_changes"]:
                print("No changes detected. Pipeline skipped.")
                notify_no_changes()
                pipeline_log["status"] = "no_changes"
                _save_pipeline_log(pipeline_log)
                return pipeline_log

        # ─── Step 2: Convert to text ──────────────────────
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

        print("  2d. Consolidation...")
        from consolidate import run_consolidation
        run_consolidation()

        pipeline_log["steps_run"].append({
            "step": 2, "name": "Convert", "status": "success",
        })

        # ─── Step 2.5: Image Analysis (optional) ─────────
        if analyze_images:
            print("\n>>> STEP 2.5: Image Analysis (optional)\n")
            try:
                from analyze_images import run_analysis
                img_result = run_analysis(backend="auto")
                pipeline_results["image_analysis"] = img_result
                pipeline_log["steps_run"].append({
                    "step": 2.5, "name": "Image Analysis", "status": "success",
                })
            except Exception as e:
                print(f"  Image analysis failed (non-critical): {e}")
                pipeline_log["steps_run"].append({
                    "step": 2.5, "name": "Image Analysis", "status": "failed",
                    "error": str(e),
                })

        # ─── Step 3: LLM Extract ─────────────────────────
        print("\n>>> STEP 3: LLM Extract\n")
        try:
            from llm_extract import run_extraction
            extract_result = run_extraction(backend="auto", force=force_extract)
            pipeline_results["extraction"] = extract_result
            pipeline_log["steps_run"].append({
                "step": 3, "name": "LLM Extract", "status": "success",
            })
        except RuntimeError as e:
            # No API key and no CLI — fallback mode
            print(f"\n  No LLM backend available: {e}")
            print("  Entering fallback mode — sources only.\n")
            pipeline_results["fallback"] = True
            pipeline_results["sync_summary"] = pipeline_results.get("sync_summary", {})
            notify_sources_ready(pipeline_results)
            pipeline_log["status"] = "fallback"
            pipeline_log["completed_at"] = datetime.now(timezone.utc).isoformat()
            _save_pipeline_log(pipeline_log)
            return pipeline_log

        # ─── Step 4: Build KB ─────────────────────────────
        print("\n>>> STEP 4: Build KB\n")
        from build_kb import run_build
        run_build()
        pipeline_log["steps_run"].append({
            "step": 4, "name": "Build KB", "status": "success",
        })

        # Also build templates
        try:
            from build_templates import run_build_templates
            run_build_templates()
        except Exception as e:
            print(f"  Template build failed (non-critical): {e}")

        # ─── Step 5: Dual-Judge ───────────────────────────
        print("\n>>> STEP 5: Dual-Judge Validation\n")
        try:
            from validation.dual_judge.evaluator import run_dual_judge_validation
            report = run_dual_judge_validation(backend="auto", verbose=True)
            pipeline_results["dual_judge"] = {
                "scores": report.compute_scores(),
                "verdict": report.compute_verdict(),
                "sampled": report.sampled_count,
                "calls_made": report.calls_made,
            }
            pipeline_log["steps_run"].append({
                "step": 5, "name": "Dual-Judge", "status": "success",
            })
        except Exception as e:
            print(f"  Dual-judge failed: {e}")
            pipeline_log["steps_run"].append({
                "step": 5, "name": "Dual-Judge", "status": "failed",
                "error": str(e),
            })

        # ─── Collect KB build info ────────────────────────
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

    # ── Send notification ──
    pipeline_results["status"] = pipeline_log["status"]
    pipeline_results["steps_run"] = pipeline_log["steps_run"]
    pipeline_results["completed_at"] = pipeline_log.get("completed_at", "")
    pipeline_results["step_errors"] = [
        f"Step {sr['step']} ({sr['name']}): {sr.get('error', '')[:200]}"
        for sr in pipeline_log["steps_run"]
        if sr.get("status") == "failed"
    ]

    try:
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
    parser = argparse.ArgumentParser(description="KB Maintenance Pipeline (LLM)")
    parser.add_argument("--skip-sync", action="store_true", help="Skip Drive sync")
    parser.add_argument("--force-full", action="store_true", help="Force full rebuild")
    parser.add_argument("--analyze-images", action="store_true",
                        help="Run optional image analysis step")
    parser.add_argument("--dry-run", action="store_true",
                        help="Scan and report changes without processing")
    parser.add_argument("--download-all", action="store_true",
                        help="Download ALL files from Drive (for CI)")
    parser.add_argument("--force-extract", action="store_true",
                        help="Force LLM re-extraction even if cache is valid")
    args = parser.parse_args()

    run_pipeline(
        skip_sync=args.skip_sync,
        force_full=args.force_full,
        analyze_images=args.analyze_images,
        dry_run=args.dry_run,
        download_all=args.download_all,
        force_extract=args.force_extract,
    )
