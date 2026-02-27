# Pipeline Backlog

## Pending Improvements

### Template KB content validation
- **Priority**: High
- **Description**: Templates KB files (`output/Term N - Templates.json`, `output/templates.json`) currently have no content validation. The QA system only checks file existence (X011, E008). Many templates have empty `core_skills`, empty `assessment_criteria_summary`, generic fallback `purpose` text, and `linked_lessons` hardcoded to all lessons in a term rather than being actually lesson-specific. Need validation checks for: field population (are skills/criteria extracted?), purpose quality (not generic fallback?), linked_lessons accuracy, and cross-check against source content.
- **Files affected**: `qa/layer1/consistency_checks.py` (new T-series checks), `build_templates.py` (extraction quality), `verification/` (template coverage)

### Cross-reference external resources to lesson slides
- **Priority**: Medium
- **Description**: External resources (videos, images, docs) that sit outside lesson slide decks are downloaded and tracked, but not mapped to the specific lesson/slide that references them. For example, `Lesson supporting videos/Fortnite OG Chapter 1.mp4` is mentioned on slide 13 of Lesson 12, but the KB doesn't link the MP4 to that slide.
- **Approach**: Add a cross-referencing step after KB build that scans slide text for filenames/references and creates a `supporting_resources` field linking external files to specific slides.
- **Files affected**: `build_kb.py`, KB schema (add `supporting_resources` per lesson)

### Separate lesson vs non-lesson coverage metrics in reports
- **Priority**: Medium
- **Description**: Overall extraction coverage (98.3%) includes admin docs, support files, and curriculum specs that aren't part of the lesson KB. The actual lesson coverage is 99.7%. Reports should clearly separate these so non-lesson gaps don't look like missing lesson content.
- **Files affected**: `verification/coverage_report.py`, `verify_extraction.py`

### V002 link check: split by lesson vs non-lesson
- **Priority**: Low
- **Description**: Link extraction coverage shows 75.5% but all 86 "lost" links are from admin/support docs or internal PPTX XML refs. Zero real lesson URLs are lost. The check should report lesson links separately.
- **Files affected**: `verification/coverage_report.py`
