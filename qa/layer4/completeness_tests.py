"""
Layer 4 Completeness Tests (UC01-UC05): Can the KB answer teacher questions?
"""

import json
from pathlib import Path
from qa.report import CheckResult
from qa.config import TERM_PROFILES, COMPLETENESS_THRESHOLDS


def run_completeness_tests(output_dir: Path) -> list[CheckResult]:
    """Run completeness tests: can every lesson answer key teacher questions?"""
    results = []

    # Load all lessons
    all_lessons = []
    for term in (1, 2, 3):
        path = output_dir / f"Term {term} - Lesson Based Structure.json"
        if not path.exists():
            continue
        with open(path, "r", encoding="utf-8") as f:
            kb = json.load(f)
        for l in kb.get("lessons", []):
            l["_term"] = term
            all_lessons.append(l)

    if not all_lessons:
        results.append(CheckResult(
            check_id="UC00", layer=4, severity="ERROR",
            passed=False, message="No lessons loaded",
            details={},
        ))
        return results

    total = len(all_lessons)
    # Content lessons = those with actual source documents (not empty placeholders)
    content_lessons = [l for l in all_lessons
                       if l.get("document_sources") or l.get("slides")
                       or l.get("metadata", {}).get("learning_objectives")]
    content_total = max(len(content_lessons), 1)

    # UC01: "What is this lesson about?" — lesson_title, 100% required
    has_title = [l for l in all_lessons if l.get("lesson_title", "").strip()]
    coverage = len(has_title) / total
    threshold = COMPLETENESS_THRESHOLDS["lesson_title"]
    missing = [
        {"term": l["_term"], "lesson_id": l.get("metadata", {}).get("lesson_id")}
        for l in all_lessons if not l.get("lesson_title", "").strip()
    ]
    results.append(CheckResult(
        check_id="UC01", layer=4,
        severity="ERROR" if coverage < threshold else "INFO",
        passed=coverage >= threshold,
        message=f"lesson_title coverage: {coverage:.0%} ({len(has_title)}/{total}) — threshold: {threshold:.0%}",
        details={"coverage": round(coverage, 3), "threshold": threshold, "missing": missing},
    ))

    # UC02: "What will students learn?" — learning_objectives, 100% required
    # Only count lessons with actual source content (not empty placeholders)
    has_objectives = [l for l in content_lessons
                      if isinstance(l.get("metadata", {}).get("learning_objectives"), list)
                      and len(l["metadata"]["learning_objectives"]) > 0]
    coverage = len(has_objectives) / content_total
    threshold = COMPLETENESS_THRESHOLDS["learning_objectives"]
    missing = [
        {"term": l["_term"], "lesson_id": l.get("metadata", {}).get("lesson_id")}
        for l in content_lessons
        if not (isinstance(l.get("metadata", {}).get("learning_objectives"), list) and l["metadata"]["learning_objectives"])
    ]
    results.append(CheckResult(
        check_id="UC02", layer=4,
        severity="ERROR" if coverage < threshold else "INFO",
        passed=coverage >= threshold,
        message=f"learning_objectives coverage: {coverage:.0%} ({len(has_objectives)}/{content_total}) — threshold: {threshold:.0%}",
        details={"coverage": round(coverage, 3), "threshold": threshold, "missing": missing[:10]},
    ))

    # UC03: "What do students do in class?" — activity_description, 100% required
    has_activity = [l for l in content_lessons
                    if l.get("metadata", {}).get("activity_description", "").strip()]
    coverage = len(has_activity) / content_total
    threshold = COMPLETENESS_THRESHOLDS["activity_description"]
    missing = [
        {"term": l["_term"], "lesson_id": l.get("metadata", {}).get("lesson_id")}
        for l in content_lessons
        if not l.get("metadata", {}).get("activity_description", "").strip()
    ]
    results.append(CheckResult(
        check_id="UC03", layer=4,
        severity="ERROR" if coverage < threshold else "INFO",
        passed=coverage >= threshold,
        message=f"activity_description coverage: {coverage:.0%} ({len(has_activity)}/{content_total}) — threshold: {threshold:.0%}",
        details={"coverage": round(coverage, 3), "threshold": threshold, "missing": missing[:10]},
    ))

    # UC04: "What resources do I need?" — resources, 60% threshold
    has_resources = [l for l in content_lessons
                     if isinstance(l.get("metadata", {}).get("resources"), list)
                     and len(l["metadata"]["resources"]) > 0]
    coverage = len(has_resources) / content_total
    threshold = COMPLETENESS_THRESHOLDS["resources"]
    results.append(CheckResult(
        check_id="UC04", layer=4,
        severity="WARNING" if coverage < threshold else "INFO",
        passed=coverage >= threshold,
        message=f"resources coverage: {coverage:.0%} ({len(has_resources)}/{content_total}) — threshold: {threshold:.0%}",
        details={"coverage": round(coverage, 3), "threshold": threshold},
    ))

    # UC05: "How is this assessed?" — assessment_signals, 80% threshold
    has_assessment = [l for l in content_lessons
                      if isinstance(l.get("metadata", {}).get("assessment_signals"), list)
                      and len(l["metadata"]["assessment_signals"]) > 0]
    coverage = len(has_assessment) / content_total
    threshold = COMPLETENESS_THRESHOLDS["assessment_signals"]
    results.append(CheckResult(
        check_id="UC05", layer=4,
        severity="WARNING" if coverage < threshold else "INFO",
        passed=coverage >= threshold,
        message=f"assessment_signals coverage: {coverage:.0%} ({len(has_assessment)}/{total}) — threshold: {threshold:.0%}",
        details={"coverage": round(coverage, 3), "threshold": threshold},
    ))

    return results
