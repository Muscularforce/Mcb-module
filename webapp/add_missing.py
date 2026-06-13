import requests
import datetime

API = "http://localhost:8000/api/entries"
today = datetime.date.today().isoformat()
yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()

# Check existing
existing = requests.get(API).json()
existing_subjects = set((e['entry_type'], e['subject']) for e in existing)

entries_to_add = [
    # More diary entries
    {
        "entry_type": "DiaryEntry",
        "subject": "English Literature",
        "teacher": "Ms. Charlotte",
        "date": yesterday,
        "summary": "Read Chapter 5 of 'To Kill a Mockingbird'. Write a 200-word character analysis of Scout Finch.",
        "attachment_url": None
    },
    {
        "entry_type": "DiaryEntry",
        "subject": "History",
        "teacher": "Mr. Gupta",
        "date": yesterday,
        "summary": "Revise the French Revolution timeline. There will be a surprise quiz next class.",
        "attachment_url": None
    },
    # More announcements
    {
        "entry_type": "Announcement",
        "subject": "Annual Sports Day",
        "teacher": "Coach Williams",
        "date": yesterday,
        "summary": "Annual Sports Day is on June 20th. All students must register for at least one event by June 15th. Track suits are mandatory.",
        "attachment_url": None
    },
    {
        "entry_type": "Announcement",
        "subject": "Science Exhibition",
        "teacher": "Dr. Feynman",
        "date": today,
        "summary": "The Inter-School Science Exhibition will be held on June 25th. Teams of 3 can register with their class teacher. Exciting prizes await!",
        "attachment_url": None
    },
]

added = 0
for entry in entries_to_add:
    key = (entry['entry_type'], entry['subject'])
    if key not in existing_subjects:
        r = requests.post(API, json=entry)
        print(f"Added [{entry['entry_type']}] {entry['subject']} -> {r.status_code}")
        added += 1
    else:
        print(f"Skipped [{entry['entry_type']}] {entry['subject']} (already exists)")

print(f"\nDone! Added {added} new entries.")

# Final summary
final = requests.get(API).json()
diaries = [e for e in final if e['entry_type'] == 'DiaryEntry']
worksheets = [e for e in final if e['entry_type'] == 'Worksheet']
announcements = [e for e in final if e['entry_type'] == 'Announcement']
print(f"\nFinal counts: {len(diaries)} Diary | {len(worksheets)} Worksheets | {len(announcements)} Announcements | Total: {len(final)}")
