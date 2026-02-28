"""
Stage 6: LLM-Only KB Builder

For each lesson in consolidated data, sends all source content to the LLM
via kb_entry_prompt.md. LLM returns the complete KB entry JSON.
Python does only: file I/O, LLM API call, write response to disk.
"""

import sys
import json
import re
from pathlib import Path
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")

from config import BASE_DIR, CONSOLIDATED_DIR, OUTPUT_DIR, CONVERTED_DIR, NATIVE_DIR

PROMPTS_DIR = BASE_DIR / "prompts"


def _discover_terms():
    """Glob consolidated files to find which terms exist. Pure I/O."""
    terms = []
    for f in sorted(CONSOLIDATED_DIR.glob("consolidated_term*.json")):
        m = re.search(r"consolidated_term(\d+)\.json$", f.name)
        if m:
            terms.append(int(m.group(1)))
    return terms


def _read_lesson_files(lesson_data):
    """Read and concatenate all document files for a lesson. Pure I/O."""
    parts = []

    for doc in lesson_data.get("documents", []):
        full_path = doc.get("full_path", "")
        if not full_path:
            # Try to resolve from relative path
            rel_path = doc.get("path", "")
            if rel_path:
                full_path = str(CONVERTED_DIR / rel_path)

        if full_path:
            try:
                text = Path(full_path).read_text(encoding="utf-8", errors="replace")
                parts.append(f"=== {doc.get('path', full_path)} ===\n{text}")
            except OSError:
                pass

    # Include native content if referenced
    native_content = lesson_data.get("native_content", [])
    for ext in native_content:
        parts.append(f"=== NATIVE: {ext.get('file_name', 'unknown')} ===\n"
                     + json.dumps(ext, indent=2, ensure_ascii=False)[:5000])

    return "\n\n".join(parts)


def run_build(backend="cli"):
    """For each lesson in consolidated data, call LLM to produce KB entry."""
    print("=" * 60)
    print("  Stage 6: KB Build (LLM)")
    print("=" * 60)
    print()

    from validation.dual_judge.client import create_client
    client = create_client(backend=backend)

    prompt_template = (PROMPTS_DIR / "kb_entry_prompt.md").read_text(encoding="utf-8")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    terms = _discover_terms()
    if not terms:
        print("No consolidated files found. Run consolidate.py first.")
        return None

    for term_num in terms:
        print(f"\nBuilding KB for Term {term_num}...")

        consolidated = json.loads(
            (CONSOLIDATED_DIR / f"consolidated_term{term_num}.json").read_text(encoding="utf-8")
        )
        by_lesson = consolidated.get("by_lesson", {})

        if not by_lesson:
            print(f"  No lesson data for Term {term_num}. Skipping.")
            continue

        lessons_out = []

        for lesson_key in sorted(by_lesson.keys(), key=lambda k: int(k) if k.isdigit() else 0):
            lesson_data = by_lesson[lesson_key]
            source_content = _read_lesson_files(lesson_data)

            if not source_content:
                print(f"  Lesson {lesson_key}: [skip - no source content]")
                continue

            prompt = (prompt_template
                      .replace("{term}", str(term_num))
                      .replace("{lesson}", lesson_key)
                      .replace("{source_content}", source_content[:80000]))

            print(f"  Lesson {lesson_key}: extracting...", end="", flush=True)
            entry = client.call(prompt)

            # Add pipeline metadata
            entry["generated_at"] = datetime.now(timezone.utc).isoformat()
            entry["pipeline_version"] = "5.0"

            lessons_out.append(entry)

            title = entry.get("lesson_title", "?")
            meta = entry.get("metadata", {})
            n_obj = len(meta.get("learning_objectives", []))
            n_kw = len(meta.get("keywords", []))
            print(f' OK "{title}" ({n_obj}obj, {n_kw}kw)')

        # Write KB output file
        output = {
            "term": term_num,
            "total_lessons": len(lessons_out),
            "generated_from": "KB Maintenance Pipeline v5 (LLM-only)",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "lessons": lessons_out,
        }

        out_path = OUTPUT_DIR / f"Term {term_num} - Lesson Based Structure.json"
        out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n  Term {term_num}: {len(lessons_out)} lessons -> {out_path}")

    print("\n" + "=" * 60)
    print("  KB Build Complete")
    print("=" * 60)
    return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LLM-based KB builder")
    parser.add_argument("--backend", choices=["cli", "sdk", "auto"], default="cli",
                        help="LLM backend (default: cli)")
    parser.add_argument("--term", type=int, default=None,
                        help="Build only this term")
    args = parser.parse_args()
    run_build(backend=args.backend)
