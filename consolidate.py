"""
Stage 5: Content Consolidation
Merges converted documents, extracted media metadata, and native Google extractions
into a unified per-lesson structure. Handles 3-layer duplicate detection.
"""

import sys
import os
import json
import re
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

from config import (
    BASE_DIR, CONVERTED_DIR, MEDIA_DIR, NATIVE_DIR, CONSOLIDATED_DIR, LOGS_DIR, SOURCES_DIR,
    WEEK_LESSON_MAP, FUZZY_NAME_THRESHOLD, VIDEO_EXTENSIONS, VIDEO_URL_PATTERNS,
    CONSOLIDATE_COMBINED,
)

FILE_MANIFEST_PATH = BASE_DIR / "file_manifest.json"

# Term key → term number mapping
TERM_KEY_MAP = {"term1": 1, "term2": 2, "term3": 3}

# Max lessons per term (Term 1 = 24, Term 2 = 14, Term 3 = 24)
TERM_MAX_LESSONS = {1: 24, 2: 14, 3: 24}


# ──────────────────────────────────────────────────────────
# Term + Lesson extraction from paths
# ──────────────────────────────────────────────────────────

def extract_term_from_path(path):
    """Extract term number from file path. Returns int (1/2/3) or None."""
    path_lower = path.lower().replace("\\", "/")

    # Match folder prefix from sync: "term1/...", "term2/...", "term3/..."
    for key, num in TERM_KEY_MAP.items():
        if path_lower.startswith(key + "/") or f"/{key}/" in path_lower:
            return num

    # Match descriptive folder names from Drive
    if "term 1" in path_lower or "foundations" in path_lower:
        return 1
    if "term 2" in path_lower or "accelerator" in path_lower:
        return 2
    if "term 3" in path_lower or "mastery" in path_lower:
        return 3

    return None


def extract_lesson_from_path(path, term=None):
    """Extract lesson number(s) from file path."""
    path_lower = path.lower()
    max_lesson = TERM_MAX_LESSONS.get(term, 24) if term else 24

    # "Lesson X -Y" or "Lesson X - Y" format (exemplar files like "Lesson 1 -2.md")
    # Must be checked BEFORE single-lesson regex to avoid matching only "Lesson 1"
    match = re.search(r"lesson[_\s\-]*(\d{1,2})\s*[-–—]\s*(\d{1,2})", path_lower)
    if match:
        start, end = int(match.group(1)), int(match.group(2))
        if 1 <= start <= max_lesson and 1 <= end <= max_lesson and start != end:
            return list(range(start, end + 1))

    # Explicit "Lesson X"
    match = re.search(r"lesson[_\s\-]*(\d{1,2})", path_lower)
    if match:
        num = int(match.group(1))
        if 1 <= num <= max_lesson:
            return [num]

    # "Lessons X-Y"
    match = re.search(r"lessons?\s*(\d{1,2})\s*[-–]\s*(\d{1,2})", path_lower)
    if match:
        start, end = int(match.group(1)), int(match.group(2))
        if 1 <= start <= max_lesson and 1 <= end <= max_lesson:
            return list(range(start, end + 1))

    # Week folder → lessons (only for curriculum content, not support docs)
    if not any(skip in path_lower for skip in ["assessment", "exemplar", "teacher guide"]):
        match = re.search(r"week[_\s\-]*(\d)", path_lower)
        if match:
            week = int(match.group(1))
            if week in WEEK_LESSON_MAP:
                return WEEK_LESSON_MAP[week]

    # Cross-term check: skip files that reference a different term
    if term:
        for t_num in range(1, 4):
            if t_num != term and re.search(rf"term\s*{t_num}\b", path_lower):
                return []  # File belongs to different term

    # Portfolio / all lessons
    if any(t in path_lower for t in ["portfolio", "all weeks", "all lessons"]):
        return list(range(1, max_lesson + 1))

    return []


def determine_content_type(path):
    """Determine content type from path."""
    path_lower = path.lower()
    if "teachers slides" in path_lower or "teacher slides" in path_lower:
        return "teachers_slides"
    if "students slides" in path_lower or "student slides" in path_lower:
        return "students_slides"
    if "lesson plan" in path_lower:
        return "lesson_plan"
    if "exemplar" in path_lower:
        return "exemplar_work"
    if "portfolio" in path_lower:
        return "portfolio"
    if "assessment" in path_lower:
        return "assessment_guide"
    if "design brief" in path_lower:
        return "design_brief"
    if "curriculum" in path_lower:
        return "curriculum_doc"
    return "other"


# ──────────────────────────────────────────────────────────
# Duplicate detection (3 layers)
# ──────────────────────────────────────────────────────────

def normalize_name(name):
    """Normalize filename for fuzzy matching."""
    name = re.sub(r"\s*\(\d+\)\s*", "", name)  # Remove "(1)" copies
    name = re.sub(r"[_\-\s]+", " ", name).strip().lower()
    name = re.sub(r"\.\w+$", "", name)  # Remove extension
    return name


def levenshtein_ratio(s1, s2):
    """Calculate Levenshtein similarity ratio (0-1)."""
    if not s1 or not s2:
        return 0
    if s1 == s2:
        return 1.0

    rows = len(s1) + 1
    cols = len(s2) + 1
    dist = [[0] * cols for _ in range(rows)]

    for i in range(rows):
        dist[i][0] = i
    for j in range(cols):
        dist[0][j] = j

    for i in range(1, rows):
        for j in range(1, cols):
            cost = 0 if s1[i - 1] == s2[j - 1] else 1
            dist[i][j] = min(
                dist[i - 1][j] + 1,
                dist[i][j - 1] + 1,
                dist[i - 1][j - 1] + cost,
            )

    max_len = max(len(s1), len(s2))
    return 1 - dist[-1][-1] / max_len


def detect_duplicates(items):
    """
    3-layer duplicate detection:
    1. Exact name match (catches "(1)" copies)
    2. Fuzzy name match (normalization + Levenshtein)
    3. MD5 content comparison
    """
    duplicates = []
    seen_exact = {}
    seen_normalized = {}
    seen_md5 = {}

    for item in items:
        name = item.get("name", "")
        normalized = normalize_name(name)
        md5 = item.get("md5", "")

        # Layer 1: Exact name
        if name in seen_exact:
            duplicates.append({
                "type": "exact_name",
                "file": name,
                "duplicate_of": seen_exact[name],
            })
            continue
        seen_exact[name] = item.get("id", "")

        # Layer 2: Fuzzy name
        is_fuzzy_dup = False
        for prev_norm, prev_id in seen_normalized.items():
            ratio = levenshtein_ratio(normalized, prev_norm)
            if ratio >= FUZZY_NAME_THRESHOLD and normalized != prev_norm:
                duplicates.append({
                    "type": "fuzzy_name",
                    "file": name,
                    "similarity": round(ratio, 3),
                    "similar_to": prev_id,
                })
                is_fuzzy_dup = True
                break
        if not is_fuzzy_dup:
            seen_normalized[normalized] = name

        # Layer 3: MD5
        if md5 and md5 in seen_md5:
            duplicates.append({
                "type": "md5_content",
                "file": name,
                "duplicate_of": seen_md5[md5],
            })
            continue
        if md5:
            seen_md5[md5] = name

    return duplicates


# ──────────────────────────────────────────────────────────
# Consolidation
# ──────────────────────────────────────────────────────────

def load_converted_files():
    """Load all converted markdown/CSV files with term awareness."""
    files = []
    if not CONVERTED_DIR.exists():
        return files

    for f in CONVERTED_DIR.rglob("*"):
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext not in (".md", ".csv"):
            continue

        try:
            with open(f, "r", encoding="utf-8") as fh:
                content = fh.read()
        except Exception:
            content = ""

        rel_path = str(f.relative_to(CONVERTED_DIR))
        term = extract_term_from_path(rel_path)
        lessons = extract_lesson_from_path(rel_path, term=term)
        ctype = determine_content_type(rel_path)

        # Count slides in markdown
        slide_count = len(re.findall(r"^## Slide \d+", content, re.MULTILINE))

        files.append({
            "path": rel_path,
            "full_path": str(f),
            "content_type": ctype,
            "term": term,
            "lessons": lessons,
            "format": ext.lstrip("."),
            "char_count": len(content),
            "slide_count": slide_count if slide_count > 0 else None,
            "content_preview": content[:1000],
        })

    return files


def load_media_metadata():
    """Load extracted media metadata with term awareness."""
    meta_path = MEDIA_DIR / "extraction_metadata.json"
    if not meta_path.exists():
        return []

    with open(meta_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    images = []
    for pptx_info in data.get("pptx_files", []):
        rel_path = pptx_info.get("relative_path", "")
        term = extract_term_from_path(rel_path)
        lessons = extract_lesson_from_path(rel_path, term=term)

        for img in pptx_info.get("images", []):
            images.append({
                "source_pptx": rel_path,
                "image_path": img.get("image_path", ""),
                "slide_numbers": img.get("slide_numbers", []),
                "primary_slide": img.get("primary_slide"),
                "term": term,
                "lessons": lessons,
                "extension": img.get("extension", ""),
            })

    return images


def load_native_extractions():
    """Load native Google API extractions."""
    native_path = NATIVE_DIR / "native_extractions.json"
    if not native_path.exists():
        return []

    with open(native_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data.get("extractions", [])


def load_native_image_metadata():
    """Load images extracted from native Google Slides via the Slides API."""
    meta_path = MEDIA_DIR / "native_image_metadata.json"
    if not meta_path.exists():
        return []

    with open(meta_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    images = []
    for pres_info in data.get("presentations", []):
        source_name = pres_info.get("source_name", "")
        term_key = pres_info.get("term", "")
        term = TERM_KEY_MAP.get(term_key)
        if term is None:
            term = extract_term_from_path(source_name)

        source_path = pres_info.get("source_path", "") or source_name
        lessons = extract_lesson_from_path(source_path, term=term)

        for img in pres_info.get("images", []):
            images.append({
                "source_pptx": source_name,
                "image_path": img.get("image_path", ""),
                "slide_numbers": img.get("slide_numbers", []),
                "primary_slide": img.get("primary_slide"),
                "term": term,
                "lessons": lessons,
                "extension": img.get("extension", ""),
                "size_bytes": img.get("size_bytes", 0),
                "source": "native_slides_api",
            })

    return images


def load_pptx_links():
    """Load hyperlinks extracted from PPTX files (Stage 1)."""
    meta_path = MEDIA_DIR / "extraction_metadata.json"
    if not meta_path.exists():
        return []

    with open(meta_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    links = []
    for pptx_info in data.get("pptx_files", []):
        rel_path = pptx_info.get("relative_path", "")
        term = extract_term_from_path(rel_path)
        lessons = extract_lesson_from_path(rel_path, term=term)

        for link in pptx_info.get("links", []):
            links.append({
                "url": link.get("url", ""),
                "text": link.get("text", ""),
                "slide_number": link.get("slide_number"),
                "link_type": link.get("link_type", "text_hyperlink"),
                "source": "pptx",
                "source_file": rel_path,
                "term": term,
                "lessons": lessons,
            })

    return links


def load_pdf_links():
    """Load hyperlinks and images extracted from PDFs.
    Checks both extraction_metadata.json (new) and pdf_extraction_metadata.json (legacy)."""
    links = []
    images = []
    seen_urls = set()

    # New format: PDF links in extraction_metadata.json
    meta_path = MEDIA_DIR / "extraction_metadata.json"
    if meta_path.exists():
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for pdf_info in data.get("pdf_files", []):
            rel_path = pdf_info.get("relative_path", "")
            term = extract_term_from_path(rel_path)
            lessons = extract_lesson_from_path(rel_path, term=term)
            for link in pdf_info.get("links", []):
                url = link.get("url", "")
                key = (url, rel_path)
                if key not in seen_urls:
                    seen_urls.add(key)
                    links.append({
                        "url": url,
                        "text": "",
                        "page_number": link.get("page_number"),
                        "source": "pdf",
                        "source_file": rel_path,
                        "term": term,
                        "lessons": lessons,
                    })

    # Legacy format: pdf_extraction_metadata.json
    legacy_path = MEDIA_DIR / "pdf_extraction_metadata.json"
    if legacy_path.exists():
        with open(legacy_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for pdf_info in data.get("files", []):
            rel_path = pdf_info.get("relative_path", "")
            term = extract_term_from_path(rel_path)
            lessons = extract_lesson_from_path(rel_path, term=term)
            for link in pdf_info.get("links", []):
                url = link.get("url", "")
                key = (url, rel_path)
                if key not in seen_urls:
                    seen_urls.add(key)
                    links.append({
                        "url": url,
                        "text": "",
                        "page_number": link.get("page_number"),
                        "source": "pdf",
                        "source_file": rel_path,
                        "term": term,
                        "lessons": lessons,
                    })
            for img in pdf_info.get("images", []):
                images.append({
                    "image_path": img.get("image_path", ""),
                    "page_number": img.get("page_number"),
                    "term": term,
                    "lessons": lessons,
                    "extension": img.get("extension", ""),
                    "size_bytes": img.get("size_bytes", 0),
                    "source": "pdf",
                    "source_file": rel_path,
                })

    return links, images


def load_docx_links():
    """Load hyperlinks extracted from DOCX files (Stage 1)."""
    meta_path = MEDIA_DIR / "extraction_metadata.json"
    if not meta_path.exists():
        return []

    with open(meta_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    links = []
    for docx_info in data.get("docx_files", []):
        rel_path = docx_info.get("relative_path", "")
        term = extract_term_from_path(rel_path)
        lessons = extract_lesson_from_path(rel_path, term=term)

        for link in docx_info.get("links", []):
            links.append({
                "url": link.get("url", ""),
                "text": link.get("text", ""),
                "link_type": link.get("link_type", "docx_hyperlink"),
                "source": "docx",
                "source_file": rel_path,
                "term": term,
                "lessons": lessons,
            })

    return links


def load_video_files():
    """Scan sources directory for video files (MP4/MOV/etc).
    Returns list of video file metadata with term/lesson mapping."""
    videos = []
    if not SOURCES_DIR.exists():
        return videos

    for f in SOURCES_DIR.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix.lower() not in VIDEO_EXTENSIONS:
            continue

        try:
            rel_path = str(f.relative_to(SOURCES_DIR))
        except ValueError:
            rel_path = f.name

        term = extract_term_from_path(rel_path)
        lessons = extract_lesson_from_path(rel_path, term=term)

        videos.append({
            "filename": f.name,
            "path": str(f),
            "relative_path": rel_path,
            "size_bytes": f.stat().st_size,
            "extension": f.suffix.lower(),
            "term": term,
            "lessons": lessons,
            "source": "video_file",
        })

    return videos


def collect_all_links(pptx_links, native_extractions, pdf_links, docx_links=None):
    """Merge links from all sources: PPTX, DOCX, native Slides/Docs, PDF.
    Returns list with term/lesson assignments."""
    all_links = list(pptx_links) + list(pdf_links) + list(docx_links or [])

    # Links from native Google Slides and Docs
    for ext in native_extractions:
        name = ext.get("file_name", "")
        source_path = ext.get("source_path", "")
        ntype = ext.get("native_type", "")

        term_key = ext.get("term", "")
        term = TERM_KEY_MAP.get(term_key)
        if term is None:
            term = extract_term_from_path(source_path or name)

        ext_lessons = extract_lesson_from_path(source_path or name, term=term)

        if ntype == "google_slides":
            for slide in ext.get("slides", []):
                for link in slide.get("links", []):
                    all_links.append({
                        "url": link.get("url", ""),
                        "text": link.get("text", ""),
                        "slide_number": link.get("slide_number"),
                        "source": "native_slides",
                        "source_file": name,
                        "term": term,
                        "lessons": ext_lessons,
                    })

        elif ntype == "google_doc":
            for link in ext.get("links", []):
                all_links.append({
                    "url": link.get("url", ""),
                    "text": link.get("text", ""),
                    "source": "native_doc",
                    "source_file": name,
                    "term": term,
                    "lessons": ext_lessons,
                })

    return all_links


def is_video_url(url):
    """Check if a URL matches known video service patterns."""
    for pattern in VIDEO_URL_PATTERNS:
        if pattern.search(url):
            return True
    return False


def collect_all_video_refs(video_files, native_extractions, all_links):
    """Merge video references from: video files, embedded Slides videos, video URLs.
    Returns list with term/lesson assignments."""
    video_refs = []

    # 1. Video files from sources/
    for vf in video_files:
        video_refs.append({
            "type": "video_file",
            "title": Path(vf["filename"]).stem,
            "filename": vf["filename"],
            "path": vf["path"],
            "url": "",
            "size_bytes": vf.get("size_bytes", 0),
            "term": vf["term"],
            "lessons": vf["lessons"],
        })

    # 2. Embedded videos from native Slides API
    for ext in native_extractions:
        if ext.get("native_type") != "google_slides":
            continue
        name = ext.get("file_name", "")
        source_path = ext.get("source_path", "")
        term_key = ext.get("term", "")
        term = TERM_KEY_MAP.get(term_key)
        if term is None:
            term = extract_term_from_path(source_path or name)
        ext_lessons = extract_lesson_from_path(source_path or name, term=term)

        for slide in ext.get("slides", []):
            for vid in slide.get("videos", []):
                video_refs.append({
                    "type": "embedded_video",
                    "title": "",
                    "url": vid.get("url", ""),
                    "video_id": vid.get("video_id", ""),
                    "source_name": name,
                    "slide_number": vid.get("slide_number"),
                    "term": term,
                    "lessons": ext_lessons,
                })

    # 3. YouTube/Vimeo/Drive video links from hyperlinks
    seen_urls = set()
    for link in all_links:
        url = link.get("url", "")
        if not url or url in seen_urls:
            continue
        if is_video_url(url):
            seen_urls.add(url)
            video_refs.append({
                "type": "video_link",
                "title": link.get("text", ""),
                "url": url,
                "source": link.get("source", ""),
                "source_file": link.get("source_file", ""),
                "term": link.get("term"),
                "lessons": link.get("lessons", []),
            })

    return video_refs


def detect_new_files():
    """Scan source files and flag any not present in file_manifest.json as pending_review.

    Returns list of newly detected file paths. Updates the manifest in-place.
    """
    if not SOURCES_DIR.exists():
        return []

    # Load existing manifest
    manifest = {"files": [], "categories": {}, "_description": "", "_usage": "", "_updated": ""}
    if FILE_MANIFEST_PATH.exists():
        try:
            with open(FILE_MANIFEST_PATH, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            pass

    known_paths = {entry.get("path", "").replace("\\", "/") for entry in manifest.get("files", [])}

    # Scan all source files (skip temp files and non-content extensions)
    content_extensions = {".pptx", ".docx", ".xlsx", ".pdf", ".mp4", ".mov", ".avi", ".webm"}
    new_files = []

    for file_path in sorted(SOURCES_DIR.rglob("*")):
        if not file_path.is_file() or file_path.name.startswith("~$"):
            continue
        ext = file_path.suffix.lower()
        if ext not in content_extensions:
            continue

        try:
            rel_path = str(file_path.relative_to(SOURCES_DIR)).replace("\\", "/")
        except ValueError:
            continue

        if rel_path not in known_paths:
            term = extract_term_from_path(rel_path)
            new_entry = {
                "path": rel_path,
                "category": "pending_review",
                "term": term,
                "detected_at": datetime.now(timezone.utc).isoformat(),
            }
            manifest.get("files", []).append(new_entry)
            new_files.append(rel_path)

    # Save updated manifest if new files found
    if new_files:
        manifest["_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with open(FILE_MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

    # Write a notification file if new files found so it persists across runs
    notification_path = BASE_DIR / "validation" / "file_alerts.json"
    if new_files:
        notification_path.parent.mkdir(parents=True, exist_ok=True)
        alert = {
            "alert_type": "new_files_detected",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "count": len(new_files),
            "files": new_files,
            "action_required": "Review file_manifest.json — classify pending_review files as "
                               "lesson_content, support_resource, or exclude.",
        }
        # Merge with existing alerts
        existing_alerts = []
        if notification_path.exists():
            try:
                with open(notification_path, "r", encoding="utf-8") as f:
                    existing_alerts = json.load(f).get("alerts", [])
            except Exception:
                pass
        existing_alerts.append(alert)
        with open(notification_path, "w", encoding="utf-8") as f:
            json.dump({"alerts": existing_alerts}, f, indent=2, ensure_ascii=False)

    return new_files


def detect_stale_files():
    """Find files in file_manifest.json that no longer exist on disk.

    Returns list of stale file paths. Does NOT remove them from the manifest
    (that requires user review).
    """
    if not FILE_MANIFEST_PATH.exists():
        return []

    try:
        with open(FILE_MANIFEST_PATH, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception:
        return []

    stale = []
    for entry in manifest.get("files", []):
        rel_path = entry.get("path", "")
        if not rel_path:
            continue
        full_path = SOURCES_DIR / rel_path.replace("/", os.sep)
        if not full_path.exists():
            stale.append(rel_path)

    # Write notification if stale files found
    if stale:
        notification_path = BASE_DIR / "validation" / "file_alerts.json"
        notification_path.parent.mkdir(parents=True, exist_ok=True)
        alert = {
            "alert_type": "stale_files_detected",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "count": len(stale),
            "files": stale,
            "action_required": "These files are in file_manifest.json but no longer exist on disk. "
                               "They may have been renamed, moved, or deleted.",
        }
        existing_alerts = []
        if notification_path.exists():
            try:
                with open(notification_path, "r", encoding="utf-8") as f:
                    existing_alerts = json.load(f).get("alerts", [])
            except Exception:
                pass
        existing_alerts.append(alert)
        with open(notification_path, "w", encoding="utf-8") as f:
            json.dump({"alerts": existing_alerts}, f, indent=2, ensure_ascii=False)

    return stale


def run_consolidation():
    """Merge all sources into unified per-term, per-lesson structure."""
    print("=" * 60)
    print("  Stage 5: Content Consolidation")
    print("=" * 60)
    print()

    CONSOLIDATED_DIR.mkdir(parents=True, exist_ok=True)

    # Detect new source files not in file_manifest.json
    print("Checking for new source files...")
    new_files = detect_new_files()
    if new_files:
        print(f"  {len(new_files)} new source file(s) detected — added to file_manifest.json as pending_review:")
        for nf in new_files[:10]:
            print(f"     - {nf}")
        if len(new_files) > 10:
            print(f"     ... and {len(new_files) - 10} more")
        print(f"  Review file_manifest.json to classify them.\n")
    else:
        print("  No new files detected.\n")

    # Detect stale files (in manifest but no longer on disk)
    print("Checking for stale/missing files...")
    stale_files = detect_stale_files()
    if stale_files:
        print(f"  {len(stale_files)} file(s) in manifest no longer found on disk:")
        for sf in stale_files[:10]:
            print(f"     - {sf}")
        if len(stale_files) > 10:
            print(f"     ... and {len(stale_files) - 10} more")
        print(f"  These files may have been renamed, moved, or deleted.\n")
    else:
        print("  No stale files detected.\n")

    # Load all sources
    print("Loading converted documents...")
    converted = load_converted_files()
    print(f"  {len(converted)} converted files")

    print("Loading media metadata (PPTX)...")
    media = load_media_metadata()
    print(f"  {len(media)} PPTX-extracted images")

    print("Loading PPTX hyperlinks...")
    pptx_links = load_pptx_links()
    print(f"  {len(pptx_links)} PPTX links")

    print("Loading native Slides API images...")
    native_images = load_native_image_metadata()
    print(f"  {len(native_images)} native API images")

    print("Loading native Google extractions...")
    native = load_native_extractions()
    print(f"  {len(native)} native extractions")

    print("Loading DOCX hyperlinks...")
    docx_links = load_docx_links()
    print(f"  {len(docx_links)} DOCX links")

    print("Loading PDF metadata...")
    pdf_links, pdf_images = load_pdf_links()
    print(f"  {len(pdf_links)} PDF links, {len(pdf_images)} PDF images")

    print("Loading video files...")
    video_files = load_video_files()
    print(f"  {len(video_files)} video files")

    # Collect all links and video references
    print("\nCollecting all links...")
    all_links = collect_all_links(pptx_links, native, pdf_links, docx_links)
    print(f"  {len(all_links)} total links across all sources")

    print("Collecting all video references...")
    all_video_refs = collect_all_video_refs(video_files, native, all_links)
    print(f"  {len(all_video_refs)} total video references")

    # Detect duplicates across converted files
    print("\nRunning duplicate detection...")
    all_items = []
    for c in converted:
        all_items.append({"name": Path(c["path"]).name, "id": c["path"], "md5": ""})
    duplicates = detect_duplicates(all_items)
    print(f"  Found {len(duplicates)} potential duplicates")

    # Build per-term, per-lesson structure: by_term[term_num][lesson_num]
    by_term = defaultdict(lambda: defaultdict(lambda: {
        "documents": [],
        "images": [],
        "native_content": [],
        "links": [],
        "video_refs": [],
    }))

    # Assign converted documents
    for doc in converted:
        term = doc.get("term")
        if term is None:
            continue
        for lesson in doc.get("lessons", []):
            by_term[term][lesson]["documents"].append(doc)

    # Assign PPTX images
    for img in media:
        term = img.get("term")
        if term is None:
            continue
        for lesson in img.get("lessons", []):
            by_term[term][lesson]["images"].append(img)

    # Assign native Slides API images
    for img in native_images:
        term = img.get("term")
        if term is None:
            continue
        for lesson in img.get("lessons", []):
            by_term[term][lesson]["images"].append(img)

    # Assign native extractions — use the "term" field stored during extraction
    for ext in native:
        name = ext.get("file_name", "")
        source_path = ext.get("source_path", "")

        # Determine term: prefer explicit "term" field, fall back to path parsing
        term_key = ext.get("term", "")
        term = TERM_KEY_MAP.get(term_key)
        if term is None:
            term = extract_term_from_path(source_path or name)
        if term is None:
            continue

        ext_lessons = extract_lesson_from_path(source_path or name, term=term)
        for lesson in ext_lessons:
            by_term[term][lesson]["native_content"].append(ext)

    # Assign PDF images
    for img in pdf_images:
        term = img.get("term")
        if term is None:
            continue
        for lesson in img.get("lessons", []):
            by_term[term][lesson]["images"].append(img)

    # Assign links to lessons
    for link in all_links:
        term = link.get("term")
        if term is None:
            continue
        for lesson in link.get("lessons", []):
            by_term[term][lesson]["links"].append(link)

    # Assign video references to lessons
    for vref in all_video_refs:
        term = vref.get("term")
        if term is None:
            continue
        for lesson in vref.get("lessons", []):
            by_term[term][lesson]["video_refs"].append(vref)

    # Build consolidated output — structured by_term → by_lesson
    consolidated = {
        "consolidated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_documents": len(converted),
            "total_images": len(media) + len(native_images) + len(pdf_images),
            "total_pptx_images": len(media),
            "total_native_images": len(native_images),
            "total_pdf_images": len(pdf_images),
            "total_native": len(native),
            "total_links": len(all_links),
            "total_video_refs": len(all_video_refs),
            "total_video_files": len(video_files),
            "total_duplicates": len(duplicates),
            "terms_covered": sorted(by_term.keys()),
        },
        "by_term": {},
        "duplicates": duplicates,
        "unassigned": {
            "documents": [d for d in converted if not d.get("lessons") or d.get("term") is None],
            "native": [n for n in native if not extract_lesson_from_path(n.get("file_name", ""))],
        },
    }

    for term_num in sorted(by_term.keys()):
        term_lessons = by_term[term_num]
        term_data = {"by_lesson": {}}

        for lesson_num in sorted(term_lessons.keys()):
            data = term_lessons[lesson_num]
            term_data["by_lesson"][str(lesson_num)] = {
                "lesson": lesson_num,
                "term": term_num,
                "document_count": len(data["documents"]),
                "image_count": len(data["images"]),
                "native_count": len(data["native_content"]),
                "link_count": len(data["links"]),
                "video_ref_count": len(data["video_refs"]),
                "documents": data["documents"],
                "images": data["images"],
                "native_content": data["native_content"],
                "links": data["links"],
                "video_refs": data["video_refs"],
            }

        consolidated["by_term"][str(term_num)] = term_data

    # ── Save per-term files ──
    # Build filename → term mapping for duplicate filtering
    file_term_map = {}
    for c in converted:
        fname = Path(c["path"]).name
        term = c.get("term")
        if term:
            file_term_map.setdefault(fname, set()).add(term)

    per_term_paths = []
    for term_str in sorted(consolidated["by_term"].keys(), key=int):
        term_num = int(term_str)
        term_data = consolidated["by_term"][term_str]
        term_lessons = term_data.get("by_lesson", {})

        # Term-specific counts
        term_docs = sum(l.get("document_count", 0) for l in term_lessons.values())
        term_imgs = sum(l.get("image_count", 0) for l in term_lessons.values())
        term_native = sum(l.get("native_count", 0) for l in term_lessons.values())
        term_links = sum(l.get("link_count", 0) for l in term_lessons.values())
        term_video_refs = sum(l.get("video_ref_count", 0) for l in term_lessons.values())
        term_video_file_count = sum(1 for vf in video_files if vf.get("term") == term_num)

        # Filter duplicates to this term
        term_dups = [
            d for d in duplicates
            if term_num in file_term_map.get(d.get("file", ""), set())
        ]

        # Filter unassigned to this term
        term_unassigned_docs = [
            d for d in consolidated["unassigned"]["documents"]
            if d.get("term") == term_num
        ]
        term_unassigned_native = [
            n for n in consolidated["unassigned"]["native"]
            if TERM_KEY_MAP.get(n.get("term", "")) == term_num
            or extract_term_from_path(n.get("source_path", "") or n.get("file_name", "")) == term_num
        ]

        per_term_output = {
            "consolidated_at": consolidated["consolidated_at"],
            "term": term_num,
            "summary": {
                "total_lessons": len(term_lessons),
                "total_documents": term_docs,
                "total_images": term_imgs,
                "total_native": term_native,
                "total_links": term_links,
                "total_video_refs": term_video_refs,
                "total_video_files": term_video_file_count,
                "total_duplicates": len(term_dups),
            },
            "by_lesson": term_lessons,
            "duplicates": term_dups,
            "unassigned": {
                "documents": term_unassigned_docs,
                "native": term_unassigned_native,
            },
        }

        term_path = CONSOLIDATED_DIR / f"consolidated_term{term_num}.json"
        with open(term_path, "w", encoding="utf-8") as f:
            json.dump(per_term_output, f, indent=2, ensure_ascii=False)
        per_term_paths.append(term_path)

    # ── Optionally save combined file ──
    write_combined = CONSOLIDATE_COMBINED or "--combined" in sys.argv
    if write_combined:
        combined_path = CONSOLIDATED_DIR / "consolidated_content.json"
        with open(combined_path, "w", encoding="utf-8") as f:
            json.dump(consolidated, f, indent=2, ensure_ascii=False)

    # ── Print summary ──
    print(f"\nConsolidated content:")
    for term_str in sorted(consolidated["by_term"].keys(), key=int):
        term_data = consolidated["by_term"][term_str]
        lessons = term_data["by_lesson"]
        print(f"  Term {term_str}: {len(lessons)} lessons")
        for lesson_str in sorted(lessons.keys(), key=int):
            l = lessons[lesson_str]
            parts = [
                f"{l['document_count']} docs",
                f"{l['image_count']} imgs",
                f"{l['native_count']} native",
            ]
            if l.get("link_count", 0) > 0:
                parts.append(f"{l['link_count']} links")
            if l.get("video_ref_count", 0) > 0:
                parts.append(f"{l['video_ref_count']} videos")
            print(f"    Lesson {lesson_str}: {', '.join(parts)}")
    print(f"  Unassigned docs: {len(consolidated['unassigned']['documents'])}")
    print(f"  Duplicates found: {len(duplicates)}")

    for p in per_term_paths:
        print(f"\nSaved: {p}")
    if write_combined:
        print(f"Saved: {CONSOLIDATED_DIR / 'consolidated_content.json'}")
    print("=" * 60)

    return consolidated


if __name__ == "__main__":
    run_consolidation()
