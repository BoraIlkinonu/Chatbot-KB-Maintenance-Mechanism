"""
QA Audit Script — Validates Real Pipeline Output Against Known Audit Counts

Standalone script (not pytest). Loads actual pipeline output files and validates
against hardcoded audit numbers from the content audit.

Usage: python qa_audit.py
Output: validation/qa_audit_report.json
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")

from config import MEDIA_DIR, NATIVE_DIR, CONSOLIDATED_DIR, OUTPUT_DIR, VALIDATION_DIR


def check(name, condition, actual=None, expected=None, tolerance=None):
    """Run a single audit check. Returns dict with result."""
    result = {
        "check": name,
        "passed": condition,
        "status": "PASS" if condition else "FAIL",
    }
    if actual is not None:
        result["actual"] = actual
    if expected is not None:
        result["expected"] = expected
    if tolerance is not None:
        result["tolerance"] = tolerance
    return result


def within_tolerance(actual, expected, tolerance_pct):
    """Check if actual is within tolerance_pct of expected."""
    if expected == 0:
        return actual == 0
    lower = expected * (1 - tolerance_pct / 100)
    upper = expected * (1 + tolerance_pct / 100)
    return lower <= actual <= upper


def audit_stage1():
    """Validate Stage 1 output: extraction_metadata.json."""
    checks = []
    meta_path = MEDIA_DIR / "extraction_metadata.json"

    if not meta_path.exists():
        checks.append(check("Stage 1: metadata file exists", False))
        return checks

    with open(meta_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Total PPTX images ≈ 1042 (±5%)
    total_images = data.get("total_images", 0)
    checks.append(check(
        "Stage 1: total PPTX images ≈ 1042",
        within_tolerance(total_images, 1042, 5),
        actual=total_images, expected=1042, tolerance="±5%",
    ))

    # Total PPTX links ≈ 146 (±10%)
    total_links = data.get("total_links", 0)
    checks.append(check(
        "Stage 1: total PPTX links ≈ 146",
        within_tolerance(total_links, 146, 10),
        actual=total_links, expected=146, tolerance="±10%",
    ))

    # Every PPTX file entry has both images and links keys
    all_have_keys = all(
        "images" in p and "links" in p
        for p in data.get("pptx_files", [])
    )
    checks.append(check(
        "Stage 1: every PPTX entry has 'images' and 'links' keys",
        all_have_keys,
    ))

    return checks


def audit_stage2():
    """Validate Stage 2 output: pdf_extraction_metadata.json."""
    checks = []
    meta_path = MEDIA_DIR / "pdf_extraction_metadata.json"

    if not meta_path.exists():
        checks.append(check("Stage 2: PDF metadata file exists", False))
        return checks

    with open(meta_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Total PDF images ≈ 68 (±10%)
    total_images = data.get("total_images", 0)
    checks.append(check(
        "Stage 2: total PDF images ≈ 68",
        within_tolerance(total_images, 68, 10),
        actual=total_images, expected=68, tolerance="±10%",
    ))

    # Total PDF links ≈ 157 (±10%)
    # Note: initial estimate was 110; real data shows 157 (Explorer Overview alone has 130)
    total_links = data.get("total_links", 0)
    checks.append(check(
        "Stage 2: total PDF links ≈ 157",
        within_tolerance(total_links, 157, 10),
        actual=total_links, expected=157, tolerance="±10%",
    ))

    return checks


def audit_stage3():
    """Validate Stage 3 output: native_extractions.json."""
    checks = []
    native_path = NATIVE_DIR / "native_extractions.json"

    if not native_path.exists():
        checks.append(check("Stage 3: native extractions file exists", False))
        return checks

    with open(native_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    extractions = data.get("extractions", [])

    # Count links and videos from native Slides
    slides_links = 0
    slides_videos = 0
    docs_links = 0

    for ext in extractions:
        ntype = ext.get("native_type", "")
        if ntype == "google_slides" and "error" not in ext:
            slides_links += ext.get("total_links", 0)
            slides_videos += ext.get("total_videos", 0)
            # Verify per-slide structure
        elif ntype == "google_doc" and "error" not in ext:
            docs_links += ext.get("total_links", 0)

    # Total native Slides links ≈ 80 (±10%)
    checks.append(check(
        "Stage 3: native Slides links ≈ 80",
        within_tolerance(slides_links, 80, 10),
        actual=slides_links, expected=80, tolerance="±10%",
    ))

    # Total native Slides embedded videos ≈ 3
    checks.append(check(
        "Stage 3: native Slides embedded videos ≈ 3",
        within_tolerance(slides_videos, 3, 50),
        actual=slides_videos, expected=3, tolerance="±50%",
    ))

    # Total native Docs links ≈ 25 (±10%)
    checks.append(check(
        "Stage 3: native Docs links ≈ 25",
        within_tolerance(docs_links, 25, 10),
        actual=docs_links, expected=25, tolerance="±10%",
    ))

    # Every google_slides extraction has links and videos per slide
    slides_extractions = [e for e in extractions if e.get("native_type") == "google_slides" and "error" not in e]
    all_slides_have_fields = all(
        all("links" in s and "videos" in s for s in e.get("slides", []))
        for e in slides_extractions
    )
    checks.append(check(
        "Stage 3: every Slides extraction has 'links' and 'videos' per slide",
        all_slides_have_fields,
    ))

    # Every google_doc extraction has top-level links list
    docs_extractions = [e for e in extractions if e.get("native_type") == "google_doc" and "error" not in e]
    all_docs_have_links = all("links" in e for e in docs_extractions)
    checks.append(check(
        "Stage 3: every Doc extraction has top-level 'links' list",
        all_docs_have_links,
    ))

    return checks


def _load_consolidated_combined():
    """Load consolidated data: per-term files first, fall back to combined file."""
    per_term_files = sorted(CONSOLIDATED_DIR.glob("consolidated_term*.json"))
    if per_term_files:
        # Reconstruct combined view from per-term files
        by_term = {}
        all_duplicates = []
        all_unassigned_docs = []
        all_unassigned_native = []
        total_links = 0
        total_video_refs = 0
        total_video_files = 0
        total_documents = 0
        total_images = 0
        total_native = 0

        for ptf in per_term_files:
            with open(ptf, "r", encoding="utf-8") as f:
                td = json.load(f)
            term_num = str(td.get("term", ptf.stem.replace("consolidated_term", "")))
            by_term[term_num] = {"by_lesson": td.get("by_lesson", {})}
            all_duplicates.extend(td.get("duplicates", []))
            unassigned = td.get("unassigned", {})
            all_unassigned_docs.extend(unassigned.get("documents", []))
            all_unassigned_native.extend(unassigned.get("native", []))
            s = td.get("summary", {})
            total_links += s.get("total_links", 0)
            total_video_refs += s.get("total_video_refs", 0)
            total_video_files += s.get("total_video_files", 0)
            total_documents += s.get("total_documents", 0)
            total_images += s.get("total_images", 0)
            total_native += s.get("total_native", 0)

        return {
            "summary": {
                "total_documents": total_documents,
                "total_images": total_images,
                "total_native": total_native,
                "total_links": total_links,
                "total_video_refs": total_video_refs,
                "total_video_files": total_video_files,
                "total_duplicates": len(all_duplicates),
            },
            "by_term": by_term,
            "duplicates": all_duplicates,
            "unassigned": {
                "documents": all_unassigned_docs,
                "native": all_unassigned_native,
            },
        }

    # Fallback: combined file
    cons_path = CONSOLIDATED_DIR / "consolidated_content.json"
    if cons_path.exists():
        with open(cons_path, "r", encoding="utf-8") as f:
            return json.load(f)

    return None


def audit_stage5():
    """Validate Stage 5 output: per-term consolidated files (or combined fallback)."""
    checks = []

    # Check per-term files exist
    per_term_files = sorted(CONSOLIDATED_DIR.glob("consolidated_term*.json"))
    combined_path = CONSOLIDATED_DIR / "consolidated_content.json"
    has_files = len(per_term_files) > 0 or combined_path.exists()
    checks.append(check("Stage 5: consolidated content files exist", has_files))
    if not has_files:
        return checks

    data = _load_consolidated_combined()
    if data is None:
        checks.append(check("Stage 5: consolidated data loadable", False))
        return checks

    summary = data.get("summary", {})

    # Summary has required fields
    for field in ("total_links", "total_video_refs", "total_video_files"):
        checks.append(check(
            f"Stage 5: summary has '{field}' field",
            field in summary,
        ))

    # total_video_files ≈ 14
    total_vf = summary.get("total_video_files", 0)
    checks.append(check(
        "Stage 5: total_video_files ≈ 14",
        within_tolerance(total_vf, 14, 30),
        actual=total_vf, expected=14, tolerance="±30%",
    ))

    # Every lesson entry has links and video_refs keys
    lessons_with_keys = 0
    total_lessons = 0
    lessons_with_links = 0

    for term_str, term_data in data.get("by_term", {}).items():
        for lesson_str, lesson in term_data.get("by_lesson", {}).items():
            total_lessons += 1
            if "links" in lesson and "video_refs" in lesson:
                lessons_with_keys += 1
            if lesson.get("link_count", 0) > 0 or len(lesson.get("links", [])) > 0:
                lessons_with_links += 1

    checks.append(check(
        "Stage 5: every lesson has 'links' and 'video_refs' keys",
        lessons_with_keys == total_lessons,
        actual=lessons_with_keys, expected=total_lessons,
    ))

    # At least 30/46 lessons have non-empty links
    checks.append(check(
        "Stage 5: ≥30 lessons have non-empty links",
        lessons_with_links >= 30,
        actual=lessons_with_links, expected="≥30",
    ))

    return checks


def audit_stage6():
    """Validate Stage 6 output: KB JSONs."""
    checks = []

    # Collect all lessons across terms
    all_lessons = {}  # (term, lesson_num) -> lesson_entry
    for term_num in (1, 2, 3):
        kb_path = OUTPUT_DIR / f"Term {term_num} - Lesson Based Structure.json"
        if not kb_path.exists():
            continue
        with open(kb_path, "r", encoding="utf-8") as f:
            kb = json.load(f)
        for lesson in kb.get("lessons", []):
            lid = lesson.get("metadata", {}).get("lesson_id", 0)
            all_lessons[(term_num, lid)] = lesson

    if not all_lessons:
        checks.append(check("Stage 6: at least one KB file exists", False))
        return checks

    # Count lessons with various content types
    lessons_with_tools = sum(
        1 for l in all_lessons.values()
        if len(l.get("metadata", {}).get("endstar_tools", [])) > 0
    )
    lessons_with_videos = sum(
        1 for l in all_lessons.values()
        if len(l.get("metadata", {}).get("videos", [])) > 0
    )
    lessons_with_resources = sum(
        1 for l in all_lessons.values()
        if len(l.get("metadata", {}).get("resources", [])) > 0
    )

    # endstar_tools non-empty for ≥10 lessons
    checks.append(check(
        "Stage 6: endstar_tools non-empty for ≥10 lessons",
        lessons_with_tools >= 10,
        actual=lessons_with_tools, expected="≥10",
    ))

    # videos non-empty for ≥8 lessons
    checks.append(check(
        "Stage 6: videos non-empty for ≥8 lessons",
        lessons_with_videos >= 8,
        actual=lessons_with_videos, expected="≥8",
    ))

    # resources non-empty for ≥30 lessons
    checks.append(check(
        "Stage 6: resources non-empty for ≥30 lessons",
        lessons_with_resources >= 30,
        actual=lessons_with_resources, expected="≥30",
    ))

    # ── Spot checks ──

    # Term 2 Lesson 5: resources contains "notebooklm"
    t2l5 = all_lessons.get((2, 5))
    if t2l5:
        resources_text = " ".join(t2l5.get("metadata", {}).get("resources", [])).lower()
        checks.append(check(
            "Stage 6 spot: T2L5 resources contains 'notebooklm'",
            "notebooklm" in resources_text,
            actual=resources_text[:200],
        ))
    else:
        checks.append(check("Stage 6 spot: T2L5 exists", False))

    # Term 2 Lesson 11: resources has ≥1 entry (no video files in this lesson folder)
    t2l11 = all_lessons.get((2, 11))
    if t2l11:
        res_count = len(t2l11.get("metadata", {}).get("resources", []))
        checks.append(check(
            "Stage 6 spot: T2L11 resources has ≥1 entry",
            res_count >= 1,
            actual=res_count, expected="≥1",
        ))
    else:
        checks.append(check("Stage 6 spot: T2L11 exists", False))

    # Term 3 Lesson 6: endstar_tools contains "Mechanics"
    t3l6 = all_lessons.get((3, 6))
    if t3l6:
        tools = t3l6.get("metadata", {}).get("endstar_tools", [])
        checks.append(check(
            "Stage 6 spot: T3L6 endstar_tools contains 'Mechanics'",
            "Mechanics" in tools,
            actual=tools,
        ))
    else:
        checks.append(check("Stage 6 spot: T3L6 exists", False))

    # Term 1 Lesson 1: resources has ≥2 entries (PPTX has 2 hyperlinks: Google Form + Endstar)
    t1l1 = all_lessons.get((1, 1))
    if t1l1:
        res_count = len(t1l1.get("metadata", {}).get("resources", []))
        checks.append(check(
            "Stage 6 spot: T1L1 resources has ≥2 entries",
            res_count >= 2,
            actual=res_count, expected="≥2",
        ))
    else:
        checks.append(check("Stage 6 spot: T1L1 exists", False))

    return checks


def run_audit():
    """Run all audit checks and generate report."""
    print("=" * 60)
    print("  QA Audit — Pipeline Output Validation")
    print("=" * 60)
    print()

    all_checks = []
    stages = [
        ("Stage 1: Media Extraction", audit_stage1),
        ("Stage 2: Document Conversion", audit_stage2),
        ("Stage 3: Native Google Extraction", audit_stage3),
        ("Stage 5: Consolidation", audit_stage5),
        ("Stage 6: KB Build", audit_stage6),
    ]

    for stage_name, audit_fn in stages:
        print(f"\n{stage_name}")
        print("-" * 40)
        stage_checks = audit_fn()
        for c in stage_checks:
            icon = "PASS" if c["passed"] else "FAIL"
            detail = ""
            if "actual" in c:
                detail = f" (actual={c['actual']}"
                if "expected" in c:
                    detail += f", expected={c['expected']}"
                if "tolerance" in c:
                    detail += f", tolerance={c['tolerance']}"
                detail += ")"
            print(f"  [{icon}] {c['check']}{detail}")
        all_checks.extend(stage_checks)

    # Summary
    passed = sum(1 for c in all_checks if c["passed"])
    failed = sum(1 for c in all_checks if not c["passed"])
    total = len(all_checks)

    print(f"\n{'=' * 60}")
    print(f"  Results: {passed}/{total} PASSED, {failed} FAILED")
    print(f"{'=' * 60}")

    # Save report
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "audit_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_checks": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": round(passed / total * 100, 1) if total > 0 else 0,
        },
        "checks": all_checks,
    }

    report_path = VALIDATION_DIR / "qa_audit_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\nReport saved: {report_path}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_audit())
