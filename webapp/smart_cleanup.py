"""
Smart AI-like cleanup of the MCB database.
Uses pattern matching and heuristics to fix titles, remove junk, and deduplicate.
"""
import re
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
from database import SessionLocal
from models import Entry

db = SessionLocal()

all_entries = db.query(Entry).order_by(Entry.id).all()
print(f"Starting with {len(all_entries)} entries\n")

# ============================================================
#  STEP 1: DELETE JUNK ENTRIES
#  - Student name header cards
#  - Entries with no real content
# ============================================================
print("--- STEP 1: Removing junk entries ---")
junk_ids = []
for e in all_entries:
    subj = (e.subject or "").strip()
    summ = (e.summary or "").strip()

    # Student name header cards (e.g. "JOVAN FRANCIS FERNANDES 23RIS0154 . Class X - A")
    if "JOVAN" in subj.upper() and "FERNANDES" in subj.upper():
        junk_ids.append(e.id)
        print(f"  JUNK [id={e.id}] [{e.entry_type}] '{subj}' -- student name header")
        continue

    # Same pattern in summary
    if re.search(r"23RIS\d+.*Class\s+X", summ, re.I) and len(summ) < 80:
        junk_ids.append(e.id)
        print(f"  JUNK [id={e.id}] [{e.entry_type}] '{subj}' -- student info card")
        continue

    # Empty or near-empty entries
    if len(summ) < 15 and not e.attachment_url:
        junk_ids.append(e.id)
        print(f"  JUNK [id={e.id}] [{e.entry_type}] '{subj}' -- too short")
        continue

if junk_ids:
    db.query(Entry).filter(Entry.id.in_(junk_ids)).delete(synchronize_session=False)
    db.commit()
    print(f"  Removed {len(junk_ids)} junk entries\n")
else:
    print("  No junk found\n")


# ============================================================
#  STEP 2: FIX WORKSHEET TITLES (single-letter subjects)
#  Extract real subject from summary text
# ============================================================
print("--- STEP 2: Fixing worksheet subjects ---")
worksheets = db.query(Entry).filter(Entry.entry_type == "Worksheet").all()
fixed_ws = 0

for ws in worksheets:
    subj = (ws.subject or "").strip()
    summ = (ws.summary or "").strip()

    needs_fix = len(subj) <= 2 or subj in ["Teacher", "System"]

    if not needs_fix:
        continue

    # The summary typically looks like:
    # "M Math Revision Sheet Answerkey Maths Sat ,06 Jun 2026 Submission due date..."
    # "S Science-06 Jun 2026 Home Assignment Science Sat ,06 Jun 2026..."
    # "E English-06 Jun 2026 Home Assignment English Sat ,06 Jun 2026..."
    # "G GRADE X IT PA-I RS Answer Key IT Tue ,02 Jun 2026..."
    # "R Revision worksheet -01 Answer Key Hindi Tue ,02 Jun 2026..."
    # "I IT PA-I RS Answer Key IT ..."
    # "H Hindi ..."
    # "W Work Sheet ..."

    new_subject = None

    # Strategy 1: Look for known subject names anywhere in the summary
    subject_keywords = [
        (r"\bMath(?:ematics|s)?\b", "Mathematics"),
        (r"\bPhysics\b", "Physics"),
        (r"\bChemistry\b", "Chemistry"),
        (r"\bBiology\b", "Biology"),
        (r"\bEnglish\b", "English"),
        (r"\bHindi\b", "Hindi"),
        (r"\bSanskrit\b", "Sanskrit"),
        (r"\bKannada\b", "Kannada"),
        (r"\bSocial\s*Stud(?:ies|y)\b", "Social Studies"),
        (r"\bScience\b", "Science"),
        (r"\b(?:IT|Information\s*Technology)\b", "IT"),
        (r"\bComputer\b", "Computer Science"),
        (r"\bGeneral\s*Knowledge\b", "General Knowledge"),
        (r"\bGK\b", "General Knowledge"),
        (r"\bArt\b", "Art"),
        (r"\bMusic\b", "Music"),
        (r"\bPE\b|Physical\s*Education", "Physical Education"),
        (r"\bEconomics\b", "Economics"),
        (r"\bGeography\b", "Geography"),
        (r"\bHistory\b", "History"),
        (r"\bCivics\b", "Civics"),
        (r"\bPolitical\s*Science\b", "Political Science"),
    ]

    for pattern, name in subject_keywords:
        # Skip if the match is just the single-letter prefix
        match = re.search(pattern, summ, re.I)
        if match and match.start() > 0:  # found after the first char
            new_subject = name
            break
        elif match and match.start() == 0:
            new_subject = name
            break

    # Strategy 2: If summary starts with "X SubjectName-Date..." pattern
    if not new_subject:
        m = re.match(r"^[A-Z]\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", summ)
        if m:
            candidate = m.group(1).strip()
            if len(candidate) >= 3:
                new_subject = candidate

    # Strategy 3: Look for "Home Assignment SUBJECT" pattern
    if not new_subject:
        m = re.search(r"Home\s+Assignment\s+([A-Za-z\s]+?)(?:\s+\w{3}\s*,)", summ, re.I)
        if m:
            new_subject = m.group(1).strip()

    # Strategy 4: Look for "Answer Key SUBJECT" pattern
    if not new_subject:
        m = re.search(r"Answer\s+Key\s+([A-Za-z\s]+?)(?:\s+\w{3}\s*,)", summ, re.I)
        if m:
            new_subject = m.group(1).strip()

    if new_subject:
        old = ws.subject
        ws.subject = new_subject
        fixed_ws += 1
        print(f"  FIXED [id={ws.id}] '{old}' -> '{new_subject}'")
    else:
        print(f"  SKIP  [id={ws.id}] '{subj}' -- could not determine subject from: {summ[:60]}")

db.commit()
print(f"  Fixed {fixed_ws} worksheet subjects\n")


# ============================================================
#  STEP 3: FIX ANNOUNCEMENT TITLES
#  Extract real title from summary when subject is generic
# ============================================================
print("--- STEP 3: Fixing announcement titles ---")
announcements = db.query(Entry).filter(Entry.entry_type == "Announcement").all()
fixed_ann = 0

for ann in announcements:
    subj = (ann.subject or "").strip()
    summ = (ann.summary or "").strip()

    needs_fix = subj.lower() in ["announcement", "system", "teacher", ""] or subj.startswith("Dear ")

    if not needs_fix:
        continue

    new_title = None

    # Pattern: "TITLE IN CAPS Dear Parents, ..." or "TITLE IN CAPS GR.X Dear Parents..."
    m = re.match(r"^([A-Z][A-Z\s\-\.&,/]+?)(?:\s+(?:GR|GRADE|CLASS)[\.\s].*?)?(?:\s+Dear\s+)", summ)
    if m:
        raw = m.group(1).strip().rstrip(",.-")
        if len(raw) >= 5:
            # Title case it
            new_title = raw.title()

    # Pattern: "TITLE Dear Students..."
    if not new_title:
        m = re.match(r"^([A-Z][A-Z\s\-\.&,/]+?)(?:\s+Dear\s+)", summ)
        if m:
            raw = m.group(1).strip().rstrip(",.-")
            if len(raw) >= 5:
                new_title = raw.title()

    # Pattern: just take first sentence if it looks like a title
    if not new_title:
        first_sentence = re.split(r"[.!]\s", summ)[0]
        if len(first_sentence) < 80 and len(first_sentence) >= 10:
            new_title = first_sentence.strip()

    if new_title:
        # Clean up
        new_title = re.sub(r"\s+", " ", new_title).strip()
        if len(new_title) > 60:
            new_title = new_title[:57] + "..."

        old = ann.subject
        ann.subject = new_title
        fixed_ann += 1
        print(f"  FIXED [id={ann.id}] '{old}' -> '{new_title}'")
    else:
        print(f"  SKIP  [id={ann.id}] '{subj}' -- could not extract title from: {summ[:60]}")

db.commit()
print(f"  Fixed {fixed_ann} announcement titles\n")


# ============================================================
#  STEP 4: FIX TEACHER NAMES
#  Replace generic "Teacher" / "System" with extracted names
# ============================================================
print("--- STEP 4: Fixing teacher names ---")
fixed_teachers = 0
remaining = db.query(Entry).all()
for e in remaining:
    teacher = (e.teacher or "").strip()
    summ = (e.summary or "").strip()

    if teacher not in ["Teacher", "System", ""]:
        continue

    # Try to find "Regards, NAME" or "By: NAME" patterns
    m = re.search(r"Regards,?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)", summ)
    if m:
        e.teacher = m.group(1).strip()
        fixed_teachers += 1
        continue

    # For announcements from admin, set a sensible default
    if e.entry_type == "Announcement" and teacher in ["System", ""]:
        e.teacher = "School Admin"
        fixed_teachers += 1

db.commit()
print(f"  Fixed {fixed_teachers} teacher names\n")


# ============================================================
#  STEP 5: REMOVE DUPLICATES
#  Keep only the first occurrence of each unique entry
# ============================================================
print("--- STEP 5: Removing duplicates ---")
remaining = db.query(Entry).order_by(Entry.id).all()
seen = set()
dup_ids = []
for e in remaining:
    # Create a fingerprint from type + first 80 chars of summary
    key = (e.entry_type, (e.summary or "")[:80])
    if key in seen:
        dup_ids.append(e.id)
    else:
        seen.add(key)

if dup_ids:
    db.query(Entry).filter(Entry.id.in_(dup_ids)).delete(synchronize_session=False)
    db.commit()
    print(f"  Removed {len(dup_ids)} duplicates\n")
else:
    print("  No duplicates found\n")


# ============================================================
#  FINAL SUMMARY
# ============================================================
final = db.query(Entry).order_by(Entry.id).all()
print("=" * 60)
print(f"  CLEANUP COMPLETE - {len(final)} entries remaining")
print("=" * 60)

for etype in ['DiaryEntry', 'Worksheet', 'Announcement']:
    subset = [e for e in final if e.entry_type == etype]
    print(f"\n  {etype} ({len(subset)}):")
    for e in subset:
        att = " [FILE]" if e.attachment_url else ""
        print(f"    [{e.subject}] by {e.teacher} | {e.date}{att}")

db.close()
