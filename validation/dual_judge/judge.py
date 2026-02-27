"""
Dual-judge consensus: two independent LLM calls must agree on ALL fields.

Both judges evaluate independently. Consensus requires agreement across
all 20 fields. 2 attempts, plus a 3rd tiebreaker if still no consensus.
"""

import json
import time
from collections import Counter

from validation.dual_judge.client import CliClient, SdkClient

ALL_FIELDS = [
    "lesson_title", "learning_objectives", "description_of_activities",
    "core_topics", "teacher_notes", "slides", "videos", "resources",
    "success_criteria", "big_question", "uae_link", "endstar_tools",
    "keywords", "activity_type", "assessment_signals",
    "curriculum_alignment", "ai_focus", "artifacts", "grade_band",
    "document_sources",
]


class DualJudge:
    """Two independent LLM calls with full consensus checking."""

    def __init__(self, client: CliClient | SdkClient):
        self.client = client

    def _call_judge(self, prompt: str) -> dict:
        """Make a single judge call, returning fallback on failure."""
        try:
            result = self.client.call(prompt)
            if isinstance(result, str):
                result = json.loads(result)
            return result
        except Exception as e:
            return {
                f: {"verdict": "MISSING", "evidence": f"Call failed: {e}"}
                for f in ALL_FIELDS
            }

    def _check_consensus(self, results: list[dict]) -> tuple[bool, dict]:
        """Check if two judge results agree on all fields.
        Returns (all_agree, votes_dict)."""
        all_agree = True
        votes = {}
        for field in ALL_FIELDS:
            v1 = results[0].get(field, {}).get("verdict", "")
            v2 = results[1].get(field, {}).get("verdict", "")
            votes[field] = [v1, v2]
            if v1 != v2:
                all_agree = False
        return all_agree, votes

    def evaluate(self, prompt: str) -> dict:
        """Run dual-judge evaluation on a lesson.

        2 attempts for full consensus. If no consensus after 2 attempts,
        a 3rd tiebreaker judge is called and per-field majority vote decides.

        Returns dict with per-field verdicts, consensus flag, and metadata.
        """
        all_results = []

        for attempt in range(1, 3):
            results = []
            for _ in range(2):
                results.append(self._call_judge(prompt))
                time.sleep(0.5)  # Avoid rate limits

            all_results = results
            all_agree, votes = self._check_consensus(results)

            if all_agree:
                merged = results[0].copy()
                merged["_consensus"] = True
                merged["_attempt"] = attempt
                merged["_judge_votes"] = votes
                return merged

        # No consensus after 2 attempts — call a 3rd tiebreaker judge
        tiebreaker = self._call_judge(prompt)
        time.sleep(0.5)
        all_results.append(tiebreaker)

        # Majority vote across all 3 judges (2 from last attempt + tiebreaker)
        merged = {}
        votes = {}
        for field in ALL_FIELDS:
            verdicts = []
            for r in all_results:
                fd = r.get(field, {})
                verdicts.append(fd.get("verdict", "MISSING"))
            votes[field] = verdicts
            # Pick majority verdict
            counter = Counter(verdicts)
            majority_verdict = counter.most_common(1)[0][0]
            # Use evidence from the judge that gave the majority verdict
            for r in all_results:
                fd = r.get(field, {})
                if fd.get("verdict", "") == majority_verdict:
                    merged[field] = fd
                    break

        merged["_consensus"] = True
        merged["_attempt"] = "tiebreaker"
        merged["_judge_votes"] = votes
        return merged
