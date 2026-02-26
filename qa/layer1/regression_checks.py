"""
Layer 1 Regression Checks (R001-R006): Compare current build vs previous builds.
"""

import json
import shutil
from pathlib import Path
from datetime import datetime, timezone
from qa.report import CheckResult
from qa.config import REGRESSION_MAX_RESOURCE_DECREASE


def _load_previous_build(previous_dir: Path, term: int):
    """Load previous build KB for a term."""
    path = previous_dir / f"Term {term} - Lesson Based Structure.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def _build_lesson_map(kb_data):
    """Build a dict of lesson_id -> lesson entry."""
    result = {}
    for l in kb_data.get("lessons", []):
        lid = l.get("metadata", {}).get("lesson_id", 0)
        result[lid] = l
    return result


def run_regression_checks(kb_data, term: int, previous_builds_dir: Path) -> list[CheckResult]:
    """Run all regression checks comparing current vs previous build."""
    results = []
    prev = _load_previous_build(previous_builds_dir, term)

    if not prev:
        # No previous build — all checks pass vacuously
        for check_id in ("R001", "R002", "R003", "R004", "R005", "R006"):
            results.append(CheckResult(
                check_id=check_id, layer=1, severity="INFO",
                passed=True,
                message=f"No previous build for term {term} — skipping regression check",
                details={"term": term, "skipped": True},
            ))
        return results

    curr_lessons = _build_lesson_map(kb_data)
    prev_lessons = _build_lesson_map(prev)

    # R001: Lesson count did not decrease from previous build
    curr_count = len(curr_lessons)
    prev_count = len(prev_lessons)
    results.append(CheckResult(
        check_id="R001", layer=1, severity="ERROR",
        passed=curr_count >= prev_count,
        message=f"Lesson count decreased: {prev_count} -> {curr_count}" if curr_count < prev_count else f"Lesson count stable or increased: {prev_count} -> {curr_count}",
        details={"term": term, "previous": prev_count, "current": curr_count},
    ))

    # R002: No lesson lost its learning_objectives
    lost_objectives = []
    for lid, prev_l in prev_lessons.items():
        prev_objs = prev_l.get("metadata", {}).get("learning_objectives", [])
        curr_l = curr_lessons.get(lid, {})
        curr_objs = curr_l.get("metadata", {}).get("learning_objectives", [])
        if prev_objs and not curr_objs:
            lost_objectives.append(lid)
    results.append(CheckResult(
        check_id="R002", layer=1, severity="WARNING",
        passed=len(lost_objectives) == 0,
        message=f"{len(lost_objectives)} lessons lost their learning_objectives: {lost_objectives}" if lost_objectives else "No lessons lost learning_objectives",
        details={"term": term, "lost": lost_objectives},
    ))

    # R003: No lesson lost its videos
    lost_videos = []
    for lid, prev_l in prev_lessons.items():
        prev_vids = prev_l.get("metadata", {}).get("videos", [])
        curr_l = curr_lessons.get(lid, {})
        curr_vids = curr_l.get("metadata", {}).get("videos", [])
        if prev_vids and not curr_vids:
            lost_videos.append(lid)
    results.append(CheckResult(
        check_id="R003", layer=1, severity="WARNING",
        passed=len(lost_videos) == 0,
        message=f"{len(lost_videos)} lessons lost their videos: {lost_videos}" if lost_videos else "No lessons lost videos",
        details={"term": term, "lost": lost_videos},
    ))

    # R004: Total resources not decreased by >20%
    prev_total_res = sum(len(l.get("metadata", {}).get("resources", [])) for l in prev_lessons.values())
    curr_total_res = sum(len(l.get("metadata", {}).get("resources", [])) for l in curr_lessons.values())
    if prev_total_res > 0:
        decrease = (prev_total_res - curr_total_res) / prev_total_res
        results.append(CheckResult(
            check_id="R004", layer=1, severity="WARNING",
            passed=decrease <= REGRESSION_MAX_RESOURCE_DECREASE,
            message=f"Resources decreased by {decrease:.0%} ({prev_total_res} -> {curr_total_res})" if decrease > REGRESSION_MAX_RESOURCE_DECREASE else f"Resources stable: {prev_total_res} -> {curr_total_res}",
            details={"term": term, "previous": prev_total_res, "current": curr_total_res, "decrease": round(decrease, 3)},
        ))
    else:
        results.append(CheckResult(
            check_id="R004", layer=1, severity="WARNING",
            passed=True,
            message="Previous build had 0 resources — no regression possible",
            details={"term": term, "previous": 0, "current": curr_total_res},
        ))

    # R005: No new empty activity_description where content existed
    lost_activities = []
    for lid, prev_l in prev_lessons.items():
        prev_desc = prev_l.get("metadata", {}).get("activity_description", "")
        curr_l = curr_lessons.get(lid, {})
        curr_desc = curr_l.get("metadata", {}).get("activity_description", "")
        if prev_desc.strip() and not curr_desc.strip():
            lost_activities.append(lid)
    results.append(CheckResult(
        check_id="R005", layer=1, severity="WARNING",
        passed=len(lost_activities) == 0,
        message=f"{len(lost_activities)} lessons lost activity_description: {lost_activities}" if lost_activities else "No lessons lost activity descriptions",
        details={"term": term, "lost": lost_activities},
    ))

    # R006: Overall field completeness score not decreased
    def _completeness(lessons_map):
        fields = ["lesson_title", "learning_objectives", "core_topics", "activity_description", "resources", "videos", "endstar_tools", "keywords"]
        total = 0
        filled = 0
        for l in lessons_map.values():
            meta = l.get("metadata", {})
            for f in fields:
                total += 1
                val = meta.get(f, l.get(f, ""))
                if isinstance(val, list) and len(val) > 0:
                    filled += 1
                elif isinstance(val, str) and val.strip():
                    filled += 1
        return filled / max(total, 1)

    prev_score = _completeness(prev_lessons)
    curr_score = _completeness(curr_lessons)
    results.append(CheckResult(
        check_id="R006", layer=1, severity="INFO",
        passed=curr_score >= prev_score - 0.01,  # Allow 1% tolerance
        message=f"Completeness {'decreased' if curr_score < prev_score - 0.01 else 'stable'}: {prev_score:.1%} -> {curr_score:.1%}",
        details={"term": term, "previous": round(prev_score, 3), "current": round(curr_score, 3)},
    ))

    return results


def archive_current_build(output_dir: Path, previous_builds_dir: Path):
    """Archive current KB builds to previous_builds/ for future regression checks."""
    previous_builds_dir.mkdir(parents=True, exist_ok=True)
    for kb_path in output_dir.glob("Term * - Lesson Based Structure.json"):
        dest = previous_builds_dir / kb_path.name
        shutil.copy2(kb_path, dest)
