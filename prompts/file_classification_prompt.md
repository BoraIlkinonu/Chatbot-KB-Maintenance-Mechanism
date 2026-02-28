# File Classification Prompt

You are a curriculum file classifier. Your job is to classify a batch of file paths from an educational content repository into structured metadata.

## Context

This repository contains teaching materials organized by term and lesson for the Explorer's Programme (game design / AI curriculum for G9–G10). The folder structure typically follows:
- `term{N}/` or `Term N - <Name>/` as top-level term folders
- Term 1 = "Foundations", Term 2 = "Accelerator", Term 3 = "Mastery"
- Lesson folders like `Lesson 5/` or `Lesson 3-5/` contain files for those lessons
- Files include: Teachers Slides (.pptx), Students Slides (.pptx), Lesson Plans (.docx), Exemplar Work, Assessment Guides, Portfolio decks, Design Briefs, Curriculum docs

## Task

Classify each file path below. For each file, determine:

1. **term** (int or null) — Which term this file belongs to. Determine from folder names:
   - "term1", "Term 1", "Foundations" → 1
   - "term2", "Term 2", "Accelerator" → 2
   - "term3", "Term 3", "Mastery" → 3
   - If unclear, null

2. **lessons** (array of int) — Which lesson number(s) this file relates to:
   - "Lesson 5" → [5]
   - "Lesson 3-5" or "Lessons 3-5" → [3, 4, 5]
   - Portfolio/assessment/rubric/design brief files that span the whole term → [] (empty array). Only assign lesson numbers if the filename/path explicitly contains a lesson number.
   - If no lesson can be determined → []

3. **content_type** (string) — One of:
   - "teachers_slides" — Teacher-facing slide decks
   - "students_slides" — Student-facing slide decks
   - "lesson_plan" — Lesson plan documents
   - "exemplar_work" — Student exemplar/sample work
   - "portfolio" — Portfolio templates or decks
   - "assessment_guide" — Assessment guides, rubrics
   - "design_brief" — Design brief documents
   - "curriculum_doc" — Curriculum alignment documents
   - "video" — Video files (MP4, MOV, etc.)
   - "other" — Anything that doesn't fit above

4. **has_slides** (bool) — true if the file contains slide content (PPTX, Google Slides)

## File Paths

```
{file_paths}
```

## Required JSON Output

Respond with ONLY a JSON array — no explanation, no markdown fences, just the raw JSON:

[
  {
    "path": "<original path>",
    "term": 1,
    "lessons": [5],
    "content_type": "teachers_slides",
    "has_slides": true
  }
]
