"""
Strategic sampling for Layer 2 LLM cross-validation.
Controls which items get LLM review within the budget.
"""

import random
from qa.report import CheckResult


class StrategicSampler:
    """Selects items for LLM review, prioritizing high-risk items within budget."""

    def __init__(self, budget: int):
        self.budget = budget
        self.allocated = 0

    def remaining(self) -> int:
        return max(0, self.budget - self.allocated)

    def sample_errors(self, errors: list[CheckResult], max_per_check_id: int = 2) -> list[CheckResult]:
        """Sample errors for Phase 1 investigation.

        Priority: ERROR severity first, then WARNING.
        Max 2 per check_id type to avoid spending budget on same issue.
        """
        if not errors or self.remaining() == 0:
            return []

        # Sort: ERROR first, then WARNING
        severity_order = {"ERROR": 0, "WARNING": 1, "INFO": 2}
        sorted_errors = sorted(errors, key=lambda e: severity_order.get(e.severity, 3))

        selected = []
        per_check = {}

        for err in sorted_errors:
            if self.remaining() - len(selected) <= 0:
                break
            count = per_check.get(err.check_id, 0)
            if count >= max_per_check_id:
                continue
            selected.append(err)
            per_check[err.check_id] = count + 1
            # Each error investigation uses ~2 calls (dual-judge)
            if len(selected) * 2 >= self.remaining():
                break

        self.allocated += len(selected) * 2
        return selected

    def sample_lessons(self, lessons: list[dict], terms: list[int]) -> list[dict]:
        """Sample passing lessons for Phase 2 verification.

        Ensures at least 1 lesson from each term for coverage.
        Each lesson uses ~2 calls (dual-judge).
        """
        if not lessons or self.remaining() < 2:
            return []

        max_lessons = self.remaining() // 2  # 2 calls per lesson

        # Ensure coverage: 1 per term minimum
        by_term = {}
        for l in lessons:
            t = l.get("term", 0)
            by_term.setdefault(t, []).append(l)

        selected = []
        for t in terms:
            candidates = by_term.get(t, [])
            if candidates:
                selected.append(random.choice(candidates))

        # Fill remaining budget with random selection
        remaining_pool = [l for l in lessons if l not in selected]
        remaining_slots = max_lessons - len(selected)
        if remaining_slots > 0 and remaining_pool:
            extra = random.sample(remaining_pool, min(remaining_slots, len(remaining_pool)))
            selected.extend(extra)

        self.allocated += len(selected) * 2
        return selected
