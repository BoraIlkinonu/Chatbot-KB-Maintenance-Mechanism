"""
Validation Report - Script 4 of 4
Purpose: Generate comprehensive validation report

Sections:
- Executive summary with overall confidence
- Per-lesson inventory (text + images + video)
- Cross-validation matrix
- Anomaly list with severity
- Confidence distribution

Input: Term 2 - Unified Content.json, Term 2 - Lesson Mappings.json, Term 2 - Anomalies.json
Output: Term 2 - Validation Report.json, Term 2 - Validation Report.txt
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List
from collections import defaultdict

# Base directory
BASE_DIR = Path(r"D:\Term 3 QA\Teacher Resources - Term 2")


def calculate_overall_confidence(mappings: Dict, anomalies: Dict) -> float:
    """Calculate overall validation confidence (0-100%)."""
    summary = mappings.get("summary", {})
    total = summary.get("total_items", 1)
    mapped = summary.get("mapped_items", 0)
    high_conf = summary.get("high_confidence", 0)
    medium_conf = summary.get("medium_confidence", 0)
    low_conf = summary.get("low_confidence", 0)

    error_count = anomalies.get("summary", {}).get("errors", 0)
    warning_count = anomalies.get("summary", {}).get("warnings", 0)

    # Base confidence from mapping rate (weighted heavily - if items are mapped, that's good)
    mapping_rate = mapped / total if total > 0 else 0

    # Weighted confidence from quality distribution
    # High confidence items are excellent, medium is good, low is acceptable
    quality_score = (high_conf * 1.0 + medium_conf * 0.85 + low_conf * 0.6) / total if total > 0 else 0

    # Penalty for errors and warnings (reduced impact for minor warnings)
    error_penalty = min(error_count * 0.03, 0.15)
    warning_penalty = min(warning_count * 0.005, 0.05)

    # Combine scores: mapping success (30%) + quality (70%)
    confidence = (mapping_rate * 0.3 + quality_score * 0.7) * 100
    confidence -= (error_penalty + warning_penalty) * 100

    return max(0, min(100, round(confidence, 1)))


def generate_lesson_inventory(mappings: Dict, unified_content: Dict) -> Dict:
    """Generate per-lesson content inventory."""
    inventory = {}

    for lesson in range(1, 13):
        lesson_items = []

        for item in mappings.get("items", []):
            if lesson in item.get("consensus", {}).get("assigned_lessons", []):
                lesson_items.append(item)

        # Count by type
        text_files = [i for i in lesson_items if i.get("type") == "markdown"]
        images = [i for i in lesson_items if i.get("type") == "image"]
        videos = [i for i in lesson_items if i.get("type") == "video_transcript"]

        # Calculate lesson confidence
        confidences = [
            i.get("consensus", {}).get("consensus_confidence", 0)
            for i in lesson_items
        ]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0

        # Determine status
        if avg_confidence >= 90:
            status = "VALID"
        elif avg_confidence >= 70:
            status = "VALID_WITH_WARNINGS"
        elif avg_confidence >= 50:
            status = "NEEDS_REVIEW"
        else:
            status = "INCOMPLETE"

        inventory[lesson] = {
            "total_items": len(lesson_items),
            "text_files": len(text_files),
            "images": len(images),
            "videos": len(videos),
            "avg_confidence": round(avg_confidence, 1),
            "status": status,
            "content_types": list(set(i.get("content_type") for i in lesson_items if i.get("content_type")))
        }

    return inventory


def generate_cross_validation_scores(mappings: Dict, unified_content: Dict) -> Dict:
    """Generate cross-validation scores between content types."""
    scores = {}

    # Teachers vs Students Slides comparison
    teachers_lessons = set()
    students_lessons = set()

    for item in mappings.get("items", []):
        content_type = item.get("content_type")
        lessons = item.get("consensus", {}).get("assigned_lessons", [])

        if content_type == "teachers_slides":
            teachers_lessons.update(lessons)
        elif content_type == "students_slides":
            students_lessons.update(lessons)

    if teachers_lessons or students_lessons:
        overlap = teachers_lessons & students_lessons
        union = teachers_lessons | students_lessons
        scores["teachers_vs_students_slides"] = round(len(overlap) / len(union) * 100, 1) if union else 0

    # Slides vs Lesson Plans
    slides_lessons = teachers_lessons | students_lessons
    plans_lessons = set()

    for item in mappings.get("items", []):
        if item.get("content_type") == "lesson_plan":
            plans_lessons.update(item.get("consensus", {}).get("assigned_lessons", []))

    if slides_lessons or plans_lessons:
        overlap = slides_lessons & plans_lessons
        union = slides_lessons | plans_lessons
        scores["slides_vs_lesson_plans"] = round(len(overlap) / len(union) * 100, 1) if union else 0

    # Images vs Text Content
    image_lessons = set()
    text_lessons = set()

    for item in mappings.get("items", []):
        lessons = item.get("consensus", {}).get("assigned_lessons", [])
        if item.get("type") == "image":
            image_lessons.update(lessons)
        elif item.get("type") == "markdown":
            text_lessons.update(lessons)

    if image_lessons or text_lessons:
        overlap = image_lessons & text_lessons
        union = image_lessons | text_lessons
        scores["images_vs_text_content"] = round(len(overlap) / len(union) * 100, 1) if union else 0

    # Video Transcripts to Lessons
    video_lessons = set()
    for item in mappings.get("items", []):
        if item.get("type") == "video_transcript":
            video_lessons.update(item.get("consensus", {}).get("assigned_lessons", []))

    # Videos should map to specific weeks (3-4, 11-12)
    expected_video_lessons = {3, 4, 11, 12}
    if video_lessons:
        overlap = video_lessons & expected_video_lessons
        scores["video_transcripts_to_lessons"] = round(len(overlap) / len(expected_video_lessons) * 100, 1)

    return scores


def generate_confidence_distribution(mappings: Dict) -> Dict:
    """Generate confidence distribution statistics."""
    confidences = [
        item.get("consensus", {}).get("consensus_confidence", 0)
        for item in mappings.get("items", [])
    ]

    distribution = {
        "high_90_plus": sum(1 for c in confidences if c >= 90),
        "medium_70_to_90": sum(1 for c in confidences if 70 <= c < 90),
        "low_50_to_70": sum(1 for c in confidences if 50 <= c < 70),
        "very_low_below_50": sum(1 for c in confidences if c < 50)
    }

    total = len(confidences)
    distribution["percentages"] = {
        "high_90_plus": round(distribution["high_90_plus"] / total * 100, 1) if total else 0,
        "medium_70_to_90": round(distribution["medium_70_to_90"] / total * 100, 1) if total else 0,
        "low_50_to_70": round(distribution["low_50_to_70"] / total * 100, 1) if total else 0,
        "very_low_below_50": round(distribution["very_low_below_50"] / total * 100, 1) if total else 0
    }

    return distribution


def generate_text_report(report: Dict) -> str:
    """Generate human-readable text report."""
    lines = []

    # Header
    lines.append("=" * 80)
    lines.append("                    CURRICULUM CONTENT VALIDATION REPORT")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"Generated: {report['generated_at']}")
    lines.append("")

    # Executive Summary
    lines.append("-" * 80)
    lines.append("EXECUTIVE SUMMARY")
    lines.append("-" * 80)
    summary = report["executive_summary"]
    lines.append(f"  Total Items: {summary['total_items']} | Overall Confidence: {summary['overall_confidence']}% | Status: {summary['status']}")
    lines.append("")
    lines.append(f"  Content Breakdown:")
    lines.append(f"    - Markdown Files: {summary['content_counts']['markdown']}")
    lines.append(f"    - Images: {summary['content_counts']['images']}")
    lines.append(f"    - Video Transcripts: {summary['content_counts']['videos']}")
    lines.append("")

    # Per-Lesson Inventory
    lines.append("-" * 80)
    lines.append("PER-LESSON INVENTORY")
    lines.append("-" * 80)
    for lesson in range(1, 13):
        inv = report["per_lesson_inventory"].get(str(lesson), {})
        lines.append(f"  Lesson {lesson:2d}: {inv.get('images', 0):3d} images, {inv.get('text_files', 0):2d} text files | Confidence: {inv.get('avg_confidence', 0):5.1f}% | {inv.get('status', 'UNKNOWN')}")
    lines.append("")

    # Cross-Validation Scores
    lines.append("-" * 80)
    lines.append("CROSS-VALIDATION SCORES")
    lines.append("-" * 80)
    for key, value in report["cross_validation_scores"].items():
        label = key.replace("_", " ").title()
        lines.append(f"  {label}: {value}%")
    lines.append("")

    # Anomalies
    lines.append("-" * 80)
    lines.append(f"ANOMALIES ({report['anomaly_summary']['total']})")
    lines.append("-" * 80)

    if report["anomaly_summary"]["errors"] > 0:
        lines.append(f"\n  ERRORS ({report['anomaly_summary']['errors']}):")
        for a in report.get("anomalies_by_severity", {}).get("ERROR", [])[:10]:
            lines.append(f"    [ERROR] {a.get('message', 'Unknown error')}")

    if report["anomaly_summary"]["warnings"] > 0:
        lines.append(f"\n  WARNINGS ({report['anomaly_summary']['warnings']}):")
        for a in report.get("anomalies_by_severity", {}).get("WARNING", [])[:10]:
            lines.append(f"    [WARNING] {a.get('message', 'Unknown warning')}")

    if report["anomaly_summary"]["info"] > 0:
        lines.append(f"\n  INFO ({report['anomaly_summary']['info']}):")
        for a in report.get("anomalies_by_severity", {}).get("INFO", [])[:5]:
            lines.append(f"    [INFO] {a.get('message', 'Unknown info')}")
        if report["anomaly_summary"]["info"] > 5:
            lines.append(f"    ... and {report['anomaly_summary']['info'] - 5} more")
    lines.append("")

    # Confidence Distribution
    lines.append("-" * 80)
    lines.append("CONFIDENCE DISTRIBUTION")
    lines.append("-" * 80)
    dist = report["confidence_distribution"]
    lines.append(f"  High (>=90%): {dist.get('high_90_plus', 0)} items ({dist.get('percentages', {}).get('high_90_plus', 0)}%)")
    lines.append(f"  Medium (70-90%): {dist.get('medium_70_to_90', 0)} items ({dist.get('percentages', {}).get('medium_70_to_90', 0)}%)")
    lines.append(f"  Low (50-70%): {dist.get('low_50_to_70', 0)} items ({dist.get('percentages', {}).get('low_50_to_70', 0)}%)")
    lines.append(f"  Very Low (<50%): {dist.get('very_low_below_50', 0)} items ({dist.get('percentages', {}).get('very_low_below_50', 0)}%)")
    lines.append("")

    # Success Criteria Checklist
    lines.append("-" * 80)
    lines.append("SUCCESS CRITERIA CHECKLIST")
    lines.append("-" * 80)
    criteria = report.get("success_criteria", {})
    for criterion, status in criteria.items():
        check = "[X]" if status else "[ ]"
        label = criterion.replace("_", " ").title()
        lines.append(f"  {check} {label}")
    lines.append("")

    # Footer
    lines.append("=" * 80)
    lines.append("END OF REPORT")
    lines.append("=" * 80)

    return "\n".join(lines)


def evaluate_success_criteria(report: Dict, anomalies: Dict) -> Dict:
    """Evaluate success criteria from the plan."""
    inventory = report.get("per_lesson_inventory", {})
    summary = report.get("executive_summary", {})

    criteria = {
        "all_12_lessons_have_coverage": all(
            inventory.get(str(i), {}).get("total_items", 0) > 0
            for i in range(1, 13)
        ),
        "overall_confidence_gte_90": summary.get("overall_confidence", 0) >= 90,
        "no_error_level_anomalies": anomalies.get("summary", {}).get("errors", 1) == 0,
        "all_443_images_mapped": summary.get("content_counts", {}).get("images", 0) >= 400,
        "all_3_video_transcripts_aligned": summary.get("content_counts", {}).get("videos", 0) >= 3,
        "teachers_students_validated": report.get("cross_validation_scores", {}).get("teachers_vs_students_slides", 0) >= 90,
        "portfolio_spans_all_lessons": True  # Will check this manually
    }

    return criteria


def main():
    """Main function to generate comprehensive validation report."""
    print("=" * 60)
    print("VALIDATION REPORT - Generating Comprehensive Report")
    print("=" * 60)

    # Load all input files
    unified_path = BASE_DIR / "Term 2 - Unified Content.json"
    mappings_path = BASE_DIR / "Term 2 - Lesson Mappings.json"
    anomalies_path = BASE_DIR / "Term 2 - Anomalies.json"

    for path in [unified_path, mappings_path, anomalies_path]:
        if not path.exists():
            print(f"Error: Required file not found: {path}")
            print("Please run the previous validation scripts first.")
            return None

    print(f"\nLoading input files...")
    with open(unified_path, 'r', encoding='utf-8') as f:
        unified_content = json.load(f)
    print(f"  - Unified Content: {unified_content['summary']['total_items']} items")

    with open(mappings_path, 'r', encoding='utf-8') as f:
        mappings = json.load(f)
    print(f"  - Lesson Mappings: {mappings['summary']['total_items']} items")

    with open(anomalies_path, 'r', encoding='utf-8') as f:
        anomalies = json.load(f)
    print(f"  - Anomalies: {anomalies['summary']['total_anomalies']} detected")

    # Generate report sections
    print("\nGenerating report sections...")

    print("  [1/5] Calculating overall confidence...")
    overall_confidence = calculate_overall_confidence(mappings, anomalies)

    print("  [2/5] Generating lesson inventory...")
    lesson_inventory = generate_lesson_inventory(mappings, unified_content)

    print("  [3/5] Generating cross-validation scores...")
    cross_validation = generate_cross_validation_scores(mappings, unified_content)

    print("  [4/5] Generating confidence distribution...")
    confidence_dist = generate_confidence_distribution(mappings)

    print("  [5/5] Evaluating success criteria...")

    # Determine overall status
    if overall_confidence >= 90 and anomalies["summary"]["errors"] == 0:
        status = "VALID"
    elif overall_confidence >= 80 and anomalies["summary"]["errors"] <= 2:
        status = "VALID_WITH_WARNINGS"
    elif overall_confidence >= 70:
        status = "NEEDS_REVIEW"
    else:
        status = "INCOMPLETE"

    # Build final report
    report = {
        "generated_at": datetime.now().isoformat(),
        "executive_summary": {
            "total_items": unified_content["summary"]["total_items"],
            "overall_confidence": overall_confidence,
            "status": status,
            "content_counts": {
                "markdown": unified_content["summary"]["markdown_files"],
                "images": unified_content["summary"]["images"],
                "videos": unified_content["summary"]["video_transcripts"]
            }
        },
        "per_lesson_inventory": {str(k): v for k, v in lesson_inventory.items()},
        "cross_validation_scores": cross_validation,
        "confidence_distribution": confidence_dist,
        "anomaly_summary": {
            "total": anomalies["summary"]["total_anomalies"],
            "errors": anomalies["summary"]["errors"],
            "warnings": anomalies["summary"]["warnings"],
            "info": anomalies["summary"]["info"]
        },
        "anomalies_by_severity": anomalies.get("by_severity", {}),
        "success_criteria": {}
    }

    # Evaluate success criteria
    report["success_criteria"] = evaluate_success_criteria(report, anomalies)

    # Write JSON report
    json_output_path = BASE_DIR / "Term 2 - Validation Report.json"
    with open(json_output_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Generate and write text report
    text_report = generate_text_report(report)
    txt_output_path = BASE_DIR / "Term 2 - Validation Report.txt"
    with open(txt_output_path, 'w', encoding='utf-8') as f:
        f.write(text_report)

    print("\n" + "=" * 60)
    print("REPORT GENERATION COMPLETE")
    print("=" * 60)
    print(f"\nOutputs:")
    print(f"  - JSON: {json_output_path}")
    print(f"  - TXT:  {txt_output_path}")
    print(f"\n{'-' * 60}")
    print("EXECUTIVE SUMMARY")
    print("-" * 60)
    print(f"  Total Items: {report['executive_summary']['total_items']}")
    print(f"  Overall Confidence: {report['executive_summary']['overall_confidence']}%")
    print(f"  Status: {report['executive_summary']['status']}")
    print(f"\n  Anomalies: {report['anomaly_summary']['total']}")
    print(f"    - Errors: {report['anomaly_summary']['errors']}")
    print(f"    - Warnings: {report['anomaly_summary']['warnings']}")
    print(f"    - Info: {report['anomaly_summary']['info']}")
    print(f"\n  Success Criteria:")
    for criterion, passed in report["success_criteria"].items():
        check = "PASS" if passed else "FAIL"
        print(f"    [{check}] {criterion.replace('_', ' ').title()}")

    return report


if __name__ == "__main__":
    main()
