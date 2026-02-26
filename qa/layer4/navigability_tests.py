"""
Layer 4 Navigability Tests (UN01-UN05): Lesson uniqueness and disambiguation.
"""

import json
import re
from pathlib import Path
from qa.report import CheckResult
from qa.config import TERM_PROFILES


def run_navigability_tests(output_dir: Path) -> list[CheckResult]:
    """Run navigability tests: can users find and distinguish lessons?"""
    results = []

    # Load all KBs
    kbs = {}
    for term in (1, 2, 3):
        path = output_dir / f"Term {term} - Lesson Based Structure.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                kbs[term] = json.load(f)

    if not kbs:
        results.append(CheckResult(
            check_id="UN00", layer=4, severity="ERROR",
            passed=False, message="No KB files loaded",
            details={},
        ))
        return results

    # UN01: All lesson titles unique within a term
    dup_titles = []
    for term, kb in kbs.items():
        seen = {}
        for l in kb.get("lessons", []):
            title = l.get("lesson_title", "").strip().lower()
            lid = l.get("metadata", {}).get("lesson_id", 0)
            if title in seen:
                dup_titles.append({"term": term, "title": title, "lesson_ids": [seen[title], lid]})
            else:
                seen[title] = lid
    results.append(CheckResult(
        check_id="UN01", layer=4, severity="ERROR",
        passed=len(dup_titles) == 0,
        message=f"{len(dup_titles)} duplicate titles within terms" if dup_titles else "All lesson titles unique within each term",
        details={"duplicates": dup_titles},
    ))

    # UN02: Titles are human-readable (not "Lesson 1.pptx" or "Slide 1")
    bad_titles = []
    bad_patterns = [
        re.compile(r'^lesson\s+\d+\.pptx$', re.IGNORECASE),
        re.compile(r'^slide\s+\d+$', re.IGNORECASE),
        re.compile(r'^untitled', re.IGNORECASE),
        re.compile(r'^file\s', re.IGNORECASE),
    ]
    for term, kb in kbs.items():
        for l in kb.get("lessons", []):
            title = l.get("lesson_title", "").strip()
            lid = l.get("metadata", {}).get("lesson_id", 0)
            for pattern in bad_patterns:
                if pattern.match(title):
                    bad_titles.append({"term": term, "lesson_id": lid, "title": title})
                    break
    results.append(CheckResult(
        check_id="UN02", layer=4, severity="ERROR",
        passed=len(bad_titles) == 0,
        message=f"{len(bad_titles)} non-human-readable titles" if bad_titles else "All titles are human-readable",
        details={"bad_titles": bad_titles},
    ))

    # UN03: Lesson IDs sequential and match title numbering
    seq_issues = []
    for term, kb in kbs.items():
        lessons = kb.get("lessons", [])
        expected_count = TERM_PROFILES.get(term, {}).get("total_lessons", 12)
        ids = sorted(l.get("metadata", {}).get("lesson_id", 0) for l in lessons)
        expected_ids = list(range(1, expected_count + 1))
        if ids != expected_ids:
            seq_issues.append({"term": term, "actual": ids, "expected": expected_ids})
        # Check title numbering matches
        for l in lessons:
            lid = l.get("metadata", {}).get("lesson_id", 0)
            title = l.get("lesson_title", "")
            match = re.search(r'lesson\s+(\d+)', title, re.IGNORECASE)
            if match:
                title_num = int(match.group(1))
                if title_num != lid:
                    seq_issues.append({"term": term, "lesson_id": lid, "title_num": title_num, "title": title})
    results.append(CheckResult(
        check_id="UN03", layer=4, severity="WARNING",
        passed=len(seq_issues) == 0,
        message=f"{len(seq_issues)} sequencing/numbering issues" if seq_issues else "All lesson IDs sequential and match title numbering",
        details={"issues": seq_issues[:10]},
    ))

    # UN04: Terms distinguishable by content (not identical topics across terms)
    term_topics = {}
    for term, kb in kbs.items():
        topics = set()
        for l in kb.get("lessons", []):
            for t in l.get("metadata", {}).get("core_topics", []):
                if isinstance(t, str):
                    topics.add(t.strip().lower())
        term_topics[term] = topics
    # Check overlap
    overlaps = {}
    term_list = sorted(term_topics.keys())
    for i, t1 in enumerate(term_list):
        for t2 in term_list[i + 1:]:
            s1 = term_topics.get(t1, set())
            s2 = term_topics.get(t2, set())
            union = s1 | s2
            intersection = s1 & s2
            overlap_pct = len(intersection) / max(len(union), 1)
            overlaps[f"T{t1}-T{t2}"] = round(overlap_pct, 2)
    max_overlap = max(overlaps.values()) if overlaps else 0
    results.append(CheckResult(
        check_id="UN04", layer=4, severity="INFO" if max_overlap < 0.8 else "WARNING",
        passed=max_overlap < 0.8,
        message=f"Topic overlap between terms: {overlaps} — {'distinguishable' if max_overlap < 0.8 else 'too similar'}",
        details={"overlaps": overlaps},
    ))

    # UN05: Consistent term metadata across lessons
    inconsistencies = []
    for term, kb in kbs.items():
        term_ids = set()
        grade_bands = set()
        for l in kb.get("lessons", []):
            meta = l.get("metadata", {})
            term_ids.add(meta.get("term_id"))
            gb = meta.get("grade_band", "")
            if gb:
                grade_bands.add(gb)
        if len(term_ids) > 1:
            inconsistencies.append({"term": term, "field": "term_id", "values": list(term_ids)})
        if len(grade_bands) > 1:
            inconsistencies.append({"term": term, "field": "grade_band", "values": list(grade_bands)})
    results.append(CheckResult(
        check_id="UN05", layer=4, severity="WARNING",
        passed=len(inconsistencies) == 0,
        message=f"{len(inconsistencies)} metadata inconsistencies within terms" if inconsistencies else "Term metadata consistent across all lessons",
        details={"inconsistencies": inconsistencies},
    ))

    return results
