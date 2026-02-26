"""
Layer 3 Boundary Tests (B001-B007): Extreme/boundary condition handling.
"""

import json
from pathlib import Path
from qa.report import CheckResult
from qa.config import TERM_PROFILES


def run_boundary_tests(output_dir: Path) -> list[CheckResult]:
    """Run boundary condition tests against KB output."""
    results = []

    # Load all KBs
    loaded_kbs = {}
    for term in (1, 2, 3):
        path = output_dir / f"Term {term} - Lesson Based Structure.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                loaded_kbs[term] = json.load(f)

    # B001: High-volume lessons (60+ images) handled correctly
    high_volume = []
    for term, kb in loaded_kbs.items():
        for l in kb.get("lessons", []):
            img_count = len(l.get("metadata", {}).get("images", []))
            if img_count >= 60:
                lid = l.get("metadata", {}).get("lesson_id", 0)
                high_volume.append({"term": term, "lesson_id": lid, "images": img_count})
    # High volume lessons should still have proper metadata
    hv_ok = True
    for hv in high_volume:
        kb = loaded_kbs.get(hv["term"])
        if kb:
            lesson = next((l for l in kb["lessons"]
                           if l.get("metadata", {}).get("lesson_id") == hv["lesson_id"]), None)
            if lesson and not lesson.get("lesson_title", "").strip():
                hv_ok = False
    results.append(CheckResult(
        check_id="B001", layer=3, severity="WARNING",
        passed=hv_ok,
        message=f"{len(high_volume)} high-volume lessons (60+ images) — all have proper metadata" if hv_ok else "High-volume lesson(s) missing metadata",
        details={"high_volume_lessons": high_volume},
    ))

    # B002: Lessons with 0 videos/tools are allowed (not errors)
    zero_videos = 0
    zero_tools = 0
    total_lessons = 0
    for term, kb in loaded_kbs.items():
        for l in kb.get("lessons", []):
            total_lessons += 1
            if len(l.get("metadata", {}).get("videos", [])) == 0:
                zero_videos += 1
            if len(l.get("metadata", {}).get("endstar_tools", [])) == 0:
                zero_tools += 1
    results.append(CheckResult(
        check_id="B002", layer=3, severity="INFO",
        passed=True,  # Always passes — this is informational
        message=f"{zero_videos}/{total_lessons} lessons have 0 videos, {zero_tools}/{total_lessons} have 0 tools (acceptable)",
        details={"zero_videos": zero_videos, "zero_tools": zero_tools, "total": total_lessons},
    ))

    # B003: Term 1's 22 lessons (non-standard count) handled
    kb1 = loaded_kbs.get(1)
    if kb1:
        t1_count = len(kb1.get("lessons", []))
        results.append(CheckResult(
            check_id="B003", layer=3, severity="ERROR",
            passed=t1_count == 22,
            message=f"Term 1 has {t1_count} lessons (expected 22)",
            details={"actual": t1_count, "expected": 22},
        ))
    else:
        results.append(CheckResult(
            check_id="B003", layer=3, severity="ERROR",
            passed=False, message="Term 1 KB not loaded",
            details={},
        ))

    # B004: Activity description truncation doesn't cut mid-word
    truncated = []
    for term, kb in loaded_kbs.items():
        for l in kb.get("lessons", []):
            desc = l.get("metadata", {}).get("activity_description", "")
            if isinstance(desc, str) and len(desc) > 200:
                stripped = desc.rstrip()
                # Check common truncation signs
                if stripped.endswith("...") or (stripped[-1].isalnum() and len(stripped) > 1000):
                    lid = l.get("metadata", {}).get("lesson_id", 0)
                    truncated.append({"term": term, "lesson_id": lid, "ending": stripped[-40:]})
    results.append(CheckResult(
        check_id="B004", layer=3, severity="INFO",
        passed=len(truncated) == 0,
        message=f"{len(truncated)} activity descriptions may be truncated" if truncated else "No truncated activity descriptions detected",
        details={"potentially_truncated": truncated[:10]},
    ))

    # B005: Multi-source lessons (PPTX + native doc) merge correctly
    # Only applicable to Term 3 which has native docs
    kb3 = loaded_kbs.get(3)
    if kb3:
        multi_source = []
        for l in kb3.get("lessons", []):
            native_slides = l.get("native_slides", [])
            doc_sources = l.get("document_sources", [])
            if native_slides and doc_sources:
                lid = l.get("metadata", {}).get("lesson_id", 0)
                multi_source.append({
                    "lesson_id": lid,
                    "native_count": len(native_slides),
                    "doc_sources": len(doc_sources),
                })
        # Multi-source lessons should have richer content
        for ms in multi_source:
            lesson = next((l for l in kb3["lessons"]
                           if l.get("metadata", {}).get("lesson_id") == ms["lesson_id"]), None)
            if lesson:
                meta = lesson.get("metadata", {})
                if not meta.get("learning_objectives") and not meta.get("core_topics"):
                    ms["issue"] = "multi-source lesson has no objectives or topics"
        issues = [ms for ms in multi_source if "issue" in ms]
        results.append(CheckResult(
            check_id="B005", layer=3, severity="WARNING",
            passed=len(issues) == 0,
            message=f"{len(multi_source)} multi-source lessons, {len(issues)} with merge issues" if multi_source else "No multi-source lessons found (Term 3 only)",
            details={"multi_source": multi_source[:10]},
        ))
    else:
        results.append(CheckResult(
            check_id="B005", layer=3, severity="WARNING",
            passed=True, message="Term 3 KB not loaded — skipped",
            details={"skipped": True},
        ))

    # B006: Enrichment fields present (pipeline_version as proxy)
    missing_enrichment = []
    for term, kb in loaded_kbs.items():
        for l in kb.get("lessons", []):
            lid = l.get("metadata", {}).get("lesson_id", 0)
            if not l.get("pipeline_version"):
                missing_enrichment.append({"term": term, "lesson_id": lid})
    results.append(CheckResult(
        check_id="B006", layer=3, severity="INFO",
        passed=True,  # Informational
        message=f"{len(missing_enrichment)} lessons missing enrichment fields",
        details={"count": len(missing_enrichment), "samples": missing_enrichment[:10]},
    ))

    # B007: Lesson ID ordering matches list position
    ordering_issues = []
    for term, kb in loaded_kbs.items():
        lessons = kb.get("lessons", [])
        for i, l in enumerate(lessons):
            lid = l.get("metadata", {}).get("lesson_id", 0)
            if lid != i + 1:
                ordering_issues.append({"term": term, "position": i, "lesson_id": lid, "expected": i + 1})
    results.append(CheckResult(
        check_id="B007", layer=3, severity="INFO",
        passed=len(ordering_issues) == 0,
        message=f"{len(ordering_issues)} lessons have mismatched position/ID" if ordering_issues else "All lesson IDs match list position",
        details={"issues": ordering_issues[:10]},
    ))

    return results
