"""
Merge slide number and path metadata into MASTER_all_results.json
"""

import json
from pathlib import Path

# Paths
EXTRACTION_META = Path(r"D:\Term 3 QA\Teacher Resources - Term 2\Extracted Media\metadata\extraction_metadata.json")
MASTER_RESULTS = Path(r"D:\Term 3 QA\Teacher Resources - Term 2\Extracted Media\claude_descriptions\results\MASTER_all_results.json")

def normalize_path(path):
    """Normalize path for matching - remove trailing spaces, underscores before extension"""
    import re
    # Remove trailing spaces before extension
    path = re.sub(r'\s+\.pptx$', '.pptx', path, flags=re.IGNORECASE)
    # Remove underscores before extension
    path = re.sub(r'_\.pptx$', '.pptx', path, flags=re.IGNORECASE)
    return path

def build_image_lookup(extraction_data):
    """
    Build a lookup from (pptx_relative_path, image_index) -> image metadata
    Also build lookup by image filename
    """
    lookup_by_path = {}
    lookup_by_filename = {}

    for pptx_file in extraction_data.get("pptx_files", []):
        relative_path = pptx_file.get("relative_path", "")
        source_path = pptx_file.get("source_path", "")

        # Create normalized version of path for matching
        normalized_path = normalize_path(relative_path)

        for img in pptx_file.get("images", []):
            index = img.get("index")
            original_name = img.get("original_name", "")
            image_path = img.get("image_path", "")
            slide_numbers = img.get("slide_numbers", [])
            primary_slide = img.get("primary_slide")

            metadata = {
                "source_pptx": source_path,
                "relative_pptx": relative_path,
                "extracted_image_path": image_path,
                "original_media_name": original_name,
                "slide_numbers": slide_numbers,
                "primary_slide": primary_slide
            }

            # Store by original relative path and index
            key = (relative_path, index)
            lookup_by_path[key] = metadata

            # Also store by normalized path
            norm_key = (normalized_path, index)
            if norm_key != key:
                lookup_by_path[norm_key] = metadata

            # Also store by extracted image filename
            if image_path:
                filename = Path(image_path).name
                # Key by folder + filename for uniqueness
                folder = Path(image_path).parent.name
                lookup_by_filename[(folder, filename)] = metadata

    return lookup_by_path, lookup_by_filename

def match_batch_to_pptx(batch_name, source_field):
    """
    Try to match a batch name to a PPTX relative path
    Returns a list of possible PPTX paths (some batches span multiple files)
    """
    import re

    # Direct source field mapping
    if source_field:
        return [source_field]

    # Try to infer from batch name
    batch_lower = batch_name.lower()

    # Skip video batches - these are keyframes, not from PPTX
    if 'video' in batch_lower:
        return []

    # Explicit mappings
    mappings = {
        "exemplar_week_1_lessons_1-2": ["Assessment Guides\\Exemplar work\\Week 1\\Exampler Work - Lesson 1-2.pptx"],
        "exemplar_week_2_lessons_3-4": ["Assessment Guides\\Exemplar work\\Week 2\\Exampler Work - Lesson 3-4.pptx"],
        "exemplar_weeks_3-6": [
            "Assessment Guides\\Exemplar work\\Week 3\\Exampler Work - Lesson 5-6_.pptx",
            "Assessment Guides\\Exemplar work\\Week 4\\Exampler Work - Lesson 7-8.pptx",
            "Assessment Guides\\Exemplar work\\Week 5\\Exampler Work - Lesson 9-10.pptx",
            "Assessment Guides\\Exemplar work\\Week 6\\Exampler Work - Lesson 11-12_.pptx",
        ],
        "student_portfolio": ["Student Portfolio\\Activities & Portfolio Deck.pptx"],
        "portfolio": ["Student Portfolio\\Activities & Portfolio Deck.pptx"],
    }

    for key, value in mappings.items():
        if key in batch_lower:
            return value

    # Try lesson number extraction for curriculum batches
    # Pattern: Curriculum_Week5_Lesson10 -> Week 5, Lesson 10
    lesson_match = re.search(r'week(\d+)[_\s]*lesson[_\s]*(\d+)', batch_lower)
    if lesson_match:
        week_num = lesson_match.group(1)
        lesson_num = lesson_match.group(2)
        # Return both Teachers and Students slides paths
        return [
            f"Curriculum Content\\Week {week_num}\\Teachers Slides\\Lesson {lesson_num}.pptx",
            f"Curriculum Content\\Week {week_num}\\Teachers Slides\\Lesson {lesson_num} .pptx",  # Some have trailing space
            f"Curriculum Content\\Week {week_num}\\Teachers Slides\\Lesson {lesson_num}_.pptx",  # Some have underscore
            f"Curriculum Content\\Week {week_num}\\Students Slides\\Lesson {lesson_num}.pptx",
        ]

    return []

def main():
    print("Loading extraction metadata...")
    with open(EXTRACTION_META, 'r', encoding='utf-8') as f:
        extraction_data = json.load(f)

    print("Loading MASTER results...")
    with open(MASTER_RESULTS, 'r', encoding='utf-8') as f:
        master_data = json.load(f)

    # Build lookup tables
    lookup_by_path, lookup_by_filename = build_image_lookup(extraction_data)
    print(f"Built lookup with {len(lookup_by_path)} images by path, {len(lookup_by_filename)} by filename")

    # Track statistics
    matched = 0
    unmatched = 0

    # Track video keyframes separately
    video_keyframes = 0

    # Process image descriptions in MASTER
    for batch in master_data.get("image_descriptions", []):
        batch_name = batch.get("batch", "")
        source = batch.get("source", "")

        # Try to find matching PPTX paths
        pptx_paths = match_batch_to_pptx(batch_name, source)

        # Check if this is a video batch
        is_video = 'video' in batch_name.lower()

        for result in batch.get("results", []):
            index = result.get("index")
            # Handle index as string or int
            if isinstance(index, str):
                try:
                    index = int(index)
                except ValueError:
                    pass
            filename = result.get("filename", "")

            # Video keyframes don't have slides
            if is_video:
                result["source_pptx"] = None
                result["extracted_image_path"] = None
                result["slide_numbers"] = []
                result["primary_slide"] = None
                result["is_video_keyframe"] = True
                video_keyframes += 1
                continue

            # Try multiple matching strategies
            metadata = None

            # Strategy 1: Match by source paths and index (try both original and normalized)
            for pptx_path in pptx_paths:
                key = (pptx_path, index)
                if key in lookup_by_path:
                    metadata = lookup_by_path[key]
                    break
                # Also try normalized version
                norm_key = (normalize_path(pptx_path), index)
                if norm_key in lookup_by_path:
                    metadata = lookup_by_path[norm_key]
                    break

            # Strategy 2: Match by filename if we have one
            if not metadata and filename:
                # Try to find by filename pattern
                for (folder, fname), meta in lookup_by_filename.items():
                    if fname == filename:
                        metadata = meta
                        break

            # Strategy 3: For images with source, try direct lookup
            if not metadata and source:
                key = (source, index)
                if key in lookup_by_path:
                    metadata = lookup_by_path[key]

            # Add metadata if found
            if metadata:
                result["source_pptx"] = metadata["source_pptx"]
                result["extracted_image_path"] = metadata["extracted_image_path"]
                result["slide_numbers"] = metadata["slide_numbers"]
                result["primary_slide"] = metadata["primary_slide"]
                matched += 1
            else:
                # Mark as unmatched but add empty fields
                result["source_pptx"] = source if source else None
                result["extracted_image_path"] = None
                result["slide_numbers"] = []
                result["primary_slide"] = None
                unmatched += 1

    print(f"\nMatching complete:")
    print(f"  PPTX images matched: {matched}")
    print(f"  PPTX images unmatched: {unmatched}")
    print(f"  Video keyframes (no slides): {video_keyframes}")

    # Save updated MASTER
    print("\nSaving updated MASTER_all_results.json...")
    with open(MASTER_RESULTS, 'w', encoding='utf-8') as f:
        json.dump(master_data, f, indent=2, ensure_ascii=False)

    print("Done!")

if __name__ == "__main__":
    main()
