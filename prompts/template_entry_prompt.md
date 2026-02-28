# Template Entry Prompt

You are analyzing a file from the Explorer's Programme (game design / AI curriculum for G9-G10) to determine if it is an assessment template and, if so, extract structured metadata.

## File Information

- **File name**: {file_name}
- **File path**: {file_path}

## File Content

```
{content}
```

## Task

1. Determine if this file is genuinely an assessment template, rubric, or evaluation guide.
   - Return `"is_template": false` for: exemplar work, design briefs, regular lesson slides, lesson plans, or content that merely mentions assessment in passing.
   - Return `"is_template": true` for: assessment guides, rubrics, portfolio templates, pitch/showcase evaluation forms, grading criteria documents.

2. If it IS a template, extract the following metadata:

### Fields

- **template_name** (string): A clean name for this template (derived from file name, without extension)
- **component** (string): The programme component. Exactly one of:
  - `"assessment"` — Student portfolio, portfolio deck, portfolio assessment
  - `"showcase"` — Pitch rubric, showcase evaluation, presentation rubric
  - `"summative-product"` — Assessment guide, teacher rubric, grading rubric, level design rubric
  - `"formative"` — Formative assessment, peer assessment, self-assessment templates
- **label** (string): A human-readable label (e.g., "Student Portfolio", "Pitch / Showcase", "Assessment / Rubric")
- **purpose** (string): 2-3 sentence description of what this template is for. Extract from content if possible.
- **skills** (array of strings): Core skills assessed by this template. Look for bullet points mentioning skills students should demonstrate (create, design, develop, build, communicate, collaborate, iterate, etc.). Max 10.
- **criteria** (array of strings): Assessment criteria or rubric items. Look for grading criteria, rubric rows, performance descriptors. Max 10.
- **weighting** (int or null): Percentage weighting if stated in the content (e.g., "25% of final grade"). null if not stated.
- **term** (int or null): Which term this template belongs to. Determine from path/content if possible.
- **lessons** (array of int): Lesson numbers this template covers. Empty array `[]` for term-wide templates.

## Required JSON Output

Respond with ONLY a JSON object — no explanation, no markdown fences, just the raw JSON.

If it IS a template:
```
{
  "is_template": true,
  "template_name": "Assessment Guide - Term 2",
  "component": "summative-product",
  "label": "Assessment / Rubric",
  "purpose": "Teacher rubric for evaluating student game design projects across all Term 2 lessons.",
  "skills": ["game design", "level design", "iteration"],
  "criteria": ["Game mechanics implementation", "Visual design quality"],
  "weighting": 50,
  "term": 2,
  "lessons": []
}
```

If it is NOT a template:
```
{"is_template": false}
```
