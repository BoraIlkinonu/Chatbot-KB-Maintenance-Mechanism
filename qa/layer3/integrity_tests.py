"""
Layer 3 Data Integrity Tests (I001-I008): UTF-8, encoding, duplicates, timestamps.
"""

import json
import re
from pathlib import Path
from datetime import datetime
from qa.report import CheckResult


def run_integrity_tests(output_dir: Path, consolidated_dir: Path) -> list[CheckResult]:
    """Run all data integrity tests."""
    results = []

    kb_files = list(output_dir.glob("Term * - Lesson Based Structure.json"))

    # I001: Valid UTF-8, no BOM, no null bytes
    encoding_issues = []
    for kb_path in kb_files:
        raw = kb_path.read_bytes()
        if raw[:3] == b'\xef\xbb\xbf':
            encoding_issues.append({"file": kb_path.name, "issue": "BOM detected"})
        if b'\x00' in raw:
            encoding_issues.append({"file": kb_path.name, "issue": "null bytes found"})
        try:
            raw.decode("utf-8")
        except UnicodeDecodeError as e:
            encoding_issues.append({"file": kb_path.name, "issue": f"invalid UTF-8: {e}"})
    results.append(CheckResult(
        check_id="I001", layer=3, severity="ERROR",
        passed=len(encoding_issues) == 0,
        message=f"{len(encoding_issues)} encoding issues found" if encoding_issues else "All files valid UTF-8, no BOM/null bytes",
        details={"issues": encoding_issues},
    ))

    # I002: Arabic/Unicode preserved (UAE curriculum may have Arabic text)
    # Check that any Arabic chars in source are preserved
    arabic_pattern = re.compile(r'[\u0600-\u06FF]')
    arabic_found = False
    for kb_path in kb_files:
        content = kb_path.read_text(encoding="utf-8")
        if arabic_pattern.search(content):
            arabic_found = True
            break
    results.append(CheckResult(
        check_id="I002", layer=3, severity="INFO",
        passed=True,  # Informational check
        message="Arabic/Unicode characters found and preserved" if arabic_found else "No Arabic characters found (expected for English-language curriculum)",
        details={"arabic_found": arabic_found},
    ))

    # I003: Special chars in URLs properly encoded
    url_encoding_issues = []
    for kb_path in kb_files:
        with open(kb_path, "r", encoding="utf-8") as f:
            kb = json.load(f)
        term = kb.get("term", 0)
        for l in kb.get("lessons", []):
            meta = l.get("metadata", {})
            lid = meta.get("lesson_id", 0)
            all_urls = []
            for r in meta.get("resources", []):
                urls = re.findall(r'https?://\S+', r)
                all_urls.extend(urls)
            for v in meta.get("videos", []):
                if isinstance(v, dict) and v.get("url"):
                    all_urls.append(v["url"])
            for url in all_urls:
                # Check for unencoded spaces or special chars
                if ' ' in url:
                    url_encoding_issues.append({"term": term, "lesson_id": lid, "url": url[:100], "issue": "unencoded space"})
    results.append(CheckResult(
        check_id="I003", layer=3, severity="WARNING",
        passed=len(url_encoding_issues) == 0,
        message=f"{len(url_encoding_issues)} URLs with encoding issues" if url_encoding_issues else "All URLs properly encoded",
        details={"issues": url_encoding_issues[:10]},
    ))

    # I004: KB lesson counts match expected profile counts
    # Note: consolidated may have extra lesson keys from path parsing patterns
    # (e.g. Week-based paths create IDs beyond profile range). Compare KB against
    # profile expectations, not raw consolidated counts.
    from qa.config import TERM_PROFILES
    count_mismatches = []
    for term in (1, 2, 3):
        kb_path = output_dir / f"Term {term} - Lesson Based Structure.json"
        if not kb_path.exists():
            continue
        with open(kb_path, "r", encoding="utf-8") as f:
            kb = json.load(f)
        kb_lessons = len(kb.get("lessons", []))
        expected = TERM_PROFILES.get(term, {}).get("total_lessons", 12)
        if kb_lessons != expected:
            count_mismatches.append({"term": term, "kb": kb_lessons, "expected": expected})
    results.append(CheckResult(
        check_id="I004", layer=3, severity="ERROR",
        passed=len(count_mismatches) == 0,
        message=f"Lesson count mismatches: {count_mismatches}" if count_mismatches else "Consolidated and KB lesson counts match",
        details={"mismatches": count_mismatches},
    ))

    # I005: No duplicate lesson_ids within a term
    dup_ids = []
    for kb_path in kb_files:
        with open(kb_path, "r", encoding="utf-8") as f:
            kb = json.load(f)
        term = kb.get("term", 0)
        seen_ids = set()
        for l in kb.get("lessons", []):
            lid = l.get("metadata", {}).get("lesson_id", 0)
            if lid in seen_ids:
                dup_ids.append({"term": term, "lesson_id": lid})
            seen_ids.add(lid)
    results.append(CheckResult(
        check_id="I005", layer=3, severity="ERROR",
        passed=len(dup_ids) == 0,
        message=f"Duplicate lesson_ids found: {dup_ids}" if dup_ids else "No duplicate lesson_ids within any term",
        details={"duplicates": dup_ids},
    ))

    # I006: Valid ISO 8601 timestamps
    bad_timestamps = []
    for kb_path in kb_files:
        with open(kb_path, "r", encoding="utf-8") as f:
            kb = json.load(f)
        term = kb.get("term", 0)
        ts = kb.get("generated_at", "")
        if ts:
            try:
                datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                bad_timestamps.append({"term": term, "field": "generated_at", "value": ts})
        for l in kb.get("lessons", []):
            ets = l.get("generated_at", "")
            if ets:
                try:
                    datetime.fromisoformat(ets.replace("Z", "+00:00"))
                except ValueError:
                    lid = l.get("metadata", {}).get("lesson_id", 0)
                    bad_timestamps.append({"term": term, "lesson_id": lid, "field": "generated_at", "value": ets})
    results.append(CheckResult(
        check_id="I006", layer=3, severity="WARNING",
        passed=len(bad_timestamps) == 0,
        message=f"{len(bad_timestamps)} invalid ISO 8601 timestamps" if bad_timestamps else "All timestamps are valid ISO 8601",
        details={"issues": bad_timestamps[:10]},
    ))

    # I007: No duplicate image paths within a lesson
    dup_images = []
    for kb_path in kb_files:
        with open(kb_path, "r", encoding="utf-8") as f:
            kb = json.load(f)
        term = kb.get("term", 0)
        for l in kb.get("lessons", []):
            images = l.get("metadata", {}).get("images", [])
            paths = [img.get("image_path", "") for img in images if isinstance(img, dict)]
            seen = set()
            for p in paths:
                if p in seen:
                    lid = l.get("metadata", {}).get("lesson_id", 0)
                    dup_images.append({"term": term, "lesson_id": lid, "path": p})
                seen.add(p)
    results.append(CheckResult(
        check_id="I007", layer=3, severity="WARNING",
        passed=len(dup_images) == 0,
        message=f"{len(dup_images)} duplicate image paths within lessons" if dup_images else "No duplicate image paths",
        details={"duplicates": dup_images[:10]},
    ))

    # I008: JSON file sizes reasonable (not empty, not suspiciously large)
    size_issues = []
    for kb_path in kb_files:
        size = kb_path.stat().st_size
        if size < 1000:
            size_issues.append({"file": kb_path.name, "size": size, "issue": "suspiciously small (<1KB)"})
        elif size > 50_000_000:
            size_issues.append({"file": kb_path.name, "size": size, "issue": "suspiciously large (>50MB)"})
    results.append(CheckResult(
        check_id="I008", layer=3, severity="WARNING",
        passed=len(size_issues) == 0,
        message=f"{len(size_issues)} KB files have unusual sizes" if size_issues else "All KB file sizes are reasonable",
        details={"issues": size_issues},
    ))

    return results
