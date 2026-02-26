"""
Layer 1 Schema Checks (S001-S016): JSON structure & field type validation.
"""

import re
from qa.report import CheckResult
from qa.config import TERM_PROFILES, CANONICAL_TOOLS, GRADE_BAND_PATTERN


def run_schema_checks(kb_data, term: int) -> list[CheckResult]:
    """Run all schema checks against a loaded KB JSON for a given term."""
    results = []
    profile = TERM_PROFILES.get(term, {})
    expected_lessons = profile.get("total_lessons", 12)
    lessons = kb_data.get("lessons", [])

    # S001: Top-level KB has required fields
    required_top = ["term", "total_lessons", "generated_at", "lessons"]
    missing_top = [k for k in required_top if k not in kb_data]
    results.append(CheckResult(
        check_id="S001", layer=1, severity="ERROR",
        passed=len(missing_top) == 0,
        message=f"Top-level KB missing fields: {missing_top}" if missing_top else "Top-level KB has all required fields",
        details={"term": term, "missing": missing_top},
    ))

    # S002: Every lesson has non-empty lesson_title
    empty_titles = [i for i, l in enumerate(lessons) if not l.get("lesson_title", "").strip()]
    results.append(CheckResult(
        check_id="S002", layer=1, severity="ERROR",
        passed=len(empty_titles) == 0,
        message=f"{len(empty_titles)} lessons have empty lesson_title" if empty_titles else "All lessons have non-empty lesson_title",
        details={"term": term, "empty_indices": empty_titles},
    ))

    # S003: Every lesson has metadata dict with required keys
    required_meta = ["term_id", "lesson_id", "core_topics", "learning_objectives", "endstar_tools", "videos", "resources", "keywords", "images"]
    lessons_missing_meta = []
    for i, l in enumerate(lessons):
        meta = l.get("metadata")
        if not isinstance(meta, dict):
            lessons_missing_meta.append({"index": i, "missing": "metadata not a dict"})
            continue
        missing = [k for k in required_meta if k not in meta]
        if missing:
            lessons_missing_meta.append({"index": i, "missing": missing})
    results.append(CheckResult(
        check_id="S003", layer=1, severity="ERROR",
        passed=len(lessons_missing_meta) == 0,
        message=f"{len(lessons_missing_meta)} lessons missing metadata keys" if lessons_missing_meta else "All lessons have required metadata keys",
        details={"term": term, "issues": lessons_missing_meta[:5]},
    ))

    # S004: metadata.term_id matches parent KB term
    mismatched_terms = []
    for i, l in enumerate(lessons):
        meta = l.get("metadata", {})
        if meta.get("term_id") != term:
            mismatched_terms.append({"index": i, "got": meta.get("term_id"), "expected": term})
    results.append(CheckResult(
        check_id="S004", layer=1, severity="ERROR",
        passed=len(mismatched_terms) == 0,
        message=f"{len(mismatched_terms)} lessons have wrong term_id" if mismatched_terms else "All metadata.term_id match parent KB term",
        details={"term": term, "mismatches": mismatched_terms[:5]},
    ))

    # S005: metadata.lesson_id within term's lesson range
    out_of_range = []
    for i, l in enumerate(lessons):
        lid = l.get("metadata", {}).get("lesson_id", -1)
        if not (1 <= lid <= expected_lessons):
            out_of_range.append({"index": i, "lesson_id": lid, "max": expected_lessons})
    results.append(CheckResult(
        check_id="S005", layer=1, severity="ERROR",
        passed=len(out_of_range) == 0,
        message=f"{len(out_of_range)} lessons have lesson_id outside range 1-{expected_lessons}" if out_of_range else f"All lesson_ids within 1-{expected_lessons}",
        details={"term": term, "out_of_range": out_of_range[:5]},
    ))

    # S006: core_topics is list of non-empty strings
    bad_topics = []
    for i, l in enumerate(lessons):
        topics = l.get("metadata", {}).get("core_topics", [])
        if not isinstance(topics, list):
            bad_topics.append({"index": i, "issue": "not a list"})
        elif any(not isinstance(t, str) or not t.strip() for t in topics):
            bad_topics.append({"index": i, "issue": "contains empty or non-string entries"})
    results.append(CheckResult(
        check_id="S006", layer=1, severity="WARNING",
        passed=len(bad_topics) == 0,
        message=f"{len(bad_topics)} lessons have invalid core_topics" if bad_topics else "All core_topics are valid",
        details={"term": term, "issues": bad_topics[:5]},
    ))

    # S007: learning_objectives is list of non-empty strings
    bad_objectives = []
    for i, l in enumerate(lessons):
        objs = l.get("metadata", {}).get("learning_objectives", [])
        if not isinstance(objs, list):
            bad_objectives.append({"index": i, "issue": "not a list"})
        elif any(not isinstance(o, str) or not o.strip() for o in objs):
            bad_objectives.append({"index": i, "issue": "contains empty or non-string entries"})
    results.append(CheckResult(
        check_id="S007", layer=1, severity="WARNING",
        passed=len(bad_objectives) == 0,
        message=f"{len(bad_objectives)} lessons have invalid learning_objectives" if bad_objectives else "All learning_objectives are valid",
        details={"term": term, "issues": bad_objectives[:5]},
    ))

    # S008: endstar_tools values in canonical tool names
    bad_tools = []
    for i, l in enumerate(lessons):
        tools = l.get("metadata", {}).get("endstar_tools", [])
        if isinstance(tools, list):
            invalid = [t for t in tools if t not in CANONICAL_TOOLS]
            if invalid:
                bad_tools.append({"index": i, "invalid": invalid})
    results.append(CheckResult(
        check_id="S008", layer=1, severity="WARNING",
        passed=len(bad_tools) == 0,
        message=f"{len(bad_tools)} lessons have non-canonical endstar_tools" if bad_tools else "All endstar_tools are canonical",
        details={"term": term, "issues": bad_tools[:5]},
    ))

    # S009: videos is list of dicts with url key
    bad_videos = []
    for i, l in enumerate(lessons):
        videos = l.get("metadata", {}).get("videos", [])
        if not isinstance(videos, list):
            bad_videos.append({"index": i, "issue": "not a list"})
        else:
            for j, v in enumerate(videos):
                if not isinstance(v, dict) or "url" not in v:
                    bad_videos.append({"index": i, "video_index": j, "issue": "missing url key"})
                    break
    results.append(CheckResult(
        check_id="S009", layer=1, severity="WARNING",
        passed=len(bad_videos) == 0,
        message=f"{len(bad_videos)} lessons have invalid videos format" if bad_videos else "All videos entries are valid dicts with url",
        details={"term": term, "issues": bad_videos[:5]},
    ))

    # S010: resources is list of strings
    bad_resources = []
    for i, l in enumerate(lessons):
        res = l.get("metadata", {}).get("resources", [])
        if not isinstance(res, list):
            bad_resources.append({"index": i, "issue": "not a list"})
        elif any(not isinstance(r, str) for r in res):
            bad_resources.append({"index": i, "issue": "contains non-string entries"})
    results.append(CheckResult(
        check_id="S010", layer=1, severity="WARNING",
        passed=len(bad_resources) == 0,
        message=f"{len(bad_resources)} lessons have invalid resources format" if bad_resources else "All resources are lists of strings",
        details={"term": term, "issues": bad_resources[:5]},
    ))

    # S011: keywords is list of non-empty strings
    bad_keywords = []
    for i, l in enumerate(lessons):
        kws = l.get("metadata", {}).get("keywords", [])
        if not isinstance(kws, list):
            bad_keywords.append({"index": i, "issue": "not a list"})
        elif any(not isinstance(k, str) or not k.strip() for k in kws):
            bad_keywords.append({"index": i, "issue": "contains empty or non-string entries"})
    results.append(CheckResult(
        check_id="S011", layer=1, severity="WARNING",
        passed=len(bad_keywords) == 0,
        message=f"{len(bad_keywords)} lessons have invalid keywords" if bad_keywords else "All keywords are valid",
        details={"term": term, "issues": bad_keywords[:5]},
    ))

    # S012: images is list of dicts with image_path key
    bad_images = []
    for i, l in enumerate(lessons):
        imgs = l.get("metadata", {}).get("images", [])
        if not isinstance(imgs, list):
            bad_images.append({"index": i, "issue": "not a list"})
        else:
            for j, img in enumerate(imgs):
                if not isinstance(img, dict) or "image_path" not in img:
                    bad_images.append({"index": i, "image_index": j, "issue": "missing image_path"})
                    break
    results.append(CheckResult(
        check_id="S012", layer=1, severity="INFO",
        passed=len(bad_images) == 0,
        message=f"{len(bad_images)} lessons have invalid images format" if bad_images else "All images entries are valid dicts with image_path",
        details={"term": term, "issues": bad_images[:5]},
    ))

    # S013: grade_band matches pattern G\d+-G\d+
    bad_grades = []
    for i, l in enumerate(lessons):
        gb = l.get("metadata", {}).get("grade_band", "")
        if gb and not re.match(GRADE_BAND_PATTERN, gb):
            bad_grades.append({"index": i, "grade_band": gb})
    results.append(CheckResult(
        check_id="S013", layer=1, severity="WARNING",
        passed=len(bad_grades) == 0,
        message=f"{len(bad_grades)} lessons have non-standard grade_band" if bad_grades else "All grade_band values match expected pattern",
        details={"term": term, "issues": bad_grades[:5]},
    ))

    # S014: pipeline_version field present (enrichment fields now at top level)
    missing_version = [i for i, l in enumerate(lessons) if not l.get("pipeline_version")]
    results.append(CheckResult(
        check_id="S014", layer=1, severity="INFO",
        passed=len(missing_version) == 0,
        message=f"{len(missing_version)} lessons missing pipeline_version" if missing_version else "All lessons have pipeline_version",
        details={"term": term, "missing_indices": missing_version[:10]},
    ))

    # S015: No null values where arrays expected (must be [])
    array_fields = ["core_topics", "learning_objectives", "endstar_tools", "videos", "resources", "keywords", "images"]
    null_arrays = []
    for i, l in enumerate(lessons):
        meta = l.get("metadata", {})
        for field in array_fields:
            if field in meta and meta[field] is None:
                null_arrays.append({"index": i, "field": field})
    results.append(CheckResult(
        check_id="S015", layer=1, severity="ERROR",
        passed=len(null_arrays) == 0,
        message=f"{len(null_arrays)} null values where arrays expected" if null_arrays else "No null values in array fields",
        details={"term": term, "nulls": null_arrays[:10]},
    ))

    # S016: total_lessons matches actual len(lessons)
    declared = kb_data.get("total_lessons", 0)
    actual = len(lessons)
    results.append(CheckResult(
        check_id="S016", layer=1, severity="ERROR",
        passed=declared == actual,
        message=f"total_lessons ({declared}) != actual lessons ({actual})" if declared != actual else f"total_lessons matches actual count ({actual})",
        details={"term": term, "declared": declared, "actual": actual},
    ))

    return results
