import os
import re
import sys
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://rainbow.myclassboard.com"
LOGIN_URL = f"{BASE_URL}/Account/Login"
DIARY_URL = f"{BASE_URL}/StudentERP/StaffDiaryToStudent_CalendarView"

# Change this date whenever needed.
# Example: "17 Mar 2026" or "18 Mar 2026"
DIARY_DATE = "17 Mar 2026"

USERNAME = os.getenv("MCB_USERNAME", "").strip()
PASSWORD = os.getenv("MCB_PASSWORD", "").strip()

if not USERNAME or not PASSWORD:
    print("Missing MCB_USERNAME or MCB_PASSWORD in .env")
    sys.exit(1)


def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text


def pick_input_name(inputs, kinds):
    for inp in inputs:
        name = (inp.get("name") or "").strip()
        itype = (inp.get("type") or "").strip().lower()
        if itype in kinds and name:
            return name
    return None


def login(session: requests.Session) -> None:
    page = session.get(LOGIN_URL, timeout=30)
    page.raise_for_status()

    soup = BeautifulSoup(page.text, "html.parser")
    form = soup.find("form")
    if form is None:
        raise RuntimeError("Login form not found.")

    action = form.get("action") or LOGIN_URL
    if action.startswith("/"):
        action = BASE_URL + action

    inputs = form.find_all("input")

    hidden_data = {}
    for inp in inputs:
        name = inp.get("name")
        value = inp.get("value", "")
        if name and (inp.get("type") or "").lower() == "hidden":
            hidden_data[name] = value

    username_name = pick_input_name(inputs, {"text", "email"})
    password_name = pick_input_name(inputs, {"password"})

    if not username_name or not password_name:
        raise RuntimeError("Could not detect username/password field names on the login page.")

    payload = dict(hidden_data)
    payload[username_name] = USERNAME
    payload[password_name] = PASSWORD

    resp = session.post(action, data=payload, timeout=30, allow_redirects=True)
    resp.raise_for_status()

    print("Logged in")


def fetch_diary_html(session: requests.Session, diary_date: str) -> str:
    payload = {"DiaryDate": diary_date}
    resp = session.post(DIARY_URL, data=payload, timeout=30)
    resp.raise_for_status()
    print("Request sent")
    return resp.text


def parse_diary(html: str):
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.card")

    results = []

    for card in cards:
        badge = card.select_one("span.badge")
        summary = card.select_one("div.summery-class")
        if not badge or not summary:
            continue

        badge_text = clean_text(badge.get_text(" ", strip=True))
        summary_text = clean_text(summary.get_text(" ", strip=True))

        subject_tag = card.find_previous("h6")
        subject = "Unknown"
        if subject_tag:
            subject = clean_text(subject_tag.get_text(" ", strip=True))

        teacher = "Unknown"
        teacher_tag = card.select_one("span[style*='darkgray']")
        if teacher_tag:
            teacher = clean_text(teacher_tag.get_text(" ", strip=True))

        attachments = []
        for a in card.find_all("a"):
            href = a.get("href", "")
            text = clean_text(a.get_text(" ", strip=True))
            if href or text:
                attachments.append(text if text else href)

        results.append(
            {
                "subject": subject,
                "type": badge_text,
                "teacher": teacher,
                "text": summary_text,
                "attachments": attachments,
            }
        )

    return results


def main():
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36"
            )
        }
    )

    login(session)

    html = fetch_diary_html(session, DIARY_DATE)
    entries = parse_diary(html)

    if not entries:
        print(f"No reminders/classwork/homework found for {DIARY_DATE}.")
        return

    for i, entry in enumerate(entries, start=1):
        print("\n" + "=" * 40)
        print(f"{i}. Subject: {entry['subject']}")
        print(f"Type: {entry['type']}")
        print(f"Teacher: {entry['teacher']}")
        print(f"Text: {entry['text']}")
        if entry["attachments"]:
            print("Attachments:")
            for item in entry["attachments"]:
                print(f" - {item}")


if __name__ == "__main__":
    main()
