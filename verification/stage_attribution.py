"""
Stage Attribution: determine which pipeline stage lost each unmatched atom.

Attribution cascade (first stage where atom is missing = the stage that lost it):
  Stage 1: media/extraction_metadata.json (images + links)
  Stage 2: converted/*.md files
  Stage 3: native_extracts/*.json
  Stage 5: consolidated/consolidated_term{1,2,3}.json
  Stage 6: output/Term {N} - Lesson Based Structure.json
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from verification import ContentAtom, normalize_text


@dataclass
class Attribution:
    """Where a content atom was lost in the pipeline."""
    atom: ContentAtom
    lost_at_stage: int         # 1, 2, 3, 5, or 6
    stage_name: str
    reason: str                # Human-readable explanation
    present_in_stages: list[int]  # Stages where it WAS found


STAGE_NAMES = {
    1: "Media Extraction",
    2: "Document Conversion",
    3: "Native Google Extraction",
    5: "Consolidation",
    6: "KB Build",
}


def _load_stage1_data(media_dir):
    """Load extraction_metadata.json — images and links from Stage 1."""
    meta_path = Path(media_dir) / "extraction_metadata.json"
    if not meta_path.exists():
        return {"links": [], "images": []}

    with open(meta_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    links = []
    images = []
    for pptx_entry in data.get("pptx_files", []):
        for link in pptx_entry.get("links", []):
            links.append(link.get("url", "").strip().lower())
        for img in pptx_entry.get("images", []):
            images.append(img.get("original_media_name", "").lower())

    return {"links": links, "images": images}


def _load_stage2_content(converted_dir):
    """Load all converted markdown AND csv content from Stage 2."""
    content_set = set()
    converted = Path(converted_dir)
    if not converted.exists():
        return content_set

    for f in converted.rglob("*"):
        if f.suffix.lower() not in (".md", ".csv"):
            continue
        try:
            text = f.read_text(encoding="utf-8")
            for para in text.split("\n"):
                para = para.strip()
                if len(para) >= 10:
                    content_set.add(normalize_text(para))
        except Exception:
            continue

    return content_set


def _load_stage3_content(native_dir):
    """Load content from native Google API extracts."""
    content_set = set()
    links = set()
    native = Path(native_dir)
    if not native.exists():
        return content_set, links

    for json_file in native.rglob("*.json"):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Handle combined extractions file
            extractions = data.get("extractions", [data])

            for ext in extractions:
                # Google Doc content blocks
                for block in ext.get("content_blocks", []):
                    text = block.get("text", "").strip()
                    if len(text) >= 10:
                        content_set.add(normalize_text(text))

                # Top-level links
                for link in ext.get("links", []):
                    url = link.get("url", "").strip().lower() if isinstance(link, dict) else str(link).lower()
                    if url:
                        links.add(url)

                # Slides — "texts" key (list of strings), not "elements"
                for slide in ext.get("slides", []):
                    for text in slide.get("texts", []):
                        text = str(text).strip()
                        if len(text) >= 10:
                            content_set.add(normalize_text(text))
                    # Fallback: elements key
                    for elem in slide.get("elements", []):
                        text = elem.get("text", "").strip() if isinstance(elem, dict) else str(elem).strip()
                        if len(text) >= 10:
                            content_set.add(normalize_text(text))
                    notes = slide.get("speaker_notes", "").strip()
                    if len(notes) >= 10:
                        content_set.add(normalize_text(notes))
                    # Per-slide links
                    for link in slide.get("links", []):
                        url = link.get("url", "").strip().lower() if isinstance(link, dict) else str(link).lower()
                        if url:
                            links.add(url)

                # Google Sheet rows
                for sheet in ext.get("sheets", []):
                    for row in sheet.get("rows", []) or sheet.get("data", []):
                        if isinstance(row, (list, tuple)):
                            for cell in row:
                                cell_text = str(cell).strip()
                                if len(cell_text) >= 10:
                                    content_set.add(normalize_text(cell_text))

        except Exception:
            continue

    return content_set, links


def _load_stage5_content(consolidated_dir):
    """Load consolidated JSON content."""
    content_set = set()
    links = set()
    consolidated = Path(consolidated_dir)
    if not consolidated.exists():
        return content_set, links

    for json_file in consolidated.glob("consolidated_term*.json"):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Walk all string values in the consolidated data
            _collect_strings(data, content_set, links)
        except Exception:
            continue

    return content_set, links


def _collect_strings(obj, content_set, links):
    """Recursively collect all string content from a nested data structure."""
    if isinstance(obj, str):
        stripped = obj.strip()
        if len(stripped) >= 10:
            content_set.add(normalize_text(stripped))
        # Check for URLs
        if re.match(r"https?://", stripped, re.IGNORECASE):
            links.add(stripped.lower())
    elif isinstance(obj, dict):
        for v in obj.values():
            _collect_strings(v, content_set, links)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _collect_strings(item, content_set, links)


def _is_in_content(atom: ContentAtom, content_set: set, link_set: set = None) -> bool:
    """Check if an atom's content appears in a stage's output."""
    norm = normalize_text(atom.content)

    if atom.atom_type in ("link", "video_url"):
        url = atom.content.strip().lower().rstrip("/")
        if link_set and url in link_set:
            return True
        # Also check in content set
        if norm in content_set:
            return True
        # Substring check
        for item in (link_set or set()):
            if url in item or item in url:
                return True
        return False

    if atom.atom_type == "image":
        media_name = normalize_text(atom.content)
        return any(media_name in item for item in content_set)

    # Text-based: check if normalized content is a substring of any content item
    if norm in content_set:
        return True
    # Substring containment
    for item in content_set:
        if norm in item or item in norm:
            return True
    return False


def attribute_losses(unmatched_atoms: list[ContentAtom],
                     media_dir, converted_dir, native_dir,
                     consolidated_dir, output_dir) -> list[Attribution]:
    """For each unmatched atom, determine which pipeline stage lost it."""
    # Load stage outputs
    stage1 = _load_stage1_data(media_dir)
    stage1_links = set(stage1["links"])
    stage1_images = set(stage1["images"])

    stage2_content = _load_stage2_content(converted_dir)

    stage3_content, stage3_links = _load_stage3_content(native_dir)

    stage5_content, stage5_links = _load_stage5_content(consolidated_dir)

    attributions = []

    for atom in unmatched_atoms:
        present_in = []

        # Stage 1 check (links and images only)
        if atom.atom_type in ("link", "video_url"):
            url = atom.content.strip().lower().rstrip("/")
            if any(url in l or l in url for l in stage1_links):
                present_in.append(1)
        elif atom.atom_type == "image":
            media_name = atom.content.lower()
            if media_name in stage1_images:
                present_in.append(1)

        # Stage 2 check
        if _is_in_content(atom, stage2_content):
            present_in.append(2)

        # Stage 3 check
        if _is_in_content(atom, stage3_content, stage3_links):
            present_in.append(3)

        # Stage 5 check
        if _is_in_content(atom, stage5_content, stage5_links):
            present_in.append(5)

        # Determine where it was lost
        if not present_in:
            # Never extracted — lost at earliest possible stage
            if atom.atom_type in ("link", "video_url", "image"):
                lost_stage = 1
                reason = f"{atom.atom_type} never extracted from source"
            elif atom.atom_type == "speaker_note":
                lost_stage = 1
                reason = "speaker note content not captured at extraction"
            else:
                lost_stage = 2
                reason = "text content not captured during conversion"
        else:
            last_present = max(present_in)
            # Lost at the next stage after the last one it appeared in
            stage_order = [1, 2, 3, 5, 6]
            idx = stage_order.index(last_present)
            if idx + 1 < len(stage_order):
                lost_stage = stage_order[idx + 1]
            else:
                lost_stage = 6
            reason = f"present in stage {last_present} but missing from KB output"

        attributions.append(Attribution(
            atom=atom,
            lost_at_stage=lost_stage,
            stage_name=STAGE_NAMES.get(lost_stage, f"Stage {lost_stage}"),
            reason=reason,
            present_in_stages=present_in,
        ))

    return attributions
