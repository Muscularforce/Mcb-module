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
#  STEP 2: FIX WORKSHEET TITLES
#  Extract specific worksheet title from summary text
# ============================================================
def extract_worksheet_title(summary: str) -> str:
    summary = summary.strip()
    # Remove leading uppercase letter followed by space
    title = re.sub(r"^[A-Z]\s+", "", summary)
    
    # Split at weekday name followed by space and comma, or just comma (e.g. Sat ,)
    match = re.search(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s*,", title, re.IGNORECASE)
    if match:
        title = title[:match.start()].strip()
    else:
        # Fallback split at date (like 06 Jun 2026)
        match_date = re.search(r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b", title, re.IGNORECASE)
        if match_date:
            title = title[:match_date.start()].strip()
            
    # Remove any trailing "Expired" keyword if it gets caught
    title = re.sub(r"\bExpired\b\s*$", "", title, flags=re.IGNORECASE).strip()
    
    # List of subjects to strip from the end of the worksheet title
    subjects = [
        "Mathematics", "Maths", "Math", "Science", "English", "Social Studies", "Social Study", "Social",
        "Information Technology", "IT", "Hindi", "Sanskrit", "Kannada", "Computer Science", "Computer",
        "General Knowledge", "GK", "Art", "Music", "Physical Education", "PE", "Physics", "Chemistry", "Biology"
    ]
    
    # Build a regex matching any of these subjects at the end of the string
    subject_pattern = r"[\s\-\,]+(?:" + "|".join(re.escape(s) for s in subjects) + r")\s*$"
    
    # Double pass to clean trailing subject repetitions
    title = re.sub(subject_pattern, "", title, flags=re.IGNORECASE).strip()
    title = re.sub(subject_pattern, "", title, flags=re.IGNORECASE).strip()
    
    # Remove trailing hyphens or commas
    title = re.sub(r"[\-\,\s]+$", "", title).strip()
    
    # Normalize spaces
    title = re.sub(r"\s+", " ", title)
    return title

print("--- STEP 2: Fixing worksheet titles ---")
worksheets = db.query(Entry).filter(Entry.entry_type == "Worksheet").all()
fixed_ws = 0

for ws in worksheets:
    summ = (ws.summary or "").strip()
    if not summ:
        continue

    new_title = extract_worksheet_title(summ)
    if new_title and new_title != ws.subject:
        old = ws.subject
        ws.subject = new_title
        fixed_ws += 1
        print(f"  FIXED [id={ws.id}] '{old}' -> '{new_title}'")

db.commit()
print(f"  Fixed {fixed_ws} worksheet titles\n")


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
