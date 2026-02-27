"""
Dual-judge consensus: two independent LLM calls must agree on ALL fields.

Both judges evaluate independently. Consensus requires agreement across
all 20 fields (Tier 1, 2, and 3). Up to 5 retry attempts.
"""

import json
import time

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

    def evaluate(self, prompt: str) -> dict:
        """Run dual-judge evaluation on a lesson.

        Returns dict with per-field verdicts, consensus flag, and metadata.
        """
        for attempt in range(1, 6):
            results = []
            for _ in range(2):
                try:
                    result = self.client.call(prompt)
                    if isinstance(result, str):
                        result = json.loads(result)
                    results.append(result)
                except Exception as e:
                    fallback = {
                        f: {"verdict": "MISSING", "evidence": f"Call failed: {e}"}
                        for f in ALL_FIELDS
                    }
                    results.append(fallback)
                time.sleep(0.5)  # Avoid rate limits

            # Check consensus: ALL fields must agree between both judges
            all_agree = True
            votes = {}
            for field in ALL_FIELDS:
                v1 = results[0].get(field, {}).get("verdict", "")
                v2 = results[1].get(field, {}).get("verdict", "")
                votes[field] = [v1, v2]
                if v1 != v2:
                    all_agree = False

            if all_agree:
                merged = results[0].copy()
                merged["_consensus"] = True
                merged["_attempt"] = attempt
                merged["_judge_votes"] = votes
                return merged

        # No consensus after 5 attempts — return first judge's result flagged
        merged = results[0].copy()
        merged["_consensus"] = False
        merged["_attempt"] = 5
        merged["_judge_votes"] = votes
        return merged
