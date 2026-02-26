"""
QA configuration: term profiles, thresholds, canonical values.
"""

# Per-term reality profiles — replaces broken EXPECTED_CONTENT_TYPES
TERM_PROFILES = {
    1: {
        "total_lessons": 22,
        "has_native_docs": False,
        "has_student_slides": False,
        "has_lesson_plans": False,
        "lessons_with_lesson_plans": [],
    },
    2: {
        "total_lessons": 14,
        "has_native_docs": False,
        "has_student_slides": False,
        "has_lesson_plans": False,
        "lessons_with_lesson_plans": [],
    },
    3: {
        "total_lessons": 24,
        "has_native_docs": True,
        "has_student_slides": True,
        "has_lesson_plans": True,
        "lessons_with_lesson_plans": [1, 2, 3, 4, 5, 6, 7, 11, 12],
    },
}

# Canonical Endstar tool names (must match config.ENDSTAR_TOOLS values)
CANONICAL_TOOLS = {
    "Triggers", "NPCs", "Interactions", "Mechanics", "Logic",
    "Connections", "Props", "Rule Blocks", "Visuals", "Sound",
    "NPC dialogue", "Level flow", "Prototyping tools",
}

# Grade band pattern
GRADE_BAND_PATTERN = r"G\d+[\-–]G\d+"

# Verdict thresholds
VERDICT_THRESHOLDS = {
    "max_warnings_for_pass": 10,
    "min_layer4_pass_rate": 0.80,
    "min_llm_confidence": 0.80,
}

# Content quality thresholds
CONTENT_THRESHOLDS = {
    "min_objective_length": 10,
    "min_activity_length": 50,
    "min_keyword_length": 2,
    "max_keyword_frequency": 0.80,  # keyword in >80% lessons = overfit
}

# Layer 4 completeness thresholds
COMPLETENESS_THRESHOLDS = {
    "lesson_title": 1.00,        # 100% coverage required
    "learning_objectives": 1.00,  # 100% coverage required
    "activity_description": 1.00, # 100% coverage required
    "resources": 0.60,           # 60% threshold
    "assessment_signals": 0.80,  # 80% threshold
}

# LLM defaults
LLM_DEFAULTS = {
    "budget": 15,
    "timeout": 300,
    "max_retries": 3,
    "backoff_base": 2,
    "model": "sonnet",
}

# Video URL patterns (syntactic check)
VIDEO_URL_DOMAINS = {"youtube.com", "youtu.be", "vimeo.com", "drive.google.com"}

# Regression: max allowed decrease in resources (percentage)
REGRESSION_MAX_RESOURCE_DECREASE = 0.20
