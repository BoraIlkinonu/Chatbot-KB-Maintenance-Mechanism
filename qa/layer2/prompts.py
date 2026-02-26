"""
Prompt templates for Layer 2 LLM cross-validation.
Separated from logic for maintainability.
"""


def _truncate(text: str, max_chars: int = 3000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n... [truncated, {len(text)} total chars]"


# ── Phase 1: Error Investigation ──

ERROR_INVESTIGATION_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["TRUE_POSITIVE", "FALSE_POSITIVE", "UNCERTAIN"],
        },
        "reason": {"type": "string"},
        "evidence": {"type": "string"},
    },
    "required": ["verdict", "reason", "evidence"],
}


def build_error_investigation_prompt(error: dict, source_text: str, kb_text: str) -> str:
    return f"""You are a curriculum KB quality expert. Investigate whether this validation error is a TRUE POSITIVE (real problem) or FALSE POSITIVE (the validation check is wrong).

VALIDATION ERROR:
Check ID: {error.get('check_id', '')}
Message: {error.get('message', '')}
Severity: {error.get('severity', '')}
Details: {error.get('details', {})}

SOURCE CONTENT (raw PPTX text — ground truth):
{_truncate(source_text)}

KB OUTPUT (pipeline extraction):
{_truncate(kb_text)}

Analyze:
1. Does the source actually have the content the error says is missing or wrong?
2. Is the error caused by a naming/formatting mismatch rather than missing content?
3. Is the KB output actually correct despite the validation error?

Return JSON with: verdict (TRUE_POSITIVE/FALSE_POSITIVE/UNCERTAIN), reason, evidence."""


# ── Phase 2: Pass Verification ──

FIELD_EVALUATION_SCHEMA = {
    "type": "object",
    "properties": {
        field: {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["CORRECT", "PARTIAL", "INCORRECT", "MISSING"]},
                "evidence": {"type": "string"},
            },
            "required": ["verdict", "evidence"],
        }
        for field in [
            "lesson_title", "learning_objectives", "core_topics",
            "activity_description", "resources", "videos",
            "endstar_tools", "keywords",
        ]
    },
    "required": [
        "lesson_title", "learning_objectives", "core_topics",
        "activity_description", "resources", "videos",
        "endstar_tools", "keywords",
    ],
}

EVALUATED_FIELDS = [
    "lesson_title", "learning_objectives", "core_topics",
    "activity_description", "resources", "videos",
    "endstar_tools", "keywords",
]


def build_lesson_evaluation_prompt(source_text: str, kb_text: str) -> str:
    return f"""You are a curriculum KB quality expert. Compare the SOURCE CONTENT (raw PPTX text) against the EXTRACTED KB OUTPUT and evaluate each field.

SOURCE CONTENT (ground truth from PPTX slides):
{_truncate(source_text, 4000)}

KB OUTPUT (pipeline extraction):
{_truncate(kb_text, 2000)}

Evaluate these fields. Rate each CORRECT / PARTIAL / INCORRECT / MISSING:
1. lesson_title — Does it accurately capture the lesson title from the slides?
2. learning_objectives — Are the extracted objectives present in the source?
3. core_topics — Do they reflect actual slide content themes?
4. activity_description — Does it match activities described in slides?
5. resources — Are extracted URLs present in the source PPTX links?
6. videos — Are YouTube/video URLs correctly identified and separated?
7. endstar_tools — Are the matched tools actually mentioned in slide text?
8. keywords — Are they relevant to the actual lesson content?

Return JSON with each field as a key containing verdict and evidence."""
