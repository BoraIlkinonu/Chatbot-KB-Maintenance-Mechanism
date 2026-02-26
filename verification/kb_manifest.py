"""
KB Manifest Builder.

Parses the final KB JSON output files into ContentAtoms for comparison
against the source manifest.
"""

import json
import re
from pathlib import Path

from verification import ContentAtom, KBManifest


def _parse_lesson_atoms(lesson_data, term):
    """Extract ContentAtoms from a single lesson's KB entry."""
    atoms = []
    meta = lesson_data.get("metadata", {})
    lesson_num = meta.get("lesson_id")

    def add(atom_type, content, location, **extra_meta):
        if content and str(content).strip():
            atoms.append(ContentAtom(
                atom_type=atom_type,
                content=str(content).strip(),
                source_file=f"kb:term{term}",
                location=location,
                term=term,
                lesson=lesson_num,
                metadata=extra_meta,
            ))

    # Top-level fields
    add("text_block", lesson_data.get("lesson_title", ""), "lesson_title")

    # Metadata fields
    add("text_block", meta.get("title", ""), "metadata.title")

    for i, topic in enumerate(meta.get("core_topics", [])):
        add("text_block", topic, f"metadata.core_topics[{i}]")

    for i, obj in enumerate(meta.get("learning_objectives", [])):
        add("text_block", obj, f"metadata.learning_objectives[{i}]")

    add("text_block", meta.get("activity_description", ""), "metadata.activity_description")

    for i, signal in enumerate(meta.get("assessment_signals", [])):
        add("text_block", signal, f"metadata.assessment_signals[{i}]")

    for i, ai in enumerate(meta.get("ai_focus", [])):
        add("text_block", ai, f"metadata.ai_focus[{i}]")

    # Resources (may contain URLs)
    for i, res in enumerate(meta.get("resources", [])):
        # Extract URL from resource string
        url_match = re.search(r"https?://[^\s,)\"]+", str(res))
        if url_match:
            add("link", url_match.group(0), f"metadata.resources[{i}]",
                full_resource=str(res))
        add("text_block", str(res), f"metadata.resources[{i}]:text")

    # Videos
    for i, video in enumerate(meta.get("videos", [])):
        url = video.get("url", "")
        if url:
            add("video_url", url, f"metadata.videos[{i}]",
                video_title=video.get("title", ""))

    # Keywords
    for i, kw in enumerate(meta.get("keywords", [])):
        add("text_block", kw, f"metadata.keywords[{i}]", is_keyword=True)

    # PPTX Images — store source_pptx and slide_numbers for slide-based matching
    for i, img in enumerate(meta.get("images", [])):
        img_path = img.get("image_path", "")
        if img_path:
            source_pptx = img.get("source_pptx", "")
            slide_numbers = sorted(img.get("slide_numbers", []))
            media_name = Path(img_path).name
            add("image", media_name, f"metadata.images[{i}]",
                image_path=img_path,
                source_pptx=source_pptx,
                slide_numbers=slide_numbers)

    # Top-level enrichment fields (formerly nested under "enriched")
    add("text_block", lesson_data.get("big_question", ""), "big_question")
    add("text_block", lesson_data.get("uae_link", ""), "uae_link")

    for i, crit in enumerate(lesson_data.get("success_criteria", [])):
        add("text_block", crit, f"success_criteria[{i}]")

    # Curriculum alignment standards
    for i, align in enumerate(lesson_data.get("curriculum_alignment", [])):
        text = align.get("text", "") if isinstance(align, dict) else str(align)
        if text:
            add("text_block", text, f"curriculum_alignment[{i}]")

    # Programme metadata
    prog_meta = lesson_data.get("programme_metadata", {})
    if isinstance(prog_meta, dict):
        for key in ("subject", "year_group", "duration"):
            val = prog_meta.get(key, "")
            if val:
                add("text_block", val, f"programme_metadata.{key}")

    # Remaining content (catch-all for unconsumed native doc sections)
    for i, section in enumerate(lesson_data.get("remaining_content", [])):
        heading = section.get("heading", "")
        for j, line in enumerate(section.get("content", [])):
            if line and str(line).strip():
                add("text_block", str(line).strip(),
                    f"remaining_content[{i}].content[{j}]",
                    section_heading=heading)

    # Teacher notes
    for i, note in enumerate(lesson_data.get("teacher_notes", [])):
        notes_text = note.get("notes", "")
        if notes_text:
            add("speaker_note", notes_text, f"teacher_notes[{i}]",
                slide=note.get("slide"))

    # Slides content (PPTX-converted + native that didn't overlap)
    for i, slide in enumerate(lesson_data.get("slides", [])):
        content = slide.get("content", "")
        if content:
            add("text_block", content, f"slides[{i}]",
                slide_number=slide.get("slide_number"))

    # Helper: parse table dict into text for matching
    def _table_to_text(table):
        parts = []
        headers = table.get("headers", [])
        if headers:
            parts.append(" | ".join(str(h) for h in headers))
        for row in table.get("rows", []):
            if isinstance(row, list):
                parts.append(" | ".join(str(c) for c in row))
        return "\n".join(parts)

    # Rubrics (assessment tables)
    for i, table in enumerate(lesson_data.get("rubrics", [])):
        if isinstance(table, dict):
            table_text = _table_to_text(table)
            if table_text.strip():
                add("table", table_text, f"rubrics[{i}]")

    # Data tables (slide content tables)
    for i, table in enumerate(lesson_data.get("data_tables", [])):
        if isinstance(table, dict):
            table_text = _table_to_text(table)
            if table_text.strip():
                add("table", table_text, f"data_tables[{i}]")

    # Schedule tables
    for i, table in enumerate(lesson_data.get("schedule_tables", [])):
        if isinstance(table, dict):
            table_text = _table_to_text(table)
            if table_text.strip():
                add("table", table_text, f"schedule_tables[{i}]")

    # Native Slides content (dedicated fields)
    for i, ns in enumerate(lesson_data.get("native_slides", [])):
        content = ns.get("content", "")
        if content:
            add("text_block", content, f"native_slides[{i}]",
                slide_number=ns.get("slide_number"),
                source_file=ns.get("source_file", ""))
        notes = ns.get("speaker_notes", "")
        if notes:
            add("speaker_note", notes, f"native_slides[{i}]:notes",
                slide=ns.get("slide_number"))

    # Native images (Google Slides API URLs)
    for i, ni in enumerate(lesson_data.get("native_images", [])):
        url = ni.get("url", "")
        if url:
            add("image_ref", url, f"native_images[{i}]",
                image_path=url,
                source_pptx=ni.get("source_file", ""),
                slide_numbers=[ni.get("slide_number")] if ni.get("slide_number") else [])

    # Native tables
    for i, table in enumerate(lesson_data.get("native_tables", [])):
        if isinstance(table, dict):
            table_text = _table_to_text(table)
            if table_text.strip():
                add("table", table_text, f"native_tables[{i}]")

    # Native links
    for i, nl in enumerate(lesson_data.get("native_links", [])):
        url = nl.get("url", "")
        if url:
            add("link", url, f"native_links[{i}]",
                text=nl.get("text", ""))

    # Artifacts
    for i, artifact in enumerate(lesson_data.get("artifacts", [])):
        add("text_block", str(artifact), f"artifacts[{i}]")

    # Key facts
    for i, fact in enumerate(lesson_data.get("key_facts", [])):
        add("text_block", str(fact), f"key_facts[{i}]")

    return atoms


def build_kb_manifest(output_dir) -> KBManifest:
    """Parse all KB JSON output files into a KBManifest."""
    output_dir = Path(output_dir)
    atoms = []
    terms_found = []

    # Find all term KB files
    kb_files = sorted(output_dir.glob("Term * - Lesson Based Structure.json"))

    for kb_file in kb_files:
        print(f"  KB file: {kb_file.name}")
        try:
            with open(kb_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"    Error reading {kb_file.name}: {e}")
            continue

        term = data.get("term")
        if term:
            terms_found.append(term)

        for lesson in data.get("lessons", []):
            lesson_atoms = _parse_lesson_atoms(lesson, term)
            atoms.extend(lesson_atoms)

    print(f"\n  Total KB atoms: {len(atoms)} from terms {terms_found}")
    return KBManifest(atoms=atoms, terms_found=terms_found)
