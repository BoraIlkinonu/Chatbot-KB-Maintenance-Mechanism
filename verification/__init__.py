"""
Exhaustive Extraction Verification Package.

ContentAtom: the fundamental unit of extractable content.
Every piece of text, link, image, table, or speaker note from a source file
becomes a ContentAtom with a normalized fingerprint for matching against KB output.
"""

import hashlib
import re
from dataclasses import dataclass, field
from typing import NamedTuple


@dataclass
class ContentAtom:
    """A single piece of extractable content from a source file."""
    atom_type: str          # "text_block", "link", "image", "table", "speaker_note", "video_url"
    content: str            # The actual content (text, URL, image path, etc.)
    source_file: str        # Which source file it came from
    location: str           # "slide:3", "paragraph:12", "note:5", etc.
    term: int | None = None
    lesson: int | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        return compute_fingerprint(self.content)

    @property
    def is_trivial(self) -> bool:
        """Content too short to be meaningful (decorative labels, bullets)."""
        stripped = normalize_text(self.content)
        return len(stripped) < 5


def normalize_text(s: str) -> str:
    """Lowercase, strip whitespace, collapse spaces."""
    if not s:
        return ""
    s = s.lower().strip()
    s = " ".join(s.split())
    return s


def compute_fingerprint(s: str) -> str:
    """SHA-256 of normalized text."""
    norm = normalize_text(s)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


class SourceManifest(NamedTuple):
    atoms: list[ContentAtom]
    source_files: list[str]
    excluded_files: list[str] = []


class KBManifest(NamedTuple):
    atoms: list[ContentAtom]
    terms_found: list[int]
