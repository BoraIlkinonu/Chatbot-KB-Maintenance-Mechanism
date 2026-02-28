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

from config import SOURCES_DIR, CONVERTED_DIR, NATIVE_DIR, OUTPUT_DIR, BASE_DIR, CONSOLIDATED_DIR
from consolidate import get_file_classification

PROMPTS_DIR = BASE_DIR / "prompts"


# ──────────────────────────────────────────────────────────
# Template identification via LLM (with regex fallback)
# ──────────────────────────────────────────────────────────

def classify_template(name, path):
    """Classify a file as a template type. Returns rule dict or None.

    Tries LLM classification first, falls back to regex patterns.
    """
    # Regex fallback (fast, no LLM needed for basic matching)
    combined = f"{name} {path}".lower()

    # Skip non-template files
    if re.search(r"exemplar|design\s*brief", combined, re.IGNORECASE):
        return None

    if re.search(r"portfolio\s*deck|activities.*portfolio", combined, re.IGNORECASE):
        return {"component": "assessment", "default_weight": 25, "label": "Student Portfolio"}
    if re.search(r"pitch\s*rubric|pitch.*student|showcase", combined, re.IGNORECASE):
        return {"component": "showcase", "default_weight": 25, "label": "Pitch / Showcase"}
    if re.search(r"rubric|assessment.*guide|assessment.*teacher|assessment.*student|level\s*design.*rubric", combined, re.IGNORECASE):
        return {"component": "summative-product", "default_weight": 50, "label": "Assessment / Rubric"}

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

def classify_template_via_llm(name, path, content):
    """Classify template and extract metadata via LLM.

    Returns dict with {is_template, component, purpose, skills, criteria, weighting}
    or None if LLM is unavailable.
    """
    try:
        prompt_path = PROMPTS_DIR / "template_metadata_prompt.md"
        template = prompt_path.read_text(encoding="utf-8")
        prompt = (template
                  .replace("{file_name}", name)
                  .replace("{file_path}", path)
                  .replace("{content}", (content or "")[:8000]))

        from validation.dual_judge.client import create_client
        client = create_client(backend="cli")
        result = client.call(prompt)
        return result
    except Exception:
        return None


def extract_purpose(content):
    """Extract a purpose/description from content text via LLM fallback."""
    if not content:
        return ""
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("|") or stripped.startswith("#") or len(stripped) < 40:
            continue
        return stripped[:500]
    return ""


def extract_skills_and_criteria(content):
    """Extract core skills and assessment criteria from content via LLM fallback."""
    if not content:
        return [], []
    skills = []
    criteria = []
    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("-", "•", "*")):
            item = stripped.lstrip("-•*").strip()
            if len(item) < 10:
                continue
            item_lower = item.lower()
            if any(kw in item_lower for kw in ["skill", "able to", "demonstrate", "create", "design",
                                                 "develop", "build", "communicate", "collaborate", "iterate"]):
                skills.append(item)
            elif any(kw in item_lower for kw in ["criteria", "must", "should", "evidence", "grade",
                                                   "mark", "score", "level", "band", "rubric", "submit"]):
                criteria.append(item)
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
    """Determine which term a template belongs to from its path.

    Uses LLM classification cache, falls back to regex.
    """
    cls = get_file_classification(path)
    return cls.get("term")


def _discover_lesson_nums(term):
    """Discover lesson numbers for a term from consolidated or KB data."""
    # Try consolidated data first
    cons_path = CONSOLIDATED_DIR / f"consolidated_term{term}.json"
    if cons_path.exists():
        try:
            data = json.loads(cons_path.read_text(encoding="utf-8"))
            return sorted(int(k) for k in data.get("by_lesson", {}).keys())
        except Exception:
            pass
    # Fall back to KB output
    kb_path = OUTPUT_DIR / f"Term {term} - Lesson Based Structure.json"
    if kb_path.exists():
        try:
            data = json.loads(kb_path.read_text(encoding="utf-8"))
            return sorted(
                l.get("metadata", {}).get("lesson_id", 0)
                for l in data.get("lessons", [])
                if l.get("metadata", {}).get("lesson_id")
            )
        except Exception:
            pass
    return []


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

    # Try LLM-based metadata extraction first
    llm_meta = classify_template_via_llm(name, template.get("path", ""), content)

    if llm_meta and llm_meta.get("is_template", True):
        purpose = llm_meta.get("purpose", "")
        skills = llm_meta.get("skills", [])
        criteria = llm_meta.get("criteria", [])
        if llm_meta.get("component"):
            rule = {**rule, "component": llm_meta["component"]}
        if llm_meta.get("weighting") is not None:
            rule = {**rule, "default_weight": llm_meta["weighting"]}
    else:
        # Fallback: regex-based extraction
        purpose = extract_purpose(content) if content else ""
        skills, criteria = extract_skills_and_criteria(content) if content else ([], [])

    # Discover linked lessons from consolidated/KB data
    linked_lessons = []
    if term is not None:
        lesson_nums = _discover_lesson_nums(term)
        linked_lessons = [f"Lesson {i}" for i in lesson_nums]

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
        print("\nNo template files found. Ensure assessment/rubric files exist in sources/.")
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
