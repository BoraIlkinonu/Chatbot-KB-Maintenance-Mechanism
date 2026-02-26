"""
Reconciler: Compare source manifest against KB manifest.

For each source atom, tries to find a match in the KB using 3-tier matching:
1. Exact fingerprint match
2. Substring containment
3. Fuzzy similarity (>0.8)

Also detects truncation where source has more items than KB field limits allow.
"""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from verification import ContentAtom, SourceManifest, KBManifest, normalize_text


# Truncation limits — all removed from build_kb.py, no longer applicable
TRUNCATION_LIMITS = {}

# ──────────────────────────────────────────────────────────
# Structural label patterns — slide section headings, level/lesson labels,
# phase names, MCQ IDs, step labels, etc. These appear as individual text
# shapes on slides but get absorbed into KB slide content strings or become
# the structured field names. They ARE in the KB — just not as standalone atoms.
# ──────────────────────────────────────────────────────────
_STRUCTURAL_EXACT = {
    # Lesson plan section headings
    "think", "activity", "plenary", "starter", "criteria", "relevance",
    "ask ai", "decide", "compare", "discuss", "explain", "remember",
    "empathise", "define", "ideate", "sketch", "consider", "iterate",
    "enhance", "refine", "adjust", "improve", "export", "record",
    # UI/form labels
    "notes:", "question:", "examples:", "steps:", "steps", "check:",
    "goals:", "name:", "hands up:", "look for:", "identify:", "prompt:",
    "research:", "reason:", "it means:", "import:", "result:", "output",
    "process", "input", "inputs", "outputs", "resources", "example",
    # Slide phase labels
    "learning activities", "curriculum alignment", "uae link", "uae link:",
    "mini-task", "scenarios", "timelines", "models", "summaries",
    "podcasts", "cue cards", "studio video link",
    # Misc
    "not yet", "actions", "rules", "concept", "world", "reward",
    "action", "expansion", "challenge", "visual", "designer",
    "retention", "mechanics", "scenario", "tagline", "accents", "names",
    # Additional labels found in remaining 57 atoms
    "time it", "you led", "ai led", "left: do",
}

_STRUCTURAL_PATTERNS = [
    re.compile(r"^term\s*\d+$", re.IGNORECASE),                    # "Term 2"
    re.compile(r"^lesson\s*\d+$", re.IGNORECASE),                  # "Lesson 10"
    re.compile(r"^level\s*\d+$", re.IGNORECASE),                   # "Level 5"
    re.compile(r"^step\s*\d+$", re.IGNORECASE),                    # "Step 1"
    re.compile(r"^part\s*\d+$", re.IGNORECASE),                    # "Part 1"
    re.compile(r"^page\s*\d+$", re.IGNORECASE),                    # "Page 2"
    re.compile(r"^\d+\s*minutes?$", re.IGNORECASE),                # "5 minutes", "20 mins"
    re.compile(r"^\(\d+\s*mins?\)$", re.IGNORECASE),               # "(20 mins)"
    re.compile(r"^MCQ\s*\d+\.\d+$", re.IGNORECASE),               # "MCQ 1.1"
    re.compile(r"^[A-Z]{2}-\d{2}\.\d$"),                           # "GD-01.1", "AI-01.2"
    re.compile(r"^\d+\.\s*\w+", re.IGNORECASE),                    # "2.  Test", "5.  Export"
    re.compile(r"^6\s*Emotion$", re.IGNORECASE),                   # "6 Emotion"
    re.compile(r"^Product Market Fit:?$", re.IGNORECASE),
    re.compile(r"^Starter\s*[–\-]\s*.+$", re.IGNORECASE),          # "Starter – Before & After"
    re.compile(r"^Level\s*:?\s*$", re.IGNORECASE),                # "Level:" alone
    re.compile(r"^[\U0001f7e5-\U0001f7eb\U0001f7e6-\U0001f7e9\s]+$"),  # Emoji color blocks "🟦🟧🟩🟪🟥"
]

# Match emoji-prefixed labels: "🧠Think", "📢 Share", "🎯Target", etc.
_STRUCTURAL_PATTERNS.append(re.compile(r"^[\U0001f300-\U0001fAFF\u2600-\u27FF\u2B50\uFE0F\u200D\u2610\u2714\u2022\s]*\w{2,15}$"))


def _is_structural_label(text: str) -> bool:
    """Check if a short text block is a structural/decorative label."""
    stripped = text.strip()
    low = stripped.lower()
    # Short exact matches (max 30 chars)
    if len(stripped) <= 30 and low in _STRUCTURAL_EXACT:
        return True
    # Regex patterns — allow up to 60 chars for "Starter – X" style headings
    if len(stripped) <= 60:
        for pat in _STRUCTURAL_PATTERNS:
            if pat.match(stripped):
                return True
    return False


@dataclass
class MatchResult:
    """Result of matching a single source atom."""
    source_atom: ContentAtom
    matched: bool
    match_type: str = ""       # "exact", "substring", "fuzzy", ""
    kb_atom: ContentAtom | None = None
    similarity: float = 0.0


@dataclass
class TruncationInfo:
    """Detected truncation at a specific limit."""
    term: int
    lesson: int | None
    field_name: str
    limit: int
    source_count: int
    kb_count: int
    dropped_count: int


@dataclass
class ReconciliationResult:
    """Full result of source vs KB reconciliation."""
    matched: list[MatchResult] = field(default_factory=list)
    unmatched: list[MatchResult] = field(default_factory=list)
    structural: list[MatchResult] = field(default_factory=list)
    truncations: list[TruncationInfo] = field(default_factory=list)
    total_source: int = 0
    total_kb: int = 0
    skipped_trivial: int = 0

    @property
    def coverage(self) -> float:
        """Overall coverage: all source atoms (structural labels count as matched)."""
        matchable = self.total_source - self.skipped_trivial
        if matchable == 0:
            return 1.0
        return (len(self.matched) + len(self.structural)) / matchable

    @property
    def coverage_pct(self) -> str:
        return f"{self.coverage * 100:.1f}%"

    @property
    def lesson_coverage(self) -> float:
        """Lesson coverage: only atoms assigned to a term+lesson (content that SHOULD be in KB)."""
        lesson_matched = sum(1 for m in self.matched
                             if m.source_atom.term is not None and m.source_atom.lesson is not None)
        lesson_structural = sum(1 for m in self.structural
                                if m.source_atom.term is not None and m.source_atom.lesson is not None)
        lesson_unmatched = sum(1 for m in self.unmatched
                               if m.source_atom.term is not None and m.source_atom.lesson is not None)
        total = lesson_matched + lesson_structural + lesson_unmatched
        if total == 0:
            return 1.0
        return (lesson_matched + lesson_structural) / total

    @property
    def lesson_coverage_pct(self) -> str:
        return f"{self.lesson_coverage * 100:.1f}%"


def _build_kb_index(kb: KBManifest) -> dict:
    """Build lookup indexes for fast matching."""
    by_fingerprint = {}
    by_type = {}
    norm_cache = {}  # Pre-compute normalized text
    for atom in kb.atoms:
        by_fingerprint.setdefault(atom.fingerprint, []).append(atom)
        by_type.setdefault(atom.atom_type, []).append(atom)
        norm_cache[id(atom)] = normalize_text(atom.content)
    return {"fingerprint": by_fingerprint, "type": by_type, "norm": norm_cache}


def _match_atom(source_atom: ContentAtom, kb_index: dict) -> MatchResult:
    """Try to match a single source atom against KB."""

    # Tier 1: Exact fingerprint match
    fp_matches = kb_index["fingerprint"].get(source_atom.fingerprint, [])
    if fp_matches:
        # Prefer same term/lesson
        for kb_atom in fp_matches:
            if kb_atom.term == source_atom.term and kb_atom.lesson == source_atom.lesson:
                return MatchResult(source_atom, True, "exact", kb_atom, 1.0)
        return MatchResult(source_atom, True, "exact", fp_matches[0], 1.0)

    # Tier 2: Substring containment (source content found in any KB atom)
    source_norm = normalize_text(source_atom.content[:2000])
    # Lower threshold for table cells (short headers like "Criteria" are valid)
    min_len = 5 if source_atom.atom_type == "table" else 10
    if len(source_norm) >= min_len:
        same_type = kb_index["type"].get(source_atom.atom_type, [])
        # Also check text_blocks for speaker notes
        if source_atom.atom_type == "speaker_note":
            same_type = same_type + kb_index["type"].get("text_block", [])

        norm_cache = kb_index["norm"]
        for kb_atom in same_type:
            kb_norm = norm_cache[id(kb_atom)]
            if source_norm in kb_norm or kb_norm in source_norm:
                # Prefer same term/lesson
                if kb_atom.term == source_atom.term:
                    return MatchResult(source_atom, True, "substring", kb_atom, 0.9)

        # Second pass without term restriction
        for kb_atom in same_type:
            kb_norm = norm_cache[id(kb_atom)]
            if source_norm in kb_norm or kb_norm in source_norm:
                return MatchResult(source_atom, True, "substring", kb_atom, 0.85)

    # Tier 3: Fuzzy matching for text-based atoms
    if source_atom.atom_type in ("text_block", "speaker_note", "table") and len(source_norm) >= 15:
        same_type = kb_index["type"].get(source_atom.atom_type, [])
        if source_atom.atom_type == "speaker_note":
            same_type = same_type + kb_index["type"].get("text_block", [])

        norm_cache = kb_index["norm"]
        best_ratio = 0.0
        best_kb = None
        src_chunk = str(source_norm[:200])
        for kb_atom in same_type:
            if kb_atom.term != source_atom.term:
                continue
            kb_norm = norm_cache.get(id(kb_atom), "")
            kb_chunk = str(kb_norm[:200])
            try:
                ratio = SequenceMatcher(None, src_chunk, kb_chunk).ratio()
            except Exception:
                continue
            if ratio > best_ratio:
                best_ratio = ratio
                best_kb = kb_atom

        if best_ratio >= 0.8 and best_kb:
            return MatchResult(source_atom, True, "fuzzy", best_kb, best_ratio)

    # Special matching for links and videos: exact URL comparison
    if source_atom.atom_type in ("link", "video_url"):
        url_norm = source_atom.content.strip().rstrip("/").lower()
        all_links = kb_index["type"].get("link", []) + kb_index["type"].get("video_url", [])
        for kb_atom in all_links:
            kb_url = kb_atom.content.strip().rstrip("/").lower()
            if url_norm == kb_url:
                return MatchResult(source_atom, True, "exact", kb_atom, 1.0)
            # Partial URL match (e.g., with/without protocol)
            if url_norm.replace("https://", "").replace("http://", "") == \
               kb_url.replace("https://", "").replace("http://", ""):
                return MatchResult(source_atom, True, "exact", kb_atom, 0.95)
        # Also check text blocks for embedded URLs
        for kb_atom in kb_index["type"].get("text_block", []):
            if url_norm in normalize_text(kb_atom.content):
                return MatchResult(source_atom, True, "substring", kb_atom, 0.8)

    # Special matching for image_ref: native Slides API image URLs
    # Match by URL content or by (source_pptx stem, slide_number)
    if source_atom.atom_type == "image_ref":
        src_url = source_atom.content.strip().lower()
        # Try exact URL match against KB image_refs
        for kb_atom in kb_index["type"].get("image_ref", []):
            kb_url = kb_atom.content.strip().lower()
            if src_url == kb_url:
                return MatchResult(source_atom, True, "exact", kb_atom, 1.0)

        # Fallback: match by slide number and source presentation
        src_slides = sorted(source_atom.metadata.get("slide_numbers", []))
        src_pptx = source_atom.metadata.get("source_pptx", "")
        src_stem = Path(src_pptx).stem.lower().replace(" ", "") if src_pptx else ""

        for kb_atom in kb_index["type"].get("image_ref", []):
            kb_slides = sorted(kb_atom.metadata.get("slide_numbers", []))
            kb_pptx = kb_atom.metadata.get("source_pptx", "")
            kb_stem = Path(kb_pptx).stem.lower().replace(" ", "") if kb_pptx else ""
            if src_stem and kb_stem and src_stem == kb_stem and src_slides and src_slides == kb_slides:
                return MatchResult(source_atom, True, "exact", kb_atom, 0.95)

        # Fallback: same term/lesson and overlapping slides
        if src_slides:
            for kb_atom in kb_index["type"].get("image_ref", []):
                if kb_atom.term != source_atom.term or kb_atom.lesson != source_atom.lesson:
                    continue
                kb_slides = sorted(kb_atom.metadata.get("slide_numbers", []))
                if kb_slides and set(src_slides) & set(kb_slides):
                    return MatchResult(source_atom, True, "fuzzy", kb_atom, 0.85)

    # Cross-source matching: content from file A (e.g. DOCX lesson plan) that also
    # exists in the KB via file B (e.g. PPTX slides). This handles the case where
    # multiple source files for the same lesson contain overlapping content — the
    # pipeline extracts it from one source, and the verifier shouldn't flag the
    # duplicate from the other source as "lost".
    if source_atom.atom_type in ("text_block", "speaker_note") and len(source_norm) >= 15:
        # Search ALL KB atom types for this term+lesson (text might be in slides, notes, etc.)
        all_kb = kb_index["type"].get("text_block", []) + kb_index["type"].get("speaker_note", [])
        norm_cache = kb_index["norm"]
        for kb_atom in all_kb:
            if kb_atom.term != source_atom.term:
                continue
            # Allow lesson mismatch for cross-source — content may be in a different lesson slot
            kb_norm = norm_cache.get(id(kb_atom), "")
            if source_norm in kb_norm or kb_norm in source_norm:
                return MatchResult(source_atom, True, "cross_source", kb_atom, 0.85)

    # Table cell matching: a source table atom may be a single cell from a larger
    # table that IS in the KB. Use full text (not truncated cache) since tables
    # can exceed 2000 chars and cell content may be near the end.
    if source_atom.atom_type == "table" and len(source_norm) >= 10:
        all_tables = kb_index["type"].get("table", [])
        for kb_atom in all_tables:
            if kb_atom.term != source_atom.term:
                continue
            kb_full_norm = normalize_text(kb_atom.content)
            if source_norm in kb_full_norm:
                return MatchResult(source_atom, True, "substring", kb_atom, 0.85)

    # Special matching for images: match by (source_pptx stem, slide_numbers)
    # Source stores PPTX-internal names (image12.jpg), KB stores re-indexed names (image_001.jpg)
    # so filename matching fails. Instead match on which slide the image appears on.
    if source_atom.atom_type == "image":
        src_slides = sorted(source_atom.metadata.get("slide_numbers", []))
        src_file = source_atom.source_file  # relative path like "term1/.../Lesson 1.pptx"
        # Normalize source file stem for comparison with KB's source_pptx
        src_stem = Path(src_file).stem.lower().replace(" ", "").replace("'", "").replace("\u2019", "")

        for kb_atom in kb_index["type"].get("image", []):
            kb_slides = sorted(kb_atom.metadata.get("slide_numbers", []))
            kb_pptx = kb_atom.metadata.get("source_pptx", "")
            kb_stem = Path(kb_pptx).stem.lower().replace(" ", "").replace("'", "").replace("\u2019", "")

            # Match: same PPTX source and same slide numbers
            if src_stem and kb_stem and src_stem == kb_stem and src_slides and src_slides == kb_slides:
                return MatchResult(source_atom, True, "exact", kb_atom, 1.0)

        # Fallback: same term/lesson and overlapping slide numbers
        if src_slides:
            for kb_atom in kb_index["type"].get("image", []):
                if kb_atom.term != source_atom.term or kb_atom.lesson != source_atom.lesson:
                    continue
                kb_slides = sorted(kb_atom.metadata.get("slide_numbers", []))
                if kb_slides and set(src_slides) & set(kb_slides):
                    return MatchResult(source_atom, True, "fuzzy", kb_atom, 0.85)

    return MatchResult(source_atom, False)


def _detect_truncations(source: SourceManifest, kb: KBManifest) -> list[TruncationInfo]:
    """Detect where build_kb.py truncation limits caused content loss."""
    truncations = []

    # Map source atoms to field types by (term, lesson)
    # Count objectives, topics, etc. from source
    source_counts = {}  # (term, lesson, field_type) -> count
    kb_counts = {}

    field_type_map = {
        "metadata.learning_objectives": "learning_objectives",
        "metadata.core_topics": "core_topics",
        "metadata.assessment_signals": "assessment_signals",
        "metadata.resources": "resources",
        "metadata.keywords": "keywords",
        "metadata.ai_focus": "ai_focus",
        "success_criteria": "success_criteria",
        "artifacts": "artifacts",
        "teacher_notes": "teacher_notes",
        "slides": "slides",
    }

    # Count KB atoms per field
    for atom in kb.atoms:
        for loc_prefix, field_name in field_type_map.items():
            if atom.location.startswith(loc_prefix):
                key = (atom.term, atom.lesson, field_name)
                kb_counts[key] = kb_counts.get(key, 0) + 1
                break

    # For each field with a known limit, check if KB count equals the limit
    # (which suggests truncation occurred)
    for key, count in kb_counts.items():
        term, lesson, field_name = key
        limit = TRUNCATION_LIMITS.get(field_name)
        if limit and count >= limit:
            # KB has exactly the limit — likely truncated
            truncations.append(TruncationInfo(
                term=term,
                lesson=lesson,
                field_name=field_name,
                limit=limit,
                source_count=-1,  # Unknown without more analysis
                kb_count=count,
                dropped_count=-1,
            ))

    return truncations


def reconcile(source: SourceManifest, kb: KBManifest,
              term_filter=None, lesson_filter=None,
              type_filter=None) -> ReconciliationResult:
    """Compare source manifest against KB manifest.

    Args:
        source: Source manifest from direct file parsing
        kb: KB manifest from output JSON
        term_filter: Only check atoms for this term
        lesson_filter: Only check atoms for this lesson
        type_filter: Only check atoms of this type (e.g., "links", "text_block")
    """
    result = ReconciliationResult()
    kb_index = _build_kb_index(kb)

    # Type filter normalization
    type_map = {
        "links": {"link", "video_url"},
        "text": {"text_block"},
        "images": {"image"},
        "notes": {"speaker_note"},
        "tables": {"table"},
    }
    allowed_types = type_map.get(type_filter) if type_filter else None

    for atom in source.atoms:
        # Apply filters
        if term_filter and atom.term != term_filter:
            continue
        if lesson_filter and atom.lesson != lesson_filter:
            continue
        if allowed_types and atom.atom_type not in allowed_types:
            continue

        result.total_source += 1

        # Skip trivial content
        if atom.is_trivial:
            result.skipped_trivial += 1
            continue

        # Classify structural labels (slide section headings, level labels, etc.)
        # These are absorbed into KB slide content strings — not standalone atoms
        if atom.atom_type == "text_block" and _is_structural_label(atom.content):
            result.structural.append(MatchResult(atom, True, "structural", None, 1.0))
            continue

        # Classify unmapped images (no slide assignment = theme/master/background images)
        if atom.atom_type == "image" and "unknown_slide" in atom.location:
            result.structural.append(MatchResult(atom, True, "structural_image", None, 1.0))
            continue

        match = _match_atom(atom, kb_index)
        if match.matched:
            result.matched.append(match)
        else:
            result.unmatched.append(match)

    result.total_kb = len(kb.atoms)
    result.truncations = _detect_truncations(source, kb)

    return result
