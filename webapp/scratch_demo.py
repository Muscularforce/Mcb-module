import sys
import os
import requests
import datetime
from dotenv import load_dotenv

# Load env before importing main
env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env'))
load_dotenv(dotenv_path=env_path)

# Setup path to import main from mcb-to-notion-sync
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'mcb-to-notion-sync')))

try:
    from main import send_discord_message, send_discord_date_separator
    discord_available = True
except ImportError as e:
    print(f"Could not import discord logic: {e}")
    discord_available = False

date_str_discord = datetime.datetime.now().strftime("%d %b %Y")
date_str_api = datetime.datetime.now().strftime("%Y-%m-%d")

# 1. Send the ASCII date separator to Discord
if discord_available:
    send_discord_date_separator(date_str_discord)

# 2. Define some rich demo worksheets with attachment URLs
demo_entries = [
    {
        "subject": "Advanced Mathematics",
        "type": "worksheet",
        "teacher": "Mr. Euler",
        "summary": "This worksheet covers integration by parts and differential equations. Please submit by Friday.",
        "attachment_name": "Calculus_Practice.pdf",
        "attachment_url": "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
        "diary_id": 101,
        "subject_id": 201,
        "unique_key": "dummy1",
        "date": date_str_discord
    },
    {
        "subject": "Physics",
        "type": "worksheet",
        "teacher": "Dr. Feynman",
        "summary": "Quantum mechanics intro worksheet. Review the wave function collapse theory before attempting.",
        "attachment_name": "Quantum_Worksheet_1.pdf",
        "attachment_url": "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
        "diary_id": 102,
        "subject_id": 202,
        "unique_key": "dummy2",
        "date": date_str_discord
    },
    {
        "subject": "School Administration",
        "type": "announcement",
        "teacher": "Principal Smith",
        "summary": "Reminder: The school will be closed this Friday for a teacher training day. Enjoy the long weekend!",
        "attachment_name": "Holiday_Schedule.pdf",
        "attachment_url": "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
        "diary_id": 103,
        "subject_id": 203,
        "unique_key": "dummy3",
        "date": date_str_discord
    }
]

# Send to Discord
if discord_available:
    for entry in demo_entries:
        send_discord_message(entry=entry)
        print(f"Sent {entry['subject']} to Discord.")

# 3. Post to the FastAPI backend so they appear on the web UI
demo_entries_api = [
    {
        "entry_type": "Worksheet",
        "subject": "Advanced Mathematics",
        "teacher": "Mr. Euler",
        "date": date_str_api,
        "summary": "This worksheet covers integration by parts and differential equations. Please submit by Friday.",
        "attachment_url": "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
    },
    {
        "entry_type": "Worksheet",
        "subject": "Physics",
        "teacher": "Dr. Feynman",
        "date": date_str_api,
        "summary": "Quantum mechanics intro worksheet. Review the wave function collapse theory before attempting.",
        "attachment_url": "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
    },
    {
        "entry_type": "Announcement",
        "subject": "School Administration",
        "teacher": "Principal Smith",
        "date": date_str_api,
        "summary": "Reminder: The school will be closed this Friday for a teacher training day. Enjoy the long weekend!",
        "attachment_url": "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
    }
]

for entry in demo_entries_api:
    try:
        r = requests.post("http://localhost:8000/api/entries", json=entry)
        print(f"API Response for {entry['subject']}: {r.status_code}")
    except Exception as e:
        print("API failed (Make sure the FastAPI server is running):", e)

print("Finished demo script!")
