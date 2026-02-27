# Pipeline Backlog

## Pending Improvements

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
