"""
Ground truth extraction from source files for dual-judge evaluation.

Reads the consolidated JSON (by_lesson → documents → full_path to converted
.md files) and native_content arrays to build a complete text representation
of what the source files actually contain.
"""

import json
from pathlib import Path

from config import CONSOLIDATED_DIR


def extract_ground_truth(term: int, lesson_num: int) -> str:
    """Extract all source content for a lesson as readable text.

    Reads consolidated JSON to find converted documents and native content,
    then reads the actual files. Returns a single string for LLM evaluation.
    """
    consolidated_file = CONSOLIDATED_DIR / f"consolidated_term{term}.json"
    if not consolidated_file.exists():
        return "[No source content found]"

    data = json.loads(consolidated_file.read_text(encoding="utf-8"))
    by_lesson = data.get("by_lesson", {})
    lesson_data = by_lesson.get(str(lesson_num), {})

    if not lesson_data:
        return "[No source content found]"

    parts = []

    # 1. Converted documents (PPTX→MD, DOCX→MD, etc.)
    for doc in lesson_data.get("documents", []):
        doc_text = _extract_document(doc)
        if doc_text:
            parts.append(doc_text)

    # 2. Native Google Docs/Slides content
    for native in lesson_data.get("native_content", []):
        native_text = _extract_native(native)
        if native_text:
            parts.append(native_text)

    if not parts:
        return "[No source content found]"

    return "\n\n".join(parts)


def _extract_document(doc: dict) -> str | None:
    """Extract text from a converted document entry.

    Each document has a full_path to a .md file on disk and metadata
    like content_type, format, slide_count.
    """
    full_path = doc.get("full_path", "")
    rel_path = doc.get("path", "")
    content_type = doc.get("content_type", "unknown")

    if not full_path:
        return None

    path = Path(full_path)
    if not path.exists():
        return None

    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None

    if not text:
        return None

    # Cap at 8000 chars per document to stay within prompt limits
    if len(text) > 8000:
        text = text[:8000] + "\n[... truncated ...]"

    header = f"=== {content_type.upper()} — {rel_path} ==="
    return f"{header}\n{text}"


def _extract_native(native: dict) -> str | None:
    """Extract text from native Google Docs/Slides content.

    Native content comes in two formats:
    - Slides: has 'slides' array with pageElements
    - Docs: has 'content_blocks' array with text blocks
    """
    title = native.get("title", native.get("file_name", "unknown"))
    native_type = native.get("native_type", "unknown")
    parts = [f"=== NATIVE {native_type.upper()} — {title} ==="]

    # Google Slides format (from native extraction)
    if "slides" in native and isinstance(native["slides"], list):
        for i, slide in enumerate(native["slides"], 1):
            slide_parts = [f"--- Slide {i} ---"]

            # Text elements from shapes
            for element in slide.get("pageElements", slide.get("elements", [])):
                text = _extract_shape_text(element)
                if text:
                    slide_parts.append(text)

            # Direct text field
            if slide.get("text"):
                slide_parts.append(str(slide["text"]))

            # Speaker notes
            notes = slide.get("notes", "")
            if notes:
                slide_parts.append(f"[Speaker Notes]: {notes}")

            # Links
            for link in slide.get("links", []):
                url = link.get("url", link) if isinstance(link, dict) else str(link)
                slide_parts.append(f"[Link]: {url}")

            if len(slide_parts) > 1:  # More than just the header
                parts.extend(slide_parts)

    # Google Docs format (from native extraction)
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

    # Pre-extracted section fields (some native docs have these directly)
    for key in ["big_question", "uae_link", "learning_objectives",
                "success_criteria", "activities", "assessment",
                "curriculum_alignment"]:
        val = native.get(key)
        if val:
            content = val if isinstance(val, str) else json.dumps(val, ensure_ascii=False)
            parts.append(f"[{key}]: {content}")

    if len(parts) <= 1:  # Only header, no content
        return None

    result = "\n".join(parts)
    # Cap at 5000 chars per native doc
    if len(result) > 5000:
        result = result[:5000] + "\n[... truncated ...]"
    return result


def _extract_shape_text(element: dict) -> str | None:
    """Extract text from a Google Slides shape/pageElement."""
    # Direct text field
    if "text" in element and isinstance(element["text"], str):
        return element["text"].strip() or None

    # Nested shape → text → textElements
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
