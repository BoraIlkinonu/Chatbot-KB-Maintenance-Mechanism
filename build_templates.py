"""
Templates KB Builder
Identifies assessment template files from the Drive folder scan, downloads/extracts
their content, and generates structured metadata matching the Templates sheet schema.

Actual template files found in Drive folders:
  Term 1:
    - Pitch Rubric.pptx (shortcut)
    - Students Assessment Templates (Google Doc)
    - US Curriculum Assessment Guide - Term 1 (PDF)
    - Pitch and Student Rubric links (Google Doc)
    - Endstar Level Design - Teacher Rubric (Google Doc)
  Term 2:
    - TERM 2 ASSESSMENT - STUDENT GUIDE.docx + PDF
    - TERM 2 ASSESSMENT - TEACHER (PORTFOLIO + GAME) (Google Doc) + PDF
    - Activities & Portfolio Deck (PPTX, 35MB)

Output schema matches existing Templates sheet:
  { "file": "<drive link>", "metadata": { ... } }
"""

import sys
import json
import re
from pathlib import Path
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")

from config import SOURCES_DIR, CONVERTED_DIR, NATIVE_DIR, OUTPUT_DIR, BASE_DIR


# ──────────────────────────────────────────────────────────
# Template identification rules (by file name/path)
# ──────────────────────────────────────────────────────────

TEMPLATE_RULES = [
    {
        "name_patterns": [r"portfolio\s*deck", r"activities.*portfolio"],
        "component": "assessment",
        "default_weight": 25,
        "label": "Student Portfolio",
    },
    {
        "name_patterns": [r"pitch\s*rubric", r"pitch.*student", r"showcase"],
        "component": "showcase",
        "default_weight": 25,
        "label": "Pitch / Showcase",
    },
    {
        "name_patterns": [
            r"rubric", r"assessment.*guide", r"assessment.*teacher",
            r"assessment.*student", r"level\s*design.*rubric",
        ],
        "component": "summative-product",
        "default_weight": 50,
        "label": "Assessment / Rubric",
    },
]

# Path patterns to skip (non-template files that match keywords)
SKIP_PATTERNS = [r"exemplar", r"design\s*brief"]


def classify_template(name, path):
    """Classify a file as a template type. Returns rule dict or None."""
    combined = f"{name} {path}".lower()

    for skip in SKIP_PATTERNS:
        if re.search(skip, combined, re.IGNORECASE):
            return None

    for rule in TEMPLATE_RULES:
        for pattern in rule["name_patterns"]:
            if re.search(pattern, combined, re.IGNORECASE):
                return rule

    return None


# ──────────────────────────────────────────────────────────
# Template discovery from Drive scan
# ──────────────────────────────────────────────────────────

def find_templates_in_scan():
    """Find template files from drive_folder_structure.json."""
    scan_path = BASE_DIR / "drive_folder_structure.json"
    if not scan_path.exists():
        return []

    with open(scan_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    templates = []

    def walk(node, folder_path=""):
        name = node.get("name", "")
        current_path = f"{folder_path}/{name}" if folder_path else name

        if node.get("type") == "file":
            rule = classify_template(name, current_path)
            if rule:
                templates.append({
                    "drive_id": node.get("drive_id", ""),
                    "name": name,
                    "path": current_path,
                    "mime_type": node.get("mime_type", ""),
                    "is_native_google": node.get("is_native_google", False),
                    "native_type": node.get("native_type"),
                    "web_link": node.get("web_view_link", "") or node.get("web_link", ""),
                    "size": node.get("size_bytes", 0),
                    "modified_time": node.get("modified_time", ""),
                    "rule": rule,
                })

        for child in node.get("children", []):
            walk(child, current_path)

    for folder in data.get("folders", []):
        walk(folder)

    return templates


def find_templates_in_sources():
    """Find template files from downloaded sources directory."""
    templates = []

    if not SOURCES_DIR.exists():
        return templates

    for f in SOURCES_DIR.rglob("*"):
        if not f.is_file() or f.name.startswith("~$"):
            continue

        rule = classify_template(f.name, str(f))
        if rule:
            templates.append({
                "name": f.name,
                "path": str(f),
                "local_path": str(f),
                "rule": rule,
            })

    return templates


# ──────────────────────────────────────────────────────────
# Content extraction from converted/native files
# ──────────────────────────────────────────────────────────

def find_converted_content(template_name):
    """Find converted markdown/CSV content for a template file."""
    if not CONVERTED_DIR.exists():
        return ""

    # Normalize for matching
    normalized = template_name.lower().replace(" ", "").replace("-", "").replace("_", "")

    for f in CONVERTED_DIR.rglob("*"):
        if not f.is_file():
            continue
        f_normalized = f.stem.lower().replace(" ", "").replace("-", "").replace("_", "")
        if normalized[:20] in f_normalized or f_normalized[:20] in normalized:
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    return fh.read()
            except Exception:
                pass

    return ""


def find_native_content(drive_id):
    """Find native Google API extraction for a template file."""
    native_path = NATIVE_DIR / "native_extractions.json"
    if not native_path.exists():
        return None

    with open(native_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for extraction in data.get("extractions", []):
        if extraction.get("drive_id") == drive_id or extraction.get("file_id") == drive_id:
            return extraction

    return None


# ──────────────────────────────────────────────────────────
# Metadata generation
# ──────────────────────────────────────────────────────────

def extract_purpose(content):
    """Extract a purpose/description from content text."""
    for line in content.split("\n"):
        stripped = line.strip()
        # Skip table rows, headers, short lines
        if stripped.startswith("|") or stripped.startswith("#") or len(stripped) < 40:
            continue
        # Return first substantial paragraph
        return stripped[:500]
    return ""


def extract_skills_and_criteria(content):
    """Extract core skills and assessment criteria from content."""
    skills = []
    criteria = []

    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue

        # Bullet items
        if stripped.startswith("-") or stripped.startswith("•") or stripped.startswith("*"):
            item = stripped.lstrip("-•*").strip()
            if len(item) < 10:
                continue

            item_lower = item.lower()
            if any(kw in item_lower for kw in [
                "skill", "able to", "demonstrate", "create", "design",
                "develop", "build", "communicate", "collaborate", "iterate"
            ]):
                skills.append(item)
            elif any(kw in item_lower for kw in [
                "criteria", "must", "should", "evidence", "grade",
                "mark", "score", "level", "band", "rubric", "submit"
            ]):
                criteria.append(item)

        # Table cells often contain criteria
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            for cell in cells:
                if len(cell) > 20 and any(kw in cell.lower() for kw in [
                    "basic", "intermediate", "advanced", "emerging", "proficient"
                ]):
                    criteria.append(cell)

    return skills[:10], criteria[:10]


def extract_from_native(native_data):
    """Extract text content from native Google API data."""
    if not native_data:
        return ""

    parts = []
    ntype = native_data.get("native_type", "")

    if ntype == "google_doc":
        for block in native_data.get("content_blocks", []):
            if block.get("type") == "paragraph":
                parts.append(block.get("text", ""))
            elif block.get("type") == "table":
                for row in block.get("rows", []):
                    parts.append(" | ".join(row))

    elif ntype == "google_slides":
        for slide in native_data.get("slides", []):
            for text in slide.get("texts", []):
                parts.append(text)
            if slide.get("speaker_notes"):
                parts.append(slide["speaker_notes"])

    elif ntype == "google_sheet":
        for sheet in native_data.get("sheets", []):
            if sheet.get("headers"):
                parts.append(" | ".join(sheet["headers"]))
            for row in sheet.get("rows", []):
                parts.append(" | ".join(row))

    return "\n".join(parts)


def determine_term(path):
    """Determine which term a template belongs to from its path."""
    path_lower = path.lower()
    if "term 1" in path_lower or "term1" in path_lower or "foundations" in path_lower:
        return 1
    elif "term 2" in path_lower or "term2" in path_lower or "accelerator" in path_lower:
        return 2
    elif "term 3" in path_lower or "term3" in path_lower or "mastery" in path_lower:
        return 3
    return None


def build_template_entry(template):
    """Build a single template metadata entry."""
    rule = template["rule"]
    name = template["name"]
    stem = Path(name).stem

    # Gather content from all available sources
    content = find_converted_content(stem)
    native = find_native_content(template.get("drive_id", ""))
    if native:
        native_text = extract_from_native(native)
        content = content + "\n" + native_text if content else native_text

    # Generate slug
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")

    # Determine term
    term = determine_term(template.get("path", ""))

    # Extract from content
    purpose = extract_purpose(content) if content else ""
    skills, criteria = extract_skills_and_criteria(content) if content else ([], [])

    # Build linked lessons based on term
    if term == 1:
        linked_lessons = [f"Lesson {i}" for i in range(1, 25)]
    elif term == 2:
        linked_lessons = [f"Lesson {i}" for i in range(1, 13)]
    else:
        linked_lessons = []

    # File link: prefer Drive web link, fall back to local path
    file_link = template.get("web_link", "") or template.get("local_path", "") or template.get("path", "")

    metadata = {
        "id": slug,
        "template_name": stem,
        "programme_component": rule["component"],
        "purpose": purpose if purpose else f"{rule['label']} template for the Explorer's Programme",
        "weighting_percent": rule["default_weight"],
        "linked_lessons": linked_lessons,
        "core_skills": skills,
        "assessment_criteria_summary": {
            "items": criteria,
        },
        "term": term,
        "source_drive_id": template.get("drive_id", ""),
        "modified_time": template.get("modified_time", ""),
    }

    return {
        "file": file_link,
        "metadata": metadata,
    }


# ──────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────

def run_build_templates():
    """Build Templates KB from Drive folder files."""
    print("=" * 60)
    print("  Templates KB Builder")
    print("=" * 60)
    print()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Find template files from Drive scan
    print("Scanning Drive folder structure...")
    drive_templates = find_templates_in_scan()
    print(f"  Found {len(drive_templates)} templates in Drive scan")

    # Also check downloaded sources
    print("Scanning downloaded sources...")
    local_templates = find_templates_in_sources()
    print(f"  Found {len(local_templates)} templates in local sources")

    # Merge (prefer Drive scan for metadata, use local for content)
    all_templates = drive_templates if drive_templates else local_templates

    if not all_templates:
        print("\nNo template files found.")
        return None

    # Group by term
    by_term = {}
    for t in all_templates:
        term = determine_term(t.get("path", ""))
        by_term.setdefault(term, []).append(t)

    print(f"\nTemplates by term:")
    for term, items in sorted(by_term.items(), key=lambda x: x[0] or 99):
        term_label = f"Term {term}" if term else "Unknown"
        print(f"  {term_label}: {len(items)} files")
        for item in items:
            component = item["rule"]["label"]
            print(f"    [{component}] {item['name']}")

    # Build metadata for each template
    print("\nBuilding template metadata...")
    results = []
    for t in all_templates:
        print(f"  Processing: {t['name']}")
        entry = build_template_entry(t)
        results.append(entry)

    # Save per-term and combined
    combined = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_templates": len(results),
        "templates": results,
    }

    output_path = OUTPUT_DIR / "templates.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(combined, f, indent=2, ensure_ascii=False)

    # Also save per-term
    for term, items in by_term.items():
        if term is None:
            continue
        term_results = [build_template_entry(t) for t in items]
        term_output = OUTPUT_DIR / f"Term {term} - Templates.json"
        with open(term_output, "w", encoding="utf-8") as f:
            json.dump({
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "term": term,
                "total_templates": len(term_results),
                "templates": term_results,
            }, f, indent=2, ensure_ascii=False)
        print(f"  Saved: {term_output}")

    print(f"\nAll templates saved: {output_path}")
    print(f"Total: {len(results)} templates")
    print("=" * 60)

    return combined


if __name__ == "__main__":
    run_build_templates()
