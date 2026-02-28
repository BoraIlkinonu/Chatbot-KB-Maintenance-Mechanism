# Code Review: Hardcoded Assumptions Detector

You are reviewing a Python file from an educational content pipeline. Find any hardcoded assumptions about curriculum structure that should instead be derived from data or LLM classification.

## What to Flag

1. **Hardcoded term numbers** — `range(1, 4)`, `[1, 2, 3]`, `if term == 1` for content logic
2. **Hardcoded lesson counts** — `range(1, 13)`, `range(1, 23)`, max lesson constants
3. **Keyword lists for classification** — Dictionaries mapping keywords to categories (e.g., tool names, content types)
4. **Regex patterns for content understanding** — Patterns that extract semantic meaning (not structural parsing)
5. **If-elif chains for classification** — Cascading conditions that classify content by keyword matching
6. **Hardcoded mappings** — Week-to-lesson maps, term name maps, file category maps
7. **Default values that assume structure** — Grade bands, component names, weighting percentages

## What is OK (Do NOT Flag)

- Structural parsing (JSON keys, file extensions, markdown headers)
- Path manipulation (directory traversal, file I/O)
- Schema validation (checking required fields exist)
- Configuration constants (API URLs, directory paths)
- Test assertions

## Python File

```python
{file_content}
```

## Required JSON Output

Respond with ONLY a JSON array of violations:

[
  {
    "line": 42,
    "code": "ENDSTAR_TOOLS = {...}",
    "reason": "Hardcoded keyword-to-tool mapping should be LLM-classified",
    "severity": "high"
  }
]

severity: "high" (content classification logic), "medium" (hardcoded defaults), "low" (minor assumptions)
