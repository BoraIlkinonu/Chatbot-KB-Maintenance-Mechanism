"""
Lesson number extraction from file names/paths.
Extracted from build_kb.py — lightweight regex helper.
"""

import re


def extract_lesson_range(filepath: str) -> list[int]:
    """Extract lesson number(s) from a file path, handling ranges like 'Lesson 1-2'.
    Returns list of lesson numbers."""
    path_str = filepath.replace("\\", "/")

    # Range: "Lesson 1-2" or "Lesson 1 -2" or "Lesson 3-5"
    m = re.search(r"Lesson[_\s\-]*(\d{1,2})\s*[-\u2013\u2014]\s*(\d{1,2})", path_str, re.IGNORECASE)
    if m:
        start, end = int(m.group(1)), int(m.group(2))
        if 1 <= start <= end <= 50:
            return list(range(start, end + 1))

    # Single: "Lesson 5"
    m = re.search(r"Lesson[_\s\-]*(\d{1,2})", path_str, re.IGNORECASE)
    if m:
        num = int(m.group(1))
        if num >= 1:
            return [num]

    return []
