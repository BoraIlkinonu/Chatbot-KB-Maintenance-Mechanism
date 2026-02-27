"""
Exhaustive Extraction Verification Tool.

Independently parses source files (bypassing the pipeline), builds a ground-truth
manifest of every content atom, and compares against KB output to identify exactly
what was lost and where.

Usage:
    python verify_extraction.py                    # Full verification
    python verify_extraction.py --term 2           # Single term
    python verify_extraction.py --lesson 5         # Specific lesson (all terms)
    python verify_extraction.py --type links       # Only check links
    python verify_extraction.py --verbose          # Show every unmatched atom
    python verify_extraction.py --json             # JSON report to stdout
    python verify_extraction.py --fix-report       # Generate fix suggestions

Exit codes: 0 = >=95% coverage, 1 = 80-95%, 2 = <80%
"""

import os
import sys
import json
import argparse

sys.stdout.reconfigure(encoding="utf-8")

from config import SOURCES_DIR, NATIVE_DIR, OUTPUT_DIR, MEDIA_DIR, CONVERTED_DIR, CONSOLIDATED_DIR, VALIDATION_DIR

from verification.source_manifest import build_source_manifest
from verification.kb_manifest import build_kb_manifest
from verification.reconciler import reconcile
from verification.stage_attribution import attribute_losses
from verification.coverage_report import (
    format_coverage_report, generate_json_report, save_report,
    generate_check_results,
)


def main():
    parser = argparse.ArgumentParser(
        description="Verify extraction completeness by comparing source files against KB output."
    )
    parser.add_argument("--term", type=int, help="Only verify a specific term (1, 2, or 3)")
    parser.add_argument("--lesson", type=int, help="Only verify a specific lesson number")
    parser.add_argument("--type", choices=["links", "text", "images", "notes", "tables"],
                        help="Only check a specific content type")
    parser.add_argument("--verbose", action="store_true", help="Show every unmatched atom")
    parser.add_argument("--json", action="store_true", help="Output JSON report to stdout")
    parser.add_argument("--fix-report", action="store_true",
                        help="Include fix suggestions for each loss category")
    parser.add_argument("--save", action="store_true",
                        help="Save reports to validation directory")
    parser.add_argument("--github-summary", action="store_true",
                        help="Write summary to $GITHUB_STEP_SUMMARY for Actions visibility")
    args = parser.parse_args()

    print("=" * 70)
    print("  Exhaustive Extraction Verification")
    print("=" * 70)
    print()

    # Phase 1: Build source manifest
    print("Phase 1: Building source manifest...")
    source_manifest = build_source_manifest(SOURCES_DIR, NATIVE_DIR)
    print()

    # Phase 2: Build KB manifest
    print("Phase 2: Building KB manifest...")
    kb_manifest = build_kb_manifest(OUTPUT_DIR)
    print()

    # Phase 3: Reconcile
    print("Phase 3: Reconciling source vs KB...")
    result = reconcile(
        source_manifest, kb_manifest,
        term_filter=args.term,
        lesson_filter=args.lesson,
        type_filter=args.type,
    )
    print(f"  Lesson Coverage: {result.lesson_coverage_pct} (content that should be in KB)")
    print(f"  Overall Coverage: {result.coverage_pct} (all source files)")
    print(f"  Matched: {len(result.matched)}, Unmatched: {len(result.unmatched)}")
    print()

    # Phase 4: Attribution
    print("Phase 4: Attributing losses...")
    unmatched_atoms = [m.source_atom for m in result.unmatched]
    attributions = attribute_losses(
        unmatched_atoms,
        media_dir=MEDIA_DIR,
        converted_dir=CONVERTED_DIR,
        native_dir=NATIVE_DIR,
        consolidated_dir=CONSOLIDATED_DIR,
        output_dir=OUTPUT_DIR,
    )
    print(f"  Attributed {len(attributions)} losses")
    print()

    # Output
    excluded = source_manifest.excluded_files if hasattr(source_manifest, 'excluded_files') else []
    kb_atoms = kb_manifest.atoms if hasattr(kb_manifest, 'atoms') else []
    if args.json:
        report = generate_json_report(result, attributions, kb_atoms_list=kb_atoms)
        report["excluded_files"] = excluded
        if args.fix_report:
            report["fix_suggestions"] = _generate_fix_suggestions(attributions, result)
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        text = format_coverage_report(result, attributions, args.verbose, excluded_files=excluded)
        print(text)

        if args.fix_report:
            print(_format_fix_suggestions(attributions, result))

    # Save reports
    if args.save:
        text_path, json_path = save_report(
            result, attributions, VALIDATION_DIR, args.verbose,
            excluded_files=excluded,
            kb_atoms_list=kb_atoms,
        )
        print(f"Reports saved to: {text_path}, {json_path}")

    # GitHub Actions integration
    checks = generate_check_results(result, attributions, kb_atoms_list=kb_atoms)
    failed_checks = [c for c in checks if not c.passed]

    if args.github_summary:
        _write_github_summary(result, checks, failed_checks)
        _send_slack_notification(result, checks, failed_checks)

    # Exit code based on lesson coverage (content that should be in KB)
    coverage = result.lesson_coverage
    if coverage >= 0.95:
        return 0
    elif coverage >= 0.80:
        return 1
    else:
        return 2


def _write_github_summary(result, checks, failed_checks):
    """Write markdown summary to $GITHUB_STEP_SUMMARY for Actions visibility."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    # Split lesson vs non-lesson
    lesson_unmatched = sum(1 for m in result.unmatched
                           if m.source_atom.term is not None and m.source_atom.lesson is not None)
    nonlesson_unmatched = len(result.unmatched) - lesson_unmatched

    lines = ["## KB Extraction Verification", ""]
    lines.append(f"**Lesson Content** (slides, lesson plans — powers the chatbot):")
    lines.append(f"  Coverage: **{result.lesson_coverage_pct}** | Unmatched: {lesson_unmatched}")
    lines.append("")
    lines.append(f"**Non-Lesson Content** (admin docs, guides — does NOT affect chatbot):")
    lines.append(f"  Coverage: {result.coverage_pct} overall | Unmatched: {nonlesson_unmatched}")
    lines.append("")

    # V-check table
    lines.append("| Check | Status | Details |")
    lines.append("|-------|--------|---------|")
    for c in checks:
        status = "PASS" if c.passed else f"**{c.severity}**"
        lines.append(f"| {c.check_id} | {status} | {c.message} |")
    lines.append("")

    if failed_checks:
        lines.append("### Action Required")
        for c in failed_checks:
            lines.append(f"- **{c.check_id}**: {c.message}")
    else:
        lines.append("All checks passed.")

    with open(summary_path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _send_slack_notification(result, checks, failed_checks):
    """Send Slack notification when checks fail or need attention."""
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return

    # Only notify when there are failures or warnings
    if not failed_checks:
        return

    import urllib.request

    # Split lesson vs non-lesson for clear Slack display
    lesson_unmatched = sum(1 for m in result.unmatched
                           if m.source_atom.term is not None and m.source_atom.lesson is not None)
    nonlesson_unmatched = len(result.unmatched) - lesson_unmatched

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "KB Pipeline Alert", "emoji": True},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":books: *Lesson Content* (powers the chatbot):\n"
                    f"  Coverage: *{result.lesson_coverage_pct}* | Unmatched: {lesson_unmatched}\n\n"
                    f":file_folder: *Non-Lesson Content* (admin docs, guides — does NOT affect chatbot):\n"
                    f"  Unmatched: {nonlesson_unmatched}"
                ),
            },
        },
    ]

    # Add failed checks
    fail_lines = []
    for c in failed_checks:
        fail_lines.append(f"*{c.check_id}* [{c.severity}]: {c.message}")
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": "\n".join(fail_lines)},
    })

    payload = json.dumps({"blocks": blocks}).encode("utf-8")
    req = urllib.request.Request(
        webhook_url, data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        print("Slack notification sent.")
    except Exception as e:
        print(f"Slack notification could not be sent: {e} — pipeline results are unaffected")


def _generate_fix_suggestions(attributions, result):
    """Generate fix suggestions for each loss category."""
    suggestions = []

    # Group by lost_at_stage
    stage_atoms = {}
    for a in attributions:
        stage_atoms.setdefault(a.lost_at_stage, []).append(a)

    if 1 in stage_atoms:
        group_links = [a for a in stage_atoms[1] if "GroupShape" in a.reason or a.atom.atom_type == "link"]
        if group_links:
            suggestions.append({
                "issue": "Links/content lost in GroupShape skip (extract_media.py:133)",
                "fix": "Use _iter_shapes_recursive() to descend into GroupShape.shapes",
                "atoms_affected": len(group_links),
            })
        note_links = [a for a in stage_atoms[1] if a.atom.atom_type == "speaker_note"]
        if note_links:
            suggestions.append({
                "issue": "Speaker note links not extracted (extract_media.py)",
                "fix": "Add hyperlink extraction from slide.notes_slide.notes_text_frame",
                "atoms_affected": len(note_links),
            })

    if 2 in stage_atoms:
        suggestions.append({
            "issue": f"Content lost during document conversion (Stage 2): {len(stage_atoms[2])} atoms",
            "fix": "Extract run.hyperlink.address in convert_pptx() and para hyperlinks in convert_docx()",
            "atoms_affected": len(stage_atoms[2]),
        })

    if 5 in stage_atoms:
        suggestions.append({
            "issue": f"Content lost during consolidation (Stage 5): {len(stage_atoms[5])} atoms",
            "fix": "Check path pattern matching — files may not match term/lesson regex",
            "atoms_affected": len(stage_atoms[5]),
        })

    if 6 in stage_atoms:
        suggestions.append({
            "issue": f"Content lost during KB build (Stage 6): {len(stage_atoms[6])} atoms",
            "fix": "Review truncation limits ([:5], [:10], [:500]) in build_kb.py",
            "atoms_affected": len(stage_atoms[6]),
        })

    if result.truncations:
        suggestions.append({
            "issue": f"Truncation limits hit in {len(result.truncations)} fields",
            "fix": "Increase or remove [:N] limits in build_kb.py for affected fields",
            "fields": list(set(t.field_name for t in result.truncations)),
        })

    return suggestions


def _format_fix_suggestions(attributions, result):
    """Format fix suggestions as text."""
    suggestions = _generate_fix_suggestions(attributions, result)
    if not suggestions:
        return ""

    lines = ["Fix Suggestions:", "-" * 50]
    for i, s in enumerate(suggestions, 1):
        lines.append(f"  {i}. {s['issue']}")
        lines.append(f"     Fix: {s['fix']}")
        if "atoms_affected" in s:
            lines.append(f"     Atoms affected: {s['atoms_affected']}")
        if "fields" in s:
            lines.append(f"     Fields: {', '.join(s['fields'])}")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
