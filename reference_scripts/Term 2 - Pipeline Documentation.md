# Term 2 Content Conversion Pipeline
## Comprehensive Documentation for Future Agents

**Last Updated:** 2026-02-25
**Project:** Endstar AI Assistant - Term 2 Game Design Curriculum KB
**Scope:** 12 lessons across 6 weeks (UAE heritage-themed game design course)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Source Material Inventory](#2-source-material-inventory)
3. [Pipeline Architecture](#3-pipeline-architecture)
4. [Stage 1: Media Extraction](#4-stage-1-media-extraction)
5. [Stage 2: Document Conversion](#5-stage-2-document-conversion)
6. [Stage 3: Video Processing](#6-stage-3-video-processing)
7. [Stage 4: Vision Analysis (Image Descriptions)](#7-stage-4-vision-analysis)
8. [Stage 5: Data Consolidation](#8-stage-5-data-consolidation)
9. [Stage 6: KB Building & CSV Enhancement](#9-stage-6-kb-building--csv-enhancement)
10. [Stage 7: Multi-Way Validation](#10-stage-7-multi-way-validation)
11. [Output Files Reference](#11-output-files-reference)
12. [Known Issues & Decisions](#12-known-issues--decisions)
13. [QA Test Suite (Separate System)](#13-qa-test-suite)
14. [Environment & Dependencies](#14-environment--dependencies)
15. [Quick-Start Guide](#15-quick-start-guide)

---

## 1. Executive Summary

This pipeline converts 50+ raw teacher resource files (PPTX, DOCX, PDF, XLSX, MP4) into a structured, validated knowledge base with:

- **61 markdown files** (text content from all documents)
- **443 AI-described images** (extracted from PPTX slides with educational context)
- **3 video transcripts** (Whisper-transcribed with ~21,000 chars total)
- **12/12 lesson coverage** verified through a 5-signal validation system

The pipeline consists of **16 Python scripts** organized into 7 stages, executed sequentially with some stages parallelizable.

### Pipeline Flow Diagram

```
Teacher Resources/ (50+ source files)
    |
    +---> [Stage 1] extract_media.py
    |         |---> Extracted Media/pptx_images/ (750+ images, 32 folders)
    |         |---> Extracted Media/video_keyframes/ (72 keyframes, 4 folders)
    |         |---> Extracted Media/video_transcripts/ (3 WAV audio files)
    |         +---> Extracted Media/metadata/extraction_metadata.json
    |
    +---> [Stage 2] convert_docs.py
    |         +---> Converted/ (61 markdown + CSV files)
    |
    +---> [Stage 3] transcribe_videos.py
    |         +---> video_transcripts/*_transcript.json + .txt
    |         +---> Extracted Media/audio/transcriptions.json
    |
    +---> [Stage 4] Claude Code Agents (manual per-lesson)
    |         +---> claude_descriptions/results/batch_lesson*_detailed.json (x12)
    |         +---> claude_descriptions/results/batch_exemplar_*.json (x3)
    |         +---> claude_descriptions/results/batch_portfolio.json
    |         +---> claude_descriptions/results/batch_video_*.json (x3)
    |
    +---> [Stage 5] Consolidation (inline Python)
    |         +---> MASTER_all_results.json (443 images, 19 batches)
    |
    +---> [Stage 5b] merge_slide_metadata.py
    |         +---> Updated MASTER_all_results.json (with slide numbers)
    |
    +---> [Stage 6] compare_and_build_kb.py
    |         +---> Knowledge Base/term2_knowledge_base.json
    |
    +---> [Stage 6b] fix_csv_and_add_images.py
    |         +---> Term 2 - Lesson Based Structure (Fixed).csv
    |
    +---> [Stage 7] validation_parser.py --> validation_mapper.py
              --> validation_anomalies.py --> validation_report.py
              +---> Term 2 - Validation Report.json + .txt
```

---

## 2. Source Material Inventory

### Folder Structure

```
Teacher Resources/
+-- Assessment Guides/
|   +-- Exemplar work/
|   |   +-- Week 1/
|   |   |   +-- Exampler Work - Lesson 1-2.pptx
|   |   +-- Week 2/
|   |   |   +-- Exampler Work - Lesson 3-4.pptx
|   |   |   +-- Designing_Restoring_Light.mp4
|   |   +-- Week 3-6/
|   |       +-- Exampler Work Lesson 5-12.pptx
|   |       +-- Designing_Restoring_Light.mp4  (duplicate of Week 2)
|   |       +-- Light_of_the_Mosque.mp4
|   |       +-- The_Unseen_Hero.mp4
|   +-- Student Guide/
|   |   +-- Student Assessment Guide.docx
|   |   +-- Student Assessment Guide (visual version).docx
|   |   +-- Student Assessment Guide.pdf
|   |   +-- Student Assessment Guide (visual version).pdf
|   +-- Teacher Guide/
|       +-- Teacher Assessment Guide.docx
|       +-- Teacher Assessment Guide (visual version).docx
|       +-- Teacher Assessment Guide.pdf
|       +-- Teacher Assessment Guide (visual version).pdf
+-- Curriculum Alignment/
|   +-- Curriculum Alignment GCSE.pdf
+-- Curriculum Content/
|   +-- LOs and Success Criteria/
|   |   +-- Learning Schedule.xlsx
|   +-- Week 1/ through Week 6/  (6 folders)
|       +-- Lesson Plans/
|       |   +-- Lesson {N}.docx  (2 per week = 12 total)
|       +-- Students Slides/
|       |   +-- Lesson {N}.pptx  (2 per week = 12 total)
|       +-- Teachers Slides/
|           +-- Lesson {N}.pptx  (2 per week = 12 total)
+-- Student Portfolio/
    +-- Activities & Portfolio Deck.pptx
```

### File Counts by Type

| Type | Count | Content |
|------|-------|---------|
| PPTX | 30 | Teachers Slides (12), Students Slides (12), Exemplars (3), Portfolio (1), Others (2) |
| DOCX | 12 | Lesson Plans (12) |
| PDF  | 5  | Assessment guides (4), Curriculum alignment (1) |
| XLSX | 1  | Learning Schedule |
| MP4  | 3  | Designing_Restoring_Light, Light_of_the_Mosque, The_Unseen_Hero |
| **Total** | **51** | |

### Week-to-Lesson Mapping

| Week | Lessons | Videos |
|------|---------|--------|
| 1 | 1, 2 | -- |
| 2 | 3, 4 | Designing_Restoring_Light |
| 3 | 5, 6 | -- |
| 4 | 7, 8 | -- |
| 5 | 9, 10 | -- |
| 6 | 11, 12 | Light_of_the_Mosque, The_Unseen_Hero |

---

## 3. Pipeline Architecture

### Scripts by Stage

| Stage | Script | Purpose | Status |
|-------|--------|---------|--------|
| 1 | `extract_media.py` | Extract images from PPTX + keyframes from video | COMPLETE |
| 2 | `convert_docs.py` | Convert DOCX/PPTX/PDF/XLSX to Markdown/CSV | COMPLETE |
| 2b | `verify_conversions.py` | Verify text preservation after conversion | COMPLETE |
| 3 | `transcribe_videos.py` | Whisper transcription of 3 videos | COMPLETE |
| 4 | `vision_claude_pipeline.py` | Generate batch files for Claude image analysis | COMPLETE |
| 4b | *Claude Code Agents* | Manual per-lesson image analysis (see Stage 4) | COMPLETE |
| 4c | `vision_gemini_pipeline.py` | Gemini Vision API analysis (FAILED - see notes) | FAILED |
| 4d | `run_gemini.py` | Runner for Gemini pipeline | FAILED |
| 4e | `gemini_retry.py` | Retry failed Gemini analyses | FAILED |
| 4f | `resume_gemini.py` | Resume interrupted Gemini processing | FAILED |
| 5 | *Inline consolidation script* | Merge all batch results into MASTER file | COMPLETE |
| 5b | `merge_slide_metadata.py` | Add slide numbers to MASTER results | COMPLETE |
| 6 | `compare_and_build_kb.py` | Build final KB from all sources | COMPLETE |
| 6b | `fix_csv_and_add_images.py` | Embed image/video data into lesson CSV | COMPLETE |
| 7a | `validation_parser.py` | Parse all content into unified structure | DESIGNED |
| 7b | `validation_mapper.py` | Apply 5 validation signals | DESIGNED |
| 7c | `validation_anomalies.py` | Detect alignment issues | DESIGNED |
| 7d | `validation_report.py` | Generate validation report | DESIGNED |

### Utility Scripts (Not Part of Pipeline)

| Script | Purpose |
|--------|---------|
| `inspect_docx_styles.py` | DOCX style inspector (unrelated project) |
| `write_inspector.py` | Bootstrap for inspect_docx_styles (unrelated) |

---

## 4. Stage 1: Media Extraction

### Script: `extract_media.py`

**Purpose:** Extract all embedded images from PPTX files and keyframes from video files, with slide-number tracking.

**How it works:**
1. Scans `Teacher Resources/` recursively for `.pptx` and video files
2. For each PPTX:
   - Opens the ZIP archive to find media files (`ppt/media/`)
   - Parses XML relationship files (`ppt/slides/_rels/`) to map images to slides
   - Extracts images, renames them sequentially (`image_001.png`, etc.)
   - Records which slide numbers each image appears on
   - Extracts text content per slide for cross-referencing
3. For each video:
   - Uses `ffmpeg` to extract keyframes at 10-second intervals
   - Uses `ffprobe` for duration/metadata
   - Extracts WAV audio for later transcription

**Key Functions:**
- `build_slide_image_mapping()` -- Parses PPTX XML to map media filenames to slide numbers
- `extract_pptx_images()` -- Main PPTX extraction with deduplication
- `extract_slide_text()` -- Extracts all text from each slide
- `extract_video_keyframes()` -- ffmpeg keyframe extraction
- `extract_video_audio()` -- WAV audio extraction for Whisper

**Input:** `Teacher Resources/` (all PPTX + MP4 files)

**Output:**
```
Extracted Media/
+-- pptx_images/                      (32 subdirectories)
|   +-- Curriculum_Content_Week_1_Teachers_Slides_Lesson_1/
|   |   +-- image_001.png
|   |   +-- image_002.jpg
|   |   +-- ... (20-40 images per lesson)
|   +-- Curriculum_Content_Week_1_Students_Slides_Lesson_1/
|   +-- ... (24 curriculum dirs + 3 exemplar + 3 other + 1 portfolio)
+-- video_keyframes/                  (4 subdirectories)
|   +-- Assessment_Guides_Exemplar_work_Week_2_Designing_Restoring_Light/
|   |   +-- keyframe_001.jpg through keyframe_0XX.jpg
|   +-- ... (3 more video keyframe folders)
+-- video_transcripts/                (WAV audio files)
|   +-- Designing_Restoring_Light.wav
|   +-- Light_of_the_Mosque.wav
|   +-- The_Unseen_Hero.wav
+-- metadata/
    +-- extraction_metadata.json      (master index of all extractions)
```

**Statistics:**
- ~750+ total images extracted from PPTX files
- ~72 keyframes extracted from 3 videos
- 32 image directories created
- Slide-to-image mapping captured for cross-referencing

**Naming Convention for Directories:**
Folder names are derived from the relative path with separators replaced by underscores:
`Curriculum_Content_Week_{N}_Teachers_Slides_Lesson_{N}`

---

## 5. Stage 2: Document Conversion

### Script: `convert_docs.py`

**Purpose:** Convert all source documents to machine-readable Markdown format, preserving folder structure.

**How it works:**
1. Walks `Teacher Resources/` finding DOCX, PPTX, PDF, XLSX files
2. For each file type:
   - **DOCX:** Uses `python-docx` to extract paragraphs with style-based headers, tables as markdown tables
   - **PPTX:** Slide-by-slide conversion with `## Slide N` headers, preserving notes
   - **PDF:** Page-by-page text extraction with `PyPDF2`
   - **XLSX:** Each sheet becomes a CSV file via `openpyxl`
3. Outputs to `Converted/` maintaining the same folder hierarchy

**Input:** `Teacher Resources/` (all 51 files)

**Output:**
```
Converted/
+-- Assessment Guides/
|   +-- Exemplar work/
|   |   +-- Week 1/Exampler Work - Lesson 1-2.md
|   |   +-- Week 2/Exampler Work - Lesson 3-4.md
|   |   +-- Week 3-6/Exampler Work Lesson 5-12.md
|   +-- Student Guide/
|   |   +-- Student Assessment Guide.md
|   |   +-- Student Assessment Guide (visual version).md
|   +-- Teacher Guide/
|       +-- Teacher Assessment Guide.md
|       +-- Teacher Assessment Guide (visual version).md
+-- Curriculum Alignment/
|   +-- Curriculum Alignment GCSE.md
+-- Curriculum Content/
|   +-- LOs and Success Criteria/
|   |   +-- Learning Schedule.csv
|   +-- Week 1-6/
|       +-- Lesson Plans/Lesson {1-12}.md       (12 files)
|       +-- Students Slides/Lesson {1-12}.md    (12 files)
|       +-- Teachers Slides/Lesson {1-12}.md    (12 files)
+-- Student Portfolio/
    +-- Activities & Portfolio Deck.md
```

**Total Output:** 61 files (60 markdown + 1 CSV)

### Script: `verify_conversions.py`

**Purpose:** Quality check -- ensures converted markdown preserves the text content from source files.

**How it works:**
1. For each source file, extracts raw text using native Python libraries
2. For each converted file, reads the markdown text
3. Normalizes both (strip whitespace, lowercase)
4. Calculates word-overlap similarity percentage
5. Reports results with color-coded thresholds: 90%+ PASS, 70-90% WARN, <70% LOW

**Output:** Console table (no file output). Used for manual verification.

---

## 6. Stage 3: Video Processing

### Script: `transcribe_videos.py`

**Purpose:** Transcribe video audio using OpenAI's Whisper model.

**How it works:**
1. Loads WAV files from `Extracted Media/video_transcripts/`
2. Uses Whisper "base" model for speech-to-text (configurable to "small"/"medium")
3. Outputs both structured JSON (with segments) and plain text

**Input:** 3 WAV files extracted by `extract_media.py`

**Output:**
```
Extracted Media/
+-- video_transcripts/
|   +-- Designing_Restoring_Light_transcript.json  (segments + full text)
|   +-- Designing_Restoring_Light_transcript.txt   (plain text)
|   +-- Light_of_the_Mosque_transcript.json
|   +-- Light_of_the_Mosque_transcript.txt
|   +-- The_Unseen_Hero_transcript.json
|   +-- The_Unseen_Hero_transcript.txt
+-- audio/
    +-- transcriptions.json  (combined index: all 3 transcripts)
```

**Video Content Summary:**

| Video | Week | Lessons | Duration | Content |
|-------|------|---------|----------|---------|
| Designing_Restoring_Light | 2 | 3-4 | ~8 min | Game design of a mosque heritage experience |
| Light_of_the_Mosque | 6 | 11-12 | ~9 min | Iterative design process, playtesting, feedback |
| The_Unseen_Hero | 6 | 11-12 | ~8 min | Project management in game development |

**Dependencies:** `openai-whisper`, `torch`

---

## 7. Stage 4: Vision Analysis

### CRITICAL: How Image Descriptions Were Actually Generated

The image descriptions were **NOT** generated through a traditional API pipeline. Instead, they were created using **Claude Code's multimodal capability** -- by spawning background Task agents that read each image file directly and analyzed it visually.

### Process:

1. **`vision_claude_pipeline.py`** was used to generate batch index files organizing images into groups of 10
2. **Claude Code Task agents** were launched (one per lesson/batch) with prompts to:
   - Read each image using the `Read` tool (which renders images visually)
   - Analyze content and generate structured JSON with fields:
     - `filename` -- image file name
     - `content_type` -- e.g., "diagram", "screenshot", "infographic", "logo"
     - `visual_description` -- what the image shows
     - `educational_context` -- how it relates to the lesson
     - `kb_tags` -- keyword tags for KB retrieval
   - Skip generic backgrounds, small icons (<5KB), and decorative elements
   - Save results as `batch_lesson{N}_detailed.json`

### Agent Prompt Template (for each lesson):

```
Analyze images in folder:
D:\Term 3 QA\Teacher Resources - Term 2\Extracted Media\pptx_images\
  Curriculum_Content_Week_{W}_Teachers_Slides_Lesson_{N}\

For EACH image:
1. Read the image using the Read tool
2. Analyze and create JSON entry with:
   - index, content_type, visual_description, educational_context, kb_tags
3. Skip small icons (<5KB) and generic backgrounds
Save to: batch_lesson{N}_detailed.json
```

### Batch Results Generated:

| Batch File | Source | Images |
|------------|--------|--------|
| `batch_lesson1_detailed.json` | Teachers Slides Lesson 1 | 27 |
| `batch_lesson2.json` | Teachers Slides Lesson 2 | 28 |
| `batch_lesson3_detailed.json` | Teachers Slides Lesson 3 | 27 |
| `batch_lesson4_detailed.json` | Teachers Slides Lesson 4 | 26 |
| `batch_lesson5.json` | Teachers Slides Lesson 5 | 26 |
| `batch_lesson6.json` | Teachers Slides Lesson 6 | 25 |
| `batch_lesson7.json` | Teachers Slides Lesson 7 | 24 |
| `batch_lesson8.json` | Teachers Slides Lesson 8 | 25 |
| `batch_lesson9.json` | Teachers Slides Lesson 9 | 26 |
| `batch_lesson10.json` | Teachers Slides Lesson 10 | 27 |
| `batch_lesson11.json` | Teachers Slides Lesson 11 | 24 |
| `batch_lesson12.json` | Teachers Slides Lesson 12 | 23 |
| `batch_exemplar_week1.json` | Exemplar Work Lesson 1-2 | 7 |
| `batch_exemplar_week2.json` | Exemplar Work Lesson 3-4 | 12 |
| `batch_exemplar_weeks3-6.json` | Exemplar Work Lesson 5-12 | 13 |
| `batch_portfolio.json` | Activities & Portfolio Deck | 31 |
| `batch_video_restoring_light.json` | Restoring Light keyframes | 24 |
| `batch_video_mosque.json` | Light of Mosque keyframes | 24 |
| `batch_video_unseen_hero.json` | Unseen Hero keyframes | 24 |
| **TOTAL** | | **443** |

### Gemini Pipeline (FAILED)

`vision_gemini_pipeline.py`, `run_gemini.py`, `gemini_retry.py`, and `resume_gemini.py` were attempts to use Google's Gemini Vision API as a parallel/alternative source. All failed with:
```
Error: "Part.from_text() takes 1 positional argument but 2 were given"
```
This was an SDK compatibility issue. The Gemini results were NOT used in the final KB. All 443 image descriptions come exclusively from Claude Code agents.

---

## 8. Stage 5: Data Consolidation

### Consolidation Script (Inline Python, run in Claude Code)

**Purpose:** Merge all 19 batch result files + video transcripts into a single master file.

**How it works:**
1. Loads all `batch_*.json` files from `Extracted Media/claude_descriptions/results/`
2. Skips old metadata-only files (`batch_lesson3.json`, `batch_lesson4.json` which were superseded by `_detailed` versions)
3. Loads video transcripts from `Extracted Media/audio/transcriptions.json`
4. Consolidates into a unified structure with summary statistics

**Output:** `Extracted Media/claude_descriptions/results/MASTER_all_results.json`

**Structure:**
```json
{
  "consolidated_at": "2026-02-03T16:41:48",
  "summary": {
    "total_batches": 19,
    "total_images_analyzed": 443,
    "lessons_covered": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    "categories": {
      "exemplar": 32,
      "curriculum": 308,
      "portfolio": 31,
      "video": 72
    }
  },
  "video_transcripts": {
    "Designing_Restoring_Light": { "text": "...", "language": "en" },
    "Light_of_the_Mosque": { "text": "...", "language": "en" },
    "The_Unseen_Hero": { "text": "...", "language": "en" }
  },
  "image_descriptions": [
    {
      "batch": "batch_name",
      "source": "relative/path/to/source.pptx",
      "count": 27,
      "results": [
        {
          "filename": "image_001.png",
          "content_type": "diagram",
          "visual_description": "A player motivation framework...",
          "educational_context": "Teaches students about...",
          "kb_tags": ["player-motivation", "game-design-theory"],
          "source_pptx": "D:\\...\\source.pptx",
          "extracted_image_path": "D:\\...\\image_001.png",
          "slide_numbers": [12],
          "primary_slide": 12
        }
      ]
    }
  ]
}
```

### Script: `merge_slide_metadata.py`

**Purpose:** Enrich MASTER_all_results.json with slide number and source PPTX path metadata from extraction_metadata.json.

**How it works:**
1. Reads `extraction_metadata.json` (has slide-image mappings from PPTX XML)
2. For each image in MASTER_all_results.json, matches to extraction metadata
3. Adds `slide_numbers`, `primary_slide`, and `source_pptx` fields
4. Handles path normalization issues (trailing spaces, underscores)

**Input:**
- `Extracted Media/metadata/extraction_metadata.json`
- `Extracted Media/claude_descriptions/results/MASTER_all_results.json`

**Output:** Updated `MASTER_all_results.json` with slide metadata

---

## 9. Stage 6: KB Building & CSV Enhancement

### Script: `compare_and_build_kb.py`

**Purpose:** Build a structured knowledge base organized by lesson from all content sources.

**How it works:**
1. Loads Claude results (from MASTER_all_results.json)
2. Loads Gemini results if available (from gemini_kb_data.json) -- in practice, only Claude data was used
3. Loads extraction metadata and video transcripts
4. Organizes by lesson key: `Week{w}_Lesson{l}`
5. Exports in JSON, Markdown, and CSV formats

**Output:**
```
Knowledge Base/
+-- term2_knowledge_base.json  (structured by lesson with all content)
+-- term2_knowledge_base.md    (human-readable format)
+-- term2_image_descriptions.csv (spreadsheet view)
```

### Script: `fix_csv_and_add_images.py`

**Purpose:** Fix column alignment issues in the lesson CSV and embed image/video metadata directly into each lesson row.

**How it works:**
1. Reads `Term 2 - Lesson Based Structure.csv`
2. Fixes column shift: moves activities from "Testing Scores" to "Description of Activities"
3. For each lesson row, loads matching images from MASTER_all_results.json
4. Embeds full image arrays and video data into the Metadata JSON column
5. Maps videos to lessons:
   - `Designing_Restoring_Light` --> Lessons 3-4
   - `Light_of_the_Mosque` --> Lessons 11-12
   - `The_Unseen_Hero` --> Lessons 11-12

**Output:** `Term 2 - Lesson Based Structure (Fixed).csv` (792 KB with embedded media data)

---

## 10. Stage 7: Multi-Way Validation

**Status:** Scripts are written but validation has not been executed yet.

### Architecture: 5-Signal Consensus System

```
+-------------------+
|  VALIDATION HUB   |
+-------------------+
         |
  +------+------+------+------+------+
  |      |      |      |      |      |
Signal  Signal  Signal  Signal  Signal
  1       2       3       4       5
Path   Metadata Semantic Keyword Volume
Pattern CrossRef  Align   Match   Check
(1.0)   (0.95)   (0.8)   (0.7)  (0.5)
```

### Script: `validation_parser.py` (Script 1 of 4)

**Purpose:** Parse ALL content (markdown, images, videos) into a unified structure.

**Inputs:**
- `Converted/` (61 markdown files)
- `MASTER_all_results.json` (443 image descriptions)
- `Extracted Media/audio/transcriptions.json` (3 video transcripts)
- `Term 2 - Source Inventory.csv`
- `Term 2 - Lesson Based Structure.csv`

**Output:** `Term 2 - Unified Content.json`

**Key Function:** `extract_lesson_from_path()` uses 5 regex patterns:
1. Explicit "Lesson X" in filename
2. "Lessons X-Y" range
3. Week folder inference (Week N = Lessons 2N-1, 2N)
4. Portfolio/all-lessons detection
5. Exemplar week spanning

### Script: `validation_mapper.py` (Script 2 of 4)

**Purpose:** Apply 5 weighted signals to each content item and calculate lesson-assignment consensus.

**Signals:**
| Signal | Weight | Method |
|--------|--------|--------|
| Path Pattern | 1.0 | Regex extraction from file paths |
| Metadata Cross-Ref | 0.95 | Lookup against Source Inventory CSV |
| Semantic Alignment | 0.8 | Match AI-generated kb_tags to lesson keyword dictionary |
| Keyword Matching | 0.7 | Compare content themes to lesson objectives |
| Volume Consistency | 0.5 | Statistical pattern validation |

**Lesson Keyword Dictionary:**

| Lesson | Keywords |
|--------|----------|
| 1 | design brief, problem statement, audience, UAE heritage, cultural context |
| 2 | persona, empathy map, UX, player needs, motivations, user research |
| 3 | primary research, secondary research, AI research, bias, sources |
| 4 | design specification, team roles, constraints, success criteria |
| 5 | brainstorming, concept generation, micro-prototype, storyboard |
| 6 | prototype, core mechanic, debugging, testing, iteration |
| 7 | gameplay expansion, immersion, visuals, sound, dialogue |
| 8 | peer testing, WWW/EBI, feedback analysis, theme mapping |
| 9 | iteration, refinement, feedback implementation, impact vs effort |
| 10 | team roles, project manager, milestones, timeline, risk |
| 11 | documentation, portfolio, evidence, curation, reflection |
| 12 | reflection, evaluation, SMART goals, Term 3, progress |

**Output:** `Term 2 - Lesson Mappings.json`

### Script: `validation_anomalies.py` (Script 3 of 4)

**Purpose:** Detect issues in content-to-lesson mappings.

**Anomaly Types:**
| Type | Severity | Trigger |
|------|----------|---------|
| MISALIGNED | WARNING/ERROR | Consensus < 60% |
| MISSING | ERROR | Expected content not found for a lesson |
| DUPLICATE | WARNING | Same content mapped to unrelated lessons |
| ORPHANED | WARNING | No lesson assignment possible |
| VOLUME_OUTLIER | INFO | Image count >2x standard deviation |
| NAMING_INCONSISTENT | INFO | File naming pattern mismatch |

**Expected per lesson:** 1 teachers_slides + 1 students_slides + 1 lesson_plan (minimum)

**Output:** `Term 2 - Anomalies.json`

### Script: `validation_report.py` (Script 4 of 4)

**Purpose:** Generate human-readable validation report.

**Output:** `Term 2 - Validation Report.json` + `Term 2 - Validation Report.txt`

**Report Sections:**
1. Executive Summary (total items, overall confidence, status)
2. Per-Lesson Inventory (text + images + videos per lesson)
3. Cross-Validation Scores (teachers vs students, slides vs plans, etc.)
4. Anomaly List with severity
5. Confidence Distribution (High/Medium/Low buckets)
6. Success Criteria Checklist

---

## 11. Output Files Reference

### CSV Files (Root Directory)

| File | Size | Purpose |
|------|------|---------|
| `Term 2 - Lesson Based Structure.csv` | 55 KB | Authoritative lesson metadata (12 rows) |
| `Term 2 - Lesson Based Structure (Fixed).csv` | 792 KB | Enhanced with embedded image/video data |
| `Term 2 - Source Inventory.csv` | 4 KB | All 51 source files mapped to weeks/lessons |
| `Term 2 - Left Out Assets Report.csv` | 3 KB | 39 assets: 34 recovered, 5 not recovered (PDFs) |
| `Term 2 - Templates.csv` | 12 KB | Standardized lesson/activity templates |
| `Term 2 - Conversion Gap Analysis.csv` | 17 KB | Conversion quality metrics per file |

### JSON Files

| File | Location | Size | Purpose |
|------|----------|------|---------|
| `MASTER_all_results.json` | `Extracted Media/claude_descriptions/results/` | 536 KB | ALL 443 image descriptions + 3 transcripts |
| `extraction_metadata.json` | `Extracted Media/metadata/` | ~150 KB | Image extraction index with slide numbers |
| `video_transcripts.json` | `Extracted Media/metadata/` | ~65 KB | Combined video transcript metadata |
| `transcriptions.json` | `Extracted Media/audio/` | ~65 KB | Raw Whisper transcriptions |
| `batch_index.json` | `Extracted Media/claude_descriptions/` | 5 KB | Batch processing tracker |
| `Term 2 - Templates.json` | Root | 15 KB | Template data in JSON format |

### Markdown Files

| Location | Count | Content |
|----------|-------|---------|
| `Converted/Curriculum Content/Week */Teachers Slides/` | 12 | Teacher slide content per lesson |
| `Converted/Curriculum Content/Week */Students Slides/` | 12 | Student slide content per lesson |
| `Converted/Curriculum Content/Week */Lesson Plans/` | 12 | Lesson plan documents |
| `Converted/Assessment Guides/` | 10 | Assessment guide documents |
| `Converted/Student Portfolio/` | 1 | Portfolio activities deck |
| `Converted/Curriculum Alignment/` | 1 | Curriculum alignment document |
| Other | 13 | Exemplar work, LOs, visual versions |

---

## 12. Known Issues & Decisions

### Gemini API Failure
All Gemini Vision pipeline scripts (`vision_gemini_pipeline.py`, `gemini_retry.py`, `resume_gemini.py`, `run_gemini.py`) failed due to SDK compatibility issues. **Decision:** Used Claude Code agents exclusively for all image descriptions. These scripts are kept for reference but should not be relied upon.

### PDF Content Not Recovered
5 PDF files contain embedded images that were NOT extracted or described. **Decision:** User confirmed "PDFs are not important." The text content from PDFs was still converted to markdown via `convert_docs.py`.

### Old vs New Batch Files
Some batch files exist in two versions:
- `batch_lesson3.json` (old, metadata-only) vs `batch_lesson3_detailed.json` (new, full descriptions)
- `batch_lesson4.json` (old) vs `batch_lesson4_detailed.json` (new)

The consolidation script skips the old files. **Always use `_detailed` versions when both exist.**

### Duplicate Videos
`Designing_Restoring_Light.mp4` exists in both Week 2 and Week 3-6 folders (identical file). Only transcribed once.

### Naming Typo
Source files use "Exampler" (not "Exemplar") in filenames: `Exampler Work - Lesson 1-2.pptx`. This is preserved as-is in all paths and references.

### Image Filtering
During Claude Code agent analysis, images were filtered:
- Small icons (<5KB) were skipped
- Generic decorative backgrounds were skipped
- ~750 raw images were filtered down to 443 meaningful educational images

### Portfolio Content
The Activities & Portfolio Deck spans ALL 12 lessons. In validation, it's treated as a special case with `lessons: [1-12]`.

---

## 13. QA Test Suite

The `qa_test_suite/` directory contains a **separate system** for testing the deployed AI assistant's quality. It is NOT part of the content conversion pipeline.

**Purpose:** Simulate student conversations with the deployed chatbot API and assess response quality.

**Key Components:**
| File | Role |
|------|------|
| `run_qa.py` | Main orchestrator (3-agent pipeline) |
| `student_agent.py` | Agent 1: Simulates realistic student conversations |
| `transcript_assessor.py` | Agent 2: Evaluates conversation quality |
| `report_compiler.py` | Agent 3: Generates formatted Word reports |
| `personas.py` | Student persona definitions (confused_beginner, etc.) |
| `scenarios/` | 10+ test category modules |
| `config.py` | API endpoints, timeouts, paths |
| `api_client.py` | HTTP client for chatbot API |

**Test Categories:** term1_knowledge, term2_knowledge, cross_term_confusion, hallucination_probing, boundary_tests, system_prompt_protection, response_quality, extended_conversations, term_identification, pressure_tests

---

## 14. Environment & Dependencies

### Python Libraries

```
# Core conversion
python-docx          # DOCX parsing
python-pptx          # PPTX parsing
PyPDF2               # PDF text extraction
openpyxl             # XLSX parsing
Pillow               # Image handling

# Video processing
openai-whisper       # Speech-to-text
torch                # Whisper dependency

# Vision API (failed, kept for reference)
google-generativeai  # Gemini Vision API

# QA Test Suite
rich                 # Console formatting
httpx                # HTTP client (for QA suite)
python-docx          # Report generation

# Standard library (no install needed)
pathlib, json, csv, re, subprocess, zipfile, xml.etree.ElementTree
```

### External Tools

| Tool | Required For | Install |
|------|-------------|---------|
| `ffmpeg` | Video keyframe extraction | System install |
| `ffprobe` | Video metadata extraction | Bundled with ffmpeg |

### API Keys

| Key | Required For | Notes |
|-----|-------------|-------|
| `GOOGLE_API_KEY` | Gemini Vision (UNUSED) | Pipeline failed, not needed |
| Claude Code | Image analysis | Used via Claude Code Task agents (no separate key) |

---

## 15. Quick-Start Guide

### To reproduce the full pipeline from scratch:

```bash
# Prerequisites
pip install python-docx python-pptx PyPDF2 openpyxl Pillow openai-whisper torch

# Stage 1: Extract media from source files
python extract_media.py

# Stage 2: Convert documents to markdown
python convert_docs.py

# Stage 2b: Verify conversion quality (optional)
python verify_conversions.py

# Stage 3: Transcribe videos
python transcribe_videos.py

# Stage 4: Image descriptions
# This requires Claude Code with multimodal capability.
# Launch Task agents per lesson to read and describe images.
# See "Stage 4" section above for the agent prompt template.
# Results saved to: Extracted Media/claude_descriptions/results/batch_*.json

# Stage 5: Consolidate all results
# Run the inline consolidation script (see Stage 5 section)
# Then:
python merge_slide_metadata.py

# Stage 6: Build knowledge base
python compare_and_build_kb.py
python fix_csv_and_add_images.py

# Stage 7: Validate (scripts exist but not yet executed)
python validation_parser.py
python validation_mapper.py
python validation_anomalies.py
python validation_report.py
```

### To run just the QA test suite:

```bash
cd qa_test_suite
python run_qa.py --health-check        # Check API connectivity
python run_qa.py --list-categories      # See test categories
python run_qa.py --dry-run              # Test without API calls
python run_qa.py                        # Full pipeline
```

---

## Appendix: Content Statistics

| Metric | Value |
|--------|-------|
| Total source files | 51 |
| Total converted markdown files | 61 |
| Total images extracted from PPTX | ~750 |
| Total images after filtering | 443 |
| Total video keyframes | 72 |
| Total video transcripts | 3 |
| Curriculum image descriptions | 308 |
| Exemplar image descriptions | 32 |
| Portfolio image descriptions | 31 |
| Video keyframe descriptions | 72 |
| Lessons with full coverage | 12/12 |
| Weeks with full coverage | 6/6 |
| PDF images NOT recovered | 5 files |
| Overall recovery rate | ~87% |
