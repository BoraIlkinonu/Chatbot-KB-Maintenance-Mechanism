# Dual-Judge KB Evaluation Prompt

You are a curriculum knowledge base quality expert. Your job is to evaluate whether a KB lesson entry accurately captures the content from its source teaching materials.

## Task

Compare the **Source Content** (ground truth from original files) against the **KB Entry** (extracted data). Evaluate each field independently.

## Scoring Rubric

For each field, assign ONE verdict:

- **CORRECT** (1.0) — KB field accurately captures the source content. Minor formatting differences are acceptable.
- **PARTIAL** (0.5) — KB field captures some but not all source content, OR contains minor inaccuracies. Key information is present but incomplete.
- **INCORRECT** (0.0) — KB field contains wrong information not found in source, OR significantly misrepresents the source.
- **MISSING** (0.0) — KB field is empty/null but source contains relevant content for this field.
- **N/A** — Source has no content for this field AND KB field is empty. Do not penalize.

## Fields to Evaluate

### Tier 1 — Critical (errors here are most severe)

1. **lesson_title** — Does the KB title match the lesson title from source slides/docs?
2. **learning_objectives** — Do KB objectives match ALL objectives listed in source? Check for missing or fabricated objectives.
3. **description_of_activities** — Does the KB activity description reflect the actual activities described in source slides and notes?
4. **core_topics** — Do KB topics accurately reflect the main topics covered in source content?
5. **teacher_notes** — Does the KB capture speaker notes / teacher guidance from source?
6. **slides** — Does the KB slide content capture the text from source slides? Check for missing slides.
7. **videos** — Does the KB list all video URLs/references found in source? Check for missing or fabricated URLs.
8. **resources** — Does the KB list all resource links/references from source? Check for missing or fabricated URLs.

### Tier 2 — Important (errors here are significant)

9. **success_criteria** — Do KB success criteria match those stated in source?
10. **big_question** — Does the KB big question match the source (if present)?
11. **uae_link** — Does the KB UAE link/connection match source (if present)?
12. **endstar_tools** — Do KB Endstar tools match tools mentioned in source slides?
13. **keywords** — Are KB keywords relevant terms actually found in source content?
14. **activity_type** — Does the KB activity type classification match source activities?
15. **assessment_signals** — Does the KB capture assessment information from source?

### Tier 3 — Informational (errors here are minor)

16. **curriculum_alignment** — Does KB curriculum alignment match source (if present)?
17. **ai_focus** — Does KB AI focus match AI-related content in source?
18. **artifacts** — Does KB list artifacts/deliverables mentioned in source?
19. **grade_band** — Is the KB grade band correct for this curriculum?
20. **document_sources** — Does KB correctly list the source files used?

## Important Guidelines

- Focus on **content accuracy**, not formatting.
- A field containing slightly different wording but the SAME meaning is CORRECT.
- A field that captures 80%+ of source content with no fabrication is CORRECT.
- A field with 50-80% of content captured is PARTIAL.
- URLs must match exactly — a missing or different URL is INCORRECT.
- If source has no content for a field, the KB having it empty is fine (mark N/A, not MISSING).
- Speaker notes in PPTX are legitimate source content for teacher_notes.
- Table content from slides should be captured somewhere in the KB.

## Source Content

```
{source_content}
```

## KB Entry

```json
{kb_entry}
```

## Required JSON Output

Respond with ONLY a JSON object in this exact format:

```json
{
  "lesson_title": {"verdict": "CORRECT|PARTIAL|INCORRECT|MISSING|N/A", "evidence": "brief explanation"},
  "learning_objectives": {"verdict": "...", "evidence": "..."},
  "description_of_activities": {"verdict": "...", "evidence": "..."},
  "core_topics": {"verdict": "...", "evidence": "..."},
  "teacher_notes": {"verdict": "...", "evidence": "..."},
  "slides": {"verdict": "...", "evidence": "..."},
  "videos": {"verdict": "...", "evidence": "..."},
  "resources": {"verdict": "...", "evidence": "..."},
  "success_criteria": {"verdict": "...", "evidence": "..."},
  "big_question": {"verdict": "...", "evidence": "..."},
  "uae_link": {"verdict": "...", "evidence": "..."},
  "endstar_tools": {"verdict": "...", "evidence": "..."},
  "keywords": {"verdict": "...", "evidence": "..."},
  "activity_type": {"verdict": "...", "evidence": "..."},
  "assessment_signals": {"verdict": "...", "evidence": "..."},
  "curriculum_alignment": {"verdict": "...", "evidence": "..."},
  "ai_focus": {"verdict": "...", "evidence": "..."},
  "artifacts": {"verdict": "...", "evidence": "..."},
  "grade_band": {"verdict": "...", "evidence": "..."},
  "document_sources": {"verdict": "...", "evidence": "..."}
}
```
