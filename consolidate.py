"""
Stage 5: LLM-Only Content Consolidation

Sends all converted file paths + content previews to the LLM.
LLM returns the complete consolidated JSON — which files belong to
which lessons, content types, links, and video references.
Python does only: file I/O, LLM API call, write response to disk.
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")

from config import BASE_DIR, CONVERTED_DIR, NATIVE_DIR, CONSOLIDATED_DIR

PROMPTS_DIR = BASE_DIR / "prompts"


def run_consolidation(backend="cli"):
    """Send all file info to LLM, write response to consolidated JSON."""
    print("=" * 60)
    print("  Stage 5: Consolidation (LLM)")
    print("=" * 60)
    print()

    from validation.dual_judge.client import create_client
    client = create_client(backend=backend)

    prompt_template = (PROMPTS_DIR / "consolidation_prompt.md").read_text(encoding="utf-8")
    CONSOLIDATED_DIR.mkdir(parents=True, exist_ok=True)

    term_dirs = sorted(d for d in CONVERTED_DIR.iterdir() if d.is_dir())
    if not term_dirs:
        print("No converted term directories found. Run convert_docs.py first.")
        return None

    for term_dir in term_dirs:
        term_key = term_dir.name  # "term1", "term2", "term3"
        term_num = term_key.replace("term", "")

        # Gather all file paths + first 500 chars of content
        file_info = []
        for f in sorted(term_dir.rglob("*")):
            if not f.is_file():
                continue
            try:
                content_preview = f.read_text(encoding="utf-8", errors="replace")[:500]
            except Exception:
                content_preview = ""
            file_info.append({
                "path": str(f.relative_to(CONVERTED_DIR)),
                "preview": content_preview,
            })

        if not file_info:
            print(f"  {term_key}: no files found, skipping")
            continue

        # Load native extractions for this term
        native_content = ""
        native_path = NATIVE_DIR / "native_extractions.json"
        if native_path.exists():
            try:
                all_native = json.loads(native_path.read_text(encoding="utf-8"))
                # Filter to this term's extractions
                term_extractions = [
                    ext for ext in all_native.get("extractions", [])
                    if ext.get("term") == term_key
                ]
                if term_extractions:
                    native_content = json.dumps(term_extractions, indent=2, ensure_ascii=False)[:10000]
            except (json.JSONDecodeError, OSError):
                pass

        prompt = (prompt_template
                  .replace("{term_key}", term_key)
                  .replace("{term_num}", str(term_num))
                  .replace("{file_list}", json.dumps(file_info, indent=2, ensure_ascii=False))
                  .replace("{native_extractions}", native_content or "[]"))

        print(f"  {term_key}: {len(file_info)} files -> LLM...", end="", flush=True)
        result = client.call(prompt)

        # Ensure required structure
        if "by_lesson" not in result:
            result["by_lesson"] = {}
        if "term_resources" not in result:
            result["term_resources"] = []
        if "term" not in result:
            result["term"] = int(term_num) if term_num.isdigit() else term_num

        # Add full_path to each document for downstream file reading
        for lesson_key, lesson_data in result.get("by_lesson", {}).items():
            for doc in lesson_data.get("documents", []):
                doc["full_path"] = str(CONVERTED_DIR / doc.get("path", ""))

        result["consolidated_at"] = datetime.now(timezone.utc).isoformat()

        out_path = CONSOLIDATED_DIR / f"consolidated_{term_key}.json"
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        lesson_count = len(result.get("by_lesson", {}))
        resource_count = len(result.get("term_resources", []))
        print(f" OK ({lesson_count} lessons, {resource_count} resources)")

    print()
    print("=" * 60)
    print("  Consolidation Complete")
    print("=" * 60)
    return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LLM-based consolidation")
    parser.add_argument("--backend", choices=["cli", "sdk", "auto"], default="cli",
                        help="LLM backend (default: cli)")
    args = parser.parse_args()
    run_consolidation(backend=args.backend)
