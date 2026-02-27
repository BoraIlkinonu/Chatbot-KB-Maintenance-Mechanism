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

from config import BASE_DIR
from validation.dual_judge.client import create_client
from validation.dual_judge.ground_truth import extract_ground_truth

LLM_CACHE_DIR = BASE_DIR / "llm_cache"
PROMPT_TEMPLATE_PATH = BASE_DIR / "llm_extraction_prompt.md"
IMAGE_DESCRIPTIONS_PATH = BASE_DIR / "image_descriptions.json"

# Max lessons per term
TERM_MAX_LESSONS = {1: 24, 2: 14, 3: 24}

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

    # Filter descriptions relevant to this lesson
    lesson_descs = []
    for img_path, desc in descriptions.items():
        path_lower = img_path.lower()
        # Simple heuristic: check if path contains term and lesson references
        if f"term{term}" in path_lower or f"term {term}" in path_lower:
            if f"lesson{lesson_num}" in path_lower.replace(" ", "") or \
               f"lesson {lesson_num}" in path_lower or \
               f"lesson_{lesson_num}" in path_lower:
                lesson_descs.append(f"[Image: {Path(img_path).name}] {desc}")

    if not lesson_descs:
        return source_text

    image_section = "\n\n=== IMAGE DESCRIPTIONS ===\n" + "\n".join(lesson_descs)
    return source_text + image_section


def _validate_extraction(result: dict) -> dict:
    """Ensure extraction has all required fields with correct types."""
    validated = {}
    for field in EXTRACTION_FIELDS:
        value = result.get(field)
        # Determine expected type from field name
        if field in ("lesson_title", "description_of_activities", "slides_summary",
                     "big_question", "uae_link", "activity_type", "grade_band"):
            validated[field] = str(value) if value else ""
        elif field == "teacher_notes":
            # Should be list of {slide, notes} dicts
            if isinstance(value, list):
                validated[field] = value
            else:
                validated[field] = []
        elif field == "videos":
            # Should be list of {url, title, type} dicts
            if isinstance(value, list):
                validated[field] = value
            else:
                validated[field] = []
        else:
            # All other array fields
            if isinstance(value, list):
                validated[field] = [str(v) for v in value if v]
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
    terms = terms or [1, 2, 3]

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
        max_lesson = TERM_MAX_LESSONS.get(term, 24)
        print(f"\nTerm {term} ({max_lesson} lessons):")

        for lesson_num in range(1, max_lesson + 1):
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
