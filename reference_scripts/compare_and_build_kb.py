"""
Compare Gemini and Claude Vision Results & Build Final KB
Cross-validates descriptions and builds unified knowledge base
"""

import json
from pathlib import Path
from collections import defaultdict

EXTRACTED_DIR = Path(r"D:\Term 3 QA\Teacher Resources - Term 2\Extracted Media")
GEMINI_DIR = EXTRACTED_DIR / "gemini_descriptions"
CLAUDE_DIR = EXTRACTED_DIR / "claude_descriptions"
KB_OUTPUT_DIR = Path(r"D:\Term 3 QA\Teacher Resources - Term 2\Knowledge Base")
METADATA_DIR = EXTRACTED_DIR / "metadata"

def load_gemini_results():
    """Load Gemini KB data"""
    path = GEMINI_DIR / "gemini_kb_data.json"
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def load_claude_results():
    """Load Claude KB data"""
    path = CLAUDE_DIR / "claude_kb_data.json"
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def load_transcripts():
    """Load video transcripts"""
    path = METADATA_DIR / "video_transcripts.json"
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def load_extraction_metadata():
    """Load extraction metadata"""
    path = METADATA_DIR / "extraction_metadata.json"
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def compare_descriptions(gemini_desc: dict, claude_desc: dict) -> dict:
    """Compare two descriptions and create merged/validated version"""

    comparison = {
        "gemini_only": gemini_desc is not None and claude_desc is None,
        "claude_only": claude_desc is None and gemini_desc is not None,
        "both_available": gemini_desc is not None and claude_desc is not None,
    }

    # Merge descriptions - prefer Claude for quality, Gemini for tags
    merged = {}

    if gemini_desc and "analysis" in gemini_desc:
        g_analysis = gemini_desc["analysis"]
        merged["content_type"] = g_analysis.get("Content Type", g_analysis.get("content_type", "unknown"))
        merged["gemini_description"] = g_analysis.get("Visual Description", g_analysis.get("visual_description", ""))
        merged["gemini_context"] = g_analysis.get("Educational Context", g_analysis.get("educational_context", ""))
        merged["gemini_tags"] = g_analysis.get("KB Tags", g_analysis.get("kb_tags", []))
        merged["text_content"] = g_analysis.get("Text Content", g_analysis.get("text_content", ""))

    if claude_desc:
        merged["claude_description"] = claude_desc.get("visual_description", "")
        merged["claude_context"] = claude_desc.get("educational_context", "")
        merged["claude_tags"] = claude_desc.get("kb_tags", [])
        if claude_desc.get("text_content"):
            merged["text_content"] = claude_desc.get("text_content", merged.get("text_content", ""))

    # Create unified description
    if comparison["both_available"]:
        merged["confidence"] = "high"
        merged["validated"] = True
        # Combine unique tags
        all_tags = set(merged.get("gemini_tags", []) + merged.get("claude_tags", []))
        merged["unified_tags"] = list(all_tags)
        # Prefer longer description
        g_desc = merged.get("gemini_description", "")
        c_desc = merged.get("claude_description", "")
        merged["unified_description"] = c_desc if len(c_desc) > len(g_desc) else g_desc
    else:
        merged["confidence"] = "medium"
        merged["validated"] = False
        merged["unified_tags"] = merged.get("gemini_tags", []) or merged.get("claude_tags", [])
        merged["unified_description"] = merged.get("gemini_description", "") or merged.get("claude_description", "")

    comparison["merged"] = merged
    return comparison

def build_lesson_kb(metadata: dict, gemini_data: dict, claude_data: dict, transcripts: dict):
    """Build knowledge base organized by lesson"""

    KB_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    kb = {
        "lessons": {},
        "videos": {},
        "portfolio": {},
        "assessment": {}
    }

    # Process PPTX files
    for pptx_info in metadata.get("pptx_files", []):
        relative_path = pptx_info["relative_path"]
        source_path = pptx_info["source_path"]

        # Determine category and lesson
        if "Week" in relative_path and "Lesson" in relative_path:
            # Extract week and lesson numbers
            parts = relative_path.split("\\")
            week_num = None
            lesson_num = None

            for part in parts:
                if part.startswith("Week"):
                    try:
                        week_num = int(part.replace("Week ", "").strip())
                    except:
                        pass
                if "Lesson" in part:
                    lesson_str = part.replace("Lesson", "").replace(".pptx", "").replace("_", "").strip()
                    try:
                        lesson_num = int(lesson_str)
                    except:
                        pass

            if week_num and lesson_num:
                lesson_key = f"Week{week_num}_Lesson{lesson_num}"

                if lesson_key not in kb["lessons"]:
                    kb["lessons"][lesson_key] = {
                        "week": week_num,
                        "lesson": lesson_num,
                        "slides": [],
                        "images": []
                    }

                # Add slide text
                kb["lessons"][lesson_key]["slides"] = pptx_info.get("slides", [])

                # Add image descriptions
                gemini_images = (gemini_data or {}).get("pptx_descriptions", {}).get(relative_path, [])
                claude_images = (claude_data or {}).get("pptx_descriptions", {}).get(relative_path, [])

                for i, img_info in enumerate(pptx_info.get("images", [])):
                    g_desc = gemini_images[i] if i < len(gemini_images) else None
                    c_desc = claude_images[i] if i < len(claude_images) else None

                    comparison = compare_descriptions(g_desc, c_desc)

                    kb["lessons"][lesson_key]["images"].append({
                        "image_path": img_info["image_path"],
                        "index": img_info["index"],
                        **comparison["merged"]
                    })

        elif "Portfolio" in relative_path:
            kb["portfolio"]["slides"] = pptx_info.get("slides", [])
            kb["portfolio"]["source"] = relative_path

            gemini_images = (gemini_data or {}).get("pptx_descriptions", {}).get(relative_path, [])
            claude_images = (claude_data or {}).get("pptx_descriptions", {}).get(relative_path, [])

            kb["portfolio"]["images"] = []
            for i, img_info in enumerate(pptx_info.get("images", [])):
                g_desc = gemini_images[i] if i < len(gemini_images) else None
                c_desc = claude_images[i] if i < len(claude_images) else None
                comparison = compare_descriptions(g_desc, c_desc)
                kb["portfolio"]["images"].append({
                    "image_path": img_info["image_path"],
                    **comparison["merged"]
                })

        elif "Exemplar" in relative_path or "Assessment" in relative_path:
            if "assessment" not in kb:
                kb["assessment"] = {"files": []}

            assessment_entry = {
                "source": relative_path,
                "slides": pptx_info.get("slides", []),
                "images": []
            }

            gemini_images = (gemini_data or {}).get("pptx_descriptions", {}).get(relative_path, [])
            claude_images = (claude_data or {}).get("pptx_descriptions", {}).get(relative_path, [])

            for i, img_info in enumerate(pptx_info.get("images", [])):
                g_desc = gemini_images[i] if i < len(gemini_images) else None
                c_desc = claude_images[i] if i < len(claude_images) else None
                comparison = compare_descriptions(g_desc, c_desc)
                assessment_entry["images"].append({
                    "image_path": img_info["image_path"],
                    **comparison["merged"]
                })

            kb["assessment"]["files"].append(assessment_entry)

    # Process videos
    for video_info in metadata.get("video_files", []):
        relative_path = video_info["relative_path"]
        video_name = Path(video_info["source_path"]).stem

        kb["videos"][video_name] = {
            "source": relative_path,
            "duration_seconds": video_info.get("duration_seconds", 0),
            "transcript": transcripts.get(video_name, {}).get("text", ""),
            "transcript_segments": transcripts.get(video_name, {}).get("segments", []),
            "keyframes": []
        }

        gemini_kf = (gemini_data or {}).get("video_descriptions", {}).get(relative_path, [])
        claude_kf = (claude_data or {}).get("video_descriptions", {}).get(relative_path, [])

        for i, kf_info in enumerate(video_info.get("keyframes", [])):
            g_desc = gemini_kf[i] if i < len(gemini_kf) else None
            c_desc = claude_kf[i] if i < len(claude_kf) else None
            comparison = compare_descriptions(g_desc, c_desc)

            kb["videos"][video_name]["keyframes"].append({
                "keyframe_path": kf_info["keyframe_path"],
                "timestamp": kf_info.get("timestamp_formatted", "0:00"),
                **comparison["merged"]
            })

    return kb

def export_kb_formats(kb: dict):
    """Export KB in multiple formats for different use cases"""

    # JSON - Full structured data
    json_path = KB_OUTPUT_DIR / "term2_knowledge_base.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(kb, f, indent=2, ensure_ascii=False)

    # Markdown - Human readable
    md_path = KB_OUTPUT_DIR / "term2_knowledge_base.md"
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write("# Term 2 Teacher Resources Knowledge Base\n\n")

        # Lessons
        f.write("## Lessons\n\n")
        for lesson_key in sorted(kb.get("lessons", {}).keys()):
            lesson = kb["lessons"][lesson_key]
            f.write(f"### {lesson_key.replace('_', ' ')}\n\n")

            # Slide text
            for slide in lesson.get("slides", [])[:5]:  # First 5 slides
                if slide.get("text_content"):
                    f.write(f"**Slide {slide['slide_number']}:**\n")
                    f.write(f"{slide['text_content'][:500]}...\n\n")

            # Image descriptions
            f.write(f"**Images ({len(lesson.get('images', []))}):**\n")
            for img in lesson.get("images", [])[:3]:  # First 3 images
                desc = img.get("unified_description", "No description")
                tags = ", ".join(img.get("unified_tags", []))
                f.write(f"- {desc[:200]}... [Tags: {tags}]\n")
            f.write("\n")

        # Videos
        f.write("## Videos\n\n")
        for video_name, video in kb.get("videos", {}).items():
            f.write(f"### {video_name}\n\n")
            f.write(f"**Duration:** {video.get('duration_seconds', 0) // 60} minutes\n\n")
            f.write(f"**Transcript excerpt:**\n{video.get('transcript', '')[:500]}...\n\n")
            f.write(f"**Keyframes:** {len(video.get('keyframes', []))}\n\n")

    # CSV - For spreadsheet analysis
    csv_path = KB_OUTPUT_DIR / "term2_image_descriptions.csv"
    with open(csv_path, 'w', encoding='utf-8') as f:
        f.write("Source,Image Path,Content Type,Description,Tags,Confidence\n")

        for lesson_key, lesson in kb.get("lessons", {}).items():
            for img in lesson.get("images", []):
                desc = img.get("unified_description", "").replace('"', "'")[:200]
                tags = "|".join(img.get("unified_tags", []))
                f.write(f'"{lesson_key}","{img.get("image_path", "")}",')
                f.write(f'"{img.get("content_type", "")}","{desc}","{tags}",')
                f.write(f'"{img.get("confidence", "")}"\n')

    print(f"\nExported to:")
    print(f"  JSON: {json_path}")
    print(f"  Markdown: {md_path}")
    print(f"  CSV: {csv_path}")

    return json_path, md_path, csv_path

def generate_comparison_report(gemini_data: dict, claude_data: dict):
    """Generate comparison statistics between Gemini and Claude"""

    report = {
        "gemini_available": gemini_data is not None,
        "claude_available": claude_data is not None,
        "comparison": {}
    }

    if gemini_data:
        g_pptx = sum(len(v) for v in gemini_data.get("pptx_descriptions", {}).values())
        g_video = sum(len(v) for v in gemini_data.get("video_descriptions", {}).values())
        report["gemini_stats"] = {
            "pptx_images_processed": g_pptx,
            "video_keyframes_processed": g_video
        }

    if claude_data:
        c_pptx = sum(len(v) for v in claude_data.get("pptx_descriptions", {}).values())
        c_video = sum(len(v) for v in claude_data.get("video_descriptions", {}).values())
        report["claude_stats"] = {
            "pptx_images_processed": c_pptx,
            "video_keyframes_processed": c_video
        }

    return report

def main():
    print("=" * 60)
    print("KB BUILDER & COMPARISON TOOL")
    print("=" * 60)

    # Load all data
    metadata = load_extraction_metadata()
    gemini_data = load_gemini_results()
    claude_data = load_claude_results()
    transcripts = load_transcripts()

    print(f"\nData sources:")
    print(f"  Extraction metadata: Loaded")
    print(f"  Gemini results: {'Loaded' if gemini_data else 'Not found'}")
    print(f"  Claude results: {'Loaded' if claude_data else 'Not found'}")
    print(f"  Transcripts: {len(transcripts)} videos")

    # Generate comparison report
    comparison = generate_comparison_report(gemini_data, claude_data)
    print(f"\nComparison:")
    if comparison.get("gemini_stats"):
        print(f"  Gemini: {comparison['gemini_stats']}")
    if comparison.get("claude_stats"):
        print(f"  Claude: {comparison['claude_stats']}")

    # Build KB
    print("\nBuilding knowledge base...")
    kb = build_lesson_kb(metadata, gemini_data, claude_data, transcripts)

    # Export
    export_kb_formats(kb)

    # Summary
    print("\n" + "=" * 60)
    print("KB BUILD COMPLETE")
    print("=" * 60)
    print(f"Lessons: {len(kb.get('lessons', {}))}")
    print(f"Videos: {len(kb.get('videos', {}))}")
    print(f"Assessment files: {len(kb.get('assessment', {}).get('files', []))}")

if __name__ == "__main__":
    main()
