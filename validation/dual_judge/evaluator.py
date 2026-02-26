"""
Evaluator: orchestrates loading KBs, sampling, judging, and reporting.

This is the main entry point for the dual-judge validation system.
"""

import json
from pathlib import Path

from config import OUTPUT_DIR, VALIDATION_DIR
from validation.dual_judge.client import create_client
from validation.dual_judge.ground_truth import extract_ground_truth
from validation.dual_judge.judge import DualJudge
from validation.dual_judge.sampler import sample_lessons
from validation.dual_judge.report import DualJudgeReport


def _load_prompt_template() -> str:
    """Load the dual-judge prompt template."""
    prompt_path = Path(__file__).parent.parent / "dual_judge_prompt.md"
    return prompt_path.read_text(encoding="utf-8")


def _load_kb(term: int) -> dict:
    """Load a term's KB JSON file."""
    kb_path = OUTPUT_DIR / f"Term {term} - Lesson Based Structure.json"
    if not kb_path.exists():
        return {}
    return json.loads(kb_path.read_text(encoding="utf-8"))


def _format_kb_entry(lesson: dict) -> str:
    """Format a KB lesson entry as JSON text for the prompt."""
    # Extract the key fields the judge will evaluate
    meta = lesson.get("metadata", {})
    entry = {
        "lesson_title": lesson.get("lesson_title", ""),
        "learning_objectives": meta.get("learning_objectives", []),
        "description_of_activities": lesson.get("description_of_activities", ""),
        "core_topics": meta.get("core_topics", []),
        "teacher_notes": lesson.get("teacher_notes", []),
        "slides": lesson.get("slides", []),
        "videos": meta.get("videos", []),
        "resources": meta.get("resources", []),
        "success_criteria": lesson.get("success_criteria", []),
        "big_question": lesson.get("big_question", ""),
        "uae_link": lesson.get("uae_link", ""),
        "endstar_tools": meta.get("endstar_tools", []),
        "keywords": meta.get("keywords", []),
        "activity_type": meta.get("activity_type", ""),
        "assessment_signals": meta.get("assessment_signals", []),
        "curriculum_alignment": lesson.get("curriculum_alignment", []),
        "ai_focus": meta.get("ai_focus", []),
        "artifacts": meta.get("artifacts", []),
        "grade_band": meta.get("grade_band", ""),
        "document_sources": lesson.get("document_sources", []),
    }
    return json.dumps(entry, indent=2, ensure_ascii=False)


def _build_all_lessons(terms: list[int]) -> list[dict]:
    """Build a flat list of all lesson dicts with term/lesson metadata."""
    all_lessons = []
    for term in terms:
        kb = _load_kb(term)
        if not kb:
            continue
        lessons = kb.get("lessons", [])
        for lesson in lessons:
            meta = lesson.get("metadata", {})
            lesson_num = meta.get("lesson_id", 0)
            slide_count = len(lesson.get("slides", []))
            all_lessons.append({
                "term": term,
                "lesson_num": lesson_num,
                "slide_count": slide_count,
                "kb_lesson": lesson,
            })
    return all_lessons


def run_dual_judge_validation(
    terms: list[int] | None = None,
    sample_rate: float = 0.25,
    backend: str = "auto",
    seed: int | None = None,
    budget: int = 60,
    verbose: bool = False,
) -> DualJudgeReport:
    """Run dual-LLM judge validation on KB output.

    Args:
        terms: Which terms to validate (default: [1, 2, 3])
        sample_rate: Fraction of lessons to sample (default 0.25)
        backend: LLM backend - "cli", "sdk", or "auto"
        seed: Random seed for reproducible sampling
        budget: Maximum LLM calls allowed
        verbose: Print progress to stdout

    Returns:
        DualJudgeReport with scores, verdicts, and failure details
    """
    terms = terms or [1, 2, 3]
    report = DualJudgeReport()
    report.budget = budget

    # Load LLM client
    try:
        client = create_client(backend=backend, budget=budget)
    except RuntimeError as e:
        if verbose:
            print(f"  [SKIP] No LLM backend available: {e}")
        return report

    if verbose:
        backend_name = type(client).__name__
        print(f"  Backend: {backend_name}")

    # Load all lessons across terms
    all_lessons = _build_all_lessons(terms)
    report.total_lessons = len(all_lessons)

    if verbose:
        print(f"  Total lessons: {report.total_lessons}")

    if not all_lessons:
        if verbose:
            print("  [SKIP] No KB lessons found")
        return report

    # Sample lessons
    sampled = sample_lessons(all_lessons, sample_rate=sample_rate, seed=seed, terms=terms)
    report.sampled_count = len(sampled)

    if verbose:
        terms_repr = ", ".join(
            f"T{t}: {sum(1 for s in sampled if s['term'] == t)}" for t in terms
        )
        print(f"  Sampled: {len(sampled)} lessons ({terms_repr})")

    # Load prompt template
    template = _load_prompt_template()

    # Create judge
    judge = DualJudge(client)

    # Evaluate each sampled lesson
    for i, lesson_info in enumerate(sampled, 1):
        term = lesson_info["term"]
        lesson_num = lesson_info["lesson_num"]
        kb_lesson = lesson_info["kb_lesson"]

        if not client.has_budget():
            if verbose:
                print(f"  [BUDGET] Stopping at lesson {i}/{len(sampled)} — budget exhausted")
            break

        if verbose:
            print(f"  [{i}/{len(sampled)}] T{term}L{lesson_num}...", end="", flush=True)

        # Extract ground truth from source files
        source_text = extract_ground_truth(term, lesson_num)
        kb_text = _format_kb_entry(kb_lesson)

        # Build prompt from template
        prompt = template.replace("{source_content}", source_text)
        prompt = prompt.replace("{kb_entry}", kb_text)

        # Run dual-judge
        try:
            judgment = judge.evaluate(prompt)
            report.add_result(term, lesson_num, judgment)
            consensus = judgment.get("_consensus", False)
            if verbose:
                status = "consensus" if consensus else "no consensus"
                print(f" [{status}]")
        except Exception as e:
            if verbose:
                print(f" [ERROR: {e}]")

    report.calls_made = client.calls_made

    # Save reports (per-term filenames when running a single term)
    single_term = terms[0] if len(terms) == 1 else None
    json_path = report.save_json(term=single_term)
    text_path = report.save_text(term=single_term)

    if verbose:
        scores = report.compute_scores()
        print()
        print(f"  Tier 1: {scores['tier1']:.1%}  |  Tier 2: {scores['tier2']:.1%}"
              f"  |  Tier 3: {scores['tier3']:.1%}")
        print(f"  Overall: {scores['overall']:.1%}  |  Verdict: {report.compute_verdict()}")
        print(f"  LLM Calls: {report.calls_made}/{budget}")
        print(f"  Report: {json_path}")

    return report
