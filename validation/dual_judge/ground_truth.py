"""
Ground truth extraction from source files for dual-judge evaluation.

Scans converted/ directory and native_extractions.json directly to build
ground truth text. Does NOT depend on consolidated JSON files — reads
from the same source files the pipeline uses, so it never goes stale.
"""

import json
import re
from pathlib import Path

from config import CONVERTED_DIR, NATIVE_DIR, WEEK_LESSON_MAP


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

    if not parts:
        return "[No source content found]"

    return "\n\n".join(parts)


def _extract_lesson_from_path(path: str, term: int) -> list[int]:
    """Extract lesson number(s) from file path.

    Mirrors consolidate.extract_lesson_from_path() logic so ground truth
    matches what the pipeline assigns.
    """
    path_lower = path.lower().replace("\\", "/")
    max_lesson = {1: 24, 2: 14, 3: 24}.get(term, 24)

    # Explicit "Lesson X"
    match = re.search(r"lesson[_\s\-]*(\d{1,2})", path_lower)
    if match:
        num = int(match.group(1))
        if 1 <= num <= max_lesson:
            return [num]

    # "Lessons X-Y" (range)
    match = re.search(r"lessons?\s*(\d{1,2})\s*[-–]\s*(\d{1,2})", path_lower)
    if match:
        start, end = int(match.group(1)), int(match.group(2))
        if 1 <= start <= max_lesson and 1 <= end <= max_lesson:
            return list(range(start, end + 1))

    # Week folder → lessons (skip support docs)
    if not any(skip in path_lower for skip in ["assessment", "exemplar", "teacher guide"]):
        match = re.search(r"week[_\s\-]*(\d)", path_lower)
        if match:
            week = int(match.group(1))
            if week in WEEK_LESSON_MAP:
                return WEEK_LESSON_MAP[week]

    # Cross-term check
    for t_num in range(1, 4):
        if t_num != term and re.search(rf"term\s*{t_num}\b", path_lower):
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

    # Cap at 8000 chars per document
    if len(text) > 8000:
        text = text[:8000] + "\n[... truncated ...]"

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

    result = "\n".join(parts)
    if len(result) > 5000:
        result = result[:5000] + "\n[... truncated ...]"
    return result


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
