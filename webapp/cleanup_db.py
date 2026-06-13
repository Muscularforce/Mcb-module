"""
Clean up the database:
1. Remove old demo/seed entries (ids 1-11)
2. Remove duplicates from second import run (ids 65+)
3. Fix worksheet subjects that are single letters by extracting from summary
"""
import requests
import re

API = "http://localhost:8000/api/entries"

# Get all entries
data = requests.get(API).json()
print(f"Current total: {len(data)} entries")

# We need direct DB access to delete and update. Let's use SQLAlchemy directly.
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
from database import SessionLocal
from models import Entry

db = SessionLocal()

# Step 1: Delete old demo/seed data (entries with id <= 11)
demo_ids = list(range(1, 12))
deleted_demo = db.query(Entry).filter(Entry.id.in_(demo_ids)).delete(synchronize_session=False)
print(f"Removed {deleted_demo} old demo entries")

# Step 2: Remove duplicate entries (keep the first occurrence of each unique summary)
all_entries = db.query(Entry).order_by(Entry.id).all()
seen = set()
dup_ids = []
for e in all_entries:
    key = (e.entry_type, e.subject, e.summary[:80] if e.summary else "")
    if key in seen:
        dup_ids.append(e.id)
    else:
        seen.add(key)

if dup_ids:
    deleted_dups = db.query(Entry).filter(Entry.id.in_(dup_ids)).delete(synchronize_session=False)
    print(f"Removed {deleted_dups} duplicate entries")

# Step 3: Fix worksheet subjects that are single letters
worksheets = db.query(Entry).filter(Entry.entry_type == "Worksheet").all()
subject_map = {
    "M": None, "S": None, "E": None, "G": None, "R": None,
    "I": None, "H": None, "W": None, "P": None,
}
fixed = 0
for ws in worksheets:
    if len(ws.subject.strip()) <= 2 and ws.summary:
        # Try to extract real subject from summary
        # Pattern: "M Math PA I Revision Sheet Maths Wed ,03 Jun 2026"
        # or "S Science-06 Jun 2026 Home Assignment Science"
        summary = ws.summary.strip()
        
        # Try: first word after the single letter is the subject
        # e.g. "M Math Revision Sheet..." -> "Math"
        # e.g. "S Science-06 Jun 2026..." -> "Science" 
        # e.g. "E English-06 Jun 2026..." -> "English"
        # e.g. "G GRADE X IT PA-I..." -> "IT"
        # e.g. "R Revision worksheet..." -> extract from later
        
        # Remove the leading single letter
        rest = summary[1:].strip()
        
        # Common subject patterns
        subject_patterns = [
            (r"^(Math|Maths|Mathematics)\b", "Mathematics"),
            (r"^(Science)\b", "Science"),
            (r"^(English)\b", "English"),
            (r"^(Hindi)\b", "Hindi"),
            (r"^(Social Studies|Social)\b", "Social Studies"),
            (r"^(IT|Information Technology)\b", "IT"),
            (r"^(GRADE\s+\w+\s+)(IT)\b", "IT"),
            (r"^(Physics)\b", "Physics"),
            (r"^(Chemistry)\b", "Chemistry"),
            (r"^(Biology)\b", "Biology"),
            (r"^(Sanskrit)\b", "Sanskrit"),
            (r"^(Kannada)\b", "Kannada"),
            (r"^(Revision worksheet.*)(Hindi)\b", "Hindi"),
            (r"^(Work Sheet.*)(Hindi)\b", "Hindi"),
        ]
        
        matched = False
        for pattern, subj_name in subject_patterns:
            if re.search(pattern, rest, re.I):
                ws.subject = subj_name
                fixed += 1
                matched = True
                break
        
        if not matched:
            # Fallback: use first real word (skip single chars)
            words = rest.split()
            for w in words:
                clean_w = re.sub(r'[^a-zA-Z]', '', w)
                if len(clean_w) >= 3:
                    ws.subject = clean_w.capitalize()
                    fixed += 1
                    break

# Also fix "JOVAN FRANCIS FERNANDES" subjects - these are header cards, not real entries
jovan_entries = db.query(Entry).filter(Entry.subject == "JOVAN FRANCIS FERNANDES").all()
if jovan_entries:
    for je in jovan_entries:
        db.delete(je)
    print(f"Removed {len(jovan_entries)} header entries (student name cards)")

# Fix announcement subjects like "Dear Parents,"
dear_parents = db.query(Entry).filter(Entry.subject.like("Dear Parents%")).all()
for dp in dear_parents:
    # Extract real title from summary
    summary = dp.summary or ""
    # Pattern: "BLOOD DONATION DRIVE CIRCULAR GR.NUR-XII Dear Parents..."
    # or "SCHOOL RE-OPENING GR.I-X Dear Parents..."
    parts = summary.split("Dear Parents")
    if parts[0].strip():
        dp.subject = parts[0].strip()[:60]

db.commit()

# Final count
remaining = db.query(Entry).count()
print(f"\nFixed {fixed} worksheet subject names")
print(f"Final total: {remaining} entries")

# Show final breakdown
for etype in ['DiaryEntry', 'Worksheet', 'Announcement']:
    count = db.query(Entry).filter(Entry.entry_type == etype).count()
    print(f"  {etype}: {count}")

db.close()
