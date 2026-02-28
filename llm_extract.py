"""
LLM-based KB extraction: Claude reads source text and returns structured JSON.

Reuses:
  - validation/dual_judge/client.py → create_client(), SdkClient/CliClient
  - validation/dual_judge/ground_truth.py → extract_ground_truth()

Each lesson's extraction is cached by source content SHA-256 hash.
Only re-extracts when source content changes.

Usage:
    python llm_extract.py [--terms 1 2 3] [--backend cli|sdk|auto] [--force]
"""

import sys
import json
import hashlib
import argparse
from pathlib import Path
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")

from config import BASE_DIR, CONSOLIDATED_DIR
from validation.dual_judge.client import create_client
from validation.dual_judge.ground_truth import extract_ground_truth

LLM_CACHE_DIR = BASE_DIR / "llm_cache"
PROMPT_TEMPLATE_PATH = BASE_DIR / "llm_extraction_prompt.md"
IMAGE_DESCRIPTIONS_PATH = BASE_DIR / "image_descriptions.json"

# All 19 LLM-extracted fields (grade_band is 19th, document_sources is assembly metadata)
EXTRACTION_FIELDS = [
    "lesson_title", "learning_objectives", "description_of_activities",
    "core_topics", "teacher_notes", "slides_summary", "videos", "resources",
    "success_criteria", "big_question", "uae_link", "endstar_tools",
    "keywords", "activity_type", "assessment_signals",
    "curriculum_alignment", "ai_focus", "artifacts", "grade_band",
]


def _load_prompt_template() -> str:
    """Load the extraction prompt template."""
    return PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")


def _load_image_descriptions() -> dict:
    """Load image descriptions if available (from analyze_images.py)."""
    if not IMAGE_DESCRIPTIONS_PATH.exists():
        return {}
    try:
        data = json.loads(IMAGE_DESCRIPTIONS_PATH.read_text(encoding="utf-8"))
        return data.get("descriptions", {})
    except (json.JSONDecodeError, OSError):
        return {}


def _source_hash(text: str) -> str:
    """SHA-256 hash of source text for cache invalidation."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_cached(cache_path: Path) -> tuple[dict | None, str]:
    """Load cached extraction result. Returns (result, stored_hash)."""
    if not cache_path.exists():
        return None, ""
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        return data.get("extraction"), data.get("source_hash", "")
    except (json.JSONDecodeError, OSError):
        return None, ""


def _save_cached(cache_path: Path, extraction: dict, source_hash: str,
                 term: int, lesson_num: int):
    """Save extraction result to cache."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "term": term,
        "lesson_num": lesson_num,
        "source_hash": source_hash,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "extraction": extraction,
    }
    cache_path.write_text(json.dumps(entry, indent=2, ensure_ascii=False),
                          encoding="utf-8")


def _append_image_descriptions(source_text: str, term: int,
                                lesson_num: int) -> str:
    """Append image descriptions to source text if available."""
    descriptions = _load_image_descriptions()
    if not descriptions:
        return source_text

    # Filter descriptions relevant to this lesson using consolidated classification
    from consolidate import get_file_classification
    lesson_descs = []
    for img_path, desc in descriptions.items():
        cls = get_file_classification(img_path)
        img_term = cls.get("term")
        img_lessons = cls.get("lessons", [])
        if img_term == term and lesson_num in img_lessons:
            lesson_descs.append(f"[Image: {Path(img_path).name}] {desc}")

    if not lesson_descs:
        return source_text

    image_section = "\n\n=== IMAGE DESCRIPTIONS ===\n" + "\n".join(lesson_descs)
    return source_text + image_section


# Expected types for extraction fields: "str" or "list"
_FIELD_TYPES = {
    "lesson_title": "str",
    "learning_objectives": "list",
    "description_of_activities": "str",
    "core_topics": "list",
    "teacher_notes": "list",
    "slides_summary": "str",
    "videos": "list",
    "resources": "list",
    "success_criteria": "list",
    "big_question": "str",
    "uae_link": "str",
    "endstar_tools": "list",
    "keywords": "list",
    "activity_type": "str",
    "assessment_signals": "list",
    "curriculum_alignment": "list",
    "ai_focus": "list",
    "artifacts": "list",
    "grade_band": "str",
}


def _validate_extraction(result: dict) -> dict:
    """Ensure extraction has all required fields with correct types.

    Uses schema-driven validation — no per-field if-elif chains.
    """
    validated = {}
    for field in EXTRACTION_FIELDS:
        value = result.get(field)
        expected = _FIELD_TYPES.get(field, "list")
        if expected == "str":
            validated[field] = str(value) if value else ""
        else:  # "list"
            if isinstance(value, list):
                validated[field] = value
            elif isinstance(value, str) and value:
                validated[field] = [value]
            else:
                validated[field] = []
    return validated


def extract_lesson(term: int, lesson_num: int, client, template: str) -> dict:
    """Extract all KB fields for a single lesson via LLM.

    Args:
        term: Term number
        lesson_num: Lesson number
        client: LLM client instance
        template: Prompt template with {source_content} placeholder

    Returns:
        Dict with all 19 extraction fields
    """
    source_text = extract_ground_truth(term, lesson_num)
    source_text = _append_image_descriptions(source_text, term, lesson_num)

    prompt = template.replace("{source_content}", source_text)
    result = client.call(prompt)
    return _validate_extraction(result)


def _discover_lessons(term: int) -> list[int]:
    """Discover which lessons exist for a term from consolidated data.

    Reads consolidated_term{N}.json to find actual lesson numbers.
    No hardcoded counts — the source files determine what exists.
    """
    consolidated_path = CONSOLIDATED_DIR / f"consolidated_term{term}.json"
    if not consolidated_path.exists():
        print(f"  WARNING: {consolidated_path} not found")
        return []

    try:
        data = json.loads(consolidated_path.read_text(encoding="utf-8"))
        by_lesson = data.get("by_lesson", {})
        return sorted(int(k) for k in by_lesson.keys())
    except (json.JSONDecodeError, OSError) as e:
        print(f"  WARNING: Could not read {consolidated_path}: {e}")
        return []


def _discover_terms() -> list[int]:
    """Discover which terms exist from consolidated files.

    No hardcoded term list — scans for consolidated_term*.json files.
    """
    terms = []
    for f in sorted(CONSOLIDATED_DIR.glob("consolidated_term*.json")):
        try:
            term_num = int(f.stem.replace("consolidated_term", ""))
            terms.append(term_num)
        except ValueError:
            continue
    return terms


def run_extraction(terms: list[int] | None = None, backend: str = "auto",
                   force: bool = False) -> dict:
    """Run LLM extraction for all lessons across specified terms.

    Args:
        terms: Which terms to extract (default: [1, 2, 3])
        backend: LLM backend - "cli", "sdk", or "auto"
        force: Re-extract all lessons even if cached

    Returns:
        Summary dict with counts

    Raises:
        RuntimeError: If no LLM backend is available
    """
    terms = terms or _discover_terms()
    if not terms:
        raise RuntimeError("No consolidated term files found. Run consolidation first.")

    print("=" * 60)
    print("  LLM Extraction")
    print("=" * 60)
    print()

    client = create_client(backend=backend)
    print(f"Backend: {type(client).__name__}")

    template = _load_prompt_template()
    LLM_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    extracted = 0
    cached = 0
    errors = 0
    error_details = []

    for term in terms:
        lesson_nums = _discover_lessons(term)
        print(f"\nTerm {term} ({len(lesson_nums)} lessons discovered: {lesson_nums}):")

        for lesson_num in lesson_nums:
            cache_path = LLM_CACHE_DIR / f"term{term}_lesson{lesson_num}.json"

            # Get source text and hash for cache check
            source_text = extract_ground_truth(term, lesson_num)
            if source_text == "[No source content found]":
                print(f"  L{lesson_num}: [skip - no source content]")
                continue

            source_text_with_images = _append_image_descriptions(
                source_text, term, lesson_num
            )
            current_hash = _source_hash(source_text_with_images)

            # Check cache
            if not force:
                cached_result, stored_hash = _load_cached(cache_path)
                if cached_result and stored_hash == current_hash:
                    cached += 1
                    print(f"  L{lesson_num}: [cached]")
                    continue

            # Extract via LLM
            print(f"  L{lesson_num}: extracting...", end="", flush=True)
            try:
                prompt = template.replace("{source_content}", source_text_with_images)
                result = client.call(prompt)
                validated = _validate_extraction(result)
                _save_cached(cache_path, validated, current_hash, term, lesson_num)
                extracted += 1

                # Quick quality check
                has_title = bool(validated.get("lesson_title"))
                n_objectives = len(validated.get("learning_objectives", []))
                print(f" OK (title={'Y' if has_title else 'N'}, obj={n_objectives})")
            except Exception as e:
                errors += 1
                error_details.append(f"T{term}L{lesson_num}: {e}")
                print(f" ERROR: {e}")

    print(f"\nSummary: {extracted} extracted, {cached} cached, {errors} errors")
    print(f"LLM calls: {client.calls_made}")
    print(f"Cache dir: {LLM_CACHE_DIR}")

    return {
        "extracted": extracted,
        "cached": cached,
        "errors": errors,
        "error_details": error_details,
        "calls_made": client.calls_made,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM-based KB extraction")
    parser.add_argument("--terms", type=int, nargs="+", default=None,
                        help="Terms to extract (default: all)")
    parser.add_argument("--backend", choices=["cli", "sdk", "auto"], default="auto",
                        help="LLM backend (default: auto-detect)")
    parser.add_argument("--force", action="store_true",
                        help="Re-extract all lessons even if cached")
    args = parser.parse_args()

    run_extraction(terms=args.terms, backend=args.backend, force=args.force)
