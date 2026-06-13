import requests, json

r = requests.get('http://localhost:8000/api/entries')
data = r.json()
print(f"Total entries in DB: {len(data)}")

for etype in ['DiaryEntry', 'Worksheet', 'Announcement']:
    subset = [e for e in data if e['entry_type'] == etype]
    print(f"\n=== {etype} ({len(subset)}) ===")
    for e in subset[:15]:
        subj = e['subject'][:40]
        summ = e['summary'][:60] if e.get('summary') else ''
        att = 'YES' if e.get('attachment_url') else 'NO'
        print(f"  id={e['id']} [{subj}] att={att} | {summ}")
