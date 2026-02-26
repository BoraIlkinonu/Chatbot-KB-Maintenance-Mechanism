"""
Stage 7: Validation Post-Build Check
5-signal consensus validation + anomaly detection.
ERROR-severity anomalies block KB publishing.
"""

import sys
import json
import re
import math
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

from config import (
    OUTPUT_DIR, VALIDATION_DIR, LOGS_DIR, CONSOLIDATED_DIR,
    SIGNAL_WEIGHTS, VALIDATION_THRESHOLDS, WEEK_LESSON_MAP, BLOCK_ON_ERROR,
)


# ──────────────────────────────────────────────────────────
# Lesson keyword dictionary
# ──────────────────────────────────────────────────────────

LESSON_KEYWORDS = {
    1: ["design brief", "problem statement", "audience", "constraints", "UAE heritage", "sustainability", "innovation"],
    2: ["persona", "empathy map", "UX", "player needs", "motivations", "frustrations", "bias"],
    3: ["primary research", "secondary research", "AI research", "reliability", "bias", "accuracy", "insights"],
    4: ["design specification", "team roles", "constraints", "success criteria", "research insights", "collaboration"],
    5: ["brainstorming", "concept generation", "storyboard", "micro-prototype", "core mechanic", "peer feedback"],
    6: ["prototype", "core mechanic", "debugging", "testing", "iteration", "functionality"],
    7: ["gameplay expansion", "immersion", "visuals", "sound", "dialogue", "player pathways"],
    8: ["peer testing", "WWW/EBI", "feedback analysis", "theme mapping", "usability", "prioritisation"],
    9: ["iteration", "refinement", "feedback implementation", "impact vs effort", "before/after", "player experience"],
    10: ["team roles", "project manager", "milestones", "timeline", "risk management", "accountability"],
    11: ["documentation", "portfolio", "evidence", "curation", "captions", "reflection", "design story"],
    12: ["reflection", "evaluation", "SMART goals", "Term 3", "progress", "strengths", "challenges"],
}

EXPECTED_CONTENT_TYPES = ["teachers_slides", "students_slides", "lesson_plan"]


# ──────────────────────────────────────────────────────────
# Signal functions
# ──────────────────────────────────────────────────────────

def signal_path_pattern(doc):
    """Signal 1: Extract lesson from file path."""
    path = doc.get("path", "") or ""
    match = re.search(r"lesson[_\s\-]*(\d{1,2})", path.lower())
    if match:
        num = int(match.group(1))
        if 1 <= num <= 12:
            return {"signal": "path_pattern", "lessons": [num], "confidence": 1.0}

    match = re.search(r"week[_\s\-]*(\d)", path.lower())
    if match:
        week = int(match.group(1))
        if week in WEEK_LESSON_MAP:
            return {"signal": "path_pattern", "lessons": WEEK_LESSON_MAP[week], "confidence": 0.9}

    return {"signal": "path_pattern", "lessons": None, "confidence": 0}


def signal_semantic_align(doc, lesson_num):
    """Signal 3: Match content text against lesson keywords."""
    text = (doc.get("content_preview", "") + " " + doc.get("description_of_activities", "")).lower()
    if not text.strip():
        return {"signal": "semantic_align", "score": 0, "confidence": 0}

    keywords = LESSON_KEYWORDS.get(lesson_num, [])
    hits = sum(1 for kw in keywords if kw.lower() in text)
    confidence = min(hits / max(len(keywords), 1), 1.0)

    return {"signal": "semantic_align", "score": hits, "confidence": confidence}


def signal_keyword_match(lesson_entry, lesson_num):
    """Signal 4: Compare KB keywords field against lesson keyword dict."""
    kb_keywords = lesson_entry.get("metadata", {}).get("keywords", [])
    expected = LESSON_KEYWORDS.get(lesson_num, [])

    if not kb_keywords:
        return {"signal": "keyword_match", "overlap": 0, "confidence": 0}

    kb_lower = {k.lower() for k in kb_keywords}
    exp_lower = {k.lower() for k in expected}
    overlap = len(kb_lower & exp_lower)
    confidence = overlap / max(len(exp_lower), 1)

    return {"signal": "keyword_match", "overlap": overlap, "confidence": confidence}


def signal_volume_check(lesson_num, lesson_data, all_lessons_data):
    """Signal 5: Statistical validation of content volume."""
    doc_count = lesson_data.get("document_count", 0)
    img_count = lesson_data.get("image_count", 0)

    all_docs = [d.get("document_count", 0) for d in all_lessons_data.values()]
    all_imgs = [d.get("image_count", 0) for d in all_lessons_data.values()]

    def z_score(value, values):
        if len(values) < 2:
            return 0
        avg = sum(values) / len(values)
        std = math.sqrt(sum((v - avg) ** 2 for v in values) / len(values))
        return abs(value - avg) / std if std > 0 else 0

    doc_z = z_score(doc_count, all_docs)
    img_z = z_score(img_count, all_imgs)

    is_outlier = doc_z > VALIDATION_THRESHOLDS["volume_outlier_zscore"] or \
                 img_z > VALIDATION_THRESHOLDS["volume_outlier_zscore"]

    return {
        "signal": "volume_check",
        "doc_count": doc_count,
        "img_count": img_count,
        "doc_z_score": round(doc_z, 2),
        "img_z_score": round(img_z, 2),
        "is_outlier": is_outlier,
        "confidence": 0.5 if not is_outlier else 0.2,
    }


# ──────────────────────────────────────────────────────────
# Anomaly detection
# ──────────────────────────────────────────────────────────

def detect_anomalies(kb, consolidated):
    """Run all anomaly detectors. Returns list of anomaly dicts."""
    anomalies = []
    by_lesson = consolidated.get("by_lesson", {})

    for lesson_num in range(1, 13):
        lesson_str = str(lesson_num)
        lesson_data = by_lesson.get(lesson_str, {})

        # MISSING: Expected content types
        for ctype in EXPECTED_CONTENT_TYPES:
            docs = lesson_data.get("documents", [])
            has_type = any(d.get("content_type") == ctype for d in docs)
            if not has_type:
                anomalies.append({
                    "type": "MISSING",
                    "severity": "WARNING" if ctype == "lesson_plan" else "ERROR",
                    "lesson": lesson_num,
                    "content_type": ctype,
                    "message": f"Lesson {lesson_num} missing {ctype.replace('_', ' ')}",
                })

        # VOLUME_OUTLIER
        vol = signal_volume_check(lesson_num, lesson_data, by_lesson)
        if vol["is_outlier"]:
            direction = "high" if vol["doc_count"] > 5 else "low"
            anomalies.append({
                "type": "VOLUME_OUTLIER",
                "severity": "INFO",
                "lesson": lesson_num,
                "doc_z": vol["doc_z_score"],
                "img_z": vol["img_z_score"],
                "message": f"Lesson {lesson_num} has {direction} content volume (doc z={vol['doc_z_score']}, img z={vol['img_z_score']})",
            })

    # ORPHANED: Unassigned content
    for doc in consolidated.get("unassigned", {}).get("documents", []):
        anomalies.append({
            "type": "ORPHANED",
            "severity": "WARNING",
            "path": doc.get("path", ""),
            "message": f"Document not assigned to any lesson: {doc.get('path', '')}",
        })

    # DUPLICATE
    for dup in consolidated.get("duplicates", []):
        anomalies.append({
            "type": "DUPLICATE",
            "severity": "INFO",
            "file": dup.get("file", ""),
            "duplicate_type": dup.get("type", ""),
            "message": f"Potential duplicate ({dup.get('type', '')}): {dup.get('file', '')}",
        })

    # NAMING_INCONSISTENT
    for lesson_str, ldata in by_lesson.items():
        for doc in ldata.get("documents", []):
            path = doc.get("path", "")
            if re.search(r"exampler", path, re.IGNORECASE):
                anomalies.append({
                    "type": "NAMING_INCONSISTENT",
                    "severity": "INFO",
                    "path": path,
                    "message": f"Misspelling: 'Exampler' should be 'Exemplar' in {path}",
                })

    return anomalies


# ──────────────────────────────────────────────────────────
# Validation report
# ──────────────────────────────────────────────────────────

def generate_validation_report(kb, consolidated, anomalies):
    """Generate comprehensive validation report."""
    by_severity = {"ERROR": [], "WARNING": [], "INFO": []}
    for a in anomalies:
        by_severity[a.get("severity", "INFO")].append(a)

    # Calculate overall confidence
    total_lessons = len(kb.get("lessons", []))
    error_count = len(by_severity["ERROR"])
    warning_count = len(by_severity["WARNING"])

    # Confidence formula
    base = 100 if total_lessons >= 12 else (total_lessons / 12 * 100)
    penalty = min(error_count * 5, 30) + min(warning_count * 1, 10)
    overall_confidence = max(0, round(base - penalty, 1))

    # Per-lesson inventory
    per_lesson = {}
    by_lesson = consolidated.get("by_lesson", {})
    for lesson_num in range(1, 13):
        ldata = by_lesson.get(str(lesson_num), {})
        per_lesson[lesson_num] = {
            "documents": ldata.get("document_count", 0),
            "images": ldata.get("image_count", 0),
            "native": ldata.get("native_count", 0),
            "anomalies": len([a for a in anomalies if a.get("lesson") == lesson_num]),
        }

    # Determine status
    if overall_confidence >= 90 and error_count == 0:
        status = "VALID"
    elif overall_confidence >= 80 and error_count <= 2:
        status = "VALID_WITH_WARNINGS"
    elif overall_confidence >= 60:
        status = "NEEDS_REVIEW"
    else:
        status = "INCOMPLETE"

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "overall_confidence": overall_confidence,
        "publish_blocked": BLOCK_ON_ERROR and error_count > 0,
        "summary": {
            "total_lessons": total_lessons,
            "anomalies_total": len(anomalies),
            "errors": error_count,
            "warnings": warning_count,
            "info": len(by_severity["INFO"]),
        },
        "per_lesson": per_lesson,
        "anomalies": anomalies,
        "anomalies_by_severity": {k: v for k, v in by_severity.items()},
    }

    return report


# ──────────────────────────────────────────────────────────
# Main validation
# ──────────────────────────────────────────────────────────

def run_validation():
    """Execute full validation on the built KB."""
    print("=" * 60)
    print("  Stage 7: Validation Post-Build Check")
    print("=" * 60)
    print()

    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)

    # Load KB files
    kb_files = list(OUTPUT_DIR.glob("Term * - Lesson Based Structure.json"))
    if not kb_files:
        print("No KB files found in output/. Run build_kb.py first.")
        return None

    # Load consolidated content — prefer per-term files, fall back to combined
    combined_path = CONSOLIDATED_DIR / "consolidated_content.json"
    _combined_cache = {}

    def _load_consolidated_for_term(term_num):
        """Load per-term file first, fall back to combined file."""
        per_term_path = CONSOLIDATED_DIR / f"consolidated_term{term_num}.json"
        if per_term_path.exists():
            with open(per_term_path, "r", encoding="utf-8") as f:
                return json.load(f)
        # Fallback: extract term data from combined file
        if not _combined_cache:
            if combined_path.exists():
                with open(combined_path, "r", encoding="utf-8") as f:
                    _combined_cache.update(json.load(f))
        if _combined_cache:
            term_data = _combined_cache.get("by_term", {}).get(str(term_num), {})
            return {
                "by_lesson": term_data.get("by_lesson", {}),
                "duplicates": _combined_cache.get("duplicates", []),
                "unassigned": _combined_cache.get("unassigned", {}),
            }
        return {}

    all_reports = {}
    any_blocked = False

    for kb_path in kb_files:
        print(f"\nValidating: {kb_path.name}")
        with open(kb_path, "r", encoding="utf-8") as f:
            kb = json.load(f)

        term = kb.get("term", "?")
        consolidated = _load_consolidated_for_term(term) if term != "?" else {}

        # Run anomaly detection
        anomalies = detect_anomalies(kb, consolidated)
        print(f"  Anomalies found: {len(anomalies)}")

        # Generate report
        report = generate_validation_report(kb, consolidated, anomalies)
        print(f"  Status: {report['status']}")
        print(f"  Confidence: {report['overall_confidence']}%")
        print(f"  Errors: {report['summary']['errors']}, Warnings: {report['summary']['warnings']}")

        if report["publish_blocked"]:
            print(f"  *** PUBLISHING BLOCKED — {report['summary']['errors']} ERROR-level anomalies ***")
            any_blocked = True

        # Save report
        report_path = VALIDATION_DIR / f"validation_report_term{term}.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"  Report saved: {report_path}")

        # Generate text summary
        txt_path = VALIDATION_DIR / f"validation_report_term{term}.txt"
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("=" * 70 + "\n")
            f.write(f"  VALIDATION REPORT — Term {term}\n")
            f.write("=" * 70 + "\n\n")
            f.write(f"Status: {report['status']}\n")
            f.write(f"Confidence: {report['overall_confidence']}%\n")
            f.write(f"Publish Blocked: {report['publish_blocked']}\n\n")
            f.write(f"Anomalies: {report['summary']['anomalies_total']}\n")
            f.write(f"  Errors:   {report['summary']['errors']}\n")
            f.write(f"  Warnings: {report['summary']['warnings']}\n")
            f.write(f"  Info:     {report['summary']['info']}\n\n")

            if report["anomalies_by_severity"]["ERROR"]:
                f.write("ERRORS:\n")
                for a in report["anomalies_by_severity"]["ERROR"]:
                    f.write(f"  [ERROR] {a['message']}\n")
                f.write("\n")

            if report["anomalies_by_severity"]["WARNING"]:
                f.write("WARNINGS:\n")
                for a in report["anomalies_by_severity"]["WARNING"]:
                    f.write(f"  [WARNING] {a['message']}\n")
                f.write("\n")

        all_reports[f"term{term}"] = report

    print("\n" + "=" * 60)
    print("  Validation Complete")
    print("=" * 60)
    if any_blocked:
        print("  *** KB PUBLISHING IS BLOCKED — Fix ERROR-level anomalies ***")
    else:
        print("  All validations passed. KB is ready for publishing.")

    return all_reports


if __name__ == "__main__":
    run_validation()
