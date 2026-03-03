"""
Tests for drive_scanner.lessons — lesson number extraction.
"""

import pytest
from drive_scanner.lessons import extract_lesson_range


class TestExtractLessonRange:
    def test_single_lesson(self):
        assert extract_lesson_range("Lesson 5.pptx") == [5]

    def test_single_lesson_underscore(self):
        assert extract_lesson_range("Lesson_12.pptx") == [12]

    def test_single_lesson_dash(self):
        assert extract_lesson_range("Lesson-3.pptx") == [3]

    def test_lesson_in_path(self):
        assert extract_lesson_range("Week 3/Lesson 5.pptx") == [5]

    def test_lesson_range_dash(self):
        assert extract_lesson_range("Lesson 1-2.pptx") == [1, 2]

    def test_lesson_range_endash(self):
        assert extract_lesson_range("Lesson 3\u20135.pptx") == [3, 4, 5]

    def test_lesson_range_emdash(self):
        assert extract_lesson_range("Lesson 1\u20143.docx") == [1, 2, 3]

    def test_lesson_range_spaces(self):
        assert extract_lesson_range("Lesson 1 - 2.pptx") == [1, 2]

    def test_case_insensitive(self):
        assert extract_lesson_range("lesson 7.pptx") == [7]

    def test_no_lesson(self):
        assert extract_lesson_range("Rubric Template.xlsx") == []

    def test_no_lesson_empty(self):
        assert extract_lesson_range("") == []

    def test_backslash_path(self):
        assert extract_lesson_range("Term 1\\Week 3\\Lesson 8.pptx") == [8]

    def test_lesson_number_22(self):
        assert extract_lesson_range("Lesson 22.pptx") == [22]

    def test_lp_prefix(self):
        """LP (Lesson Plan) prefix should match Lesson pattern if present."""
        assert extract_lesson_range("Lesson Plan 4.docx") == []
        # LP without Lesson prefix → no match
        assert extract_lesson_range("LP4 Draft.docx") == []

    def test_range_with_lesson_in_folder(self):
        """Full path with lesson info in filename."""
        assert extract_lesson_range("Teacher Resources/Curriculum Content/Week 3/Lesson 5.pptx") == [5]
