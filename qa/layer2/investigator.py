"""
Layer 2 LLM Investigator: Dual-judge investigation of KB quality.
"""

import json
import time
from pathlib import Path

from qa.report import CheckResult
from qa.layer2.cli_client import ClaudeCliClient
from qa.layer2.prompts import (
    ERROR_INVESTIGATION_SCHEMA,
    FIELD_EVALUATION_SCHEMA,
    EVALUATED_FIELDS,
    build_error_investigation_prompt,
    build_lesson_evaluation_prompt,
)
from qa.layer2.sampler import StrategicSampler


def _build_ground_truth_text(ground_truth: dict) -> str:
    """Format PPTX ground truth as readable text."""
    if not ground_truth or ground_truth.get("error"):
        return "[No ground truth available]"
    parts = []
    for slide in ground_truth.get("slides", []):
        parts.append(f"--- Slide {slide['slide_number']} ---")
        for text in slide.get("text", []):
            parts.append(text)
        if slide.get("notes"):
            parts.append(f"[Speaker Notes]: {slide['notes']}")
        for link in slide.get("links", []):
            parts.append(f"[Link]: {link.get('text', '')} -> {link['url']}")
        for table in slide.get("tables", []):
            for row in table:
                parts.append(" | ".join(row))
    return "\n".join(parts)


def _build_kb_text(kb_lesson: dict) -> str:
    """Format KB lesson entry as readable text."""
    if not kb_lesson:
        return "[No KB entry found]"
    parts = [f"lesson_title: {kb_lesson.get('lesson_title', '')}"]
    meta = kb_lesson.get("metadata", {})
    for field in ["core_topics", "learning_objectives", "endstar_tools", "activity_type",
                  "activity_description", "videos", "resources", "keywords"]:
        val = meta.get(field, "")
        if isinstance(val, (list, dict)):
            parts.append(f"{field}: {json.dumps(val, ensure_ascii=False)}")
        else:
            parts.append(f"{field}: {val}")
    desc = kb_lesson.get("description_of_activities", "")
    if desc:
        parts.append(f"description_of_activities: {desc[:500]}")
    return "\n".join(parts)


def _score_verdict(verdict: str) -> float:
    return {"CORRECT": 1.0, "PARTIAL": 0.5, "INCORRECT": 0.0, "MISSING": 0.0}.get(verdict, 0.0)


class Investigator:
    """Dual-judge LLM investigator for KB quality."""

    def __init__(self, client: ClaudeCliClient, sampler: StrategicSampler):
        self.client = client
        self.sampler = sampler

    def dual_judge(self, prompt: str, schema: dict, verdict_key: str = "verdict") -> dict:
        """Two independent calls must agree. Retry once on disagreement."""
        for attempt in range(1, 3):
            results = []
            for _ in range(2):
                try:
                    result = self.client.call(prompt, json_schema=schema)
                    if isinstance(result, str):
                        result = json.loads(result)
                    results.append(result)
                except Exception as e:
                    results.append({
                        verdict_key: "UNCERTAIN",
                        "reason": f"Call failed: {e}",
                        "evidence": str(e),
                    })
                time.sleep(0.5)

            v1 = results[0].get(verdict_key, "")
            v2 = results[1].get(verdict_key, "")

            if v1 == v2:
                results[0]["consensus"] = True
                results[0]["attempt"] = attempt
                results[0]["judge_votes"] = [v1, v2]
                return results[0]

        results[0]["consensus"] = False
        results[0]["attempt"] = 2
        results[0]["judge_votes"] = [v1, v2]
        return results[0]

    def dual_judge_fields(self, prompt: str, schema: dict) -> dict:
        """Dual-judge for multi-field evaluation (Phase 2)."""
        for attempt in range(1, 3):
            results = []
            for _ in range(2):
                try:
                    result = self.client.call(prompt, json_schema=schema)
                    if isinstance(result, str):
                        result = json.loads(result)
                    results.append(result)
                except Exception as e:
                    fallback = {
                        f: {"verdict": "MISSING", "evidence": str(e)}
                        for f in EVALUATED_FIELDS
                    }
                    results.append(fallback)
                time.sleep(0.5)

            all_agree = True
            votes = {}
            for field in EVALUATED_FIELDS:
                v1 = results[0].get(field, {}).get("verdict", "")
                v2 = results[1].get(field, {}).get("verdict", "")
                votes[field] = [v1, v2]
                if v1 != v2:
                    all_agree = False

            if all_agree:
                results[0]["_consensus"] = True
                results[0]["_attempt"] = attempt
                results[0]["_judge_votes"] = votes
                return results[0]

        results[0]["_consensus"] = False
        results[0]["_attempt"] = 2
        results[0]["_judge_votes"] = votes
        return results[0]

    def investigate_error(self, error: CheckResult, source_content: dict, kb_lesson: dict) -> dict:
        """Phase 1: Investigate a single error."""
        source_text = _build_ground_truth_text(source_content)
        kb_text = _build_kb_text(kb_lesson)
        prompt = build_error_investigation_prompt(error.to_dict(), source_text, kb_text)
        return self.dual_judge(prompt, ERROR_INVESTIGATION_SCHEMA, verdict_key="verdict")

    def evaluate_lesson(self, source_content: dict, kb_lesson: dict) -> dict:
        """Phase 2: Full 8-field evaluation of a lesson."""
        source_text = _build_ground_truth_text(source_content)
        kb_text = _build_kb_text(kb_lesson)
        prompt = build_lesson_evaluation_prompt(source_text, kb_text)
        judgment = self.dual_judge_fields(prompt, FIELD_EVALUATION_SCHEMA)

        # Compute overall score
        total = 0
        count = 0
        for field in EVALUATED_FIELDS:
            verdict = judgment.get(field, {}).get("verdict", "MISSING")
            total += _score_verdict(verdict)
            count += 1

        judgment["_overall_score"] = round(total / max(count, 1), 3)
        return judgment


def run_layer2(errors: list[CheckResult], lessons_with_sources: list[dict],
               terms: list[int], budget: int = None, verbose: bool = False) -> tuple[list[CheckResult], dict]:
    """Run Layer 2 LLM cross-validation.

    Args:
        errors: Layer 1 failures to investigate
        lessons_with_sources: List of dicts with {term, lesson_num, source_content, kb_lesson}
        terms: Which terms are being checked
        budget: Max LLM calls

    Returns:
        (check_results, layer_summary)
    """
    from qa.config import LLM_DEFAULTS

    budget = budget or LLM_DEFAULTS["budget"]
    client = ClaudeCliClient(budget=budget)
    sampler = StrategicSampler(budget=budget)
    investigator = Investigator(client, sampler)
    results = []

    if not client.is_available():
        results.append(CheckResult(
            check_id="L2_CLI", layer=2, severity="WARNING",
            passed=True,
            message="Claude CLI not available — Layer 2 skipped",
            details={"skipped": True},
        ))
        return results, {"confidence": 1.0, "skipped": True, "calls_made": 0, "budget": budget}

    # Phase 1: Error Investigation
    sampled_errors = sampler.sample_errors(errors)
    phase1_results = []
    confirmed = 0
    false_pos = 0

    if verbose and sampled_errors:
        print(f"  Layer 2 Phase 1: Investigating {len(sampled_errors)} errors")

    for err in sampled_errors:
        if not client.has_budget():
            break
        # Find matching source data
        matching = [l for l in lessons_with_sources
                    if l.get("term") == err.details.get("term")
                    and l.get("lesson_num") in (err.details.get("lesson_id"), err.details.get("lesson"))]
        source = matching[0].get("source_content", {}) if matching else {}
        kb = matching[0].get("kb_lesson", {}) if matching else {}

        try:
            judgment = investigator.investigate_error(err, source, kb)
            verdict = judgment.get("verdict", "UNCERTAIN")
            if verdict == "TRUE_POSITIVE":
                confirmed += 1
            elif verdict == "FALSE_POSITIVE":
                false_pos += 1
            results.append(CheckResult(
                check_id=f"L2_P1_{err.check_id}", layer=2, severity=err.severity,
                passed=verdict != "TRUE_POSITIVE",
                message=f"LLM: {verdict} — {judgment.get('reason', '')[:100]}",
                details={"original_check": err.check_id, "verdict": verdict,
                         "consensus": judgment.get("consensus"), "term": err.details.get("term")},
            ))
            if verbose:
                print(f"    {err.check_id}: {verdict} {'[consensus]' if judgment.get('consensus') else '[no consensus]'}")
        except Exception as e:
            results.append(CheckResult(
                check_id=f"L2_P1_{err.check_id}", layer=2, severity="INFO",
                passed=True,
                message=f"LLM investigation failed: {e}",
                details={"error": str(e)},
            ))

    # Phase 2: Pass Verification
    sampled_lessons = sampler.sample_lessons(lessons_with_sources, terms)
    phase2_scores = []

    if verbose and sampled_lessons:
        print(f"  Layer 2 Phase 2: Verifying {len(sampled_lessons)} lessons")

    for item in sampled_lessons:
        if not client.has_budget():
            break
        try:
            judgment = investigator.evaluate_lesson(
                item.get("source_content", {}),
                item.get("kb_lesson", {}),
            )
            score = judgment.get("_overall_score", 0)
            phase2_scores.append(score)
            passed = score >= 0.6
            results.append(CheckResult(
                check_id=f"L2_P2_T{item['term']}L{item['lesson_num']}", layer=2,
                severity="WARNING" if not passed else "INFO",
                passed=passed,
                message=f"LLM field accuracy: {score:.0%} (T{item['term']}L{item['lesson_num']})",
                details={"term": item["term"], "lesson_num": item["lesson_num"],
                         "score": score, "consensus": judgment.get("_consensus")},
            ))
            if verbose:
                print(f"    T{item['term']}L{item['lesson_num']}: {score:.0%}")
        except Exception as e:
            results.append(CheckResult(
                check_id=f"L2_P2_T{item['term']}L{item['lesson_num']}", layer=2,
                severity="INFO", passed=True,
                message=f"LLM evaluation failed: {e}",
                details={"error": str(e)},
            ))

    # Compute confidence
    avg_score = sum(phase2_scores) / max(len(phase2_scores), 1) if phase2_scores else 0.5
    fp_ratio = false_pos / max(false_pos + confirmed, 1) if (false_pos + confirmed) > 0 else 1.0
    confidence = round(avg_score * 0.7 + fp_ratio * 0.3, 2)

    summary = {
        "confidence": confidence,
        "calls_made": client.calls_made,
        "budget": budget,
        "phase1_sampled": len(sampled_errors),
        "phase1_confirmed": confirmed,
        "phase1_false_positives": false_pos,
        "phase2_sampled": len(sampled_lessons),
        "phase2_avg_score": round(avg_score, 3) if phase2_scores else None,
        "skipped": False,
    }

    return results, summary
