"""
Validation Parser - Script 1 of 4
Purpose: Parse all content into unified structure for validation

Input Files:
- Converted/*.md (60 markdown files)
- MASTER_all_results.json (443 image descriptions)
- video_transcripts.json (3 video transcripts)
- Term 2 - Lesson Based Structure.csv
- Term 2 - Source Inventory.csv

Output: Term 2 - Unified Content.json
"""

import json
import os
import re
import csv
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Base directory
BASE_DIR = Path(r"D:\Term 3 QA\Teacher Resources - Term 2")
CONVERTED_DIR = BASE_DIR / "Converted"
EXTRACTED_MEDIA_DIR = BASE_DIR / "Extracted Media"

# Lesson keyword dictionary for semantic matching
LESSON_KEYWORDS = {
    1: ["design brief", "problem statement", "audience", "constraints", "UAE heritage", "sustainability", "innovation"],
    2: ["persona", "empathy map", "UX", "player needs", "motivations", "frustrations", "bias"],
    3: ["primary research", "secondary research", "AI research", "reliability", "bias", "accuracy", "insights"],
    4: ["design specification", "team roles", "constraints", "success criteria", "research insights", "collaboration"],
    5: ["brainstorming", "concept generation", "storyboard", "micro-prototype", "core mechanic", "peer feedback"],
    6: ["prototype", "core mechanic", "debugging", "testing", "iteration", "functionality"],
    7: ["gameplay expansion", "immersion", "visuals", "sound", "dialogue", "player pathways", "UX"],
    8: ["peer testing", "WWW/EBI", "feedback analysis", "theme mapping", "usability", "prioritisation"],
    9: ["iteration", "refinement", "feedback implementation", "impact vs effort", "before/after", "player experience"],
    10: ["team roles", "project manager", "milestones", "timeline", "risk management", "accountability", "collaboration"],
    11: ["documentation", "portfolio", "evidence", "curation", "captions", "reflection", "design story"],
    12: ["reflection", "evaluation", "SMART goals", "Term 3", "progress", "strengths", "challenges"]
}

# Week to lesson mapping
WEEK_LESSON_MAP = {
    1: [1, 2],
    2: [3, 4],
    3: [5, 6],
    4: [7, 8],
    5: [9, 10],
    6: [11, 12]
}

# Video week assignments
VIDEO_WEEK_MAP = {
    "Designing_Restoring_Light": {"week": 2, "lessons": [3, 4]},
    "Light_of_the_Mosque": {"week": 6, "lessons": [11, 12]},
    "The_Unseen_Hero": {"week": 6, "lessons": [11, 12]}
}


def extract_lesson_from_path(path: str) -> Optional[Dict]:
    """
    Signal 1: Extract lesson ID from file path using regex patterns.
    Returns lesson info if found.
    """
    path_lower = path.lower()

    # Pattern 1: Explicit "Lesson X" in filename or path
    match = re.search(r'lesson[_\s\-]*(\d{1,2})', path_lower)
    if match:
        lesson_num = int(match.group(1))
        if 1 <= lesson_num <= 12:
            return {"lesson": lesson_num, "confidence": 1.0, "method": "explicit_lesson"}

    # Pattern 2: "Lessons X-Y" format (exemplar work)
    match = re.search(r'lessons?\s*(\d{1,2})\s*[-–]\s*(\d{1,2})', path_lower)
    if match:
        start = int(match.group(1))
        end = int(match.group(2))
        if 1 <= start <= 12 and 1 <= end <= 12:
            return {"lessons": list(range(start, end + 1)), "confidence": 0.95, "method": "lesson_range"}

    # Pattern 3: Week folder structure
    match = re.search(r'week[_\s\-]*(\d)', path_lower)
    if match:
        week = int(match.group(1))
        if week in WEEK_LESSON_MAP:
            return {"lessons": WEEK_LESSON_MAP[week], "week": week, "confidence": 0.9, "method": "week_folder"}

    # Pattern 4: Portfolio / All Lessons indicators
    if any(term in path_lower for term in ["portfolio", "all weeks", "all lessons", "activities & portfolio"]):
        return {"lessons": list(range(1, 13)), "confidence": 0.85, "method": "all_lessons"}

    # Pattern 5: Exemplar work with week
    if "exemplar" in path_lower:
        match = re.search(r'week[_\s\-]*(\d)', path_lower)
        if match:
            week = int(match.group(1))
            if week in WEEK_LESSON_MAP:
                return {"lessons": WEEK_LESSON_MAP[week], "week": week, "confidence": 0.9, "method": "exemplar_week"}

    return None


def parse_markdown_files() -> List[Dict]:
    """Parse all markdown files from Converted folder."""
    md_files = []

    for md_path in CONVERTED_DIR.rglob("*.md"):
        relative_path = str(md_path.relative_to(BASE_DIR))

        try:
            with open(md_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            content = f"Error reading file: {e}"

        # Extract lesson info from path
        lesson_info = extract_lesson_from_path(relative_path)

        # Determine content type
        content_type = "unknown"
        if "Teachers Slides" in relative_path:
            content_type = "teachers_slides"
        elif "Students Slides" in relative_path:
            content_type = "students_slides"
        elif "Lesson Plans" in relative_path or "Lesson Plan" in relative_path:
            content_type = "lesson_plan"
        elif "Exemplar" in relative_path:
            content_type = "exemplar_work"
        elif "Portfolio" in relative_path:
            content_type = "portfolio"
        elif "Assessment" in relative_path:
            content_type = "assessment_guide"
        elif "Design Brief" in relative_path:
            content_type = "design_brief"
        elif "Professional Development" in relative_path:
            content_type = "professional_development"
        elif "Curriculum" in relative_path:
            content_type = "curriculum_doc"

        # Count slides (markdown headers)
        slide_count = len(re.findall(r'^## Slide \d+', content, re.MULTILINE))

        md_files.append({
            "id": f"md_{len(md_files) + 1:03d}",
            "type": "markdown",
            "content_type": content_type,
            "path": relative_path,
            "filename": md_path.name,
            "lesson_info": lesson_info,
            "slide_count": slide_count if slide_count > 0 else None,
            "char_count": len(content),
            "content_preview": content[:500] if len(content) > 500 else content
        })

    return md_files


def parse_image_descriptions() -> List[Dict]:
    """Parse image descriptions from MASTER_all_results.json."""
    images = []
    master_path = EXTRACTED_MEDIA_DIR / "claude_descriptions" / "results" / "MASTER_all_results.json"

    if not master_path.exists():
        print(f"Warning: MASTER_all_results.json not found at {master_path}")
        return images

    try:
        with open(master_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading MASTER_all_results.json: {e}")
        return images

    # Parse image descriptions
    for desc_batch in data.get("image_descriptions", []):
        batch_name = desc_batch.get("batch", "unknown")
        source = desc_batch.get("source", "")

        # Extract lesson from batch name or source
        lesson_info = extract_lesson_from_path(batch_name) or extract_lesson_from_path(source)

        for result in desc_batch.get("results", []):
            images.append({
                "id": f"img_{len(images) + 1:04d}",
                "type": "image",
                "batch": batch_name,
                "source": source,
                "filename": result.get("filename", ""),
                "content_type": result.get("content_type", ""),
                "visual_description": result.get("visual_description", ""),
                "educational_context": result.get("educational_context", ""),
                "kb_tags": result.get("kb_tags", []),
                "lesson_info": lesson_info
            })

    return images


def parse_video_transcripts() -> List[Dict]:
    """Parse video transcripts from video_transcripts.json."""
    videos = []
    transcripts_path = EXTRACTED_MEDIA_DIR / "metadata" / "video_transcripts.json"

    if not transcripts_path.exists():
        print(f"Warning: video_transcripts.json not found at {transcripts_path}")
        return videos

    try:
        with open(transcripts_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error reading video_transcripts.json: {e}")
        return videos

    for video_name, video_data in data.items():
        # Get lesson mapping from VIDEO_WEEK_MAP
        video_info = VIDEO_WEEK_MAP.get(video_name, {"week": None, "lessons": []})

        text = video_data.get("text", "")
        segments = video_data.get("segments", [])

        videos.append({
            "id": f"vid_{len(videos) + 1:03d}",
            "type": "video_transcript",
            "video_name": video_name,
            "week": video_info["week"],
            "lesson_info": {
                "lessons": video_info["lessons"],
                "confidence": 1.0,
                "method": "manual_assignment"
            },
            "transcript_length": len(text),
            "segment_count": len(segments),
            "transcript_preview": text[:500] if len(text) > 500 else text,
            "language": video_data.get("language", "en")
        })

    return videos


def parse_source_inventory() -> Dict:
    """Parse Term 2 - Source Inventory.csv for authoritative mappings."""
    inventory = {}
    inventory_path = BASE_DIR / "Term 2 - Source Inventory.csv"

    if not inventory_path.exists():
        print(f"Warning: Source Inventory not found at {inventory_path}")
        return inventory

    try:
        with open(inventory_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                relative_path = row.get("Relative Path", "").strip('"')
                week = row.get("Associated Week", "")
                lesson = row.get("Associated Lesson", "")

                inventory[relative_path] = {
                    "week": week,
                    "lesson": lesson,
                    "file_type": row.get("File Type Category", ""),
                    "parent_folder": row.get("Parent Folder", "")
                }
    except Exception as e:
        print(f"Error reading Source Inventory: {e}")

    return inventory


def parse_lesson_metadata() -> Dict:
    """Parse Term 2 - Lesson Based Structure.csv for lesson metadata."""
    lessons = {}
    metadata_path = BASE_DIR / "Term 2 - Lesson Based Structure.csv"

    if not metadata_path.exists():
        print(f"Warning: Lesson Based Structure not found at {metadata_path}")
        return lessons

    try:
        with open(metadata_path, 'r', encoding='utf-8') as f:
            content = f.read()
            # Parse lesson metadata from CSV (complex JSON embedded)
            for lesson_num in range(1, 13):
                pattern = rf'"lesson_id":\s*{lesson_num},'
                if re.search(pattern, content):
                    lessons[lesson_num] = {"exists": True}
    except Exception as e:
        print(f"Error reading Lesson Based Structure: {e}")

    return lessons


def main():
    """Main function to parse all content and create unified structure."""
    print("=" * 60)
    print("VALIDATION PARSER - Parsing All Content")
    print("=" * 60)

    # Parse all content types
    print("\n[1/5] Parsing markdown files...")
    markdown_files = parse_markdown_files()
    print(f"      Found {len(markdown_files)} markdown files")

    print("\n[2/5] Parsing image descriptions...")
    images = parse_image_descriptions()
    print(f"      Found {len(images)} image descriptions")

    print("\n[3/5] Parsing video transcripts...")
    videos = parse_video_transcripts()
    print(f"      Found {len(videos)} video transcripts")

    print("\n[4/5] Parsing source inventory...")
    source_inventory = parse_source_inventory()
    print(f"      Found {len(source_inventory)} inventory entries")

    print("\n[5/5] Parsing lesson metadata...")
    lesson_metadata = parse_lesson_metadata()
    print(f"      Found {len(lesson_metadata)} lessons")

    # Create unified content structure
    unified_content = {
        "generated_at": datetime.now().isoformat(),
        "summary": {
            "total_items": len(markdown_files) + len(images) + len(videos),
            "markdown_files": len(markdown_files),
            "images": len(images),
            "video_transcripts": len(videos),
            "source_inventory_entries": len(source_inventory)
        },
        "content": {
            "markdown": markdown_files,
            "images": images,
            "videos": videos
        },
        "reference_data": {
            "source_inventory": source_inventory,
            "lesson_metadata": lesson_metadata,
            "lesson_keywords": LESSON_KEYWORDS,
            "week_lesson_map": WEEK_LESSON_MAP,
            "video_week_map": VIDEO_WEEK_MAP
        }
    }

    # Write output
    output_path = BASE_DIR / "Term 2 - Unified Content.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(unified_content, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 60)
    print("PARSING COMPLETE")
    print("=" * 60)
    print(f"\nOutput: {output_path}")
    print(f"\nSummary:")
    print(f"  - Markdown files: {len(markdown_files)}")
    print(f"  - Images: {len(images)}")
    print(f"  - Video transcripts: {len(videos)}")
    print(f"  - Total items: {unified_content['summary']['total_items']}")

    return unified_content


if __name__ == "__main__":
    main()
