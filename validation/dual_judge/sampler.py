"""
Weighted random sampling of lessons for dual-judge evaluation.

Guarantees at least 1 lesson per term and weights selection by
slide count (more slides = higher probability of being sampled).
"""

import random


# Placeholder lessons with no real content (skip these)
SKIP_LESSONS = {
    3: set(range(13, 25)),  # T3 L13-24 are placeholders
}


def sample_lessons(
    all_lessons: list[dict],
    sample_rate: float = 0.25,
    seed: int | None = None,
    terms: list[int] | None = None,
) -> list[dict]:
    """Select lessons for dual-judge evaluation.

    Args:
        all_lessons: List of {term, lesson_num, ...} dicts
        sample_rate: Fraction of lessons to sample (default 25%)
        seed: Random seed for reproducibility
        terms: Restrict to these terms (None = all)

    Returns:
        Selected lesson dicts
    """
    rng = random.Random(seed)

    # Filter to requested terms and skip placeholders
    eligible = []
    for lesson in all_lessons:
        t = lesson.get("term", 0)
        ln = lesson.get("lesson_num", 0)
        if terms and t not in terms:
            continue
        if ln in SKIP_LESSONS.get(t, set()):
            continue
        eligible.append(lesson)

    if not eligible:
        return []

    target_count = max(1, round(len(eligible) * sample_rate))

    # Guarantee at least 1 per term
    by_term: dict[int, list[dict]] = {}
    for lesson in eligible:
        by_term.setdefault(lesson["term"], []).append(lesson)

    selected = []
    for t, candidates in sorted(by_term.items()):
        # Weight by slide count (more content = higher priority)
        weights = [_slide_weight(l) for l in candidates]
        pick = rng.choices(candidates, weights=weights, k=1)[0]
        selected.append(pick)

    # Fill remaining slots
    remaining_pool = [l for l in eligible if l not in selected]
    remaining_slots = target_count - len(selected)

    if remaining_slots > 0 and remaining_pool:
        weights = [_slide_weight(l) for l in remaining_pool]
        extra = _weighted_sample_without_replacement(
            remaining_pool, weights, min(remaining_slots, len(remaining_pool)), rng,
        )
        selected.extend(extra)

    return selected


def _slide_weight(lesson: dict) -> float:
    """Weight a lesson by its slide count. More slides = more to validate."""
    slide_count = lesson.get("slide_count", 0)
    return max(1.0, float(slide_count))


def _weighted_sample_without_replacement(
    population: list, weights: list[float], k: int, rng: random.Random,
) -> list:
    """Weighted sampling without replacement."""
    pool = list(zip(population, weights))
    selected = []
    for _ in range(k):
        if not pool:
            break
        items, w = zip(*pool)
        idx = rng.choices(range(len(items)), weights=w, k=1)[0]
        selected.append(items[idx])
        pool.pop(idx)
    return selected
