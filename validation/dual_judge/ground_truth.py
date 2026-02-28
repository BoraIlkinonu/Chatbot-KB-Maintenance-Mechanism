"""
Ground truth extraction from source files for dual-judge evaluation.

Scans converted/ directory and native_extractions.json directly to build
ground truth text. Does NOT depend on consolidated JSON files — reads
from the same source files the pipeline uses, so it never goes stale.
"""

import json
import re
from pathlib import Path

from config import CONVERTED_DIR, NATIVE_DIR, MEDIA_DIR, CONSOLIDATED_DIR


def extract_ground_truth(term: int, lesson_num: int) -> str:
    """Extract all source content for a lesson as readable text.

    Scans converted/term{N}/ for markdown files matching the lesson,
    and reads native extractions for the same term+lesson. Returns a
    single string for LLM evaluation.
    """
    parts = []

    # 1. Converted documents (PPTX→MD, DOCX→MD, etc.)
    converted_dir = CONVERTED_DIR / f"term{term}"
    if converted_dir.exists():
        for md_file in sorted(converted_dir.rglob("*.md")):
            rel_path = md_file.relative_to(CONVERTED_DIR)
            lessons = _extract_lesson_from_path(str(rel_path), term)
            if lesson_num in lessons:
                doc_text = _read_md_file(md_file, str(rel_path))
                if doc_text:
                    parts.append(doc_text)

    # 2. Native Google Docs/Slides content
    native_path = NATIVE_DIR / "native_extractions.json"
    if native_path.exists():
        try:
            data = json.loads(native_path.read_text(encoding="utf-8"))
            extractions = data.get("extractions", data if isinstance(data, list) else [])
            for ext in extractions:
                ext_term = ext.get("term", "")
                if ext_term != f"term{term}":
                    continue
                name = ext.get("file_name", "")
                source_path = ext.get("source_path", name)
                lessons = _extract_lesson_from_path(source_path or name, term)
                if lesson_num in lessons:
                    native_text = _extract_native(ext)
                    if native_text:
                        parts.append(native_text)
        except (json.JSONDecodeError, OSError):
            pass

    # 3. Hyperlinks extracted from PPTX/DOCX/PDF (extraction_metadata.json)
    #    These contain real URLs from source file hyperlink metadata that
    #    are NOT visible in the converted markdown text.
    link_text = _extract_hyperlinks_for_lesson(term, lesson_num)
    if link_text:
        parts.append(link_text)

    if not parts:
        return "[No source content found]"

    return "\n\n".join(parts)


def _extract_lesson_from_path(path: str, term: int) -> list[int]:
    """Extract lesson number(s) from file path.

    Uses consolidate.get_file_classification() to match what the pipeline assigns.
    Falls back to regex for paths not in the classification cache.
    """
    from consolidate import get_file_classification
    cls = get_file_classification(path)
    lessons = cls.get("lessons", [])
    if lessons:
        return lessons

    # Regex fallback for paths not in cache
    path_lower = path.lower().replace("\\", "/")

    match = re.search(r"lesson[_\s\-]*(\d{1,2})\s*[-–—]\s*(\d{1,2})", path_lower)
    if match:
        start, end = int(match.group(1)), int(match.group(2))
        if 1 <= start and 1 <= end and start != end:
            return list(range(start, end + 1))

    match = re.search(r"lesson[_\s\-]*(\d{1,2})", path_lower)
    if match:
        num = int(match.group(1))
        if num >= 1:
            return [num]

    match = re.search(r"lessons?\s*(\d{1,2})\s*[-–]\s*(\d{1,2})", path_lower)
    if match:
        start, end = int(match.group(1)), int(match.group(2))
        if 1 <= start and 1 <= end:
            return list(range(start, end + 1))

    # Cross-term check
    for m in re.finditer(r"term\s*(\d+)\b", path_lower):
        t_num = int(m.group(1))
        if t_num != term:
            return []

    return []


def _read_md_file(path: Path, rel_path: str) -> str | None:
    """Read a converted markdown file and format it for ground truth."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None

    if not text:
        return None

    return f"=== CONVERTED — {rel_path} ===\n{text}"


def _extract_native(native: dict) -> str | None:
    """Extract text from native Google Docs/Slides content."""
    title = native.get("title", native.get("file_name", "unknown"))
    native_type = native.get("native_type", "unknown")
    parts = [f"=== NATIVE {native_type.upper()} — {title} ==="]

    # Google Slides format
    if "slides" in native and isinstance(native["slides"], list):
        for i, slide in enumerate(native["slides"], 1):
            slide_parts = [f"--- Slide {i} ---"]

            for element in slide.get("pageElements", slide.get("elements", [])):
                text = _extract_shape_text(element)
                if text:
                    slide_parts.append(text)

            if slide.get("text"):
                slide_parts.append(str(slide["text"]))

            notes = slide.get("notes", "")
            if notes:
                slide_parts.append(f"[Speaker Notes]: {notes}")

            for link in slide.get("links", []):
                url = link.get("url", link) if isinstance(link, dict) else str(link)
                slide_parts.append(f"[Link]: {url}")

            if len(slide_parts) > 1:
                parts.extend(slide_parts)

    # Google Docs format
    if "content_blocks" in native and isinstance(native["content_blocks"], list):
        for block in native["content_blocks"]:
            if isinstance(block, dict):
                heading = block.get("heading", "")
                text = block.get("text", block.get("content", ""))
                if heading:
                    parts.append(f"## {heading}")
                if text:
                    parts.append(str(text).strip())
            elif isinstance(block, str) and block.strip():
                parts.append(block.strip())

    # Links from native docs
    for link in native.get("links", []):
        if isinstance(link, dict):
            url = link.get("url", "")
            text = link.get("text", "")
            if url:
                parts.append(f"[Link]: {text} -> {url}" if text else f"[Link]: {url}")
        elif isinstance(link, str):
            parts.append(f"[Link]: {link}")

    # Pre-extracted section fields
    for key in ["big_question", "uae_link", "learning_objectives",
                "success_criteria", "activities", "assessment",
                "curriculum_alignment"]:
        val = native.get(key)
        if val:
            content = val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
            parts.append(f"[{key}]: {content}")

    if len(parts) <= 1:
        return None

    return "\n".join(parts)


def _extract_shape_text(element: dict) -> str | None:
    """Extract text from a Google Slides shape/pageElement."""
    if "text" in element and isinstance(element["text"], str):
        return element["text"].strip() or None

    shape = element.get("shape", element)
    text_content = shape.get("text", {})
    if isinstance(text_content, str):
        return text_content.strip() or None

    text_elements = text_content.get("textElements", [])
    texts = []
    for te in text_elements:
        run = te.get("textRun", {})
        content = run.get("content", "").strip()
        if content:
            texts.append(content)

    return " ".join(texts) if texts else None


def _extract_hyperlinks_for_lesson(term: int, lesson_num: int) -> str | None:
    """Extract hyperlinks from PPTX/DOCX/PDF binary metadata for a lesson.

    These URLs come from extraction_metadata.json and are NOT visible in
    the converted markdown text — without them the judge falsely flags
    legitimate URLs as fabricated.
    """
    meta_path = MEDIA_DIR / "extraction_metadata.json"
    if not meta_path.exists():
        return None

    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    links: list[str] = []

    for file_type in ("pptx_files", "docx_files", "pdf_files"):
        for file_info in data.get(file_type, []):
            rel_path = file_info.get("relative_path", "")
            file_lessons = _extract_lesson_from_path(rel_path, term)
            if lesson_num not in file_lessons:
                continue

            for link in file_info.get("links", []):
                url = link.get("url", "")
                text = link.get("text", "")
                if url:
                    entry = f"[Hyperlink]: {text} -> {url}" if text else f"[Hyperlink]: {url}"
                    if entry not in links:
                        links.append(entry)

    if not links:
        return None

    return f"=== HYPERLINKS (binary metadata) ===\n" + "\n".join(links)
