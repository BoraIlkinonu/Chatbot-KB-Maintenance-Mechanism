"""
Validation Anomalies - Script 3 of 4
Purpose: Detect and flag issues in content mappings

Anomaly Types:
- MISALIGNED: Signal consensus < 60%
- MISSING: Expected content not found
- DUPLICATE: Same content in multiple lessons
- ORPHANED: No lesson assignment possible
- VOLUME_OUTLIER: Statistical deviation
- NAMING_INCONSISTENT: Pattern mismatch

Input: Term 2 - Lesson Mappings.json, Term 2 - Unified Content.json
Output: Term 2 - Anomalies.json
"""

import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional
from collections import defaultdict

# Base directory
BASE_DIR = Path(r"D:\Term 3 QA\Teacher Resources - Term 2")

# Anomaly severity levels
SEVERITY = {
    "ERROR": 3,      # Critical issues that need immediate attention
    "WARNING": 2,    # Issues that should be reviewed
    "INFO": 1        # Informational notes
}

# Expected content per lesson
EXPECTED_CONTENT = {
    "teachers_slides": {"required": True, "per_lesson": 1},
    "students_slides": {"required": True, "per_lesson": 1},
    "lesson_plan": {"required": True, "per_lesson": 1},
    "exemplar_work": {"required": False, "per_week": 1}
}

# Expected volume ranges
VOLUME_RANGES = {
    "images_per_lesson": {"min": 15, "max": 50, "outlier_threshold": 2.0},
    "slides_per_lesson": {"min": 10, "max": 40, "outlier_threshold": 2.0}
}

# Known naming patterns
NAMING_PATTERNS = {
    "lesson_standard": r"Lesson\s*\d+\.?",
    "lesson_underscore": r"Lesson\s*\d+_",
    "week_standard": r"Week\s*\d+"
}


def detect_misaligned(mappings: Dict) -> List[Dict]:
    """Detect items with low signal consensus (<60%)."""
    anomalies = []

    for item in mappings.get("items", []):
        consensus = item.get("consensus", {})
        confidence = consensus.get("consensus_confidence", 0)

        if 0 < confidence < 60:
            anomalies.append({
                "type": "MISALIGNED",
                "severity": "WARNING",
                "item_id": item.get("id"),
                "item_type": item.get("type"),
                "path": item.get("path"),
                "confidence": confidence,
                "message": f"Low consensus confidence ({confidence}%)",
                "signals": [
                    f"{s['signal']}: {s.get('lessons')}"
                    for s in item.get("signals", [])
                    if s.get("lessons")
                ],
                "recommendation": "Manual review recommended to confirm lesson assignment"
            })

    return anomalies


def detect_missing(mappings: Dict, unified_content: Dict) -> List[Dict]:
    """Detect expected content that is missing."""
    anomalies = []

    # Check each lesson for required content types
    for lesson in range(1, 13):
        lesson_items = mappings.get("by_lesson", {}).get(str(lesson), [])

        # Get all items for this lesson
        lesson_content = []
        for item in mappings.get("items", []):
            if lesson in item.get("consensus", {}).get("assigned_lessons", []):
                lesson_content.append(item)

        # Check for teachers slides
        has_teachers_slides = any(
            i.get("content_type") == "teachers_slides"
            for i in lesson_content
        )
        if not has_teachers_slides:
            anomalies.append({
                "type": "MISSING",
                "severity": "ERROR",
                "lesson": lesson,
                "content_type": "teachers_slides",
                "message": f"Lesson {lesson} missing Teachers Slides",
                "recommendation": "Check if Teachers Slides exist but are mapped incorrectly"
            })

        # Check for students slides
        has_students_slides = any(
            i.get("content_type") == "students_slides"
            for i in lesson_content
        )
        if not has_students_slides:
            anomalies.append({
                "type": "MISSING",
                "severity": "ERROR",
                "lesson": lesson,
                "content_type": "students_slides",
                "message": f"Lesson {lesson} missing Students Slides",
                "recommendation": "Check if Students Slides exist but are mapped incorrectly"
            })

        # Check for lesson plans
        has_lesson_plan = any(
            i.get("content_type") == "lesson_plan"
            for i in lesson_content
        )
        if not has_lesson_plan:
            anomalies.append({
                "type": "MISSING",
                "severity": "WARNING",
                "lesson": lesson,
                "content_type": "lesson_plan",
                "message": f"Lesson {lesson} missing Lesson Plan",
                "recommendation": "Check Lesson Plans folder"
            })

    return anomalies


def detect_duplicates(mappings: Dict) -> List[Dict]:
    """Detect content appearing in multiple unrelated lessons."""
    anomalies = []

    # Video files that are expected to map to multiple lessons (their week's lessons)
    EXPECTED_MULTI_LESSON_VIDEOS = [
        "Light_of_the_Mosque",
        "Designing_Restoring_Light",
        "The_Unseen_Hero"
    ]

    # Track items by path/filename
    path_lessons = defaultdict(set)

    for item in mappings.get("items", []):
        path = item.get("path", "") or ""
        lessons = item.get("consensus", {}).get("assigned_lessons", [])

        if path and len(lessons) > 2:  # More than 2 lessons is suspicious
            # Skip portfolio items (expected to span all lessons)
            if "portfolio" in path.lower() or "all" in path.lower():
                continue

            # Skip video keyframes - they correctly inherit parent video's lesson(s)
            if any(video in path for video in EXPECTED_MULTI_LESSON_VIDEOS):
                continue

            # Skip exemplar and design brief resources
            if "exemplar" in path.lower() or "design brief" in path.lower():
                continue

            anomalies.append({
                "type": "DUPLICATE",
                "severity": "INFO",
                "item_id": item.get("id"),
                "path": path,
                "lessons": lessons,
                "message": f"Content mapped to {len(lessons)} lessons",
                "recommendation": "Verify if content intentionally spans multiple lessons"
            })

    return anomalies


def detect_orphaned(mappings: Dict) -> List[Dict]:
    """Detect items with no lesson assignment."""
    anomalies = []

    # Items that are legitimately not lesson-specific
    NON_LESSON_PATTERNS = [
        "curriculum alignment",
        "professional development",
        "learning schedule",
        "exemplar-games",
        "design briefs all",
        "assessment guide",
        "teacher guide",
        "student guide"
    ]

    for item in mappings.get("items", []):
        consensus = item.get("consensus", {})
        assigned_lessons = consensus.get("assigned_lessons", [])
        status = consensus.get("status", "")

        if not assigned_lessons or status == "UNMAPPED":
            # Skip items that are legitimately unassigned
            path = (item.get("path") or "").lower()
            if any(term in path for term in NON_LESSON_PATTERNS):
                continue

            anomalies.append({
                "type": "ORPHANED",
                "severity": "WARNING",
                "item_id": item.get("id"),
                "item_type": item.get("type"),
                "path": item.get("path"),
                "message": "No lesson assignment possible",
                "signals_tried": len([s for s in item.get("signals", []) if s.get("method") != "no_match"]),
                "recommendation": "Review path and content to determine correct lesson"
            })

    return anomalies


def detect_volume_outliers(mappings: Dict) -> List[Dict]:
    """Detect statistical deviations in content volume."""
    anomalies = []

    # Count items per lesson per content type
    lesson_counts = defaultdict(lambda: defaultdict(int))

    for item in mappings.get("items", []):
        lessons = item.get("consensus", {}).get("assigned_lessons", [])
        content_type = item.get("content_type", "unknown")

        for lesson in lessons:
            lesson_counts[lesson][content_type] += 1

    # Calculate averages and detect outliers
    all_image_counts = [
        lesson_counts[l].get("image", 0) + lesson_counts[l].get("pptx_image", 0)
        for l in range(1, 13)
    ]

    if all_image_counts:
        avg_images = sum(all_image_counts) / len(all_image_counts)
        std_dev = (sum((x - avg_images) ** 2 for x in all_image_counts) / len(all_image_counts)) ** 0.5

        for lesson in range(1, 13):
            count = lesson_counts[lesson].get("image", 0) + lesson_counts[lesson].get("pptx_image", 0)

            if std_dev > 0:
                z_score = abs(count - avg_images) / std_dev
                if z_score > VOLUME_RANGES["images_per_lesson"]["outlier_threshold"]:
                    direction = "high" if count > avg_images else "low"
                    anomalies.append({
                        "type": "VOLUME_OUTLIER",
                        "severity": "INFO",
                        "lesson": lesson,
                        "metric": "image_count",
                        "value": count,
                        "average": round(avg_images, 1),
                        "z_score": round(z_score, 2),
                        "message": f"Lesson {lesson} has {direction} image count ({count} vs avg {round(avg_images, 1)})",
                        "recommendation": f"Review if {'extra' if direction == 'high' else 'missing'} images are expected"
                    })

    return anomalies


def detect_naming_inconsistencies(unified_content: Dict) -> List[Dict]:
    """Detect naming pattern mismatches in file paths."""
    anomalies = []
    seen_paths = set()  # Track unique paths to avoid duplicate reports

    # Only flag significant naming issues (misspellings that could cause confusion)
    inconsistency_patterns = [
        (r"Exampler", "Misspelling: 'Exampler' should be 'Exemplar'"),
    ]

    for content_type in ["markdown", "images", "videos"]:
        for item in unified_content.get("content", {}).get(content_type, []):
            path = item.get("path", "") or item.get("source", "")

            # Skip if we've already flagged this path
            if path in seen_paths:
                continue

            for pattern, description in inconsistency_patterns:
                if re.search(pattern, path, re.IGNORECASE):
                    seen_paths.add(path)
                    anomalies.append({
                        "type": "NAMING_INCONSISTENT",
                        "severity": "INFO",
                        "item_id": item.get("id"),
                        "path": path,
                        "pattern_matched": pattern,
                        "message": description,
                        "recommendation": "Consider renaming source file for consistency"
                    })

    return anomalies


def detect_teachers_students_mismatch(unified_content: Dict) -> List[Dict]:
    """Detect mismatches between Teachers and Students slides."""
    anomalies = []

    teachers_slides = {}
    students_slides = {}

    for item in unified_content.get("content", {}).get("markdown", []):
        path = item.get("path", "")
        content_type = item.get("content_type", "")
        lesson_info = item.get("lesson_info") or {}

        lesson = lesson_info.get("lesson") or (lesson_info.get("lessons", [None])[0] if lesson_info.get("lessons") else None)

        if content_type == "teachers_slides" and lesson:
            teachers_slides[lesson] = {
                "path": path,
                "slide_count": item.get("slide_count"),
                "char_count": item.get("char_count")
            }
        elif content_type == "students_slides" and lesson:
            students_slides[lesson] = {
                "path": path,
                "slide_count": item.get("slide_count"),
                "char_count": item.get("char_count")
            }

    # Compare Teachers vs Students
    for lesson in range(1, 13):
        t = teachers_slides.get(lesson)
        s = students_slides.get(lesson)

        if t and s:
            # Check slide count difference
            if t.get("slide_count") and s.get("slide_count"):
                diff = abs(t["slide_count"] - s["slide_count"])
                if diff > 5:
                    anomalies.append({
                        "type": "TEACHERS_STUDENTS_MISMATCH",
                        "severity": "INFO",
                        "lesson": lesson,
                        "teachers_slides": t["slide_count"],
                        "students_slides": s["slide_count"],
                        "difference": diff,
                        "message": f"Lesson {lesson}: Teachers ({t['slide_count']}) vs Students ({s['slide_count']}) slide count differs by {diff}",
                        "recommendation": "Verify if difference is intentional (e.g., teacher notes)"
                    })

    return anomalies


def main():
    """Main function to detect all anomalies."""
    print("=" * 60)
    print("VALIDATION ANOMALIES - Detecting Issues")
    print("=" * 60)

    # Load input files
    mappings_path = BASE_DIR / "Term 2 - Lesson Mappings.json"
    unified_path = BASE_DIR / "Term 2 - Unified Content.json"

    if not mappings_path.exists():
        print(f"Error: Lesson Mappings not found at {mappings_path}")
        print("Please run validation_mapper.py first.")
        return None

    if not unified_path.exists():
        print(f"Error: Unified Content not found at {unified_path}")
        print("Please run validation_parser.py first.")
        return None

    print(f"\nLoading: {mappings_path}")
    with open(mappings_path, 'r', encoding='utf-8') as f:
        mappings = json.load(f)

    print(f"Loading: {unified_path}")
    with open(unified_path, 'r', encoding='utf-8') as f:
        unified_content = json.load(f)

    # Run all anomaly detectors
    print("\nRunning anomaly detection...")

    all_anomalies = []

    print("  [1/7] Detecting misaligned items...")
    all_anomalies.extend(detect_misaligned(mappings))

    print("  [2/7] Detecting missing content...")
    all_anomalies.extend(detect_missing(mappings, unified_content))

    print("  [3/7] Detecting duplicates...")
    all_anomalies.extend(detect_duplicates(mappings))

    print("  [4/7] Detecting orphaned items...")
    all_anomalies.extend(detect_orphaned(mappings))

    print("  [5/7] Detecting volume outliers...")
    all_anomalies.extend(detect_volume_outliers(mappings))

    print("  [6/7] Detecting naming inconsistencies...")
    all_anomalies.extend(detect_naming_inconsistencies(unified_content))

    print("  [7/7] Detecting Teachers/Students mismatches...")
    all_anomalies.extend(detect_teachers_students_mismatch(unified_content))

    # Categorize by severity
    by_severity = {
        "ERROR": [a for a in all_anomalies if a.get("severity") == "ERROR"],
        "WARNING": [a for a in all_anomalies if a.get("severity") == "WARNING"],
        "INFO": [a for a in all_anomalies if a.get("severity") == "INFO"]
    }

    # Categorize by type
    by_type = defaultdict(list)
    for a in all_anomalies:
        by_type[a.get("type", "UNKNOWN")].append(a)

    # Create output structure
    output = {
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "total_anomalies": len(all_anomalies),
            "errors": len(by_severity["ERROR"]),
            "warnings": len(by_severity["WARNING"]),
            "info": len(by_severity["INFO"]),
            "by_type": {k: len(v) for k, v in by_type.items()}
        },
        "by_severity": by_severity,
        "by_type": dict(by_type),
        "all_anomalies": all_anomalies
    }

    # Write output
    output_path = BASE_DIR / "Term 2 - Anomalies.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 60)
    print("ANOMALY DETECTION COMPLETE")
    print("=" * 60)
    print(f"\nOutput: {output_path}")
    print(f"\nSummary:")
    print(f"  - Total anomalies: {len(all_anomalies)}")
    print(f"  - Errors: {len(by_severity['ERROR'])}")
    print(f"  - Warnings: {len(by_severity['WARNING'])}")
    print(f"  - Info: {len(by_severity['INFO'])}")
    print(f"\nBy Type:")
    for anomaly_type, items in sorted(by_type.items()):
        print(f"  - {anomaly_type}: {len(items)}")

    # Print critical errors
    if by_severity["ERROR"]:
        print(f"\n{'!' * 60}")
        print("CRITICAL ERRORS REQUIRING ATTENTION:")
        print("!" * 60)
        for error in by_severity["ERROR"]:
            print(f"  [{error['type']}] {error['message']}")

    return output


if __name__ == "__main__":
    main()
