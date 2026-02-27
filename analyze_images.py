"""
Optional image analysis: describe educational images via Claude.

Reads extraction_metadata.json for image paths + context, sends each
image to Claude for description, caches results by content hash.
Output: image_descriptions.json mapping image_path -> description.

Usage:
    python analyze_images.py [--terms 1 2 3] [--backend cli|sdk|auto] [--force]
"""

import sys
import json
import hashlib
import argparse
from pathlib import Path
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")

from config import BASE_DIR, MEDIA_DIR
from validation.dual_judge.client import create_client
from consolidate import extract_term_from_path, extract_lesson_from_path

IMAGE_CACHE_DIR = BASE_DIR / "image_cache"
IMAGE_DESCRIPTIONS_PATH = BASE_DIR / "image_descriptions.json"

# Supported image extensions
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff"}


def _load_image_metadata() -> list[dict]:
    """Load all image paths + context from extraction_metadata.json."""
    meta_path = MEDIA_DIR / "extraction_metadata.json"
    if not meta_path.exists():
        return []

    data = json.loads(meta_path.read_text(encoding="utf-8"))
    images = []

    for pptx_info in data.get("pptx_files", []):
        rel_path = pptx_info.get("relative_path", "")
        term = extract_term_from_path(rel_path)
        lessons = extract_lesson_from_path(rel_path, term=term)

        for img in pptx_info.get("images", []):
            img_path = img.get("image_path", "")
            if not img_path:
                continue
            images.append({
                "image_path": img_path,
                "source_file": rel_path,
                "slide_numbers": img.get("slide_numbers", []),
                "primary_slide": img.get("primary_slide"),
                "term": term,
                "lessons": lessons,
                "source_type": "pptx",
            })

    # Native Slides API images
    native_meta_path = MEDIA_DIR / "native_image_metadata.json"
    if native_meta_path.exists():
        native_data = json.loads(native_meta_path.read_text(encoding="utf-8"))
        for pres_info in native_data.get("presentations", []):
            source_name = pres_info.get("source_name", "")
            term_key = pres_info.get("term", "")
            term = {"term1": 1, "term2": 2, "term3": 3}.get(term_key)
            if term is None:
                term = extract_term_from_path(source_name)
            source_path = pres_info.get("source_path", "") or source_name
            lessons = extract_lesson_from_path(source_path, term=term)

            for img in pres_info.get("images", []):
                img_path = img.get("image_path", "")
                if not img_path:
                    continue
                images.append({
                    "image_path": img_path,
                    "source_file": source_name,
                    "slide_numbers": img.get("slide_numbers", []),
                    "primary_slide": img.get("primary_slide"),
                    "term": term,
                    "lessons": lessons,
                    "source_type": "native_slides",
                })

    return images


def _content_hash(file_path: Path) -> str:
    """SHA-256 hash of file content for cache keying."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_cache() -> dict:
    """Load existing image description cache."""
    cache = {}
    if IMAGE_CACHE_DIR.exists():
        for cache_file in IMAGE_CACHE_DIR.glob("*.json"):
            try:
                entry = json.loads(cache_file.read_text(encoding="utf-8"))
                cache[entry.get("content_hash", "")] = entry
            except (json.JSONDecodeError, OSError):
                pass
    return cache


def _save_cache_entry(content_hash: str, image_path: str, description: str,
                      context: dict):
    """Save a single image description to cache."""
    IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "content_hash": content_hash,
        "image_path": image_path,
        "description": description,
        "term": context.get("term"),
        "lessons": context.get("lessons", []),
        "source_file": context.get("source_file", ""),
        "slide_numbers": context.get("slide_numbers", []),
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }
    cache_path = IMAGE_CACHE_DIR / f"{content_hash[:16]}.json"
    cache_path.write_text(json.dumps(entry, indent=2, ensure_ascii=False),
                          encoding="utf-8")
    return entry


def run_analysis(terms: list[int] | None = None, backend: str = "auto",
                 force: bool = False) -> dict:
    """Analyze images and produce image_descriptions.json.

    Args:
        terms: Restrict to these terms (None = all)
        backend: LLM backend - "cli", "sdk", or "auto"
        force: Re-analyze all images even if cached

    Returns:
        Summary dict with counts
    """
    print("=" * 60)
    print("  Image Analysis (Optional)")
    print("=" * 60)
    print()

    images = _load_image_metadata()
    if terms:
        images = [img for img in images if img.get("term") in terms]

    print(f"Found {len(images)} images to analyze")

    if not images:
        print("No images to analyze.")
        return {"total": 0, "analyzed": 0, "cached": 0, "errors": 0}

    # Load existing cache
    cache = _load_cache()
    print(f"Cache: {len(cache)} existing entries")

    # Create client
    client = create_client(backend=backend)
    print(f"Backend: {type(client).__name__}")

    analyzed = 0
    cached = 0
    errors = 0
    descriptions = {}

    for i, img_info in enumerate(images, 1):
        img_path_str = img_info["image_path"]
        img_path = Path(img_path_str)

        # Resolve relative paths against BASE_DIR
        if not img_path.is_absolute():
            img_path = BASE_DIR / img_path

        if not img_path.exists():
            continue

        # Check extension
        if img_path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue

        # Check cache
        content_hash = _content_hash(img_path)
        if not force and content_hash in cache:
            descriptions[img_path_str] = cache[content_hash]["description"]
            cached += 1
            continue

        # Build context prompt
        term = img_info.get("term", "?")
        lessons = img_info.get("lessons", [])
        slide = img_info.get("primary_slide", "?")
        source = img_info.get("source_file", "?")

        prompt = (
            f"This image is from Term {term}, "
            f"Lesson(s) {', '.join(str(l) for l in lessons) if lessons else '?'}, "
            f"Slide {slide}, file: {source}. "
            f"Describe its educational content: what it shows, "
            f"content type (diagram/chart/photo/screenshot/table/illustration), "
            f"and any text visible in the image. "
            f"Keep the description concise (2-4 sentences)."
        )

        print(f"  [{i}/{len(images)}] {img_path.name}...", end="", flush=True)

        try:
            result = client.image_call(prompt, str(img_path))
            description = result.get("description", "")
            _save_cache_entry(content_hash, img_path_str, description, img_info)
            descriptions[img_path_str] = description
            analyzed += 1
            print(f" OK ({len(description)} chars)")
        except Exception as e:
            errors += 1
            print(f" ERROR: {e}")

    # Write consolidated output
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_images": len(images),
        "analyzed": analyzed,
        "cached": cached,
        "errors": errors,
        "descriptions": descriptions,
    }
    IMAGE_DESCRIPTIONS_PATH.write_text(
        json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\nResults: {analyzed} analyzed, {cached} cached, {errors} errors")
    print(f"Output: {IMAGE_DESCRIPTIONS_PATH}")

    return {
        "total": len(images),
        "analyzed": analyzed,
        "cached": cached,
        "errors": errors,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze lesson images via Claude")
    parser.add_argument("--terms", type=int, nargs="+", default=None,
                        help="Terms to analyze (default: all)")
    parser.add_argument("--backend", choices=["cli", "sdk", "auto"], default="auto",
                        help="LLM backend (default: auto-detect)")
    parser.add_argument("--force", action="store_true",
                        help="Re-analyze all images even if cached")
    args = parser.parse_args()

    run_analysis(terms=args.terms, backend=args.backend, force=args.force)
