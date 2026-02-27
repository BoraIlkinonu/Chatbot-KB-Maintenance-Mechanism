# Guide for Content Contributors

This is for team members who create or edit lesson content in Google Drive. It explains how the automated pipeline works and what to be aware of when making changes.

## How the Pipeline Works

- Every night, an automated system scans the Google Drive source folders (Term 1, Term 2, Term 3) for any changes
- It downloads new or modified files, extracts all text, images, tables, links, and speaker notes from slide decks, lesson plans, and documents
- The extracted content is organized by term and lesson number, then built into structured Knowledge Base (KB) JSON files
- These KB files power the Endstar AI Assistant chatbot, which uses them to answer teacher and student questions
- The system sends Slack notifications when changes are detected, when errors occur, or when new images need review

## What You Need to Know

### File Naming Matters
- Lesson files **must** include the lesson number in the filename (e.g., "Lesson 7.pptx", "Lesson 12.docx")
- The pipeline uses the number in the filename to assign content to the correct lesson in the KB
- If a file is named ambiguously (e.g., "Final Version.pptx" with no lesson number), the pipeline cannot assign it to a lesson and the content will be missed

### Folder Structure Matters
- Keep lesson files inside their correct Week folder (e.g., `Week 3/Lesson 5.pptx`)
- Moving a file to a different folder causes the pipeline to treat it as deleted from the old location and new in the new location -- this triggers a full re-download and rebuild for that file
- Do **not** reorganize or rename folders without notifying the pipeline admin, as it can cause the system to lose track of files

### Things That Can Break the Pipeline
- **Renaming the top-level folders** (e.g., "Teacher Resources", "Curriculum Content") will cause the pipeline to lose track of all files inside them
- **Deleting a file** removes its content from the KB on the next run -- make sure deletions are intentional
- **Duplicating a file** with the same lesson number in the same folder will cause conflicts -- the pipeline may pick one arbitrarily
- **Google Shortcuts** (links to files in other folders) are skipped -- if you want a file included, place the actual file in the folder, not a shortcut

### Slide Decks (PPTX / Google Slides)
- All text on every slide is extracted, including text inside grouped shapes, tables, and text boxes
- **Speaker notes** are extracted and included in the KB -- treat them as public content
- Images are tracked (counted and referenced) but their visual content is not described automatically
- Very large Google Slides files (over 10MB) are exported via a separate process -- they still get fully extracted
- If you embed a video link on a slide, it will be captured in the KB

### Lesson Plans (DOCX / Google Docs)
- Section headings (Big Question, Learning Objectives, Activities, etc.) are used to structure the KB
- Maintain consistent heading styles (Heading 2 for lesson titles, Heading 3 for sections) so the parser can identify them correctly
- Free-form text without headings may end up in a catch-all "remaining content" section

### What Happens After You Make Changes
1. The nightly pipeline detects your changes within 24 hours
2. Changed files are re-downloaded and re-processed
3. The KB is rebuilt for the affected term
4. Automated quality checks run (190+ checks) to verify extraction completeness
5. If issues are found, the admin receives a Slack notification
6. No manual action is needed from you unless the admin follows up

### Support Files (Assessment Guides, Design Briefs, etc.)
- These are tracked but categorized separately from lesson content
- They feed into a "Templates KB" used for assessment and rubric queries
- Changes to these files do not affect lesson-specific KB content

### Videos and Media Files
- MP4/MOV files are tracked in the file manifest but their content is not transcribed
- If a video is referenced on a slide, the reference text is captured, but the video file itself is not linked to that specific slide (yet)
- Keep video files in clearly named folders (e.g., "Lesson supporting videos")
