"""
Layer 3 Real Output Tests (E001-E009): Verify actual KB output files.
"""

import json
import re
from pathlib import Path
from urllib.parse import urlparse
from qa.report import CheckResult
from qa.config import TERM_PROFILES


def run_real_output_tests(output_dir: Path, media_dir: Path) -> list[CheckResult]:
    """Run all real output tests against KB files on disk."""
    results = []

    # E001: Every KB JSON loads and parses correctly
    kb_files = list(output_dir.glob("Term * - Lesson Based Structure.json"))
    parse_errors = []
    loaded_kbs = {}
    for kb_path in kb_files:
        try:
            with open(kb_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            term = data.get("term", 0)
            loaded_kbs[term] = data
        except Exception as e:
            parse_errors.append({"file": kb_path.name, "error": str(e)})
    results.append(CheckResult(
        check_id="E001", layer=3, severity="ERROR",
        passed=len(parse_errors) == 0 and len(kb_files) > 0,
        message=f"{len(kb_files)} KB files loaded successfully" if not parse_errors else f"{len(parse_errors)} KB files failed to parse",
        details={"files": [f.name for f in kb_files], "errors": parse_errors},
    ))

    # E002: All 3 term KB files exist
    expected_terms = [1, 2, 3]
    missing_terms = [t for t in expected_terms if t not in loaded_kbs]
    results.append(CheckResult(
        check_id="E002", layer=3, severity="ERROR",
        passed=len(missing_terms) == 0,
        message=f"Missing KB files for terms: {missing_terms}" if missing_terms else "All 3 term KB files present",
        details={"missing": missing_terms},
    ))

    # E003: Term-specific lesson counts match profiles
    for term, profile in TERM_PROFILES.items():
        kb = loaded_kbs.get(term)
        if not kb:
            continue
        actual = len(kb.get("lessons", []))
        expected = profile["total_lessons"]
        results.append(CheckResult(
            check_id="E003", layer=3, severity="ERROR",
            passed=actual == expected,
            message=f"Term {term}: {actual} lessons (expected {expected})" if actual != expected else f"Term {term}: {expected} lessons correct",
            details={"term": term, "actual": actual, "expected": expected},
        ))

    # E004: Term 3 lessons 3-7 have big_question
    kb3 = loaded_kbs.get(3)
    if kb3:
        lessons_with_bq = []
        for l in kb3.get("lessons", []):
            lid = l.get("metadata", {}).get("lesson_id", 0)
            if l.get("big_question"):
                lessons_with_bq.append(lid)
        expected_enriched = [3, 4, 5, 6, 7]
        missing = [lid for lid in expected_enriched if lid not in lessons_with_bq]
        results.append(CheckResult(
            check_id="E004", layer=3, severity="WARNING",
            passed=len(missing) == 0,
            message=f"T3 lessons missing big_question: {missing}" if missing else "T3 L3-7 all have big_question",
            details={"expected": expected_enriched, "found": lessons_with_bq, "missing": missing},
        ))
    else:
        results.append(CheckResult(
            check_id="E004", layer=3, severity="WARNING",
            passed=False, message="Term 3 KB not loaded",
            details={"term": 3},
        ))

    # E005: Term 2 has exactly 12 lessons (not 14)
    kb2 = loaded_kbs.get(2)
    if kb2:
        t2_count = len(kb2.get("lessons", []))
        results.append(CheckResult(
            check_id="E005", layer=3, severity="ERROR",
            passed=t2_count == 12,
            message=f"Term 2 has {t2_count} lessons (expected 12)",
            details={"actual": t2_count},
        ))
    else:
        results.append(CheckResult(
            check_id="E005", layer=3, severity="ERROR",
            passed=False, message="Term 2 KB not loaded",
            details={},
        ))

    # E006: All image paths point to existing files on disk
    missing_images = []
    total_images = 0
    for term, kb in loaded_kbs.items():
        for l in kb.get("lessons", []):
            for img in l.get("metadata", {}).get("images", []):
                total_images += 1
                img_path = img.get("image_path", "")
                if img_path and not Path(img_path).exists():
                    missing_images.append({
                        "term": term,
                        "lesson_id": l.get("metadata", {}).get("lesson_id"),
                        "path": img_path,
                    })
    results.append(CheckResult(
        check_id="E006", layer=3, severity="WARNING",
        passed=len(missing_images) == 0,
        message=f"{len(missing_images)}/{total_images} image paths point to non-existent files" if missing_images else f"All {total_images} image paths exist on disk",
        details={"missing_count": len(missing_images), "total": total_images, "samples": missing_images[:5]},
    ))

    # E007: All URLs in resources/videos are syntactically valid
    bad_urls = []
    for term, kb in loaded_kbs.items():
        for l in kb.get("lessons", []):
            meta = l.get("metadata", {})
            lid = meta.get("lesson_id", 0)
            for r in meta.get("resources", []):
                urls = re.findall(r'https?://\S+', r)
                for url in urls:
                    try:
                        parsed = urlparse(url)
                        if not parsed.netloc:
                            bad_urls.append({"term": term, "lesson_id": lid, "url": url})
                    except Exception:
                        bad_urls.append({"term": term, "lesson_id": lid, "url": url})
            for v in meta.get("videos", []):
                url = v.get("url", "") if isinstance(v, dict) else ""
                if url:
                    try:
                        parsed = urlparse(url)
                        if not parsed.netloc and not url.endswith((".mp4", ".mov")):
                            bad_urls.append({"term": term, "lesson_id": lid, "url": url})
                    except Exception:
                        bad_urls.append({"term": term, "lesson_id": lid, "url": url})
    results.append(CheckResult(
        check_id="E007", layer=3, severity="WARNING",
        passed=len(bad_urls) == 0,
        message=f"{len(bad_urls)} invalid URLs found in KB output" if bad_urls else "All URLs are syntactically valid",
        details={"bad_urls": bad_urls[:10]},
    ))

    # E008: Templates KB files exist
    template_files = list(output_dir.glob("*emplate*"))
    results.append(CheckResult(
        check_id="E008", layer=3, severity="INFO",
        passed=len(template_files) > 0,
        message=f"{len(template_files)} template KB files found" if template_files else "No template KB files found",
        details={"files": [f.name for f in template_files]},
    ))

    # E009: Every KB has generated_at timestamp
    missing_ts = []
    for term, kb in loaded_kbs.items():
        if not kb.get("generated_at"):
            missing_ts.append(term)
    results.append(CheckResult(
        check_id="E009", layer=3, severity="WARNING",
        passed=len(missing_ts) == 0,
        message=f"Terms missing generated_at: {missing_ts}" if missing_ts else "All KBs have generated_at timestamps",
        details={"missing": missing_ts},
    ))

    return results
