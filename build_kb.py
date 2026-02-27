"""
Stage 4: KB JSON Builder (LLM-based)

Assembles the final Knowledge Base JSON per term using:
  1. LLM extraction cache (llm_cache/) → all semantic fields (20 fields)
  2. Converted PPTX markdown → raw slides array, speaker notes
  3. Native Google API extractions → native_slides, native_images, native_tables, native_links
  4. Media metadata → PPTX image structural data

Output schema matches the chatbot's expected format exactly.
No regex extraction — all semantic content comes from the LLM cache.
"""

import sys
import json
import re
from pathlib import Path
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")

from config import (
    CONSOLIDATED_DIR, OUTPUT_DIR, WEEK_LESSON_MAP,
    BASE_DIR, CONVERTED_DIR, NATIVE_DIR,
)


LLM_CACHE_DIR = BASE_DIR / "llm_cache"

# ──────────────────────────────────────────────────────────
# Slide markdown parsing (kept — structural, not semantic)
# ──────────────────────────────────────────────────────────

def parse_slides_from_markdown(content):
    """Parse slide-based markdown into per-slide structures with text and notes."""
    slides = []
    current_slide = None
    current_text = []
    current_notes = []
    in_notes = False

    for line in content.split("\n"):
        match = re.match(r"^## Slide (\d+)", line)
        if match:
            if current_slide is not None:
                slides.append({
                    "slide_number": current_slide,
                    "text": "\n".join(current_text).strip(),
                    "notes": "\n".join(current_notes).strip(),
                })
            current_slide = int(match.group(1))
            current_text = []
            current_notes = []
            in_notes = False
        elif current_slide is not None:
            if "**Speaker Notes:**" in line:
                in_notes = True
                continue
            if line.strip() == "---":
                continue
            if in_notes:
                current_notes.append(line)
            else:
                current_text.append(line)

    if current_slide is not None:
        slides.append({
            "slide_number": current_slide,
            "text": "\n".join(current_text).strip(),
            "notes": "\n".join(current_notes).strip(),
        })

    return slides


def extract_tables_from_markdown(content):
    """Parse markdown tables into structured {headers, rows} format."""
    tables = []
    lines = content.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|") and i + 1 < len(lines):
            next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if "|" in next_line and "---" in next_line:
                headers = [c.strip() for c in line.strip("|").split("|")]
                rows = []
                j = i + 2
                while j < len(lines) and lines[j].strip().startswith("|"):
                    row = [c.strip() for c in lines[j].strip().strip("|").split("|")]
                    rows.append(row)
                    j += 1
                tables.append({"headers": headers, "rows": rows})
                i = j
                continue
        i += 1

    return tables


# Assessment/rubric and schedule keywords for table classification
_RUBRIC_KEYWORDS = {
    "rubric", "criterion", "criteria", "assessment", "marks", "score",
    "grade", "grading", "proficient", "emerging", "exceeding", "level",
    "performance", "competency", "mastery", "beginning", "developing",
    "portfolio", "reflection", "self-assessment", "peer-assessment",
}

_SCHEDULE_KEYWORDS = {
    "week", "date", "deadline", "milestone", "schedule", "timeline",
    "session", "day", "period", "term", "semester", "calendar",
}


def classify_table(table):
    """Classify a table as 'rubric', 'schedule', or 'data'."""
    headers_text = " ".join(str(h).lower() for h in table.get("headers", []))
    rows = table.get("rows", [])
    first_row_text = " ".join(str(c).lower() for c in rows[0]) if rows else ""
    combined = headers_text + " " + first_row_text

    rubric_hits = sum(1 for kw in _RUBRIC_KEYWORDS if kw in combined)
    schedule_hits = sum(1 for kw in _SCHEDULE_KEYWORDS if kw in combined)

    if rubric_hits >= 2:
        return "rubric"
    if schedule_hits >= 2:
        return "schedule"
    if rubric_hits == 1:
        return "rubric"
    if schedule_hits == 1:
        return "schedule"
    return "data"


# ──────────────────────────────────────────────────────────
# Structural data loaders (no semantic extraction)
# ──────────────────────────────────────────────────────────

def _load_llm_extraction(term: int, lesson_num: int) -> dict | None:
    """Load LLM extraction from cache."""
    cache_path = LLM_CACHE_DIR / f"term{term}_lesson{lesson_num}.json"
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        return data.get("extraction", data)
    except (json.JSONDecodeError, OSError):
        return None


def _read_full_content(doc):
    """Read the full content of a converted document."""
    full_path = doc.get("full_path", "")
    if full_path:
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass
    return doc.get("content_preview", "")


def _extract_structural_data(lesson_data: dict, term_num: int, lesson_num: int) -> dict:
    """Extract structural (non-semantic) data from consolidated sources.

    Returns slides, native content, images, tables, links — everything
    that is direct reformatting, not extraction logic.
    """
    docs = lesson_data.get("documents", [])
    images_meta = lesson_data.get("images", [])
    native_content = lesson_data.get("native_content", [])
    links = lesson_data.get("links", [])

    # 1. Parse slides from converted PPTX markdown
    all_slides = []
    for doc in docs:
        if doc.get("content_type") not in ("teachers_slides", "students_slides"):
            continue
        content = _read_full_content(doc)
        if content:
            slides = parse_slides_from_markdown(content)
            all_slides.extend(slides)

    # 2. Extract tables from all converted markdown
    rubrics = []
    data_tables = []
    schedule_tables = []
    for doc in docs:
        content = _read_full_content(doc)
        if content:
            tables = extract_tables_from_markdown(content)
            for table in tables:
                ttype = classify_table(table)
                if ttype == "rubric":
                    rubrics.append(table)
                elif ttype == "schedule":
                    schedule_tables.append(table)
                else:
                    data_tables.append(table)

    # 3. Native Google Slides/Docs structural content
    native_slide_entries = []
    native_image_entries = []
    native_slides_tables = []
    native_link_entries = []
    native_remaining_content = []

    for ext in native_content:
        ntype = ext.get("native_type", "")
        name = ext.get("file_name", "")

        if ntype == "google_slides":
            for i, slide in enumerate(ext.get("slides", []), 1):
                # Slide text
                texts = []
                for elem in slide.get("pageElements", slide.get("elements", [])):
                    t = elem.get("text", "")
                    if isinstance(t, str) and t.strip():
                        texts.append(t.strip())
                    shape = elem.get("shape", {})
                    shape_text = shape.get("text", "")
                    if isinstance(shape_text, str) and shape_text.strip():
                        texts.append(shape_text.strip())

                if slide.get("text"):
                    texts.append(str(slide["text"]))

                native_slide_entries.append({
                    "slide_number": i,
                    "content": " ".join(texts),
                    "speaker_notes": slide.get("notes", ""),
                    "source_file": name,
                })

                # Images from native slides
                for img in slide.get("images", []):
                    native_image_entries.append({
                        "image_id": img.get("object_id", ""),
                        "url": img.get("url", ""),
                        "source_url": img.get("source_url", ""),
                        "source_file": name,
                        "slide_number": i,
                    })

                # Links from native slides
                for link in slide.get("links", []):
                    url = link.get("url", link) if isinstance(link, dict) else str(link)
                    text = link.get("text", "") if isinstance(link, dict) else ""
                    if url:
                        native_link_entries.append({
                            "url": url,
                            "text": text,
                            "slide_number": i,
                        })

                # Tables from native slides
                for table in slide.get("tables", []):
                    native_slides_tables.append(table)

        elif ntype == "google_doc":
            # Links from native docs
            for link in ext.get("links", []):
                if isinstance(link, dict) and link.get("url"):
                    native_link_entries.append({
                        "url": link["url"],
                        "text": link.get("text", ""),
                        "slide_number": 0,
                    })

            # Tables from native docs
            for table in ext.get("tables", []):
                native_slides_tables.append(table)

    # 4. PPTX image metadata (structural only — no descriptions)
    pptx_images = []
    for img in images_meta:
        pptx_images.append({
            "image_id": "",
            "content_type": "",
            "visual_description": "",
            "educational_context": "",
            "source": img.get("source", "pptx"),
            "source_pptx": img.get("source_pptx", ""),
            "image_path": img.get("image_path", ""),
            "slide_numbers": img.get("slide_numbers", []),
            "primary_slide": img.get("primary_slide"),
            "kb_tags": [],
        })

    # 5. Document sources
    doc_sources = [d.get("path", "") for d in docs if d.get("path")]

    return {
        "slides": all_slides,
        "rubrics": rubrics,
        "data_tables": data_tables,
        "schedule_tables": schedule_tables,
        "native_slides": native_slide_entries,
        "native_images": native_image_entries,
        "native_tables": native_slides_tables,
        "native_links": native_link_entries,
        "native_remaining": native_remaining_content,
        "pptx_images": pptx_images,
        "document_sources": doc_sources,
    }


def _week_for_lesson(lesson_num: int) -> int | None:
    """Look up week number from WEEK_LESSON_MAP."""
    for week, lessons in WEEK_LESSON_MAP.items():
        if lesson_num in lessons:
            return week
    return None


def build_lesson_entry(term_num: int, lesson_num: int, lesson_data: dict) -> dict | None:
    """Build a single lesson's KB entry from LLM extraction + structural data.

    Returns the lesson entry dict matching the chatbot's expected schema,
    or None if no LLM extraction is available.
    """
    # Load LLM extraction (semantic fields)
    llm = _load_llm_extraction(term_num, lesson_num)
    if llm is None:
        return None

    # Load structural data (slides, images, tables, native content)
    structural = _extract_structural_data(lesson_data, term_num, lesson_num)

    # Derive metadata title (strip "Lesson N:" prefix for the metadata.title field)
    lesson_title = llm.get("lesson_title", f"Lesson {lesson_num}")
    title_for_metadata = re.sub(
        r"^lesson\s*\d+\s*[:–\-—]\s*", "", lesson_title, flags=re.IGNORECASE
    ).strip() or lesson_title

    week = _week_for_lesson(lesson_num)

    # Use LLM teacher_notes, but fall back to slide speaker notes if LLM returned empty
    teacher_notes = llm.get("teacher_notes", [])
    if not teacher_notes:
        teacher_notes = [
            {"slide": s["slide_number"], "notes": s["notes"]}
            for s in structural["slides"]
            if s.get("notes")
        ]

    # Video entries — normalize from LLM format
    video_entries = []
    for v in llm.get("videos", []):
        if isinstance(v, dict):
            video_entries.append({
                "url": v.get("url", ""),
                "video_id": v.get("video_id", ""),
                "type": v.get("type", ""),
                "title": v.get("title", ""),
            })
        elif isinstance(v, str):
            video_entries.append({"url": v, "video_id": "", "type": "", "title": ""})

    # Build the lesson entry in the exact expected schema
    lesson_entry = {
        "lesson_title": lesson_title,
        "url": f"Lesson {lesson_num}",
        "metadata": {
            "term_id": term_num,
            "lesson_id": lesson_num,
            "title": title_for_metadata,
            "url": f"Lesson {lesson_num}",
            "grade_band": llm.get("grade_band", "G9\u2013G10") or "G9\u2013G10",
            "core_topics": llm.get("core_topics", []),
            "endstar_tools": llm.get("endstar_tools", []),
            "ai_focus": llm.get("ai_focus", []),
            "learning_objectives": llm.get("learning_objectives", []),
            "activity_type": llm.get("activity_type", ""),
            "activity_description": llm.get("description_of_activities", ""),
            "artifacts": llm.get("artifacts", []),
            "assessment_signals": llm.get("assessment_signals", []),
            "videos": video_entries,
            "resources": llm.get("resources", []),
            "keywords": llm.get("keywords", []),
            "images": structural["pptx_images"],
        },
        "description_of_activities": llm.get("description_of_activities", ""),
        "other_resources": "",
        "videos_column": "",
        "testing_scores": "",
        "comments": "",
        "prompts": "",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_version": "3.0",
        "week": week,
        "big_question": llm.get("big_question", ""),
        "uae_link": llm.get("uae_link", ""),
        "success_criteria": llm.get("success_criteria", []),
        "curriculum_alignment": llm.get("curriculum_alignment", []),
        "programme_metadata": {},
        "key_facts": [],
        "detailed_activities": llm.get("description_of_activities", ""),
        # Tables split by purpose
        "rubrics": structural["rubrics"],
        "data_tables": structural["data_tables"],
        "schedule_tables": structural["schedule_tables"],
        "teacher_notes": teacher_notes,
        "assessment_framework": [],
        # Slides (converted PPTX)
        "slides": [
            {"slide_number": s["slide_number"], "content": s["text"]}
            for s in structural["slides"]
        ],
        # Native Google API content
        "native_slides": structural["native_slides"],
        "native_images": structural["native_images"],
        "native_tables": structural["native_tables"],
        "native_links": structural["native_links"],
        "remaining_content": structural["native_remaining"],
        "image_count": len(structural["pptx_images"]) + len(structural["native_images"]),
        "document_sources": structural["document_sources"],
    }

    return lesson_entry


def run_build(term_num=None):
    """Build the KB JSON from LLM cache + consolidated structural data."""
    print("=" * 60)
    print("  Stage 4: KB Build (LLM-based)")
    print("=" * 60)
    print()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not LLM_CACHE_DIR.exists():
        print("No LLM cache found. Run llm_extract.py first.")
        return None

    # Load consolidated content for structural data
    if term_num:
        terms_to_build = [term_num]
    else:
        per_term_files = sorted(CONSOLIDATED_DIR.glob("consolidated_term*.json"))
        if per_term_files:
            terms_to_build = []
            for ptf in per_term_files:
                m = re.search(r"consolidated_term(\d+)\.json$", ptf.name)
                if m:
                    terms_to_build.append(int(m.group(1)))
            terms_to_build.sort()
        else:
            print("No consolidated content found. Run consolidate.py first.")
            return None

    if not terms_to_build:
        print("No term data found.")
        return None

    for t in terms_to_build:
        print(f"\nBuilding KB for Term {t}...")

        # Load consolidated structural data
        per_term_path = CONSOLIDATED_DIR / f"consolidated_term{t}.json"
        if per_term_path.exists():
            with open(per_term_path, "r", encoding="utf-8") as f:
                per_term_data = json.load(f)
            term_lessons = per_term_data.get("by_lesson", {})
        else:
            print(f"  No consolidated data for Term {t}. Skipping.")
            continue

        if not term_lessons:
            print(f"  No lesson data for Term {t}. Skipping.")
            continue

        lesson_nums = [int(k) for k in term_lessons.keys() if k.isdigit()]
        max_lesson = max(lesson_nums) if lesson_nums else 0
        lessons = []

        for lesson_num in range(1, max_lesson + 1):
            lesson_data = term_lessons.get(str(lesson_num), {})

            entry = build_lesson_entry(t, lesson_num, lesson_data)
            if entry is None:
                # No LLM extraction — skip this lesson
                print(f"  Lesson {lesson_num}: [skip - no LLM extraction]")
                continue

            lessons.append(entry)
            m = entry["metadata"]
            parts = [
                f'"{m["title"]}"',
                f"{len(m['core_topics'])}top",
                f"{len(m['learning_objectives'])}obj",
                f"{len(m['images'])}img",
                f"{len(m['videos'])}vid",
                f"{len(m['resources'])}res",
                f"{len(m['endstar_tools'])}tools",
                f"{len(m['keywords'])}kw",
            ]
            print(f"  Lesson {lesson_num}: {' | '.join(parts)}")

        kb = {
            "term": t,
            "total_lessons": len(lessons),
            "generated_from": "KB Maintenance Pipeline v3 (LLM extraction)",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "lessons": lessons,
        }

        output_path = OUTPUT_DIR / f"Term {t} - Lesson Based Structure.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(kb, f, indent=2, ensure_ascii=False)

        print(f"\n  Term {t}: {len(lessons)} lessons -> {output_path}")

    print("\n" + "=" * 60)
    print("  KB Build Complete")
    print("=" * 60)

    return True


if __name__ == "__main__":
    import sys as _sys
    term = int(_sys.argv[1]) if len(_sys.argv) > 1 else None
    run_build(term)
