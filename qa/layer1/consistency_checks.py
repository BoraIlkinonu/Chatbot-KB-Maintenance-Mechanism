"""
Layer 1 Cross-Stage Consistency Checks (X001-X011): Data integrity across pipeline stages.
"""

import json
from pathlib import Path
from qa.report import CheckResult
from qa.config import TERM_PROFILES


def _load_consolidated(consolidated_dir: Path, term: int):
    """Load consolidated data for a term."""
    path = consolidated_dir / f"consolidated_term{term}.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def run_consistency_checks(kb_data, term: int, consolidated_dir: Path, output_dir: Path) -> list[CheckResult]:
    """Run all cross-stage consistency checks."""
    results = []
    lessons = kb_data.get("lessons", [])
    profile = TERM_PROFILES.get(term, {})

    cons = _load_consolidated(consolidated_dir, term)
    cons_by_lesson = cons.get("by_lesson", {}) if cons else {}

    # X001: KB lesson count matches expected profile count
    # Note: consolidated may have extra lesson keys from path parsing (e.g. Week-based
    # paths create lesson IDs beyond the expected range). The KB correctly limits to
    # the profile count. We check KB against profile, and warn if consolidated differs.
    kb_count = len(lessons)
    cons_count = len(cons_by_lesson) if cons else -1
    expected_count = profile.get("total_lessons", 12)
    if cons:
        # Primary check: KB matches profile expectations
        kb_matches_profile = kb_count == expected_count
        # Secondary: compare KB vs consolidated (within expected range only)
        cons_in_range = len([k for k in cons_by_lesson if 1 <= int(k) <= expected_count]) if cons else 0
        results.append(CheckResult(
            check_id="X001", layer=1, severity="ERROR",
            passed=kb_matches_profile,
            message=f"KB has {kb_count} lessons (expected {expected_count}, consolidated has {cons_count} total, {cons_in_range} in range)",
            details={"term": term, "kb_count": kb_count, "expected": expected_count,
                      "cons_total": cons_count, "cons_in_range": cons_in_range},
        ))
    else:
        results.append(CheckResult(
            check_id="X001", layer=1, severity="ERROR",
            passed=False,
            message=f"Cannot load consolidated data for term {term}",
            details={"term": term},
        ))

    # X002: Every expected lesson (1..N) has a KB entry
    # Only check lessons within the profile range, not all consolidated keys
    kb_ids = {l.get("metadata", {}).get("lesson_id") for l in lessons}
    expected_ids = set(range(1, expected_count + 1))
    missing_in_kb = sorted(expected_ids - kb_ids)
    results.append(CheckResult(
        check_id="X002", layer=1, severity="ERROR",
        passed=len(missing_in_kb) == 0,
        message=f"Expected lessons missing from KB: {missing_in_kb}" if missing_in_kb else f"All {expected_count} expected lessons present in KB",
        details={"term": term, "missing": missing_in_kb, "expected_range": f"1-{expected_count}"},
    ))

    # X003: Link counts approximately match consolidated totals
    if cons:
        link_mismatches = []
        for l in lessons:
            lid = l.get("metadata", {}).get("lesson_id", 0)
            cons_lesson = cons_by_lesson.get(str(lid), {})
            cons_links = cons_lesson.get("link_count", 0)
            kb_links = len(l.get("metadata", {}).get("resources", [])) + len(l.get("metadata", {}).get("videos", []))
            # Allow some tolerance — KB may deduplicate or reclassify
            if cons_links > 0 and kb_links == 0:
                link_mismatches.append({"lesson_id": lid, "consolidated": cons_links, "kb": kb_links})
        results.append(CheckResult(
            check_id="X003", layer=1, severity="WARNING",
            passed=len(link_mismatches) == 0,
            message=f"{len(link_mismatches)} lessons have links in consolidated but none in KB" if link_mismatches else "Link counts consistent between consolidated and KB",
            details={"term": term, "mismatches": link_mismatches[:10]},
        ))
    else:
        results.append(CheckResult(
            check_id="X003", layer=1, severity="WARNING",
            passed=True,
            message="Skipped — no consolidated data",
            details={"term": term, "skipped": True},
        ))

    # X004: Image counts match consolidated per-lesson
    if cons:
        img_mismatches = []
        for l in lessons:
            lid = l.get("metadata", {}).get("lesson_id", 0)
            cons_lesson = cons_by_lesson.get(str(lid), {})
            cons_imgs = cons_lesson.get("image_count", 0)
            kb_imgs = len(l.get("metadata", {}).get("images", []))
            if abs(cons_imgs - kb_imgs) > max(cons_imgs * 0.2, 3):
                img_mismatches.append({"lesson_id": lid, "consolidated": cons_imgs, "kb": kb_imgs})
        results.append(CheckResult(
            check_id="X004", layer=1, severity="WARNING",
            passed=len(img_mismatches) == 0,
            message=f"{len(img_mismatches)} lessons have image count mismatches (>20% or >3 diff)" if img_mismatches else "Image counts consistent",
            details={"term": term, "mismatches": img_mismatches[:10]},
        ))
    else:
        results.append(CheckResult(
            check_id="X004", layer=1, severity="WARNING",
            passed=True,
            message="Skipped — no consolidated data",
            details={"term": term, "skipped": True},
        ))

    # X005: Lesson IDs contiguous (no gaps)
    expected_ids = set(range(1, profile.get("total_lessons", 12) + 1))
    actual_ids = {l.get("metadata", {}).get("lesson_id") for l in lessons}
    gaps = expected_ids - actual_ids
    results.append(CheckResult(
        check_id="X005", layer=1, severity="WARNING",
        passed=len(gaps) == 0,
        message=f"Missing lesson IDs: {sorted(gaps)}" if gaps else "All lesson IDs contiguous",
        details={"term": term, "expected": sorted(expected_ids), "actual": sorted(actual_ids), "gaps": sorted(gaps)},
    ))

    # X006: Lesson titles unique within term
    titles = [l.get("lesson_title", "") for l in lessons]
    seen = {}
    duplicates = []
    for i, t in enumerate(titles):
        t_lower = t.strip().lower()
        if t_lower in seen:
            duplicates.append({"title": t, "indices": [seen[t_lower], i]})
        else:
            seen[t_lower] = i
    results.append(CheckResult(
        check_id="X006", layer=1, severity="ERROR",
        passed=len(duplicates) == 0,
        message=f"{len(duplicates)} duplicate lesson titles within term {term}" if duplicates else "All lesson titles unique within term",
        details={"term": term, "duplicates": duplicates},
    ))

    # X007: Cross-term: no identical titles for same lesson_id
    # This requires loading other terms — we check only within current KB
    # Will be handled at the runner level when all terms are available
    results.append(CheckResult(
        check_id="X007", layer=1, severity="WARNING",
        passed=True,
        message="Cross-term title check deferred to runner (needs all terms)",
        details={"term": term, "deferred": True},
    ))

    # X008: KB generated_at more recent than consolidated timestamp
    if cons:
        kb_ts = kb_data.get("generated_at", "")
        cons_ts = cons.get("consolidated_at", "")
        ts_ok = kb_ts >= cons_ts if kb_ts and cons_ts else True
        results.append(CheckResult(
            check_id="X008", layer=1, severity="INFO",
            passed=ts_ok,
            message=f"KB generated_at ({kb_ts[:19]}) {'>' if ts_ok else '<'} consolidated_at ({cons_ts[:19]})" if kb_ts and cons_ts else "Timestamps not available for comparison",
            details={"term": term, "kb_ts": kb_ts, "cons_ts": cons_ts},
        ))
    else:
        results.append(CheckResult(
            check_id="X008", layer=1, severity="INFO",
            passed=True,
            message="Skipped — no consolidated data",
            details={"term": term, "skipped": True},
        ))

    # X009: Native content present only for terms with native docs
    has_native = profile.get("has_native_docs", False)
    lessons_with_native = []
    for l in lessons:
        native_slides = l.get("native_slides", [])
        if native_slides:
            lessons_with_native.append(l.get("metadata", {}).get("lesson_id"))
    if has_native:
        results.append(CheckResult(
            check_id="X009", layer=1, severity="INFO",
            passed=len(lessons_with_native) > 0,
            message=f"Term {term} has native docs: {len(lessons_with_native)} lessons have native_slides" if lessons_with_native else f"Term {term} should have native docs but none found",
            details={"term": term, "has_native": has_native, "lessons_with_native": lessons_with_native},
        ))
    else:
        results.append(CheckResult(
            check_id="X009", layer=1, severity="INFO",
            passed=True,
            message=f"Term {term} has no native docs (expected)",
            details={"term": term, "has_native": False},
        ))

    # X010: Consolidated document_count > 0 for every KB lesson
    if cons:
        empty_docs = []
        for l in lessons:
            lid = l.get("metadata", {}).get("lesson_id", 0)
            cons_lesson = cons_by_lesson.get(str(lid), {})
            doc_count = cons_lesson.get("document_count", 0)
            if doc_count == 0:
                empty_docs.append(lid)
        results.append(CheckResult(
            check_id="X010", layer=1, severity="ERROR",
            passed=len(empty_docs) == 0,
            message=f"{len(empty_docs)} KB lessons have 0 documents in consolidated: {empty_docs}" if empty_docs else "All KB lessons have documents in consolidated",
            details={"term": term, "empty_lessons": empty_docs},
        ))
    else:
        results.append(CheckResult(
            check_id="X010", layer=1, severity="ERROR",
            passed=False,
            message=f"Cannot check — no consolidated data for term {term}",
            details={"term": term},
        ))

    # X011: Templates KB exists where template sources exist
    template_path = output_dir / f"Term {term} - Templates.json"
    # Also check the combined templates file
    combined_template = output_dir / "templates.json"
    has_template = template_path.exists() or combined_template.exists()
    # Check for any template KB that references this term
    all_template_paths = list(output_dir.glob("*emplate*"))
    term_has_templates = any(f"Term {term}" in p.name or "Term 1-3" in p.name for p in all_template_paths) or combined_template.exists()
    results.append(CheckResult(
        check_id="X011", layer=1, severity="INFO",
        passed=term_has_templates,
        message=f"Templates KB {'found' if term_has_templates else 'not found'} for term {term}",
        details={"term": term, "template_files": [str(p.name) for p in all_template_paths]},
    ))

    return results
