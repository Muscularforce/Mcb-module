import requests
r = requests.get('http://localhost:8000/api/entries')
data = r.json()
print(f"Total entries from backend: {len(data)}")
print()

worksheets = [e for e in data if e['entry_type'] == 'Worksheet']
announcements = [e for e in data if e['entry_type'] == 'Announcement']
diaries = [e for e in data if e['entry_type'] == 'DiaryEntry']

print(f"=== Diary Entries: {len(diaries)} ===")
for e in diaries:
    att = "YES" if e.get('attachment_url') else "NO"
    print(f"  [{e['subject']}] teacher={e.get('teacher','N/A')} date={e.get('date')} attachment={att}")

print(f"\n=== Worksheets: {len(worksheets)} ===")
for e in worksheets:
    att = "YES" if e.get('attachment_url') else "NO"
    print(f"  [{e['subject']}] teacher={e.get('teacher','N/A')} date={e.get('date')} attachment={att}")

print(f"\n=== Announcements: {len(announcements)} ===")
for e in announcements:
    att = "YES" if e.get('attachment_url') else "NO"
    print(f"  [{e['subject']}] teacher={e.get('teacher','N/A')} date={e.get('date')} attachment={att}")
