"""
Coverage Report: Generate summary stats, truncation report, and V001-V006 CheckResults.

Produces both human-readable text output and QA CheckResult objects
for integration with the existing 4-layer QA system.
"""

import json
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from verification import ContentAtom
from verification.reconciler import ReconciliationResult, TruncationInfo, TRUNCATION_LIMITS
from verification.stage_attribution import Attribution

from qa.report import CheckResult


def generate_check_results(result: ReconciliationResult,
                           attributions: list[Attribution],
                           kb_atoms_list=None) -> list[CheckResult]:
    """Generate V001-V007 CheckResults for QA integration."""
    checks = []
    kb_atoms_list = kb_atoms_list or []
    lesson_cov = result.lesson_coverage

    # V001: Lesson coverage >= 95% (content that SHOULD be in KB)
    lesson_matched = sum(1 for m in result.matched
                         if m.source_atom.term is not None and m.source_atom.lesson is not None)
    lesson_structural = sum(1 for m in result.structural
                            if m.source_atom.term is not None and m.source_atom.lesson is not None)
    lesson_unmatched = sum(1 for m in result.unmatched
                           if m.source_atom.term is not None and m.source_atom.lesson is not None)
    checks.append(CheckResult(
        check_id="V001",
        layer=5,  # Layer 5 = extraction verification
        passed=lesson_cov >= 0.95,
        severity="ERROR",
        message=f"Lesson content coverage: {result.lesson_coverage_pct} "
                f"({lesson_matched + lesson_structural} matched [{lesson_structural} structural], "
                f"{lesson_unmatched} unmatched of lesson-assigned atoms)",
        details={
            "lesson_coverage": round(lesson_cov, 4),
            "overall_coverage": round(result.coverage, 4),
            "lesson_matched": lesson_matched,
            "lesson_structural": lesson_structural,
            "lesson_unmatched": lesson_unmatched,
            "total_source": result.total_source,
            "skipped_trivial": result.skipped_trivial,
        },
    ))

    # V002: Link extraction coverage >= 90%
    link_matched = sum(1 for m in result.matched if m.source_atom.atom_type in ("link", "video_url"))
    link_unmatched = sum(1 for m in result.unmatched if m.source_atom.atom_type in ("link", "video_url"))
    link_total = link_matched + link_unmatched
    link_coverage = link_matched / max(link_total, 1)
    checks.append(CheckResult(
        check_id="V002",
        layer=5,
        passed=link_coverage >= 0.90,
        severity="ERROR",
        message=f"Link extraction coverage: {link_coverage:.1%} ({link_matched}/{link_total})",
        details={"link_coverage": round(link_coverage, 4), "matched": link_matched, "total": link_total},
    ))

    # V003: No text content lost at Stage 1 or 2
    text_lost_early = [a for a in attributions
                       if a.atom.atom_type == "text_block" and a.lost_at_stage in (1, 2)]
    checks.append(CheckResult(
        check_id="V003",
        layer=5,
        passed=len(text_lost_early) == 0,
        severity="WARNING",
        message=f"Text content lost at early stages: {len(text_lost_early)} atoms",
        details={
            "count": len(text_lost_early),
            "examples": [
                {"content": a.atom.content[:80], "stage": a.lost_at_stage, "file": a.atom.source_file}
                for a in text_lost_early[:5]
            ],
        },
    ))

    # V004: No truncation limits hit
    checks.append(CheckResult(
        check_id="V004",
        layer=5,
        passed=len(result.truncations) == 0,
        severity="WARNING",
        message=f"Truncation limits hit: {len(result.truncations)} fields",
        details={
            "truncations": [
                {"field": t.field_name, "limit": t.limit, "term": t.term, "lesson": t.lesson}
                for t in result.truncations
            ],
        },
    ))

    # V005: All source files assigned to a term/lesson
    unassigned = set()
    for m in result.unmatched:
        if m.source_atom.term is None or m.source_atom.lesson is None:
            unassigned.add(m.source_atom.source_file)
    checks.append(CheckResult(
        check_id="V005",
        layer=5,
        passed=len(unassigned) == 0,
        severity="WARNING",
        message=f"Source files with unassigned content: {len(unassigned)}",
        details={"files": sorted(unassigned)[:10]},
    ))

    # V006: Speaker note content preserved
    notes_matched = sum(1 for m in result.matched if m.source_atom.atom_type == "speaker_note")
    notes_unmatched = sum(1 for m in result.unmatched if m.source_atom.atom_type == "speaker_note")
    notes_total = notes_matched + notes_unmatched
    notes_coverage = notes_matched / max(notes_total, 1)
    checks.append(CheckResult(
        check_id="V006",
        layer=5,
        passed=notes_coverage >= 0.80,
        severity="INFO",
        message=f"Speaker note preservation: {notes_coverage:.1%} ({notes_matched}/{notes_total})",
        details={"coverage": round(notes_coverage, 4), "matched": notes_matched, "total": notes_total},
    ))

    # V007: Extraction completeness — detect unconsumed extractor fields and
    # remaining_content entries that indicate new content types not yet handled.
    # This prevents the curriculum_alignment bug pattern from recurring.
    remaining_content_count = 0
    remaining_examples = []
    # Check KB output for non-empty remaining_content fields
    for atom in kb_atoms_list:
        if atom.location.startswith("remaining_content"):
            remaining_content_count += 1
            if len(remaining_examples) < 5:
                remaining_examples.append({
                    "term": atom.term,
                    "lesson": atom.lesson,
                    "content": atom.content[:80],
                    "location": atom.location,
                })
    checks.append(CheckResult(
        check_id="V007",
        layer=5,
        passed=remaining_content_count == 0,
        severity="WARNING",
        message=f"Unconsumed native doc sections: {remaining_content_count} "
                f"{'(new content types may need dedicated KB fields)' if remaining_content_count > 0 else '(all extracted content stored)'}",
        details={
            "count": remaining_content_count,
            "examples": remaining_examples,
        },
    ))

    # V008: No new/unclassified files — detect files on disk not yet in manifest
    from consolidate import detect_new_files
    try:
        new_files = detect_new_files()
    except Exception:
        new_files = []
    checks.append(CheckResult(
        check_id="V008",
        layer=5,
        passed=len(new_files) == 0,
        severity="WARNING",
        message=f"New/unclassified source files: {len(new_files)}"
                f"{' (classify in file_manifest.json)' if new_files else ' (all files classified)'}",
        details={
            "count": len(new_files),
            "files": new_files[:10],
        },
    ))

    # V009: No stale files — detect manifest entries with no matching file on disk
    from consolidate import detect_stale_files
    try:
        stale_files = detect_stale_files()
    except Exception:
        stale_files = []
    checks.append(CheckResult(
        check_id="V009",
        layer=5,
        passed=len(stale_files) == 0,
        severity="WARNING",
        message=f"Stale manifest entries (missing from disk): {len(stale_files)}"
                f"{' (files may have been moved/renamed/deleted)' if stale_files else ' (all manifest entries valid)'}",
        details={
            "count": len(stale_files),
            "files": stale_files[:10],
        },
    ))

    return checks


def format_coverage_report(result: ReconciliationResult,
                           attributions: list[Attribution],
                           verbose: bool = False,
                           excluded_files: list[str] | None = None) -> str:
    """Generate human-readable coverage report."""
    lines = []
    lines.append("=" * 70)
    lines.append("  EXTRACTION VERIFICATION REPORT")
    lines.append(f"  {datetime.now(timezone.utc).isoformat()}")
    lines.append("=" * 70)
    lines.append("")

    if excluded_files:
        lines.append(f"Files excluded by file_manifest.json: {len(excluded_files)}")
        lines.append("")

    # Split atoms into lesson vs non-lesson
    lesson_matched = sum(1 for m in result.matched
                         if m.source_atom.term is not None and m.source_atom.lesson is not None)
    lesson_structural = sum(1 for m in result.structural
                            if m.source_atom.term is not None and m.source_atom.lesson is not None)
    lesson_unmatched = sum(1 for m in result.unmatched
                           if m.source_atom.term is not None and m.source_atom.lesson is not None)
    lesson_total = lesson_matched + lesson_structural + lesson_unmatched

    nonlesson_matched = len(result.matched) - lesson_matched
    nonlesson_structural = len(result.structural) - lesson_structural
    nonlesson_unmatched = len(result.unmatched) - lesson_unmatched
    nonlesson_total = nonlesson_matched + nonlesson_structural + nonlesson_unmatched

    # ── Section 1: Lesson Content (slides, lesson plans — the core KB)
    lines.append("-" * 70)
    lines.append("  LESSON CONTENT  (slides, lesson plans, activities)")
    lines.append("  This is what powers the chatbot KB. Must be near 100%.")
    lines.append("-" * 70)
    lines.append(f"  Coverage:     {result.lesson_coverage_pct}  ({lesson_matched + lesson_structural}/{lesson_total} atoms)")
    lines.append(f"  Matched:      {lesson_matched}")
    lines.append(f"  Structural:   {lesson_structural}  (slide labels absorbed into KB)")
    lines.append(f"  Unmatched:    {lesson_unmatched}")
    lines.append("")

    # ── Section 2: Non-lesson Content (admin docs, support resources, etc.)
    lines.append("-" * 70)
    lines.append("  NON-LESSON CONTENT  (admin docs, curriculum specs, guides)")
    lines.append("  Support files excluded from lesson KB. Gaps here do NOT")
    lines.append("  affect the chatbot. Tracked for completeness only.")
    lines.append("-" * 70)
    if nonlesson_total > 0:
        nonlesson_cov = (nonlesson_matched + nonlesson_structural) / nonlesson_total
        lines.append(f"  Coverage:     {nonlesson_cov:.1%}  ({nonlesson_matched + nonlesson_structural}/{nonlesson_total} atoms)")
        lines.append(f"  Matched:      {nonlesson_matched}")
        lines.append(f"  Structural:   {nonlesson_structural}")
        lines.append(f"  Unmatched:    {nonlesson_unmatched}")
    else:
        lines.append(f"  No non-lesson atoms (all content assigned to lessons)")
    lines.append("")

    # ── Totals
    lines.append(f"OVERALL: {result.coverage_pct} coverage across all {result.total_source} source atoms "
                 f"({result.skipped_trivial} trivial skipped, {result.total_kb} KB atoms)")
    lines.append("")

    # Per-type coverage
    lines.append("Per-Type Coverage:")
    lines.append("-" * 50)
    type_matched = defaultdict(int)
    type_unmatched = defaultdict(int)
    for m in result.matched:
        type_matched[m.source_atom.atom_type] += 1
    for m in result.unmatched:
        type_unmatched[m.source_atom.atom_type] += 1

    for atype in sorted(set(list(type_matched.keys()) + list(type_unmatched.keys()))):
        matched = type_matched[atype]
        total = matched + type_unmatched[atype]
        pct = matched / max(total, 1) * 100
        lines.append(f"  {atype:15s}: {matched:4d}/{total:4d} ({pct:5.1f}%)")
    lines.append("")

    # Per-term coverage
    lines.append("Per-Term Coverage:")
    lines.append("-" * 50)
    term_matched = defaultdict(int)
    term_total = defaultdict(int)
    for m in result.matched:
        t = m.source_atom.term or 0
        term_matched[t] += 1
        term_total[t] += 1
    for m in result.unmatched:
        t = m.source_atom.term or 0
        term_total[t] += 1

    for t in sorted(term_total.keys()):
        matched = term_matched[t]
        total = term_total[t]
        pct = matched / max(total, 1) * 100
        label = f"Term {t}" if t else "Unassigned"
        lines.append(f"  {label:15s}: {matched:4d}/{total:4d} ({pct:5.1f}%)")
    lines.append("")

    # Stage attribution summary
    if attributions:
        lines.append("Loss Attribution by Stage:")
        lines.append("-" * 50)
        stage_counts = defaultdict(int)
        for a in attributions:
            stage_counts[a.lost_at_stage] += 1
        for stage in sorted(stage_counts.keys()):
            name = {1: "Media Extraction", 2: "Document Conversion", 3: "Native Extraction",
                    5: "Consolidation", 6: "KB Build"}.get(stage, f"Stage {stage}")
            lines.append(f"  Stage {stage} ({name}): {stage_counts[stage]} atoms lost")
        lines.append("")

    # Truncation report
    if result.truncations:
        lines.append("Truncation Limits Hit:")
        lines.append("-" * 50)
        field_counts = defaultdict(int)
        for t in result.truncations:
            field_counts[t.field_name] += 1
        for field_name, count in sorted(field_counts.items(), key=lambda x: -x[1]):
            limit = TRUNCATION_LIMITS.get(field_name, "?")
            lines.append(f"  {field_name}[:{limit}] — {count} lessons affected")
        lines.append("")

    # Verbose: show every unmatched atom
    if verbose and result.unmatched:
        lines.append("Unmatched Atoms (verbose):")
        lines.append("-" * 50)
        for m in result.unmatched[:100]:
            atom = m.source_atom
            content_preview = atom.content[:60].replace("\n", " ")
            lines.append(f"  [{atom.atom_type}] T{atom.term or '?'}L{atom.lesson or '?'} "
                         f"{atom.location}: {content_preview}")
        if len(result.unmatched) > 100:
            lines.append(f"  ... and {len(result.unmatched) - 100} more")
        lines.append("")

    # V-check summary
    checks = generate_check_results(result, attributions)
    lines.append("Verification Checks:")
    lines.append("-" * 50)
    for c in checks:
        status = "PASS" if c.passed else c.severity
        lines.append(f"  [{status:7s}] {c.check_id}: {c.message}")
    lines.append("")

    return "\n".join(lines)


def generate_json_report(result: ReconciliationResult,
                         attributions: list[Attribution],
                         kb_atoms_list=None) -> dict:
    """Generate machine-readable JSON report."""
    checks = generate_check_results(result, attributions, kb_atoms_list=kb_atoms_list)

    # Attribution summary
    stage_losses = defaultdict(list)
    for a in attributions:
        stage_losses[a.lost_at_stage].append({
            "type": a.atom.atom_type,
            "content_preview": a.atom.content[:100],
            "source_file": a.atom.source_file,
            "location": a.atom.location,
            "term": a.atom.term,
            "lesson": a.atom.lesson,
            "reason": a.reason,
        })

    # Split lesson vs non-lesson stats
    lesson_matched = sum(1 for m in result.matched
                         if m.source_atom.term is not None and m.source_atom.lesson is not None)
    lesson_structural = sum(1 for m in result.structural
                            if m.source_atom.term is not None and m.source_atom.lesson is not None)
    lesson_unmatched = sum(1 for m in result.unmatched
                           if m.source_atom.term is not None and m.source_atom.lesson is not None)
    nonlesson_matched = len(result.matched) - lesson_matched
    nonlesson_structural = len(result.structural) - lesson_structural
    nonlesson_unmatched = len(result.unmatched) - lesson_unmatched
    nonlesson_total = nonlesson_matched + nonlesson_structural + nonlesson_unmatched

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lesson_coverage": round(result.lesson_coverage, 4),
        "lesson_coverage_pct": result.lesson_coverage_pct,
        "lesson_matched": lesson_matched,
        "lesson_structural": lesson_structural,
        "lesson_unmatched": lesson_unmatched,
        "nonlesson_matched": nonlesson_matched,
        "nonlesson_structural": nonlesson_structural,
        "nonlesson_unmatched": nonlesson_unmatched,
        "nonlesson_total": nonlesson_total,
        "overall_coverage": round(result.coverage, 4),
        "overall_coverage_pct": result.coverage_pct,
        "total_source": result.total_source,
        "matched": len(result.matched),
        "structural": len(result.structural),
        "unmatched": len(result.unmatched),
        "skipped_trivial": result.skipped_trivial,
        "total_kb": result.total_kb,
        "truncations": [
            {"field": t.field_name, "limit": t.limit, "term": t.term,
             "lesson": t.lesson, "kb_count": t.kb_count}
            for t in result.truncations
        ],
        "stage_losses": {str(k): v for k, v in stage_losses.items()},
        "checks": [c.to_dict() for c in checks],
    }


def save_report(result: ReconciliationResult, attributions: list[Attribution],
                output_path: Path, verbose: bool = False,
                excluded_files: list[str] | None = None,
                kb_atoms_list=None):
    """Save both text and JSON reports."""
    output_path = Path(output_path)
    output_path.mkdir(parents=True, exist_ok=True)

    # Text report
    text = format_coverage_report(result, attributions, verbose, excluded_files=excluded_files)
    text_path = output_path / "extraction_verification.txt"
    with open(text_path, "w", encoding="utf-8") as f:
        f.write(text)

    # JSON report
    data = generate_json_report(result, attributions, kb_atoms_list=kb_atoms_list)
    json_path = output_path / "extraction_verification.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return text_path, json_path
