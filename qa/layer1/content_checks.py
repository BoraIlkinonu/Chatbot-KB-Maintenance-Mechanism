"""
Layer 1 Content Quality Checks (C001-C014): Semantic content validation.
"""

import re
from urllib.parse import urlparse
from qa.report import CheckResult
from qa.config import CANONICAL_TOOLS, CONTENT_THRESHOLDS, VIDEO_URL_DOMAINS


def _is_valid_url(s):
    """Check if string is a syntactically valid URL."""
    try:
        r = urlparse(s)
        return r.scheme in ("http", "https") and bool(r.netloc)
    except Exception:
        return False


def _extract_url(s):
    """Extract URL from a resource string like 'Label - https://...'."""
    match = re.search(r'https?://\S+', s)
    return match.group(0) if match else None


def run_content_checks(kb_data, term: int) -> list[CheckResult]:
    """Run all content quality checks against a loaded KB JSON."""
    results = []
    lessons = kb_data.get("lessons", [])

    # C001: lesson_title not a raw slide ref like "Slide 1"
    raw_titles = []
    for i, l in enumerate(lessons):
        title = l.get("lesson_title", "")
        if re.match(r"^(Slide|slide)\s+\d+", title.strip()):
            raw_titles.append({"index": i, "title": title})
    results.append(CheckResult(
        check_id="C001", layer=1, severity="ERROR",
        passed=len(raw_titles) == 0,
        message=f"{len(raw_titles)} lessons have raw slide reference titles" if raw_titles else "No raw slide reference titles",
        details={"term": term, "issues": raw_titles},
    ))

    # C002: learning_objectives text min 10 chars each
    short_objectives = []
    for i, l in enumerate(lessons):
        objs = l.get("metadata", {}).get("learning_objectives", [])
        for j, obj in enumerate(objs):
            if isinstance(obj, str) and len(obj.strip()) < CONTENT_THRESHOLDS["min_objective_length"]:
                short_objectives.append({"lesson_index": i, "obj_index": j, "text": obj, "length": len(obj.strip())})
    results.append(CheckResult(
        check_id="C002", layer=1, severity="WARNING",
        passed=len(short_objectives) == 0,
        message=f"{len(short_objectives)} learning objectives shorter than {CONTENT_THRESHOLDS['min_objective_length']} chars" if short_objectives else "All learning objectives meet minimum length",
        details={"term": term, "issues": short_objectives[:10]},
    ))

    # C003: core_topics not duplicates of each other within lesson
    dup_topics = []
    for i, l in enumerate(lessons):
        topics = l.get("metadata", {}).get("core_topics", [])
        seen = set()
        for t in topics:
            t_lower = t.strip().lower() if isinstance(t, str) else ""
            if t_lower in seen:
                dup_topics.append({"lesson_index": i, "duplicate": t})
            seen.add(t_lower)
    results.append(CheckResult(
        check_id="C003", layer=1, severity="WARNING",
        passed=len(dup_topics) == 0,
        message=f"{len(dup_topics)} duplicate core_topics found within lessons" if dup_topics else "No duplicate core_topics within lessons",
        details={"term": term, "duplicates": dup_topics[:10]},
    ))

    # C004: activity_description has substantive content (min 50 chars)
    short_activities = []
    for i, l in enumerate(lessons):
        desc = l.get("metadata", {}).get("activity_description", "")
        if isinstance(desc, str) and len(desc.strip()) < CONTENT_THRESHOLDS["min_activity_length"]:
            lid = l.get("metadata", {}).get("lesson_id", i)
            short_activities.append({"lesson_id": lid, "length": len(desc.strip())})
    results.append(CheckResult(
        check_id="C004", layer=1, severity="WARNING",
        passed=len(short_activities) == 0,
        message=f"{len(short_activities)} lessons have short activity_description (<{CONTENT_THRESHOLDS['min_activity_length']} chars)" if short_activities else "All activity descriptions meet minimum length",
        details={"term": term, "issues": short_activities},
    ))

    # C005: URLs in resources are syntactically valid
    bad_urls = []
    for i, l in enumerate(lessons):
        resources = l.get("metadata", {}).get("resources", [])
        for j, r in enumerate(resources):
            url = _extract_url(r) if isinstance(r, str) else None
            if url and not _is_valid_url(url):
                bad_urls.append({"lesson_index": i, "resource_index": j, "url": url})
    results.append(CheckResult(
        check_id="C005", layer=1, severity="WARNING",
        passed=len(bad_urls) == 0,
        message=f"{len(bad_urls)} invalid URLs in resources" if bad_urls else "All resource URLs are syntactically valid",
        details={"term": term, "issues": bad_urls[:10]},
    ))

    # C006: URLs in videos match known video URL patterns
    bad_video_urls = []
    for i, l in enumerate(lessons):
        videos = l.get("metadata", {}).get("videos", [])
        for j, v in enumerate(videos):
            if not isinstance(v, dict):
                continue
            url = v.get("url", "")
            if url:
                parsed = urlparse(url)
                domain = parsed.netloc.lower().replace("www.", "")
                if domain and domain not in VIDEO_URL_DOMAINS and not url.endswith((".mp4", ".mov", ".avi", ".webm")):
                    bad_video_urls.append({"lesson_index": i, "video_index": j, "url": url, "domain": domain})
    results.append(CheckResult(
        check_id="C006", layer=1, severity="WARNING",
        passed=len(bad_video_urls) == 0,
        message=f"{len(bad_video_urls)} video URLs don't match known video domains" if bad_video_urls else "All video URLs match known patterns",
        details={"term": term, "issues": bad_video_urls[:10]},
    ))

    # C007: keywords min 2 chars each
    short_keywords = []
    for i, l in enumerate(lessons):
        kws = l.get("metadata", {}).get("keywords", [])
        for k in kws:
            if isinstance(k, str) and len(k.strip()) < CONTENT_THRESHOLDS["min_keyword_length"]:
                short_keywords.append({"lesson_index": i, "keyword": k})
    results.append(CheckResult(
        check_id="C007", layer=1, severity="INFO",
        passed=len(short_keywords) == 0,
        message=f"{len(short_keywords)} keywords shorter than {CONTENT_THRESHOLDS['min_keyword_length']} chars" if short_keywords else "All keywords meet minimum length",
        details={"term": term, "issues": short_keywords[:10]},
    ))

    # C008: No keyword in >80% of lessons (overfit detection)
    all_keywords = {}
    for l in lessons:
        kws = l.get("metadata", {}).get("keywords", [])
        for k in kws:
            if isinstance(k, str):
                k_lower = k.strip().lower()
                all_keywords[k_lower] = all_keywords.get(k_lower, 0) + 1
    total = max(len(lessons), 1)
    threshold = CONTENT_THRESHOLDS["max_keyword_frequency"]
    overfit = {k: v for k, v in all_keywords.items() if v / total > threshold}
    results.append(CheckResult(
        check_id="C008", layer=1, severity="INFO",
        passed=len(overfit) == 0,
        message=f"{len(overfit)} keywords appear in >{threshold:.0%} of lessons (possible overfit): {list(overfit.keys())[:5]}" if overfit else "No overfitted keywords detected",
        details={"term": term, "overfit_keywords": overfit},
    ))

    # C009: endstar_tools values in canonical names list (ERROR version)
    non_canonical = []
    for i, l in enumerate(lessons):
        tools = l.get("metadata", {}).get("endstar_tools", [])
        if isinstance(tools, list):
            for t in tools:
                if t not in CANONICAL_TOOLS:
                    lid = l.get("metadata", {}).get("lesson_id", i)
                    non_canonical.append({"lesson_id": lid, "tool": t})
    results.append(CheckResult(
        check_id="C009", layer=1, severity="ERROR",
        passed=len(non_canonical) == 0,
        message=f"{len(non_canonical)} non-canonical endstar_tools values" if non_canonical else "All endstar_tools are canonical",
        details={"term": term, "issues": non_canonical[:10]},
    ))

    # C010: No lesson has empty lesson_title (content-level, distinct from S002 schema)
    empty = [l.get("metadata", {}).get("lesson_id", i) for i, l in enumerate(lessons)
             if not l.get("lesson_title", "").strip()]
    results.append(CheckResult(
        check_id="C010", layer=1, severity="ERROR",
        passed=len(empty) == 0,
        message=f"{len(empty)} lessons have empty lesson_title" if empty else "All lessons have non-empty titles",
        details={"term": term, "empty_lesson_ids": empty},
    ))

    # C011: Plain-text resources (no URL) flagged as possibly incomplete
    plain_text_res = []
    for i, l in enumerate(lessons):
        resources = l.get("metadata", {}).get("resources", [])
        for j, r in enumerate(resources):
            if isinstance(r, str) and not _extract_url(r):
                lid = l.get("metadata", {}).get("lesson_id", i)
                plain_text_res.append({"lesson_id": lid, "resource": r[:100]})
    results.append(CheckResult(
        check_id="C011", layer=1, severity="INFO",
        passed=len(plain_text_res) == 0,
        message=f"{len(plain_text_res)} plain-text resources (no URL) — possibly incomplete" if plain_text_res else "All resources contain URLs",
        details={"term": term, "plain_text": plain_text_res[:10]},
    ))

    # C012: Video URLs not duplicated across videos and resources
    duplicated = []
    for i, l in enumerate(lessons):
        video_urls = set()
        for v in l.get("metadata", {}).get("videos", []):
            if isinstance(v, dict) and v.get("url"):
                video_urls.add(v["url"])
        resources = l.get("metadata", {}).get("resources", [])
        for r in resources:
            if isinstance(r, str):
                url = _extract_url(r)
                if url and url in video_urls:
                    lid = l.get("metadata", {}).get("lesson_id", i)
                    duplicated.append({"lesson_id": lid, "url": url})
    results.append(CheckResult(
        check_id="C012", layer=1, severity="WARNING",
        passed=len(duplicated) == 0,
        message=f"{len(duplicated)} video URLs duplicated in both videos and resources" if duplicated else "No video URL duplication across videos/resources",
        details={"term": term, "duplicates": duplicated[:10]},
    ))

    # C013: assessment_signals are non-trivial (not table separators)
    trivial_signals = []
    trivial_patterns = re.compile(r'^[\s\-_|=*]+$')
    for i, l in enumerate(lessons):
        signals = l.get("metadata", {}).get("assessment_signals", [])
        if isinstance(signals, list):
            for s in signals:
                if isinstance(s, str) and (trivial_patterns.match(s) or len(s.strip()) < 3):
                    lid = l.get("metadata", {}).get("lesson_id", i)
                    trivial_signals.append({"lesson_id": lid, "signal": s[:50]})
    results.append(CheckResult(
        check_id="C013", layer=1, severity="WARNING",
        passed=len(trivial_signals) == 0,
        message=f"{len(trivial_signals)} trivial assessment_signals (separators or too short)" if trivial_signals else "All assessment_signals are substantive",
        details={"term": term, "trivial": trivial_signals[:10]},
    ))

    # C014: activity_description not truncated mid-word
    truncated = []
    for i, l in enumerate(lessons):
        desc = l.get("metadata", {}).get("activity_description", "")
        if isinstance(desc, str) and len(desc) > 100:
            # Check if it ends mid-word (no trailing punctuation/space and last char is alphanumeric)
            stripped = desc.rstrip()
            if stripped and stripped[-1].isalnum() and not stripped.endswith((".", "!", "?", ":", ")", "]", '"', "'", "\n")):
                # Could be truncated — check if it ends without completing a sentence
                lid = l.get("metadata", {}).get("lesson_id", i)
                truncated.append({"lesson_id": lid, "ending": stripped[-30:]})
    results.append(CheckResult(
        check_id="C014", layer=1, severity="INFO",
        passed=len(truncated) == 0,
        message=f"{len(truncated)} activity descriptions may be truncated mid-word" if truncated else "No truncated activity descriptions detected",
        details={"term": term, "potentially_truncated": truncated[:10]},
    ))

    return results
