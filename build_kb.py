"""
Stage 6: KB JSON Builder
Builds the final Knowledge Base JSON per term.

Extracts ALL values fresh from source documents — does NOT copy from existing KBs.
Keeps the exact same field structure as the existing KB schema.

Output schema (per the chatbot's expected format):
  Top level: term, total_lessons, generated_from, lessons[]
  Per lesson: lesson_title, url, metadata{16 fields + images[]},
    description_of_activities, other_resources, videos_column,
    testing_scores, comments, prompts, + flat enrichment fields

Data sources (priority order):
  1. Native Google API extractions (lesson plans with HEADING structure)
  2. Converted PPTX markdown (teacher slides with slide-based content)
  3. Extracted media metadata (image structural data)
"""

import sys
import json
import re
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

from config import (
    CONSOLIDATED_DIR, OUTPUT_DIR, LOGS_DIR, SOURCES_DIR, WEEK_LESSON_MAP,
    BASE_DIR, CONVERTED_DIR, NATIVE_DIR, ENDSTAR_TOOLS, ENDSTAR_AMBIGUOUS_TOOLS,
    VIDEO_URL_PATTERNS,
)


# ──────────────────────────────────────────────────────────
# Lesson keyword dictionary (from reference pipeline)
# ──────────────────────────────────────────────────────────

LESSON_KEYWORDS = {
    1: ["design brief", "problem statement", "audience", "UAE heritage", "cultural context", "sustainability", "innovation", "constraints"],
    2: ["persona", "empathy map", "UX", "player needs", "motivations", "frustrations", "user research", "bias"],
    3: ["primary research", "secondary research", "AI research", "reliability", "bias", "accuracy", "sources", "insights"],
    4: ["design specification", "team roles", "constraints", "success criteria", "collaboration", "research insights"],
    5: ["brainstorming", "concept generation", "micro-prototype", "storyboard", "core mechanic", "peer feedback"],
    6: ["prototype", "core mechanic", "debugging", "testing", "iteration", "playability"],
    7: ["gameplay expansion", "immersion", "visuals", "sound design", "dialogue", "polish"],
    8: ["peer testing", "WWW/EBI", "feedback analysis", "theme mapping", "usability"],
    9: ["iteration", "refinement", "feedback implementation", "impact vs effort", "prioritisation"],
    10: ["team roles", "project manager", "milestones", "timeline", "risk management"],
    11: ["documentation", "portfolio", "evidence", "curation", "reflection"],
    12: ["reflection", "evaluation", "SMART goals", "progress", "presentation"],
}


# ──────────────────────────────────────────────────────────
# Full file content reader
# ──────────────────────────────────────────────────────────

def read_full_content(doc):
    """Read the full content of a converted document (not just preview)."""
    full_path = doc.get("full_path", "")
    if full_path:
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass
    return doc.get("content_preview", "")


# ──────────────────────────────────────────────────────────
# Slide markdown parsing
# ──────────────────────────────────────────────────────────

def parse_slides_from_markdown(content):
    """Parse slide-based markdown into per-slide structures with text and notes."""
    slides = []
    current_slide = None
    current_text = []
    current_notes = []
    in_notes = False

    for line in content.split("\n"):
        match = re.match(r"^## Slide (\d+)", line)
        if match:
            if current_slide is not None:
                slides.append({
                    "slide_number": current_slide,
                    "text": "\n".join(current_text).strip(),
                    "notes": "\n".join(current_notes).strip(),
                })
            current_slide = int(match.group(1))
            current_text = []
            current_notes = []
            in_notes = False
        elif current_slide is not None:
            if "**Speaker Notes:**" in line:
                in_notes = True
                continue
            if line.strip() == "---":
                continue
            if in_notes:
                current_notes.append(line)
            else:
                current_text.append(line)

    if current_slide is not None:
        slides.append({
            "slide_number": current_slide,
            "text": "\n".join(current_text).strip(),
            "notes": "\n".join(current_notes).strip(),
        })

    return slides


def extract_tables_from_markdown(content):
    """Parse markdown tables into structured {headers, rows} format."""
    tables = []
    lines = content.split("\n")
    i = 0

    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|") and i + 1 < len(lines):
            next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if "|" in next_line and "---" in next_line:
                headers = [c.strip() for c in line.strip("|").split("|")]
                rows = []
                j = i + 2
                while j < len(lines) and lines[j].strip().startswith("|"):
                    row = [c.strip() for c in lines[j].strip().strip("|").split("|")]
                    rows.append(row)
                    j += 1
                tables.append({"headers": headers, "rows": rows})
                i = j
                continue
        i += 1

    return tables


# Assessment/rubric keywords for table classification
_RUBRIC_KEYWORDS = {
    "rubric", "criterion", "criteria", "assessment", "marks", "score",
    "grade", "grading", "proficient", "emerging", "exceeding", "level",
    "performance", "competency", "mastery", "beginning", "developing",
    "portfolio", "reflection", "self-assessment", "peer-assessment",
}

_SCHEDULE_KEYWORDS = {
    "week", "date", "deadline", "milestone", "schedule", "timeline",
    "session", "day", "period", "term", "semester", "calendar",
}


def classify_table(table):
    """Classify a table as 'rubric', 'schedule', or 'data'.

    Examines headers and first row content for assessment or scheduling keywords.
    """
    headers_text = " ".join(str(h).lower() for h in table.get("headers", []))
    rows = table.get("rows", [])
    first_row_text = " ".join(str(c).lower() for c in rows[0]) if rows else ""
    combined = headers_text + " " + first_row_text

    rubric_hits = sum(1 for kw in _RUBRIC_KEYWORDS if kw in combined)
    schedule_hits = sum(1 for kw in _SCHEDULE_KEYWORDS if kw in combined)

    if rubric_hits >= 2:
        return "rubric"
    if schedule_hits >= 2:
        return "schedule"
    if rubric_hits == 1:
        return "rubric"
    if schedule_hits == 1:
        return "schedule"
    return "data"


# ──────────────────────────────────────────────────────────
# Native Google Doc parsing
# ──────────────────────────────────────────────────────────

def parse_native_doc_sections(native_doc):
    """Parse a native Google Doc into heading-based sections.
    Returns dict mapping heading text -> list of content strings."""
    sections = {}
    current_heading = None
    current_content = []

    for block in native_doc.get("content_blocks", []):
        style = block.get("style", "")
        text = block.get("text", "").strip()

        if not text:
            continue

        if style in ("HEADING_1", "HEADING_2", "HEADING_3"):
            if current_heading is not None:
                sections[current_heading] = current_content
            current_heading = text
            current_content = []
        elif current_heading is not None:
            current_content.append(text)
        else:
            # Content before any heading
            sections.setdefault("_preamble", []).append(text)

    if current_heading is not None:
        sections[current_heading] = current_content

    return sections


def extract_from_native_doc(native_doc):
    """Extract structured metadata from a native Google Doc lesson plan."""
    sections = parse_native_doc_sections(native_doc)
    result = {
        "title": "",
        "big_question": "",
        "uae_link": "",
        "learning_objectives": [],
        "success_criteria": [],
        "activities": [],
        "assessment_summary": "",
        "curriculum_alignment": "",
    }

    for heading, content in sections.items():
        heading_lower = heading.lower()

        # Lesson title from HEADING_2: "Lesson X: Title" (accept :, –, —, -)
        if re.match(r"lesson\s*\d+\s*[:–\-—]", heading, re.IGNORECASE):
            result["title"] = heading

        # Big Question
        if "big question" in heading_lower:
            result["big_question"] = " ".join(content)

        # UAE Link
        if "uae" in heading_lower and "link" in heading_lower:
            result["uae_link"] = " ".join(content)

        # Learning Objectives
        if "learning objective" in heading_lower or "lesson objective" in heading_lower:
            for line in content:
                line = line.strip()
                if not line or len(line) < 10:
                    continue
                # Skip preamble lines
                if line.lower().startswith("by the end"):
                    continue
                # Split on numbered items if present
                items = re.split(r"\d+\.\s+", line)
                for item in items:
                    item = item.strip()
                    if item and len(item) > 10 and not item.lower().startswith("by the end"):
                        result["learning_objectives"].append(item)

        # Success Criteria
        if "success criteria" in heading_lower:
            for line in content:
                line = line.strip()
                if line and len(line) > 10:
                    result["success_criteria"].append(line)

        # Learning Activities / Starter
        if "learning activit" in heading_lower or "starter" in heading_lower:
            result["activities"].extend(content)

        # Assessment (Summary, for Learning, of Learning, etc.)
        if "assessment" in heading_lower:
            new_text = " ".join(content)
            if result["assessment_summary"]:
                result["assessment_summary"] += " " + new_text
            else:
                result["assessment_summary"] = new_text

        # Curriculum Alignment — keep as individual standards, not joined
        if "curriculum" in heading_lower and "alignment" in heading_lower:
            result["curriculum_alignment"] = content  # list of strings

    # ── Catch-all: capture any section NOT consumed by a specific extractor ──
    _CONSUMED_PATTERNS = [
        r"lesson\s*\d+\s*:",                    # title
        r"big question",                         # big_question
        r"uae.*link",                            # uae_link
        r"learning objective|lesson objective",  # objectives
        r"success criteria",                     # success_criteria
        r"learning activit|starter",             # activities
        r"assessment",                              # assessment
        r"curriculum.*alignment",                # curriculum_alignment
    ]
    remaining = {}
    for heading, content in sections.items():
        if heading == "_preamble":
            if content:
                remaining["_preamble"] = content
            continue
        consumed = False
        heading_lower = heading.lower()
        for pattern in _CONSUMED_PATTERNS:
            if re.search(pattern, heading_lower):
                consumed = True
                break
        if not consumed and content:
            remaining[heading] = content
    result["remaining_sections"] = remaining

    return result


def parse_docx_markdown_sections(text):
    """Parse DOCX-converted markdown into {heading: [content_lines]} sections.

    DOCX lesson plans use ## H2 headings to delimit sections. Returns a dict
    keyed by the heading text (without the ## prefix) with a list of non-empty
    content lines as values.
    """
    sections = {}
    current_heading = None
    current_lines = []

    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## "):
            # Save previous section
            if current_heading is not None:
                sections[current_heading] = current_lines
            current_heading = stripped[3:].strip()
            current_lines = []
        elif current_heading is not None and stripped:
            current_lines.append(stripped)

    # Save last section
    if current_heading is not None:
        sections[current_heading] = current_lines

    return sections


def extract_activities_from_docx_sections(sections):
    """Extract activity-related content from parsed DOCX markdown sections.

    Captures content under headings that contain activity-related keywords
    like 'Learning Activities', 'Starter', 'Reflection / Plenary'.
    Excludes headings that are clearly non-activity sections (title, criteria, etc.).
    """
    activity_keywords = [
        "learning activit", "starter", "plenary",
        "reflection / plenary", "reflection/plenary",
    ]
    # Headings to skip even if they contain a keyword
    exclude_patterns = [
        "success criteria", "curriculum", "assessment summary",
        "learning objective", "big question", "uae link",
    ]
    parts = []
    for heading, lines in sections.items():
        heading_lower = heading.lower()
        # Skip excluded sections
        if any(excl in heading_lower for excl in exclude_patterns):
            continue
        # Skip title headings (e.g., "Lesson 12: Reflection & Next Steps")
        if re.match(r"lesson\s*\d+", heading_lower):
            continue
        if any(kw in heading_lower for kw in activity_keywords):
            for line in lines:
                if len(line) > 15:  # Skip trivial lines
                    parts.append(line)
    return parts


def _ensure_trailing_punctuation(text):
    """Ensure text ends with proper punctuation. Adds a period if the text
    ends with an alphanumeric character (indicating a sentence cut off mid-flow)."""
    stripped = text.rstrip()
    if not stripped:
        return text
    if stripped[-1] not in ".!?:)]\"\u2019":
        stripped += "."
    return stripped


def extract_programme_metadata(text):
    """Extract programme-level metadata (Subject, Year Group, Duration) from text.
    Returns dict with keys present or empty dict if not found."""
    metadata = {}
    subject_match = re.search(r"Subject:\s*(.+?)(?:\n|$)", text)
    if subject_match:
        metadata["subject"] = subject_match.group(1).strip()
    year_match = re.search(r"Year Group:\s*(.+?)(?:\n|$)", text)
    if year_match:
        metadata["year_group"] = year_match.group(1).strip()
    duration_match = re.search(r"Duration:\s*(.+?)(?:\n|$)", text)
    if duration_match:
        metadata["duration"] = duration_match.group(1).strip()
    return metadata


def extract_curriculum_alignment_from_text(text):
    """Extract curriculum alignment standards from DOCX/markdown text.
    Handles both single-line and multi-line paragraphs where the framework
    name is on the first line and details follow on subsequent lines.
    Also finds framework references embedded mid-sentence."""
    prefixes = [
        "CSTA", "UK Computer Science", "UK Design", "IB Design",
        "IB MYP", "NGSS", "Common Core", "ISTE", "OECD",
        "UK D&T", "AQA",
    ]
    results = []
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            i += 1
            continue
        # Check if this line starts with a known framework prefix
        matched_prefix = None
        for prefix in prefixes:
            if stripped.startswith(prefix):
                matched_prefix = prefix
                break
        if matched_prefix:
            # Collect this line and any continuation lines (indented or non-prefix)
            block = [stripped]
            j = i + 1
            while j < len(lines):
                next_line = lines[j].strip()
                if not next_line:
                    break
                # Stop if next line starts a new framework prefix
                is_new_prefix = any(next_line.startswith(p) for p in prefixes)
                if is_new_prefix:
                    break
                # Stop if next line is a markdown heading
                if next_line.startswith("#"):
                    break
                block.append(next_line)
                j += 1
            results.append("\n".join(block))
            i = j
        else:
            # Second pass: check for framework refs embedded mid-sentence
            for prefix in prefixes:
                pos = stripped.find(prefix)
                if pos > 0:  # Found mid-line (not at start)
                    embedded = stripped[pos:].strip()
                    if embedded not in results:
                        results.append(embedded)
            i += 1
    return results


# Known curriculum framework prefixes for splitting joined alignment text
_ALIGNMENT_PREFIXES = [
    "CSTA", "UK Computer Science", "UK Design", "IB Design",
    "IB MYP", "NGSS", "Common Core", "ISTE", "OECD",
    "UK D&T", "AQA",
]


def _parse_curriculum_alignment(raw):
    """Parse curriculum alignment into structured list of {framework, standard, description}.

    Input is either a list of strings (one per standard) or a single joined string.
    """
    if isinstance(raw, str):
        # Split joined string back into individual standards
        lines = []
        for prefix in _ALIGNMENT_PREFIXES:
            parts = raw.split(prefix)
            if len(parts) > 1:
                for p in parts[1:]:
                    lines.append(prefix + p.strip())
                raw = parts[0]
        if not lines:
            lines = [raw.strip()] if raw.strip() else []
    else:
        lines = [l.strip() for l in raw if l.strip()]

    results = []
    for line in lines:
        # Try to extract framework name from known prefixes
        framework = ""
        for prefix in _ALIGNMENT_PREFIXES:
            if line.startswith(prefix):
                framework = prefix
                break
        results.append({
            "framework": framework,
            "text": line,
        })
    return results


def extract_curriculum_alignment_from_slides(slides):
    """Extract curriculum alignment from slide speaker notes (fallback for T1).
    Looks for known framework prefixes in speaker notes text, including
    references embedded mid-sentence."""
    alignments = []
    for slide in slides:
        notes = slide.get("notes", "")
        if not notes:
            continue
        lines = notes.split("\n")
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            found_start = False
            for prefix in _ALIGNMENT_PREFIXES:
                if stripped.startswith(prefix):
                    if stripped not in alignments:
                        alignments.append(stripped)
                    found_start = True
                    break
            if not found_start:
                # Second pass: find framework refs embedded mid-sentence
                for prefix in _ALIGNMENT_PREFIXES:
                    pos = stripped.find(prefix)
                    if pos > 0:
                        embedded = stripped[pos:].strip()
                        if embedded not in alignments:
                            alignments.append(embedded)
    return alignments


# ──────────────────────────────────────────────────────────
# Extraction from teacher slides markdown
# ──────────────────────────────────────────────────────────

def extract_title_from_slides(slides):
    """Extract lesson title from early slides.
    Strategy: first try 'Lesson X: Title' pattern, then look for descriptive
    headings on early slides."""
    # Strategy 1: Explicit "Lesson X: Title" or "Lesson X – Title"
    for slide in slides:
        text = slide["text"]
        lines = text.split("\n")
        for line in lines:
            line = line.strip()
            match = re.match(r"Lesson\s*\d+\s*[:–\-]\s*(.+)", line)
            if match:
                title = match.group(1).strip()
                if title and len(title) > 5:
                    return title

    # Strategy 2: Find descriptive heading on early slides (Term 1 format)
    # Skip slide 1 (usually cover/diagnostic), look at slides 2-5
    for slide in slides[1:6]:
        text = slide["text"]
        lines = text.split("\n")
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("‹") or len(stripped) < 10:
                continue
            # Skip generic text
            stripped_lower = stripped.lower()
            if any(kw in stripped_lower for kw in [
                "term ", "lesson ", "level ", "click", "please", "scan",
                "welcome", "today", "mandatory", "diagnostic", "speaker note",
                "http", "important", "explorer", "activity ", "portfolio entry",
                "upload", "submit", "download",
                "learning check", "learning objective", "lesson objective",
                "assessment", "plenary", "mcq", "quiz", "afl",
            ]):
                continue
            # A good title is 10-80 chars, starts with capital, not a question
            if (10 < len(stripped) < 80 and
                stripped[0].isupper() and
                not stripped.endswith("?") and
                not stripped.endswith(".")):
                return stripped

    return ""


def extract_learning_objectives_from_slides(slides):
    """Extract learning objectives from slides containing 'Learning Objectives' or 'Lesson Objectives'.
    Handles two formats:
    - Term 2/3: heading first, then objectives below
    - Term 1: objectives text on the same slide, heading label at bottom
    """
    objectives = []

    for slide in slides:
        text = slide["text"]
        notes = slide["notes"]
        combined = text + "\n" + notes

        if "learning objective" not in combined.lower() and "lesson objective" not in combined.lower():
            continue

        # Clean vertical tab and other control chars
        text = text.replace("\x0b", "\n").replace("\r", "\n")

        lines = text.split("\n")
        heading_idx = -1

        # Find the heading line index
        for idx, line in enumerate(lines):
            if any(kw in line.lower() for kw in ["learning objective", "lesson objective"]):
                heading_idx = idx
                break

        if heading_idx == -1:
            continue

        # Strategy A: Content AFTER the heading (Term 2/3 format)
        post_objectives = []
        current_title = ""
        # Patterns that indicate success criteria / self-assessment, not objectives
        _success_criteria_patterns = [
            "i can ", "i clearly ", "i differentiated", "i critically",
            "i have ", "i am able",
            "success criteria", "we will know", "successful when",
        ]
        for line in lines[heading_idx + 1:]:
            stripped = line.strip()
            if not stripped:
                continue
            if any(kw in stripped.lower() for kw in ["by the end"]):
                continue
            stripped = re.sub(r"^[\d.)\-•*]+\s*", "", stripped)
            if stripped.startswith("‹") or len(stripped) < 10:
                continue
            # Skip self-assessment / success criteria lines
            stripped_lower = stripped.lower()
            if any(pat in stripped_lower for pat in _success_criteria_patterns):
                continue
            # Detect title-like lines (short, title case) vs description lines
            if len(stripped) < 60 and stripped[0].isupper() and not stripped.endswith("."):
                if current_title:
                    post_objectives.append(current_title)
                current_title = stripped
            elif current_title:
                post_objectives.append(f"{current_title}: {stripped}")
                current_title = ""
            else:
                post_objectives.append(stripped)
        if current_title:
            post_objectives.append(current_title)

        # Strategy B: Content BEFORE the heading (Term 1 format)
        # Term 1 has objectives listed above the "Lesson Objectives" label
        pre_objectives = []
        for line in lines[:heading_idx]:
            stripped = line.strip()
            if not stripped or stripped.startswith("‹"):
                continue
            # Skip very short lines (slide numbers, bullets, etc.)
            if len(stripped) < 10:
                continue
            # Skip noise lines
            stripped_lower = stripped.lower()
            if any(kw in stripped_lower for kw in [
                "by the end", "term ", "lesson ", "click", "scan",
                "welcome", "today", "explorer", "http",
            ]):
                continue
            # Skip success criteria / self-assessment lines (same as Strategy A)
            if any(pat in stripped_lower for pat in _success_criteria_patterns):
                continue
            stripped = re.sub(r"^[\d.)\-•*]+\s*", "", stripped)
            if stripped and len(stripped) >= 10:
                pre_objectives.append(stripped)

        # Use whichever strategy found more content
        if len(post_objectives) >= len(pre_objectives):
            objectives.extend(post_objectives)
        else:
            objectives.extend(pre_objectives)

    return objectives


def extract_big_question_from_slides(slides):
    """Extract big question from slides with 'Big Question / Big Picture'."""
    for slide in slides:
        text = slide["text"]
        if "big question" not in text.lower() and "big picture" not in text.lower():
            continue

        lines = text.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped.endswith("?") and len(stripped) > 20:
                return stripped
            # Check for question-like text
            if "?" in stripped and len(stripped) > 20 and "big question" not in stripped.lower():
                return stripped.strip()

    return ""


def extract_uae_link_from_slides(slides):
    """Extract UAE link/context from slide content."""
    for slide in slides:
        text = slide["text"] + "\n" + slide["notes"]
        match = re.search(r"UAE\s*Link\s*:\s*(.+?)(?:\n\n|\n(?=[A-Z][a-z]+\s*:)|$)", text, re.DOTALL | re.IGNORECASE)
        if match:
            uae_text = match.group(1).strip()
            # Clean up
            uae_text = re.sub(r"\s+", " ", uae_text)
            if len(uae_text) > 20:
                return uae_text

    return ""


def extract_success_criteria_from_slides(slides):
    """Extract success criteria from slides with 'we will know we are successful',
    'Criteria:', or tiered 'All students must / Many will / Some may' format."""
    criteria = []

    for slide in slides:
        text = slide["text"]
        text_lower = text.lower()

        # Check for known success criteria triggers
        has_trigger = any(kw in text_lower for kw in [
            "successful", "success criteria", "criteria:",
            "all students must", "many students will", "some students may",
        ])
        if not has_trigger:
            continue

        lines = text.split("\n")
        capturing = False
        for line in lines:
            stripped = line.strip()
            if "successful" in stripped.lower() or "success criteria" in stripped.lower() or stripped.lower().startswith("criteria"):
                capturing = True
                continue

            # Capture tiered differentiated criteria
            tiered_match = re.match(
                r"((?:All|Many|Some)\s+students\s+(?:must|will|may|could)\b.*)",
                stripped, re.IGNORECASE,
            )
            if tiered_match:
                capturing = True
                cleaned = tiered_match.group(1).strip()
                if cleaned and len(cleaned) > 15:
                    criteria.append(cleaned)
                continue

            if capturing and stripped:
                stripped = re.sub(r"^[\d.)\-•*]+\s*", "", stripped)
                if len(stripped) > 15 and not stripped.startswith("‹"):
                    criteria.append(stripped)

    return criteria


def extract_activities_from_slides(slides):
    """Extract activity descriptions from teacher slides.
    Prioritizes student-facing activity content from slide text."""
    student_activities = []
    teacher_notes_activities = []

    for slide in slides:
        text = slide["text"]
        notes = slide["notes"]
        text_lower = text.lower()

        # Priority 1: Slide content describing student activities
        if any(kw in text_lower for kw in ["activity", "task", "students will", "students should",
                                            "portfolio entry", "your turn", "mini task",
                                            "explore:", "create:", "discuss:", "present:"]):
            lines = text.split("\n")
            for line in lines:
                stripped = line.strip()
                if len(stripped) > 25 and not stripped.startswith("‹"):
                    # Filter out navigation / header text
                    if not any(skip in stripped.lower() for skip in ["speaker note", "click here", "scan the"]):
                        student_activities.append(stripped)

        # Priority 2: Speaker notes with activity instructions (backup)
        if notes:
            notes_lower = notes.lower()
            if any(kw in notes_lower for kw in ["students", "activity", "task"]):
                for line in notes.split("\n"):
                    stripped = line.strip()
                    if (len(stripped) > 40 and
                        any(kw in stripped.lower() for kw in ["students", "activity", "task", "portfolio", "group"]) and
                        not stripped.lower().startswith("curriculum")):
                        teacher_notes_activities.append(stripped)

    # Combine: student content first, then teacher notes
    return student_activities + teacher_notes_activities


def extract_ai_focus_from_slides(slides):
    """Extract concise AI-related focus points from slide content.
    Looks for AI concepts, not just any line mentioning AI."""
    ai_points = []

    # Patterns that indicate AI teaching focus (not just mentions)
    ai_teaching_patterns = [
        r"AI\s+(?:for|in|and|basics|literacy|skills|concepts|tools|agent|workspace|ethics|responsibility)",
        r"(?:generative|agentic|rule.based|learning.based)\s+AI",
        r"AI\s+(?:does not|cannot|should|must|expands|supports|generates)",
        r"human\s+(?:judgement|oversight|control|decision|interpretation|ownership)",
        r"(?:prompt|prompting)\s+(?:engineering|design|technique)",
        r"responsible\s+(?:AI|use|technology)",
        r"machine\s+learning",
        r"(?:bias|reliability|accuracy)\s+in\s+AI",
    ]

    for slide in slides:
        text = slide["text"] + "\n" + slide["notes"]
        lines = text.split("\n")

        for line in lines:
            stripped = line.strip()
            if not stripped or len(stripped) < 20 or len(stripped) > 150:
                continue

            # Skip page numbers, links, navigation, MCQ answers
            if stripped.startswith("‹") or stripped.startswith("http"):
                continue
            if re.match(r"^[A-Da-d][\.\)]\s", stripped):
                continue

            stripped_lower = stripped.lower()

            # Check for AI teaching patterns
            for pattern in ai_teaching_patterns:
                if re.search(pattern, stripped, re.IGNORECASE):
                    cleaned = re.sub(r"^[\d.)\-•*]+\s*", "", stripped).strip()
                    if cleaned and len(cleaned) > 15:
                        ai_points.append(cleaned)
                    break

    # Deduplicate by prefix similarity
    seen = set()
    unique = []
    for point in ai_points:
        key = re.sub(r"[^a-z0-9]", "", point[:40].lower())
        if key not in seen:
            seen.add(key)
            unique.append(point)

    return unique


def extract_core_topics_from_slides(slides, lesson_num):
    """Extract core topics from slide section headings and learning content.
    Focuses on finding actual educational topic headings, not UI text."""
    topics = []

    # Skip patterns - these are NOT topics
    skip_patterns = [
        r"^click", r"^please", r"^scan", r"^start", r"^in this lesson",
        r"^by the end", r"^we will know", r"^what do", r"^big question",
        r"^your turn", r"mandatory", r"diagnostic", r"^term \d",
        r"^lesson \d", r"^today", r"explorer.*programme", r"^important",
        r"^activity \d", r"^portfolio entry", r"^upload", r"^submit",
        r"^[A-Da-d][\.\)]\s",  # MCQ answer options (A. / B) / etc.)
        r"^learning objective", r"^learning check", r"^lesson objective",
        r"^success criteria", r"^my success", r"^self.assessment",
        r"^write ", r"^short ", r"^add ", r"^fill ", r"^step \d",
        r"^open ", r"^need help", r"^follow this",
        r"^let'?s", r"^remember",
    ]

    for slide in slides[2:]:  # Skip first 2 slides (usually title/cover)
        text = slide["text"]
        lines = text.split("\n")

        for line in lines:
            stripped = line.strip().strip("*")
            if not stripped or stripped.startswith("‹") or len(stripped) < 8:
                continue

            stripped_lower = stripped.lower()

            # Skip noise patterns
            if any(re.search(p, stripped_lower) for p in skip_patterns):
                continue

            # Skip questions and very long text
            if stripped.endswith("?") or len(stripped) > 70:
                continue

            # Look for topic-like headings: short, title-case phrases
            words = stripped.split()
            if 2 <= len(words) <= 8:
                # Check if it looks like a section heading
                if (stripped[0].isupper() and
                    not stripped.endswith(".") and
                    not stripped.endswith(",") and
                    ":" not in stripped):  # Skip "Activity 1: ..."
                    topic = stripped
                    if topic not in topics:
                        topics.append(topic)

    # Supplement with lesson keyword dictionary matches
    lesson_kws = LESSON_KEYWORDS.get(lesson_num, [])
    all_text = " ".join(s["text"] + " " + s["notes"] for s in slides).lower()
    for kw in lesson_kws:
        if kw.lower() in all_text:
            # Capitalize for display
            capitalized = kw.title()
            if capitalized not in topics and not any(capitalized.lower() in t.lower() for t in topics):
                topics.append(capitalized)

    return topics


def extract_core_topics_from_native(native_content, lesson_num):
    """Extract core topics from native Google Doc content (HEADING_3 sections)."""
    topics = []
    skip_headings = ["big question", "uae link", "learning objective", "success criteria",
                     "starter", "reflection", "plenary", "assessment", "curriculum"]

    for native in native_content:
        if native.get("native_type") != "google_doc":
            continue
        for block in native.get("content_blocks", []):
            style = block.get("style", "")
            text = block.get("text", "").strip()
            if style == "HEADING_3" and text:
                text_lower = text.lower()
                # Skip standard section headings
                if any(skip in text_lower for skip in skip_headings):
                    continue
                if len(text) > 5 and len(text) < 80:
                    topics.append(text)

    # Supplement with lesson keyword dictionary
    lesson_kws = LESSON_KEYWORDS.get(lesson_num, [])
    all_text = ""
    for native in native_content:
        for block in native.get("content_blocks", []):
            all_text += block.get("text", "") + " "
    all_text_lower = all_text.lower()

    for kw in lesson_kws:
        if kw.lower() in all_text_lower:
            capitalized = kw.title()
            if capitalized not in topics and not any(capitalized.lower() in t.lower() for t in topics):
                topics.append(capitalized)

    return topics


def extract_activity_type_from_content(slides, activities_text, lesson_title=""):
    """Determine the activity type from content analysis.
    Uses lesson-specific text only (slide text + activities), not shared docs."""
    slide_text = " ".join(s["text"] + " " + s["notes"] for s in slides).lower() if slides else ""
    all_text = (slide_text + " " + activities_text).lower()
    title_lower = lesson_title.lower() if lesson_title else ""

    # Primary activity signals — ordered from most specific to most generic.
    # Use multi-word phrases to avoid false matches from common single words.
    primary_signals = {
        "Agentic AI": ["agentic ai", "ai agent", "autonomous agent", "agent framework"],
        "Brief analysis": ["design brief", "brief analysis", "analyse the brief", "problem statement"],
        "Persona and empathy mapping": ["persona", "empathy map", "player profile", "user research"],
        "Research and prototyping": ["primary research", "secondary research", "research method", "research finding"],
        "Brief refinement and team setup": ["brief refinement", "rewrite the brief", "team roles", "role allocation"],
        "Ideation and prototyping": ["brainstorm", "ideation", "concept generation", "storyboard"],
        "Prototyping and iteration": ["prototype build", "debugging", "iteration cycle", "build and test"],
        "Game expansion and polish": ["game expansion", "polish", "immersion", "visual enhancement"],
        "Peer testing and feedback": ["peer test", "peer review", "www/ebi", "ebi feedback"],
        "Iteration and refinement": ["iteration plan", "refine and improve", "priority matrix", "feedback implementation"],
        "Project management": ["project manage", "milestone", "timeline", "risk assessment"],
        "Reflection and evaluation": ["reflection", "self-evaluation", "smart goal", "presentation prep"],
        "Launch strategy": ["launch strategy", "launch plan", "go-to-market", "marketing strategy"],
        "Game readiness review": ["game readiness", "readiness review", "launch checklist", "final review"],
    }

    # Secondary activity signals (only used as fallback when no primary match)
    secondary_signals = {
        "Portfolio and documentation": ["portfolio", "documentation", "evidence", "curate"],
    }

    # Lesson-title boosting: if title contains a distinctive phrase, boost that type
    title_boost = {}
    for activity_type, signals in primary_signals.items():
        for s in signals:
            if s in title_lower:
                title_boost[activity_type] = title_boost.get(activity_type, 0) + 2

    best_type = ""
    best_score = 0
    for activity_type, signals in primary_signals.items():
        score = sum(1 for s in signals if s in all_text)
        score += title_boost.get(activity_type, 0)
        if score > best_score:
            best_score = score
            best_type = activity_type

    # Only fall back to secondary signals if no primary match
    if best_score == 0:
        for activity_type, signals in secondary_signals.items():
            score = sum(1 for s in signals if s in all_text)
            if score > best_score:
                best_score = score
                best_type = activity_type

    return best_type if best_score > 0 else ""


def extract_artifacts_from_slides(slides):
    """Extract portfolio entries and artifacts from slide content."""
    artifacts = []
    seen_keys = set()  # Normalized keys for deduplication

    for slide in slides:
        text = slide["text"] + "\n" + slide["notes"]
        # Match "Portfolio Entry/Evidence X – Title" or similar (em-dash, en-dash, hyphen, colon)
        matches = re.findall(r"Portfolio\s+(?:Entry|Evidence)\s+\d+\s*[–\-—:]\s*([^\n]+)", text, re.IGNORECASE)
        for m in matches:
            artifact = f"Portfolio Entry – {m.strip()}"
            key = artifact.lower().strip()
            if key not in seen_keys:
                seen_keys.add(key)
                artifacts.append(artifact)

        # Also look for "Portfolio Entry/Evidence X" without title
        matches = re.findall(r"(Portfolio\s+(?:Entry|Evidence)\s+\d+[^\n]*)", text, re.IGNORECASE)
        for m in matches:
            m = m.strip()
            key = m.lower().strip()
            if m and key not in seen_keys and not any(key in k for k in seen_keys):
                seen_keys.add(key)
                artifacts.append(m)

    return artifacts


def extract_assessment_signals_from_slides(slides):
    """Extract assessment signals (basic/intermediate/advanced) from content.
    Focuses on tiered criteria, 'I can...' statements, and formal quiz codes."""
    signals = []

    for slide in slides:
        text = slide["text"]
        text_lower = text.lower()

        # Look for tiered assessment patterns
        for level in ["basic", "emerging", "intermediate", "developing", "advanced", "proficient"]:
            pattern = rf"{level}\s*[:–\-]\s*([^\n]+)"
            matches = re.findall(pattern, text, re.IGNORECASE)
            for m in matches:
                signal = f"{level}: {m.strip()}"
                if signal not in signals:
                    signals.append(signal)

        # Look for formal AFL MCQ quiz codes (GD-14.1, AI-07.2, etc.)
        quiz_matches = re.findall(r"((?:GD|AI)-\d+[\.\:]\d*\s*[^\n]*)", text)
        for m in quiz_matches:
            m = m.strip()
            if m and m not in signals:
                signals.append(m)

        # "I can..." statements from success criteria slides
        if "success criteria" in text_lower or "successful" in text_lower:
            # Clean control chars
            clean_text = text.replace("\x0b", "\n")
            lines = clean_text.split("\n")
            for line in lines:
                stripped = line.strip()
                if not stripped or stripped.startswith("‹") or len(stripped) < 20:
                    continue
                # Skip header-like lines
                if "success criteria" in stripped.lower() or "successful" in stripped.lower():
                    continue
                if "lesson" in stripped.lower() and ":" in stripped:
                    continue
                # Only capture actual assessment content, not general slide text
                stripped = re.sub(r"^[\d.)\-•*]+\s*", "", stripped)
                if stripped and len(stripped) > 20:
                    # Skip separator lines (underscores, dashes, pipes, equals)
                    if re.match(r'^[\s\-_|=*]+$', stripped):
                        continue
                    stripped_lower = stripped.lower()
                    is_assessment = (
                        stripped_lower.startswith("i can") or
                        stripped_lower.startswith("i have") or
                        stripped_lower.startswith("i am able") or
                        "all students" in stripped_lower or
                        "many students" in stripped_lower or "many will" in stripped_lower or
                        "some students" in stripped_lower or "some may" in stripped_lower or
                        re.match(r"^(basic|intermediate|advanced|emerging|proficient)\s*:", stripped_lower)
                    )
                    if is_assessment:
                        signals.append(stripped)

    return signals


def extract_resources_from_slides(slides):
    """Extract resource references from slide content.
    Only extracts actual URLs — bare text mentions like 'Rubric' are not resources."""
    resources = []

    for slide in slides:
        text = slide["text"] + "\n" + slide["notes"]

        # Extract actual URLs
        urls = re.findall(r"https?://[^\s\n\)\"'>]+", text)
        for url in urls:
            url = url.rstrip(".,;:")
            if url and url not in resources:
                resources.append(url)

        # Named tool references with URLs (e.g. "Classkick at https://...")
        tool_url_matches = re.findall(
            r"(?:Classkick|Google\s+(?:Classroom|Drive|Slides|Docs))\s+(?:at\s+)?(https?://[^\s\n]+)",
            text, re.IGNORECASE
        )
        for url in tool_url_matches:
            url = url.rstrip(".,;:")
            if url and url not in resources:
                resources.append(url)

    return resources


# ──────────────────────────────────────────────────────────
# Keyword extraction (content-aware + dictionary)
# ──────────────────────────────────────────────────────────

def extract_keywords(all_text, lesson_num, lesson_specific_text=""):
    """Extract keywords combining dictionary lookup with content analysis.

    Args:
        all_text: Full concatenated text (slides + shared docs) — fallback for keyword matching.
        lesson_num: Lesson number for LESSON_KEYWORDS dictionary.
        lesson_specific_text: Text from lesson slides, speaker notes, and lesson plan only
            (not shared assessment/programme docs). Both dictionary keywords and content
            candidates are matched against this narrower text to avoid programme-wide
            terms appearing in every lesson.
    """
    keywords = []

    # Start with lesson-specific keywords that appear in content
    # Use lesson_specific_text (slides + notes + lesson plan) when available
    # to avoid programme-wide terms appearing in every lesson
    lesson_kws = LESSON_KEYWORDS.get(lesson_num, [])
    specific_lower = (lesson_specific_text or all_text).lower()

    for kw in lesson_kws:
        if kw.lower() in specific_lower:
            keywords.append(kw)

    # Additional content-based keywords — matched against lesson-specific text only
    # to avoid programme-wide terms (player, portfolio, assessment) appearing in every lesson
    specific_lower = (lesson_specific_text or all_text).lower()
    content_candidates = [
        "design brief", "problem statement", "audience", "constraints",
        "UAE heritage", "sustainability", "innovation", "persona",
        "empathy map", "UX", "player", "prototype", "debugging",
        "testing", "iteration", "brainstorming", "storyboard",
        "game mechanic", "gameplay", "level design", "feedback",
        "portfolio", "reflection", "collaboration", "teamwork",
        "assessment", "rubric", "peer testing", "presentation",
        "research", "AI", "endstar", "game design", "narrative",
        "color theory", "moodboard", "coding", "rule block",
        "agentic AI", "generative AI", "machine learning",
        "launch", "strategy", "quality assurance", "playtest",
        "immersion", "sound design", "dialogue", "polish",
    ]

    for kw in content_candidates:
        kw_lower = kw.lower()
        # Use word-boundary matching to avoid partial matches (e.g. "AI" in "detail")
        if " " in kw_lower:
            if kw_lower in specific_lower and kw not in keywords:
                keywords.append(kw)
        else:
            pattern = r"(?<![a-zA-Z])" + re.escape(kw_lower) + r"(?![a-zA-Z])"
            if re.search(pattern, specific_lower) and kw not in keywords:
                keywords.append(kw)

    return keywords


# ──────────────────────────────────────────────────────────
# Endstar tools, video refs, and resource link extraction
# ──────────────────────────────────────────────────────────

def extract_endstar_tools(all_text):
    """Match Endstar platform tool keywords against combined lesson text.
    Returns deduplicated list of canonical tool names.
    Ambiguous single-word tools (sound, mechanics, visuals) require
    co-occurrence with Endstar-related context terms."""
    text_lower = all_text.lower()
    found = set()
    # Check explicit (non-ambiguous) keywords first
    for keyword, canonical in ENDSTAR_TOOLS.items():
        if " " in keyword:
            if keyword in text_lower:
                found.add(canonical)
        else:
            pattern = r"(?<![a-z])" + re.escape(keyword) + r"(?![a-z])"
            if re.search(pattern, text_lower):
                found.add(canonical)
    # Check ambiguous single-word keywords only with Endstar context
    _context_terms = ["endstar", "platform tool", "tool panel",
                      "toolbox", "endstar tool", "endstar feature"]
    has_context = any(ct in text_lower for ct in _context_terms)
    if has_context:
        for keyword, canonical in ENDSTAR_AMBIGUOUS_TOOLS.items():
            if canonical not in found:
                pattern = r"(?<![a-z])" + re.escape(keyword) + r"(?![a-z])"
                if re.search(pattern, text_lower):
                    found.add(canonical)
    return sorted(found)


def extract_video_refs_from_slides(slides):
    """Extract video references from slide text mentions (URLs + contextual keywords).
    Captures YouTube/Vimeo URLs and Drive file links near video-related keywords."""
    video_refs = []
    seen_urls = set()
    # Patterns for video service URLs
    yt_pattern = re.compile(
        r"((?:https?://)?(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)[\w\-]+)", re.IGNORECASE
    )
    vimeo_pattern = re.compile(
        r"((?:https?://)?(?:www\.)?vimeo\.com/\d+)", re.IGNORECASE
    )
    # Drive file link near video keywords
    drive_pattern = re.compile(
        r"(https?://drive\.google\.com/file/d/[\w\-]+(?:/[^\s]*)?)", re.IGNORECASE
    )
    video_keywords = ["video", "tutorial", "watch", "\U0001f3a5", "\U0001f4f9",
                       "\U0001f517"]  # 🎥 📹 🔗

    for slide in slides:
        combined = slide["text"] + "\n" + slide["notes"]
        # Extract YouTube URLs
        for match in yt_pattern.finditer(combined):
            url = match.group(1)
            if url not in seen_urls:
                seen_urls.add(url)
                video_refs.append({
                    "url": url, "type": "youtube",
                    "title": "", "video_id": "",
                })
        # Extract Vimeo URLs
        for match in vimeo_pattern.finditer(combined):
            url = match.group(1)
            if url not in seen_urls:
                seen_urls.add(url)
                video_refs.append({
                    "url": url, "type": "vimeo",
                    "title": "", "video_id": "",
                })
        # Extract Drive file links only near video context
        combined_lower = combined.lower()
        if any(kw in combined_lower for kw in video_keywords):
            for match in drive_pattern.finditer(combined):
                url = match.group(1)
                if url not in seen_urls:
                    seen_urls.add(url)
                    video_refs.append({
                        "url": url, "type": "drive_video",
                        "title": "", "video_id": "",
                    })
    return video_refs


def build_video_entries(video_refs):
    """Build metadata.videos[] from consolidated video references.
    Deduplicates by URL/filename."""
    videos = []
    seen = set()
    for i, vref in enumerate(video_refs):
        # Dedup key: URL or filename
        key = vref.get("url", "") or vref.get("filename", "") or vref.get("video_id", "")
        if not key or key in seen:
            continue
        seen.add(key)

        vtype = vref.get("type", "")
        if vtype == "video_file":
            title = vref.get("title", vref.get("filename", ""))
            url = vref.get("path", "")
        else:
            title = vref.get("title", "") or vref.get("url", "")
            url = vref.get("url", "")

        videos.append({
            "video_id": vref.get("video_id", "") or Path(vref.get("filename", "")).stem if vref.get("filename") else "",
            "title": title,
            "url": url,
            "order": len(videos) + 1,
            "duration": "",
            "full_transcript": "",
            "type": vtype,
        })

    return videos


def build_resource_entries(links):
    """Build metadata.resources[] from consolidated hyperlinks.
    Deduplicates by URL and formats as descriptive strings."""
    resources = []
    seen_urls = set()

    for link in links:
        url = link.get("url", "").strip()
        if not url or url in seen_urls:
            continue
        # Skip non-web URLs (e.g. PPTX internal XML references like slide10.xml)
        if not url.startswith("http") and not url.startswith("mailto:"):
            continue
        seen_urls.add(url)

        # Skip video URLs — those go to metadata.videos
        is_video = False
        for pattern in VIDEO_URL_PATTERNS:
            if pattern.search(url):
                is_video = True
                break
        if is_video:
            continue

        text = link.get("text", "").strip()
        # Format as "Label - URL" if we have descriptive text, else just the URL
        if text and len(text) > 3 and not text.startswith("http"):
            resource_str = f"{text} - {url}"
        else:
            resource_str = url

        resources.append(resource_str)

    return resources


# ──────────────────────────────────────────────────────────
# KB building
# ──────────────────────────────────────────────────────────

def build_lesson_kb(lesson_num, lesson_data, term_num):
    """
    Build a single lesson's KB entry.
    Extracts ALL values fresh from source documents.
    """
    week = None
    for w, lessons in WEEK_LESSON_MAP.items():
        if lesson_num in lessons:
            week = w
            break

    docs = lesson_data.get("documents", [])
    native_content = lesson_data.get("native_content", [])

    # ── Read full content from converted files ──
    all_text = ""
    all_slides = []
    all_tables = []
    all_speaker_notes = []
    contributing_doc_paths = set()  # Track docs that actually produced content

    for doc in docs:
        content = read_full_content(doc)
        if content.strip():
            contributing_doc_paths.add(doc.get("path", ""))
        all_text += content + "\n"

        # Parse slides from ANY markdown with slide patterns
        if "## Slide " in content:
            slides = parse_slides_from_markdown(content)
            if slides:
                all_slides.extend(slides)

        tables = extract_tables_from_markdown(content)
        all_tables.extend(tables)

    # ── Parse DOCX markdown sections (## H2 headings) ──
    docx_sections = parse_docx_markdown_sections(all_text)
    docx_activities = extract_activities_from_docx_sections(docx_sections)

    # ── Extract programme metadata from all_text (DOCX lesson plans) ──
    programme_metadata = extract_programme_metadata(all_text)

    # ── Extract curriculum alignment from DOCX text (fallback for non-native lessons) ──
    docx_curriculum_lines = extract_curriculum_alignment_from_text(all_text)

    # ── Extract from native Google Doc lesson plans (priority source) ──
    native_title = ""
    native_objectives = []
    native_big_question = ""
    native_uae_link = ""
    native_success_criteria = []
    native_activities = []
    native_assessment = ""
    native_curriculum_alignment = []
    native_remaining_content = []  # catch-all for unconsumed native doc sections

    for native in native_content:
        if native.get("native_type") == "google_doc":
            extracted = extract_from_native_doc(native)
            if extracted["title"] and not native_title:
                native_title = extracted["title"]
            if extracted["learning_objectives"] and not native_objectives:
                native_objectives = extracted["learning_objectives"]
            if extracted["big_question"] and not native_big_question:
                native_big_question = extracted["big_question"]
            if extracted["uae_link"] and not native_uae_link:
                native_uae_link = extracted["uae_link"]
            if extracted["success_criteria"] and not native_success_criteria:
                native_success_criteria = extracted["success_criteria"]
            if extracted["activities"] and not native_activities:
                native_activities = extracted["activities"]
            if extracted["assessment_summary"] and not native_assessment:
                native_assessment = extracted["assessment_summary"]
            if extracted["curriculum_alignment"] and not native_curriculum_alignment:
                native_curriculum_alignment = _parse_curriculum_alignment(extracted["curriculum_alignment"])
            # Catch-all: store any unconsumed sections
            remaining = extracted.get("remaining_sections", {})
            for heading, content in remaining.items():
                native_remaining_content.append({
                    "heading": heading,
                    "content": content if isinstance(content, list) else [content],
                })

    # Extract ALL content from native slides/docs (not just keyword corpus)
    native_slides_links = []      # {url, text, slide_number}
    native_slides_videos = []     # {url, source, video_id, ...}
    native_slides_images = []     # {url, source_url, object_id}
    native_slides_tables = []     # {headers, rows}
    native_slides_speaker_notes = []  # {slide, notes}
    _seen_native_img_urls = set()

    for native in native_content:
        ntype = native.get("native_type", "")
        native_file_name = native.get("file_name", "")

        if ntype == "google_slides":
            for slide in native.get("slides", []):
                slide_num = slide.get("slide_number", 0)

                # Text → keyword corpus + structured slide content
                slide_texts = []
                for text in slide.get("texts", []):
                    all_text += text + "\n"
                    slide_texts.append(text)

                # Add native slide to all_slides for slides[]
                slide_notes = slide.get("speaker_notes", "")
                if slide_texts or slide_notes:
                    # Check if this slide_num already exists from PPTX conversion
                    existing_nums = {s["slide_number"] for s in all_slides}
                    if slide_num not in existing_nums:
                        all_slides.append({
                            "slide_number": slide_num,
                            "text": "\n".join(slide_texts),
                            "notes": slide_notes,
                        })

                # Speaker notes → keyword corpus + teacher_notes
                if slide_notes:
                    all_text += slide_notes + "\n"
                    native_slides_speaker_notes.append({
                        "slide": slide_num,
                        "notes": slide["speaker_notes"],
                    })

                # Per-slide links → resources
                for link in slide.get("links", []):
                    if link.get("url"):
                        native_slides_links.append(link)

                # Per-slide videos → video entries
                for video in slide.get("videos", []):
                    if video.get("url"):
                        native_slides_videos.append(video)

                # Per-slide image URLs → image entries (dedup by URL)
                for img in slide.get("image_urls", []):
                    img_url = img.get("url", "")
                    if img_url and img_url not in _seen_native_img_urls:
                        _seen_native_img_urls.add(img_url)
                        native_slides_images.append({
                            **img,
                            "slide_number": slide_num,
                            "source_pptx": native_file_name,
                        })

                # Per-slide tables → structured tables
                for table in slide.get("tables", []):
                    if table.get("headers") or table.get("rows"):
                        native_slides_tables.append(table)

        elif ntype == "google_doc":
            for block in native.get("content_blocks", []):
                if block.get("text"):
                    all_text += block["text"] + "\n"
            # Also extract links from Google Docs
            for link in native.get("links", []):
                if link.get("url"):
                    native_slides_links.append(link)

    # Add native Slides tables to all_tables (tagged as native)
    for t in native_slides_tables:
        t["_source"] = "native_slides"
    all_tables.extend(native_slides_tables)

    # Classify tables into rubrics, schedule_tables, data_tables
    rubrics = []
    schedule_tables = []
    data_tables = []
    for table in all_tables:
        tclass = classify_table(table)
        # Remove internal tag before storing
        clean_table = {k: v for k, v in table.items() if not k.startswith("_")}
        if tclass == "rubric":
            rubrics.append(clean_table)
        elif tclass == "schedule":
            schedule_tables.append(clean_table)
        else:
            data_tables.append(clean_table)

    # ── Extract metadata (native > slides > fallback) ──

    # Title
    title = native_title
    if not title and all_slides:
        title = extract_title_from_slides(all_slides)
    if not title:
        title = f"Lesson {lesson_num}"
    # Clean "Lesson X:" prefix for lesson_title field
    lesson_title = title
    title_match = re.match(r"Lesson\s*\d+\s*[:–\-]\s*(.+)", title)
    if title_match:
        short_title = title_match.group(1).strip()
        lesson_title = f"Lesson {lesson_num} – {short_title}"
        title_for_metadata = short_title
    else:
        lesson_title = f"Lesson {lesson_num} – {title}" if not title.lower().startswith("lesson") else title
        title_for_metadata = title

    # Learning Objectives
    learning_objectives = native_objectives
    if not learning_objectives and all_slides:
        learning_objectives = extract_learning_objectives_from_slides(all_slides)

    # Core Topics (from slides or native docs) — deduplicated case-insensitively
    core_topics = extract_core_topics_from_slides(all_slides, lesson_num) if all_slides else []
    if not core_topics and native_content:
        core_topics = extract_core_topics_from_native(native_content, lesson_num)
    # Deduplicate case-insensitively while preserving first occurrence
    seen_topics = set()
    deduped_topics = []
    for t in core_topics:
        t_lower = t.strip().lower()
        if t_lower not in seen_topics:
            seen_topics.add(t_lower)
            deduped_topics.append(t)
    core_topics = deduped_topics

    # AI Focus
    ai_focus = extract_ai_focus_from_slides(all_slides) if all_slides else []

    # Activity Type
    activities_text_parts = native_activities or extract_activities_from_slides(all_slides)
    # Supplement with DOCX markdown sections (Reflection/Plenary, Starter, etc.)
    if docx_activities:
        activities_text_parts = list(activities_text_parts) + docx_activities
    activities_text = "\n\n".join(activities_text_parts) if activities_text_parts else ""
    # Ensure activity text ends with punctuation (not mid-sentence)
    if activities_text:
        activities_text = _ensure_trailing_punctuation(activities_text)
    activity_type = extract_activity_type_from_content(all_slides, activities_text, lesson_title=title)

    # Keywords — use lesson-specific text (slides + notes + lesson plan) not shared docs
    lesson_specific_text = "\n".join(
        s["text"] + "\n" + s["notes"] for s in all_slides
    ) if all_slides else ""
    if activities_text:
        lesson_specific_text += "\n" + activities_text
    keywords = extract_keywords(all_text, lesson_num, lesson_specific_text=lesson_specific_text)

    # Artifacts
    artifacts = extract_artifacts_from_slides(all_slides) if all_slides else []

    # Assessment Signals (native first, slides supplement)
    assessment_signals = extract_assessment_signals_from_slides(all_slides) if all_slides else []
    if native_assessment and native_assessment not in " ".join(assessment_signals):
        assessment_signals.insert(0, native_assessment)

    # Resources
    resources = extract_resources_from_slides(all_slides) if all_slides else []

    # Big Question
    big_question = native_big_question
    if not big_question and all_slides:
        big_question = extract_big_question_from_slides(all_slides)

    # UAE Link
    uae_link = native_uae_link
    if not uae_link and all_slides:
        uae_link = extract_uae_link_from_slides(all_slides)

    # Success Criteria
    success_criteria = native_success_criteria
    if not success_criteria and all_slides:
        success_criteria = extract_success_criteria_from_slides(all_slides)

    # Speaker notes (PPTX + native Slides)
    speaker_notes = []
    seen_speaker_slides = set()
    for slide in all_slides:
        if slide["notes"]:
            speaker_notes.append({"slide": slide["slide_number"], "notes": slide["notes"]})
            seen_speaker_slides.add(slide["slide_number"])
    # Add native Slides speaker notes (dedup by slide number)
    for sn in native_slides_speaker_notes:
        if sn["slide"] not in seen_speaker_slides:
            speaker_notes.append(sn)
            seen_speaker_slides.add(sn["slide"])

    # Build PPTX image entries (structural only — no descriptions)
    images = []
    for img in lesson_data.get("images", []):
        images.append({
            "image_id": "",
            "content_type": "",
            "visual_description": "",
            "educational_context": "",
            "source": img.get("source", "pptx"),
            "source_pptx": img.get("source_pptx", ""),
            "image_path": img.get("image_path", ""),
            "slide_numbers": img.get("slide_numbers", []),
            "primary_slide": img.get("primary_slide"),
            "kb_tags": [],
        })

    # Build native Slides API image entries (separate from PPTX)
    native_image_entries = []
    for img in native_slides_images:
        native_image_entries.append({
            "image_id": img.get("object_id", ""),
            "url": img.get("url", ""),
            "source_url": img.get("source_url", ""),
            "source_file": img.get("source_pptx", ""),
            "slide_number": img.get("slide_number"),
        })

    # Build native links list
    native_link_entries = []
    for nl in native_slides_links:
        native_link_entries.append({
            "url": nl.get("url", ""),
            "text": nl.get("text", ""),
            "slide_number": nl.get("slide_number"),
        })

    # Build native slides content
    native_slide_entries = []
    for native in native_content:
        if native.get("native_type") != "google_slides":
            continue
        for slide in native.get("slides", []):
            snum = slide.get("slide_number", 0)
            texts = slide.get("texts", [])
            notes = slide.get("speaker_notes", "")
            if texts or notes:
                native_slide_entries.append({
                    "slide_number": snum,
                    "content": "\n".join(texts),
                    "speaker_notes": notes,
                    "source_file": native.get("file_name", ""),
                })

    # Build Endstar tools from keyword matching on lesson-specific slide text
    # (not all_text which includes shared programme docs that mention tools globally)
    lesson_slide_text = " ".join(s["text"] + " " + s["notes"] for s in all_slides)
    endstar_tools = extract_endstar_tools(lesson_slide_text)

    # Build video entries from consolidated video references + native Slides videos
    # + text-mention video refs extracted from slide content
    all_video_refs = list(lesson_data.get("video_refs", []))
    for nv in native_slides_videos:
        all_video_refs.append({
            "url": nv.get("url", ""),
            "video_id": nv.get("video_id", ""),
            "title": nv.get("url", ""),
            "type": nv.get("source", "native_slides"),
        })
    # Extract video URLs mentioned in slide text/notes
    slide_video_refs = extract_video_refs_from_slides(all_slides) if all_slides else []
    all_video_refs.extend(slide_video_refs)
    # Also extract video URLs from native slides/docs links (may not be in consolidated refs)
    seen_urls = set(vr.get("url", "") for vr in all_video_refs if vr.get("url"))
    for nl in native_slides_links:
        url = nl.get("url", "")
        if url and url not in seen_urls and any(p.search(url) for p in VIDEO_URL_PATTERNS):
            all_video_refs.append({
                "url": url, "type": "video_link",
                "title": nl.get("text", ""), "video_id": "",
            })
            seen_urls.add(url)
    video_entries = build_video_entries(all_video_refs)

    # Build resource entries from consolidated links + native Slides/Docs links
    all_links = list(lesson_data.get("links", []))
    for nl in native_slides_links:
        all_links.append({
            "url": nl.get("url", ""),
            "text": nl.get("text", ""),
        })
    resource_entries = build_resource_entries(all_links)

    # Merge slide-extracted resources with link-based resources (dedup)
    existing_resource_urls = set()
    for r in resource_entries:
        # Extract URL part for dedup
        if " - " in r:
            existing_resource_urls.add(r.split(" - ")[-1].strip())
        else:
            existing_resource_urls.add(r.strip())
    for r in resources:
        r_stripped = r.strip()
        if r_stripped and r_stripped not in existing_resource_urls:
            if not any(r_stripped in er for er in resource_entries):
                resource_entries.append(r_stripped)

    # Build the lesson entry in the exact expected schema
    lesson_entry = {
        "lesson_title": lesson_title,
        "url": f"Lesson {lesson_num}",
        "metadata": {
            "term_id": term_num,
            "lesson_id": lesson_num,
            "title": title_for_metadata,
            "url": f"Lesson {lesson_num}",
            "grade_band": "G9\u2013G10",
            "core_topics": core_topics,
            "endstar_tools": endstar_tools,
            "ai_focus": ai_focus,
            "learning_objectives": learning_objectives,
            "activity_type": activity_type,
            "activity_description": activities_text if activities_text else "",
            "artifacts": artifacts,
            "assessment_signals": assessment_signals,
            "videos": video_entries,
            "resources": resource_entries,
            "keywords": keywords,
            "images": images,
        },
        "description_of_activities": activities_text if activities_text else "",
        "other_resources": "",
        "videos_column": "",
        "testing_scores": "",
        "comments": "",
        "prompts": "",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_version": "2.1",
        "week": week,
        "big_question": big_question,
        "uae_link": uae_link,
        "success_criteria": success_criteria,
        "curriculum_alignment": (
            native_curriculum_alignment
            or _parse_curriculum_alignment(docx_curriculum_lines)
            or _parse_curriculum_alignment(extract_curriculum_alignment_from_slides(all_slides))
        ),
        "programme_metadata": programme_metadata,
        "key_facts": [],
        "detailed_activities": activities_text if activities_text else "",
        # Tables split by purpose
        "rubrics": rubrics,
        "data_tables": data_tables,
        "schedule_tables": schedule_tables,
        "teacher_notes": speaker_notes,
        "assessment_framework": [],
        # PPTX-converted slides (includes native slides that didn't overlap with PPTX)
        "slides": [{"slide_number": s["slide_number"], "content": s["text"]} for s in all_slides],
        # Native Google Slides content (dedicated fields)
        "native_slides": native_slide_entries,
        "native_images": native_image_entries,
        "native_tables": [t for t in native_slides_tables],
        "native_links": native_link_entries,
        "remaining_content": native_remaining_content,
        "image_count": len(images) + len(native_image_entries),
        "document_sources": [d.get("path", "") for d in docs if d.get("path", "") in contributing_doc_paths],
    }

    return lesson_entry


def run_build(term_num=None):
    """Build the KB JSON from consolidated content."""
    print("=" * 60)
    print("  Stage 6: KB Build")
    print("=" * 60)
    print()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load consolidated content — prefer per-term files, fall back to combined
    combined_path = CONSOLIDATED_DIR / "consolidated_content.json"
    consolidated = None  # loaded lazily as fallback

    def _load_combined():
        nonlocal consolidated
        if consolidated is None and combined_path.exists():
            with open(combined_path, "r", encoding="utf-8") as f:
                consolidated = json.load(f)
        return consolidated

    # Determine which terms to build
    if term_num:
        terms_to_build = [term_num]
    else:
        # Discover available terms from per-term files or combined file
        per_term_files = sorted(CONSOLIDATED_DIR.glob("consolidated_term*.json"))
        if per_term_files:
            import re as _re
            terms_to_build = []
            for ptf in per_term_files:
                m = _re.search(r"consolidated_term(\d+)\.json$", ptf.name)
                if m:
                    terms_to_build.append(int(m.group(1)))
            terms_to_build.sort()
        else:
            combined = _load_combined()
            if combined:
                terms_to_build = sorted(int(t) for t in combined.get("by_term", {}).keys())
            else:
                print("No consolidated content found. If running standalone, run consolidate.py first."
                      " In pipeline mode, this means Stage 5 failed.")
                return None

    if not terms_to_build:
        print("No term data found in consolidated content.")
        return None

    for t in terms_to_build:
        print(f"\nBuilding KB for Term {t}...")

        # Load per-term file first, fall back to combined
        per_term_path = CONSOLIDATED_DIR / f"consolidated_term{t}.json"
        if per_term_path.exists():
            with open(per_term_path, "r", encoding="utf-8") as f:
                per_term_data = json.load(f)
            term_lessons = per_term_data.get("by_lesson", {})
        else:
            combined = _load_combined()
            if not combined:
                print(f"  No consolidated data for Term {t} — this term may not have been synced yet. Skipping.")
                continue
            term_data = combined.get("by_term", {}).get(str(t), {})
            term_lessons = term_data.get("by_lesson", {})

        if not term_lessons:
            print(f"  No lesson data for Term {t} — no lesson-assignable files found. Skipping.")
            continue

        # Determine max lesson from actual data — no hard-coded cap
        lesson_nums = [int(k) for k in term_lessons.keys() if k.isdigit()]
        max_lesson = max(lesson_nums) if lesson_nums else 0
        lessons = []
        for lesson_num in range(1, max_lesson + 1):
            lesson_data = term_lessons.get(str(lesson_num), {})
            if not lesson_data or (
                lesson_data.get("document_count", 0) == 0
                and lesson_data.get("image_count", 0) == 0
                and lesson_data.get("native_count", 0) == 0
            ):
                continue

            entry = build_lesson_kb(lesson_num, lesson_data, t)
            lessons.append(entry)
            m = entry["metadata"]
            parts = [
                f'"{m["title"]}"',
                f"{len(m['core_topics'])}top",
                f"{len(m['learning_objectives'])}obj",
                f"{len(m['images'])}img",
                f"{len(m['videos'])}vid",
                f"{len(m['resources'])}res",
                f"{len(m['endstar_tools'])}tools",
                f"{len(m['keywords'])}kw",
            ]
            print(f"  Lesson {lesson_num}: {' | '.join(parts)}")

        kb = {
            "term": t,
            "total_lessons": len(lessons),
            "generated_from": "KB Maintenance Pipeline v2",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "lessons": lessons,
        }

        output_path = OUTPUT_DIR / f"Term {t} - Lesson Based Structure.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(kb, f, indent=2, ensure_ascii=False)

        print(f"\n  Term {t}: {len(lessons)} lessons -> {output_path}")

    print("\n" + "=" * 60)
    print("  KB Build Complete")
    print("=" * 60)

    return True


if __name__ == "__main__":
    import sys as _sys
    term = int(_sys.argv[1]) if len(_sys.argv) > 1 else None
    run_build(term)
