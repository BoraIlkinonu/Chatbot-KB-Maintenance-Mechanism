# Table Classification Prompt

You are classifying a table extracted from educational teaching materials. Determine what type of table this is based on its headers and content.

## Categories

1. **rubric** — Assessment rubrics, grading criteria, scoring matrices. Look for:
   - Headers containing: criterion, criteria, assessment, marks, score, grade, grading, proficient, emerging, exceeding, level, performance, competency, mastery, beginning, developing, portfolio, reflection, self-assessment, peer-assessment
   - Rows describing performance levels or scoring bands

2. **schedule** — Timelines, calendars, planning schedules. Look for:
   - Headers containing: week, date, deadline, milestone, schedule, timeline, session, day, period, term, semester, calendar
   - Rows with dates, week numbers, or temporal sequences

3. **data** — All other tables (content tables, reference data, activity instructions, etc.)

## Table Content

Headers: {headers}

First rows:
{rows}

## Required JSON Output

Respond with ONLY a JSON object — no explanation, no markdown fences:

{
  "classification": "rubric"
}

The classification must be exactly one of: "rubric", "schedule", "data"
