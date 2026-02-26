"""
Layer 4 Retrieval Tests: Can the KB serve each query scenario?
"""

import json
from pathlib import Path
from qa.report import CheckResult
from qa.layer4.query_scenarios import QUERY_SCENARIOS
from qa.config import TERM_PROFILES


def _load_all_kbs(output_dir: Path) -> dict:
    """Load all term KBs into {term: kb_data}."""
    kbs = {}
    for term in (1, 2, 3):
        path = output_dir / f"Term {term} - Lesson Based Structure.json"
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                kbs[term] = json.load(f)
    return kbs


def _get_lesson(kbs: dict, term: int, lesson_id: int):
    """Get a specific lesson entry."""
    kb = kbs.get(term)
    if not kb:
        return None
    for l in kb.get("lessons", []):
        if l.get("metadata", {}).get("lesson_id") == lesson_id:
            return l
    return None


def _get_field(lesson: dict, field_path: str):
    """Get a field value, supporting dot-notation like 'enriched.big_question'."""
    parts = field_path.split(".")
    current = lesson
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _search_across_terms(kbs: dict, field: str, search_value: str) -> list:
    """Search for a value across all terms and lessons."""
    matches = []
    for term, kb in kbs.items():
        for l in kb.get("lessons", []):
            meta = l.get("metadata", {})
            val = meta.get(field, [])
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, str) and search_value.lower() in item.lower():
                        matches.append({"term": term, "lesson_id": meta.get("lesson_id")})
                        break
            elif isinstance(val, str) and search_value.lower() in val.lower():
                matches.append({"term": term, "lesson_id": meta.get("lesson_id")})
    return matches


def run_retrieval_tests(output_dir: Path) -> list[CheckResult]:
    """Run all query scenario retrieval tests."""
    results = []
    kbs = _load_all_kbs(output_dir)

    if not kbs:
        results.append(CheckResult(
            check_id="U000", layer=4, severity="ERROR",
            passed=False, message="No KB files loaded — cannot run retrieval tests",
            details={},
        ))
        return results

    for scenario in QUERY_SCENARIOS:
        sid = scenario["id"]
        field = scenario["required_field"]
        scope = scenario["scope"]
        expect = scenario["expect"]

        passed = False
        message = ""
        details = {"query": scenario["query"], "field": field, "scope": scope}

        if expect == "lesson_count_matches_profile":
            # Special case: check lesson count matches profile
            term = scope.get("term", 1)
            kb = kbs.get(term)
            if kb:
                actual = len(kb.get("lessons", []))
                expected = TERM_PROFILES.get(term, {}).get("total_lessons", 12)
                passed = actual == expected
                message = f"Term {term}: {actual} lessons (expected {expected})"
            else:
                message = f"Term {term} KB not loaded"

        elif "search_value" in scope:
            # Cross-term search
            matches = _search_across_terms(kbs, field, scope["search_value"])
            if expect == "at_least_one_match":
                passed = len(matches) > 0
                message = f"Found {len(matches)} matches for '{scope['search_value']}' in {field}"
                details["matches"] = matches[:5]

        else:
            # Specific lesson lookup
            term = scope.get("term")
            lesson_id = scope.get("lesson_id")

            if term and lesson_id:
                lesson = _get_lesson(kbs, term, lesson_id)
            elif lesson_id:
                # Try all terms
                for t in (1, 2, 3):
                    lesson = _get_lesson(kbs, t, lesson_id)
                    if lesson:
                        term = t
                        break
            else:
                lesson = None

            if not lesson:
                message = f"Lesson not found: term={term}, lesson_id={lesson_id}"
            else:
                # Get the field value
                if "." in field:
                    val = _get_field(lesson, field)
                else:
                    val = lesson.get("metadata", {}).get(field, lesson.get(field))

                if expect == "non_empty_list":
                    passed = isinstance(val, list) and len(val) > 0
                    message = f"T{term}L{lesson_id} {field}: {len(val) if isinstance(val, list) else 0} items"
                elif expect == "non_empty_string":
                    passed = isinstance(val, str) and len(val.strip()) > 0
                    message = f"T{term}L{lesson_id} {field}: {'present' if passed else 'empty/missing'}"
                elif expect == "field_exists":
                    passed = val is not None
                    message = f"T{term}L{lesson_id} {field}: {'exists' if passed else 'missing'}"

        results.append(CheckResult(
            check_id=sid, layer=4,
            severity="WARNING" if not passed else "INFO",
            passed=passed,
            message=message,
            details=details,
        ))

    return results
