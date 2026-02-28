# Template Metadata Extraction Prompt

You are extracting structured metadata from an assessment/rubric template file used in the Explorer's Programme (game design / AI curriculum for G9–G10).

## Task

Analyze the file below and extract metadata for the Templates KB.

## File Information

- **File name**: {file_name}
- **File path**: {file_path}

## File Content

```
{content}
```

## Fields to Extract

1. **is_template** (bool) — Is this file genuinely an assessment template, rubric, or evaluation guide? Return false for exemplar work, design briefs, or regular lesson content that happens to mention assessment.

2. **component** (string) — The programme component this template belongs to. One of:
   - "assessment" — Student portfolio, portfolio deck, portfolio assessment
   - "showcase" — Pitch rubric, showcase evaluation, presentation rubric
   - "summative-product" — Assessment guide, teacher rubric, grading rubric, level design rubric
   - "formative" — Formative assessment, peer assessment, self-assessment templates

3. **purpose** (string) — A 1-2 sentence description of what this template is for. Extract from the content if possible, otherwise generate from the file name and type.

4. **skills** (array of strings) — Core skills assessed by this template. Look for bullet points mentioning skills students should demonstrate (create, design, develop, build, communicate, collaborate, iterate, etc.). Max 10.

5. **criteria** (array of strings) — Assessment criteria or rubric items. Look for grading criteria, rubric rows, performance descriptors. Max 10.

6. **weighting** (int or null) — Percentage weighting if stated in the content (e.g., "25% of final grade"). null if not stated.

## Required JSON Output

Respond with ONLY a JSON object — no explanation, no markdown fences:

{
  "is_template": true,
  "component": "summative-product",
  "purpose": "Teacher rubric for evaluating student game design projects",
  "skills": ["game design", "level design", "iteration"],
  "criteria": ["Game mechanics implementation", "Visual design quality"],
  "weighting": 50
}
