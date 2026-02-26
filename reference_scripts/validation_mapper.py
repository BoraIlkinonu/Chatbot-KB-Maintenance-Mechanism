"""
Validation Mapper - Script 2 of 4
Purpose: Apply 5 validation signals and calculate consensus

Signals:
1. Path Pattern (weight: 1.0) - Extract lesson IDs from file paths
2. Metadata Cross-Ref (weight: 0.95) - Validate against CSV manifests
3. Semantic Alignment (weight: 0.8) - Match AI tags to lesson keywords
4. Keyword Matching (weight: 0.7) - Compare content themes to lesson objectives
5. Volume Consistency (weight: 0.5) - Statistical validation

Input: Term 2 - Unified Content.json
Output: Term 2 - Lesson Mappings.json
"""

import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# Base directory
BASE_DIR = Path(r"D:\Term 3 QA\Teacher Resources - Term 2")

# Signal weights
SIGNAL_WEIGHTS = {
    "path_pattern": 1.0,
    "video_parent": 1.0,  # Video keyframes inherit from parent video
    "metadata_crossref": 0.95,
    "semantic_align": 0.8,
    "keyword_match": 0.7,
    "volume_check": 0.5
}

# Video to lesson mapping (authoritative)
VIDEO_LESSON_MAP = {
    "Designing_Restoring_Light": [3, 4],      # Week 2
    "Light_of_the_Mosque": [11, 12],          # Week 6
    "The_Unseen_Hero": [11, 12]               # Week 6
}

# Resources that span all lessons
ALL_LESSONS_RESOURCES = [
    "Exemplar-Games",
    "Design Briefs All",
    "Activities & Portfolio",
    "Portfolio Deck",
    "Assessment Guide",
    "Teacher Guide",
    "Student Guide",
    "Curriculum Specifications",
    "Curriculum Alignment",
    "Learning Schedule"
]

# Lesson keyword dictionary
LESSON_KEYWORDS = {
    1: ["design brief", "problem statement", "audience", "constraints", "UAE heritage", "sustainability", "innovation", "problem well stated"],
    2: ["persona", "empathy map", "UX", "player needs", "motivations", "frustrations", "bias", "target player"],
    3: ["primary research", "secondary research", "AI research", "reliability", "bias", "accuracy", "insights", "research methods"],
    4: ["design specification", "team roles", "constraints", "success criteria", "research insights", "collaboration", "rewriting the brief"],
    5: ["brainstorming", "concept generation", "storyboard", "micro-prototype", "core mechanic", "peer feedback", "idea generation"],
    6: ["prototype", "core mechanic", "debugging", "testing", "iteration", "functionality", "prototype v1"],
    7: ["gameplay expansion", "immersion", "visuals", "sound", "dialogue", "player pathways", "prototype v2"],
    8: ["peer testing", "WWW/EBI", "feedback analysis", "theme mapping", "usability", "prioritisation", "feedback"],
    9: ["iteration", "refinement", "feedback implementation", "impact vs effort", "before/after", "player experience", "prototype v3"],
    10: ["team roles", "project manager", "milestones", "timeline", "risk management", "accountability", "collaboration"],
    11: ["documentation", "portfolio", "evidence", "curation", "captions", "reflection", "design story"],
    12: ["reflection", "evaluation", "SMART goals", "Term 3", "progress", "strengths", "challenges"]
}

# Expected volume ranges (images per lesson for Teachers Slides)
EXPECTED_VOLUMES = {
    "teachers_slides": {"min": 20, "max": 45},
    "students_slides": {"min": 20, "max": 45},
    "exemplar_work": {"min": 5, "max": 15},
    "portfolio": {"min": 40, "max": 50}
}


def signal_video_parent(item: Dict) -> Dict:
    """
    Signal for video keyframes: Inherit lesson from parent video.
    Weight: 1.0 (authoritative for video content)
    """
    path = item.get("path", "") or item.get("source", "") or item.get("batch", "")

    # Check if this is a video keyframe
    for video_name, lessons in VIDEO_LESSON_MAP.items():
        if video_name in path or video_name.replace("_", " ") in path:
            return {
                "signal": "video_parent",
                "weight": SIGNAL_WEIGHTS["video_parent"],
                "lessons": lessons,
                "confidence": 1.0,
                "method": "video_inheritance",
                "parent_video": video_name
            }

    return {
        "signal": "video_parent",
        "weight": SIGNAL_WEIGHTS["video_parent"],
        "lessons": None,
        "confidence": 0,
        "method": "not_video_content"
    }


def signal_path_pattern(item: Dict) -> Dict:
    """
    Signal 1: Extract lesson from file paths using regex.
    Weight: 1.0 (most reliable)
    """
    path = item.get("path", "") or item.get("source", "") or ""
    batch = item.get("batch", "") or ""
    combined = f"{path} {batch}".strip()

    # Check for all-lessons resources first
    for resource in ALL_LESSONS_RESOURCES:
        if resource.lower() in combined.lower().replace("_", " ").replace("-", " "):
            return {
                "signal": "path_pattern",
                "weight": SIGNAL_WEIGHTS["path_pattern"],
                "lessons": list(range(1, 13)),
                "confidence": 0.95,
                "method": "all_lessons_resource"
            }

    # Check batch name for week ranges (e.g., "Exemplar_Weeks_3-6")
    week_range_match = re.search(r'weeks?[_\s\-]*(\d)[_\s\-]*(\d)', combined.lower())
    if week_range_match:
        start_week = int(week_range_match.group(1))
        end_week = int(week_range_match.group(2))
        week_lessons = {1: [1, 2], 2: [3, 4], 3: [5, 6], 4: [7, 8], 5: [9, 10], 6: [11, 12]}
        lessons = []
        for week in range(start_week, end_week + 1):
            if week in week_lessons:
                lessons.extend(week_lessons[week])
        if lessons:
            return {
                "signal": "path_pattern",
                "weight": SIGNAL_WEIGHTS["path_pattern"],
                "lessons": sorted(set(lessons)),
                "confidence": 0.9,
                "method": "batch_week_range"
            }

    if item.get("lesson_info"):
        return {
            "signal": "path_pattern",
            "weight": SIGNAL_WEIGHTS["path_pattern"],
            "lessons": item["lesson_info"].get("lessons", [item["lesson_info"].get("lesson")]),
            "confidence": item["lesson_info"].get("confidence", 1.0),
            "method": item["lesson_info"].get("method", "unknown")
        }

    # Try to extract from combined path/batch if lesson_info not set
    if combined:
        # Try various patterns
        lesson_match = re.search(r'lesson[_\s\-]*(\d{1,2})', combined.lower())
        if lesson_match:
            lesson = int(lesson_match.group(1))
            if 1 <= lesson <= 12:
                return {
                    "signal": "path_pattern",
                    "weight": SIGNAL_WEIGHTS["path_pattern"],
                    "lessons": [lesson],
                    "confidence": 1.0,
                    "method": "regex_extraction"
                }

        # Check for single week patterns
        week_match = re.search(r'week[_\s\-]*(\d)(?![_\s\-]*\d)', combined.lower())
        if week_match:
            week = int(week_match.group(1))
            week_lessons = {1: [1, 2], 2: [3, 4], 3: [5, 6], 4: [7, 8], 5: [9, 10], 6: [11, 12]}
            if week in week_lessons:
                return {
                    "signal": "path_pattern",
                    "weight": SIGNAL_WEIGHTS["path_pattern"],
                    "lessons": week_lessons[week],
                    "confidence": 0.9,
                    "method": "week_inference"
                }

    return {
        "signal": "path_pattern",
        "weight": SIGNAL_WEIGHTS["path_pattern"],
        "lessons": None,
        "confidence": 0,
        "method": "no_match"
    }


def signal_metadata_crossref(item: Dict, source_inventory: Dict) -> Dict:
    """
    Signal 2: Validate against authoritative CSV manifests.
    Weight: 0.95
    """
    path = item.get("path", "") or item.get("source", "")

    # Try to find in source inventory
    for inv_path, inv_data in source_inventory.items():
        if path and inv_path.lower() in path.lower():
            lesson_str = inv_data.get("lesson", "")
            lessons = []

            # Parse lesson string (e.g., "Lesson 1", "Lessons 3-4", "All Lessons")
            if "All" in lesson_str:
                lessons = list(range(1, 13))
                confidence = 0.85
            elif "-" in lesson_str:
                match = re.search(r'(\d+)\s*-\s*(\d+)', lesson_str)
                if match:
                    lessons = list(range(int(match.group(1)), int(match.group(2)) + 1))
                    confidence = 0.95
            else:
                match = re.search(r'(\d+)', lesson_str)
                if match:
                    lessons = [int(match.group(1))]
                    confidence = 0.95

            if lessons:
                return {
                    "signal": "metadata_crossref",
                    "weight": SIGNAL_WEIGHTS["metadata_crossref"],
                    "lessons": lessons,
                    "confidence": confidence,
                    "method": "source_inventory"
                }

    return {
        "signal": "metadata_crossref",
        "weight": SIGNAL_WEIGHTS["metadata_crossref"],
        "lessons": None,
        "confidence": 0,
        "method": "not_found"
    }


def signal_semantic_align(item: Dict) -> Dict:
    """
    Signal 3: Match AI-generated tags to lesson keywords.
    Weight: 0.8
    """
    kb_tags = item.get("kb_tags", [])
    if not kb_tags:
        return {
            "signal": "semantic_align",
            "weight": SIGNAL_WEIGHTS["semantic_align"],
            "lessons": None,
            "confidence": 0,
            "method": "no_tags"
        }

    # Score each lesson based on tag overlap
    lesson_scores = {}
    tags_lower = [t.lower().replace("-", " ").replace("_", " ") for t in kb_tags]

    for lesson, keywords in LESSON_KEYWORDS.items():
        score = 0
        keywords_lower = [k.lower() for k in keywords]

        for tag in tags_lower:
            for keyword in keywords_lower:
                if tag in keyword or keyword in tag:
                    score += 1
                elif any(word in tag for word in keyword.split()):
                    score += 0.5

        if score > 0:
            lesson_scores[lesson] = score

    if lesson_scores:
        max_score = max(lesson_scores.values())
        best_lessons = [l for l, s in lesson_scores.items() if s == max_score]
        confidence = min(max_score / 3, 1.0)  # Normalize to 0-1

        return {
            "signal": "semantic_align",
            "weight": SIGNAL_WEIGHTS["semantic_align"],
            "lessons": best_lessons,
            "confidence": confidence,
            "method": "tag_matching",
            "scores": lesson_scores
        }

    return {
        "signal": "semantic_align",
        "weight": SIGNAL_WEIGHTS["semantic_align"],
        "lessons": None,
        "confidence": 0,
        "method": "no_match"
    }


def signal_keyword_match(item: Dict) -> Dict:
    """
    Signal 4: Compare content themes to lesson objectives.
    Weight: 0.7
    """
    # Get text content from various fields
    text_content = ""
    text_content += item.get("visual_description", "") + " "
    text_content += item.get("educational_context", "") + " "
    text_content += item.get("content_preview", "") + " "
    text_content += item.get("transcript_preview", "") + " "

    if not text_content.strip():
        return {
            "signal": "keyword_match",
            "weight": SIGNAL_WEIGHTS["keyword_match"],
            "lessons": None,
            "confidence": 0,
            "method": "no_content"
        }

    text_lower = text_content.lower()

    # Score each lesson based on keyword presence
    lesson_scores = {}
    for lesson, keywords in LESSON_KEYWORDS.items():
        score = 0
        for keyword in keywords:
            if keyword.lower() in text_lower:
                score += 1

        if score > 0:
            lesson_scores[lesson] = score

    if lesson_scores:
        max_score = max(lesson_scores.values())
        best_lessons = [l for l, s in lesson_scores.items() if s == max_score]
        confidence = min(max_score / 4, 1.0)  # Normalize

        return {
            "signal": "keyword_match",
            "weight": SIGNAL_WEIGHTS["keyword_match"],
            "lessons": best_lessons,
            "confidence": confidence,
            "method": "content_analysis",
            "scores": lesson_scores
        }

    return {
        "signal": "keyword_match",
        "weight": SIGNAL_WEIGHTS["keyword_match"],
        "lessons": None,
        "confidence": 0,
        "method": "no_match"
    }


def signal_volume_check(item: Dict, volume_stats: Dict) -> Dict:
    """
    Signal 5: Check statistical patterns (images per lesson).
    Weight: 0.5
    """
    content_type = item.get("content_type", "")
    lesson_info = item.get("lesson_info", {})

    if not lesson_info or not content_type:
        return {
            "signal": "volume_check",
            "weight": SIGNAL_WEIGHTS["volume_check"],
            "lessons": None,
            "confidence": 0,
            "method": "insufficient_data"
        }

    lessons = lesson_info.get("lessons", [lesson_info.get("lesson")])
    if not lessons or lessons[0] is None:
        return {
            "signal": "volume_check",
            "weight": SIGNAL_WEIGHTS["volume_check"],
            "lessons": None,
            "confidence": 0,
            "method": "no_lesson"
        }

    # Check if volume is within expected range
    expected = EXPECTED_VOLUMES.get(content_type, {"min": 5, "max": 50})
    current_count = volume_stats.get(content_type, {}).get(str(lessons[0]), 0)

    if expected["min"] <= current_count <= expected["max"]:
        confidence = 0.8
    elif current_count > 0:
        confidence = 0.5
    else:
        confidence = 0.3

    return {
        "signal": "volume_check",
        "weight": SIGNAL_WEIGHTS["volume_check"],
        "lessons": lessons,
        "confidence": confidence,
        "method": "statistical_check",
        "current_count": current_count,
        "expected_range": expected
    }


def calculate_consensus(signals: List[Dict]) -> Dict:
    """
    Calculate weighted consensus from all signals.
    Returns final lesson assignment with confidence.

    Authoritative signals (path_pattern, video_parent) get boosted weight
    when they have high confidence, as they represent structural/manual mappings.
    """
    # Authoritative signals that should dominate when confident
    AUTHORITATIVE_SIGNALS = ["path_pattern", "video_parent"]
    AUTHORITY_BOOST = 1.5  # Boost factor for authoritative signals

    # Collect all lesson votes with weights
    lesson_votes = defaultdict(float)
    total_weight = 0
    contributing_signals = []
    has_authoritative_signal = False

    for signal in signals:
        if signal.get("lessons") and signal.get("confidence", 0) > 0:
            base_weight = signal["weight"] * signal["confidence"]

            # Boost authoritative signals when they have high confidence
            if signal["signal"] in AUTHORITATIVE_SIGNALS and signal["confidence"] >= 0.9:
                weight = base_weight * AUTHORITY_BOOST
                has_authoritative_signal = True
            else:
                weight = base_weight

            total_weight += weight
            contributing_signals.append(signal["signal"])

            for lesson in signal["lessons"]:
                if lesson is not None:
                    lesson_votes[lesson] += weight

    if not lesson_votes:
        return {
            "assigned_lessons": [],
            "consensus_confidence": 0,
            "contributing_signals": [],
            "status": "UNMAPPED"
        }

    # Find lessons with highest vote
    max_vote = max(lesson_votes.values())
    assigned_lessons = [l for l, v in lesson_votes.items() if v == max_vote]

    # Calculate confidence (0-100%)
    consensus_confidence = (max_vote / total_weight * 100) if total_weight > 0 else 0

    # Boost confidence when authoritative signal agrees with consensus
    if has_authoritative_signal:
        consensus_confidence = min(100, consensus_confidence * 1.1)

    # Determine status
    if consensus_confidence >= 90:
        status = "HIGH_CONFIDENCE"
    elif consensus_confidence >= 70:
        status = "MEDIUM_CONFIDENCE"
    elif consensus_confidence >= 50:
        status = "LOW_CONFIDENCE"
    else:
        status = "UNCERTAIN"

    return {
        "assigned_lessons": sorted(assigned_lessons),
        "consensus_confidence": round(consensus_confidence, 1),
        "contributing_signals": contributing_signals,
        "status": status,
        "vote_breakdown": dict(lesson_votes)
    }


def map_content(unified_content: Dict) -> Dict:
    """Apply all signals to all content and calculate mappings."""
    mappings = {
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "total_items": 0,
            "mapped_items": 0,
            "unmapped_items": 0,
            "high_confidence": 0,
            "medium_confidence": 0,
            "low_confidence": 0
        },
        "by_lesson": {str(i): [] for i in range(1, 13)},
        "items": []
    }

    source_inventory = unified_content.get("reference_data", {}).get("source_inventory", {})

    # Calculate volume statistics
    volume_stats = defaultdict(lambda: defaultdict(int))

    # First pass: count items per lesson per content type
    for content_type in ["markdown", "images", "videos"]:
        for item in unified_content.get("content", {}).get(content_type, []):
            lesson_info = item.get("lesson_info") or {}
            item_content_type = item.get("content_type", "unknown")
            lessons = lesson_info.get("lessons") or [lesson_info.get("lesson")]
            if lessons and lessons[0] is not None:
                for lesson in lessons:
                    volume_stats[item_content_type][str(lesson)] += 1

    # Second pass: apply all signals
    for content_type in ["markdown", "images", "videos"]:
        for item in unified_content.get("content", {}).get(content_type, []):
            signals = [
                signal_path_pattern(item),
                signal_video_parent(item),  # New: video keyframe inheritance
                signal_metadata_crossref(item, source_inventory),
                signal_semantic_align(item),
                signal_keyword_match(item),
                signal_volume_check(item, volume_stats)
            ]

            consensus = calculate_consensus(signals)

            mapping_result = {
                "id": item.get("id"),
                "type": item.get("type"),
                "content_type": item.get("content_type"),
                "path": item.get("path") or item.get("source") or item.get("video_name"),
                "signals": signals,
                "consensus": consensus
            }

            mappings["items"].append(mapping_result)
            mappings["summary"]["total_items"] += 1

            # Update summary stats
            if consensus["status"] == "HIGH_CONFIDENCE":
                mappings["summary"]["high_confidence"] += 1
                mappings["summary"]["mapped_items"] += 1
            elif consensus["status"] == "MEDIUM_CONFIDENCE":
                mappings["summary"]["medium_confidence"] += 1
                mappings["summary"]["mapped_items"] += 1
            elif consensus["status"] == "LOW_CONFIDENCE":
                mappings["summary"]["low_confidence"] += 1
                mappings["summary"]["mapped_items"] += 1
            else:
                mappings["summary"]["unmapped_items"] += 1

            # Add to by_lesson index
            for lesson in consensus.get("assigned_lessons", []):
                mappings["by_lesson"][str(lesson)].append(item.get("id"))

    return mappings


def main():
    """Main function to apply validation signals and create mappings."""
    print("=" * 60)
    print("VALIDATION MAPPER - Applying 5 Validation Signals")
    print("=" * 60)

    # Load unified content
    input_path = BASE_DIR / "Term 2 - Unified Content.json"

    if not input_path.exists():
        print(f"Error: Unified content not found at {input_path}")
        print("Please run validation_parser.py first.")
        return None

    print(f"\nLoading: {input_path}")
    with open(input_path, 'r', encoding='utf-8') as f:
        unified_content = json.load(f)

    print(f"Loaded {unified_content['summary']['total_items']} items")

    # Apply signals and calculate mappings
    print("\nApplying validation signals...")
    print("  [1] Path Pattern (weight: 1.0)")
    print("  [2] Metadata Cross-Ref (weight: 0.95)")
    print("  [3] Semantic Alignment (weight: 0.8)")
    print("  [4] Keyword Matching (weight: 0.7)")
    print("  [5] Volume Consistency (weight: 0.5)")

    mappings = map_content(unified_content)

    # Write output
    output_path = BASE_DIR / "Term 2 - Lesson Mappings.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(mappings, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 60)
    print("MAPPING COMPLETE")
    print("=" * 60)
    print(f"\nOutput: {output_path}")
    print(f"\nSummary:")
    print(f"  - Total items: {mappings['summary']['total_items']}")
    print(f"  - Mapped items: {mappings['summary']['mapped_items']}")
    print(f"  - Unmapped items: {mappings['summary']['unmapped_items']}")
    print(f"\nConfidence Distribution:")
    print(f"  - High (>=90%): {mappings['summary']['high_confidence']}")
    print(f"  - Medium (70-90%): {mappings['summary']['medium_confidence']}")
    print(f"  - Low (50-70%): {mappings['summary']['low_confidence']}")

    # Show per-lesson counts
    print(f"\nItems per Lesson:")
    for lesson in range(1, 13):
        count = len(mappings["by_lesson"][str(lesson)])
        print(f"  Lesson {lesson:2d}: {count:3d} items")

    return mappings


if __name__ == "__main__":
    main()
