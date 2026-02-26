"""
Dual-judge report: tier-weighted scoring, verdicts, failure summary.

Produces both JSON and human-readable text reports.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from config import VALIDATION_DIR

# Field tier assignments
TIERS = {
    1: ["lesson_title", "learning_objectives", "description_of_activities",
        "core_topics", "teacher_notes", "slides", "videos", "resources"],
    2: ["success_criteria", "big_question", "uae_link", "endstar_tools",
        "keywords", "activity_type", "assessment_signals"],
    3: ["curriculum_alignment", "ai_focus", "artifacts", "grade_band",
        "document_sources"],
}

TIER_LABELS = {1: "Critical", 2: "Important", 3: "Informational"}
SEVERITY_MAP = {1: "ERROR", 2: "WARNING", 3: "INFO"}

VERDICT_SCORES = {
    "CORRECT": 1.0,
    "PARTIAL": 0.5,
    "INCORRECT": 0.0,
    "MISSING": 0.0,
    "N/A": None,  # Excluded from scoring
}


class DualJudgeReport:
    """Aggregates dual-judge results across sampled lessons."""

    def __init__(self):
        self.lesson_results: list[dict] = []
        self.total_lessons: int = 0
        self.sampled_count: int = 0
        self.calls_made: int = 0
        self.budget: int = 60
        self.timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def add_result(self, term: int, lesson_num: int, judgment: dict):
        """Add a single lesson's dual-judge result."""
        entry = {
            "term": term,
            "lesson_num": lesson_num,
            "consensus": judgment.get("_consensus", False),
            "attempt": judgment.get("_attempt", 1),
            "fields": {},
        }

        for tier, fields in TIERS.items():
            for field in fields:
                field_data = judgment.get(field, {})
                verdict = field_data.get("verdict", "MISSING") if isinstance(field_data, dict) else "MISSING"
                evidence = field_data.get("evidence", "") if isinstance(field_data, dict) else ""
                votes = judgment.get("_judge_votes", {}).get(field, [])
                entry["fields"][field] = {
                    "verdict": verdict,
                    "evidence": evidence,
                    "tier": tier,
                    "votes": votes,
                }

        self.lesson_results.append(entry)

    def compute_scores(self) -> dict:
        """Compute tier scores and overall score."""
        tier_scores = {}
        for tier in [1, 2, 3]:
            total = 0.0
            count = 0
            for result in self.lesson_results:
                for field, data in result["fields"].items():
                    if data["tier"] != tier:
                        continue
                    score = VERDICT_SCORES.get(data["verdict"])
                    if score is not None:  # Skip N/A
                        total += score
                        count += 1
            tier_scores[tier] = round(total / max(count, 1), 3)

        # Overall weighted: Tier 1 = 50%, Tier 2 = 30%, Tier 3 = 20%
        overall = (
            tier_scores.get(1, 0) * 0.5
            + tier_scores.get(2, 0) * 0.3
            + tier_scores.get(3, 0) * 0.2
        )
        return {
            "tier1": tier_scores.get(1, 0),
            "tier2": tier_scores.get(2, 0),
            "tier3": tier_scores.get(3, 0),
            "overall": round(overall, 3),
        }

    def consensus_rate(self) -> float:
        """Fraction of lessons that reached dual-judge consensus."""
        if not self.lesson_results:
            return 0.0
        agreed = sum(1 for r in self.lesson_results if r["consensus"])
        return round(agreed / len(self.lesson_results), 3)

    def failures(self) -> list[dict]:
        """Get all non-CORRECT, non-N/A field results."""
        failures = []
        for result in self.lesson_results:
            t = result["term"]
            ln = result["lesson_num"]
            for field, data in result["fields"].items():
                if data["verdict"] in ("CORRECT", "N/A"):
                    continue
                failures.append({
                    "id": f"DJ_T{t}L{ln}_{field}",
                    "term": t,
                    "lesson_num": ln,
                    "field": field,
                    "tier": data["tier"],
                    "severity": SEVERITY_MAP[data["tier"]],
                    "verdict": data["verdict"],
                    "evidence": data["evidence"],
                })
        # Sort: ERROR first, then WARNING, then INFO
        order = {"ERROR": 0, "WARNING": 1, "INFO": 2}
        failures.sort(key=lambda f: (order.get(f["severity"], 3), f["id"]))
        return failures

    def compute_verdict(self) -> str:
        """Compute overall verdict: PASS / NEEDS_REVIEW / FAIL."""
        scores = self.compute_scores()
        tier1 = scores["tier1"]

        # Count Tier 1 INCORRECT fields
        tier1_incorrect = 0
        for result in self.lesson_results:
            for field, data in result["fields"].items():
                if data["tier"] == 1 and data["verdict"] == "INCORRECT":
                    tier1_incorrect += 1

        if tier1 >= 0.8 and tier1_incorrect == 0:
            return "PASS"
        elif tier1 >= 0.5:
            return "NEEDS_REVIEW"
        else:
            return "FAIL"

    def exit_code(self) -> int:
        verdict = self.compute_verdict()
        return {"PASS": 0, "NEEDS_REVIEW": 1, "FAIL": 2}[verdict]

    def to_dict(self) -> dict:
        """Full report as JSON-serializable dict."""
        scores = self.compute_scores()
        return {
            "timestamp": self.timestamp,
            "total_lessons": self.total_lessons,
            "sampled": self.sampled_count,
            "sample_rate": round(self.sampled_count / max(self.total_lessons, 1), 3),
            "calls_made": self.calls_made,
            "budget": self.budget,
            "consensus_rate": self.consensus_rate(),
            "scores": scores,
            "verdict": self.compute_verdict(),
            "failures": self.failures(),
            "lesson_results": self.lesson_results,
        }

    def save_json(self, path: Path | None = None, term: int | None = None) -> Path:
        if path is None:
            name = f"dual_judge_report_term{term}" if term else "dual_judge_report"
            path = VALIDATION_DIR / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def save_text(self, path: Path | None = None, term: int | None = None) -> Path:
        if path is None:
            name = f"dual_judge_report_term{term}" if term else "dual_judge_report"
            path = VALIDATION_DIR / f"{name}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)

        scores = self.compute_scores()
        verdict = self.compute_verdict()
        fails = self.failures()

        lines = [
            "=" * 70,
            "  DUAL-LLM JUDGE VALIDATION REPORT",
            f"  {self.timestamp}",
            "=" * 70,
            "",
            f"Sample: {self.sampled_count}/{self.total_lessons} content lessons"
            f" ({self.sampled_count / max(self.total_lessons, 1):.1%})",
            f"LLM Calls: {self.calls_made} (budget: {self.budget})",
            f"Consensus Rate: "
            f"{sum(1 for r in self.lesson_results if r['consensus'])}"
            f"/{len(self.lesson_results)}"
            f" ({self.consensus_rate():.1%})",
            "",
            f"Tier 1 Score: {scores['tier1']:.1%}  (Critical)",
            f"Tier 2 Score: {scores['tier2']:.1%}  (Important)",
            f"Tier 3 Score: {scores['tier3']:.1%}  (Informational)",
            f"Overall Score: {scores['overall']:.1%}",
            "",
            f"Verdict: {verdict}",
        ]

        if fails:
            lines.append("")
            lines.append("FAILURES:")
            lines.append("-" * 50)
            for f in fails:
                pad = 8 - len(f["severity"])
                lines.append(
                    f"  [{f['severity']}{' ' * pad}] {f['id']}: {f['verdict']}"
                    f" — {f['evidence'][:100]}"
                )

        lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        return path
