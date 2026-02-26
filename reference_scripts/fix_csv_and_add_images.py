"""
Fix Term 2 CSV:
1. Move activities data from Testing Scores to Description of Activities
2. Add image metadata to the lesson metadata JSON
"""

import csv
import json
from pathlib import Path

CSV_PATH = Path(r"D:\Term 3 QA\Teacher Resources - Term 2\Term 2 - Lesson Based Structure.csv")
MASTER_PATH = Path(r"D:\Term 3 QA\Teacher Resources - Term 2\Extracted Media\claude_descriptions\results\MASTER_all_results.json")
OUTPUT_PATH = Path(r"D:\Term 3 QA\Teacher Resources - Term 2\Term 2 - Lesson Based Structure (Fixed).csv")

def get_lesson_from_batch(batch_name):
    """Extract lesson number from batch name"""
    import re
    match = re.search(r'lesson[_\s]*(\d+)', batch_name.lower())
    if match:
        return int(match.group(1))
    return None

def build_image_data_by_lesson(master_data):
    """Build image data organized by lesson number"""
    images_by_lesson = {i: [] for i in range(1, 13)}

    for batch in master_data.get("image_descriptions", []):
        batch_name = batch.get("batch", "")

        # Skip video keyframes
        if "video" in batch_name.lower():
            continue

        lesson_num = get_lesson_from_batch(batch_name)

        for result in batch.get("results", []):
            image_entry = {
                "image_id": f"img_{batch_name}_{result.get('index', '')}",
                "content_type": result.get("content_type", ""),
                "visual_description": result.get("visual_description", ""),
                "educational_context": result.get("educational_context", ""),
                "source_pptx": result.get("source_pptx", ""),
                "slide_numbers": result.get("slide_numbers", []),
                "primary_slide": result.get("primary_slide"),
                "kb_tags": result.get("kb_tags", [])
            }

            if lesson_num:
                images_by_lesson[lesson_num].append(image_entry)

            # Handle exemplar work that spans multiple lessons
            if "exemplar_week_1" in batch_name.lower():
                for l in [1, 2]:
                    if l != lesson_num:
                        images_by_lesson[l].append(image_entry)
            elif "exemplar_week_2" in batch_name.lower():
                for l in [3, 4]:
                    if l != lesson_num:
                        images_by_lesson[l].append(image_entry)
            elif "exemplar_weeks_3-6" in batch_name.lower():
                for l in range(5, 13):
                    images_by_lesson[l].append(image_entry)
            elif "portfolio" in batch_name.lower():
                # Portfolio spans all lessons
                for l in range(1, 13):
                    if image_entry not in images_by_lesson[l]:
                        images_by_lesson[l].append(image_entry)

    return images_by_lesson

def get_video_data_by_lesson(master_data):
    """Build video data organized by lesson number - FULL DATA for agent KB"""
    videos_by_lesson = {i: [] for i in range(1, 13)}

    # Video to lesson mapping (based on curriculum week structure)
    video_lessons = {
        "Designing_Restoring_Light": [3, 4],  # Week 2
        "Light_of_the_Mosque": [11, 12],      # Week 6
        "The_Unseen_Hero": [11, 12]           # Week 6
    }

    transcripts = master_data.get("video_transcripts", {})

    for video_name, transcript_data in transcripts.items():
        lessons = video_lessons.get(video_name, [])
        full_transcript = transcript_data.get("text", "")

        # Full video entry matching Term 1 format
        video_entry = {
            "video_id": video_name,
            "title": video_name.replace("_", " "),
            "url": "",  # To be filled if available
            "order": 1,
            "duration": "estimated 5-10 min",
            "full_transcript": full_transcript,
            "summary": f"Exemplar video demonstrating {video_name.replace('_', ' ')} game design concepts and implementation.",
            "key_learning_points": [
                f"Understanding {video_name.replace('_', ' ')} design approach",
                "Practical game development workflow",
                "Design iteration and refinement process"
            ],
            "keywords": video_name.lower().split("_"),
            "related_tools": ["Endstar"],
            "difficulty": "intermediate",
            "language": transcript_data.get("language", "en")
        }

        for lesson in lessons:
            videos_by_lesson[lesson].append(video_entry)

    return videos_by_lesson

def extract_lesson_number(lesson_title):
    """Extract lesson number from title"""
    import re
    match = re.search(r'Lesson\s*(\d+)', lesson_title)
    if match:
        return int(match.group(1))
    return None

def main():
    print("Loading MASTER data...")
    with open(MASTER_PATH, 'r', encoding='utf-8') as f:
        master_data = json.load(f)

    print("Building image data by lesson...")
    images_by_lesson = build_image_data_by_lesson(master_data)

    print("Building video data by lesson...")
    videos_by_lesson = get_video_data_by_lesson(master_data)

    for lesson, images in images_by_lesson.items():
        print(f"  Lesson {lesson}: {len(images)} images")

    print("\nReading CSV...")
    with open(CSV_PATH, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        headers = next(reader)
        rows = list(reader)

    print(f"Found {len(rows)} data rows")

    # Column indices
    COL_LESSONS = 0
    COL_URL = 1
    COL_METADATA = 2
    COL_VIDEO = 3
    COL_RESOURCES = 4
    COL_ACTIVITIES = 5
    COL_TESTING = 6
    COL_COMMENTS = 7
    COL_PROMPTS = 8

    fixed_rows = []

    for row in rows:
        # Ensure row has enough columns
        while len(row) < 9:
            row.append("")

        lesson_title = row[COL_LESSONS]
        lesson_num = extract_lesson_number(lesson_title)

        # Fix 1: Move activities from Testing Scores to Description of Activities
        if not row[COL_ACTIVITIES].strip() and row[COL_TESTING].strip():
            if "Activity" in row[COL_TESTING] or "Portfolio" in row[COL_TESTING]:
                row[COL_ACTIVITIES] = row[COL_TESTING]
                row[COL_TESTING] = ""
                print(f"  Fixed column shift for {lesson_title[:40]}...")

        # Fix 2: Add images and videos to metadata (FULL EMBEDDING for agent KB)
        if lesson_num and row[COL_METADATA].strip():
            try:
                metadata = json.loads(row[COL_METADATA])

                # Add ALL images with full data (for agent KB)
                lesson_images = images_by_lesson.get(lesson_num, [])
                if lesson_images:
                    metadata["images"] = lesson_images
                    print(f"    Added {len(lesson_images)} images to Lesson {lesson_num}")

                # Add ALL videos with full data
                lesson_videos = videos_by_lesson.get(lesson_num, [])
                if lesson_videos:
                    metadata["videos"] = lesson_videos
                    print(f"    Added {len(lesson_videos)} videos to Lesson {lesson_num}")

                row[COL_METADATA] = json.dumps(metadata, indent=2, ensure_ascii=False)

            except json.JSONDecodeError as e:
                print(f"  Warning: Could not parse metadata for {lesson_title}: {e}")

        fixed_rows.append(row)

    print(f"\nWriting fixed CSV to {OUTPUT_PATH}...")
    with open(OUTPUT_PATH, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(fixed_rows)

    print("Done!")

if __name__ == "__main__":
    main()
