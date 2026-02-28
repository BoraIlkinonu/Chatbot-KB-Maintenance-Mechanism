"""
Templates KB Builder (LLM-Only)

Sends term-resource files to the LLM via template_entry_prompt.md.
LLM decides if each file is a template and returns complete metadata.
Python does only: file I/O, LLM API call, write response to disk.
"""

import sys
import json
import re
from pathlib import Path
from datetime import datetime, timezone

sys.stdout.reconfigure(encoding="utf-8")

from config import BASE_DIR, CONSOLIDATED_DIR, CONVERTED_DIR, OUTPUT_DIR

PROMPTS_DIR = BASE_DIR / "prompts"


def _discover_terms():
    """Find which terms have consolidated data. Pure I/O."""
    terms = []
    for f in sorted(CONSOLIDATED_DIR.glob("consolidated_term*.json")):
        m = re.search(r"consolidated_term(\d+)\.json$", f.name)
        if m:
            terms.append(int(m.group(1)))
    return terms


def _load_consolidated(term_num):
    """Load consolidated JSON for a term. Pure I/O."""
    path = CONSOLIDATED_DIR / f"consolidated_term{term_num}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def run_build_templates(backend="cli"):
    """Send term-resource files to LLM, write template entries."""
    print("=" * 60)
    print("  Templates KB Builder (LLM)")
    print("=" * 60)
    print()

    from validation.dual_judge.client import create_client
    client = create_client(backend=backend)

    prompt_template = (PROMPTS_DIR / "template_entry_prompt.md").read_text(encoding="utf-8")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    terms = _discover_terms()
    if not terms:
        print("No consolidated files found. Run consolidate.py first.")
        return None

    all_templates = []

    for term_num in terms:
        consolidated = _load_consolidated(term_num)
        term_resources = consolidated.get("term_resources", [])

        if not term_resources:
            print(f"  Term {term_num}: no term resources found")
            continue

        print(f"  Term {term_num}: {len(term_resources)} term-resource files")

        for doc in term_resources:
            doc_path = doc.get("path", "")
            full_path = str(CONVERTED_DIR / doc_path) if doc_path else ""

            # Read file content
            content = ""
            if full_path:
                try:
                    content = Path(full_path).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    pass

            if not content:
                continue

            file_name = Path(doc_path).name if doc_path else "unknown"

            prompt = (prompt_template
                      .replace("{file_name}", file_name)
                      .replace("{file_path}", doc_path)
                      .replace("{content}", content[:15000]))

            print(f"    {file_name}...", end="", flush=True)
            result = client.call(prompt)

            if result.get("is_template"):
                # Generate slug for ID
                stem = Path(file_name).stem
                slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")

                template_entry = {
                    "file": doc_path,
                    "metadata": {
                        "id": slug,
                        "template_name": result.get("template_name", stem),
                        "programme_component": result.get("component", "assessment"),
                        "label": result.get("label", ""),
                        "purpose": result.get("purpose", ""),
                        "weighting_percent": result.get("weighting"),
                        "linked_lessons": [
                            f"Lesson {i}" for i in result.get("lessons", [])
                        ],
                        "core_skills": result.get("skills", []),
                        "assessment_criteria_summary": {
                            "items": result.get("criteria", []),
                        },
                        "term": result.get("term", term_num),
                    },
                }
                all_templates.append(template_entry)
                print(f" TEMPLATE [{result.get('component', '?')}]")
            else:
                print(" (not a template)")

    # Write combined output
    combined = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_templates": len(all_templates),
        "templates": all_templates,
    }

    output_path = OUTPUT_DIR / "templates.json"
    output_path.write_text(json.dumps(combined, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  Saved: {output_path} ({len(all_templates)} templates)")

    # Also save per-term files
    by_term = {}
    for t in all_templates:
        term = t["metadata"].get("term")
        by_term.setdefault(term, []).append(t)

    for term, items in by_term.items():
        if term is None:
            continue
        term_output = OUTPUT_DIR / f"Term {term} - Templates.json"
        term_output.write_text(json.dumps({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "term": term,
            "total_templates": len(items),
            "templates": items,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Saved: {term_output}")

    print("\n" + "=" * 60)
    print("  Templates Build Complete")
    print("=" * 60)
    return combined


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LLM-based templates builder")
    parser.add_argument("--backend", choices=["cli", "sdk", "auto"], default="cli",
                        help="LLM backend (default: cli)")
    args = parser.parse_args()
    run_build_templates(backend=args.backend)
