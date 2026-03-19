import os
import re
from datetime import datetime
from bs4 import BeautifulSoup
from notion_client import Client
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

PORTAL_URL = "https://rainbow.myclassboard.com"
DIARY_URL = "https://rainbow.myclassboard.com/StudentERP/StaffDiaryToStudent_CalenderView_AllActivities"

NOTION_TOKEN = os.environ["NOTION_TOKEN"]
NOTION_DATABASE_ID = os.environ["NOTION_DATABASE_ID"]
MCB_USERNAME = os.environ["MCB_USERNAME"]
MCB_PASSWORD = os.environ["MCB_PASSWORD"]

notion = Client(auth=NOTION_TOKEN)


def today_diary_date():
    return datetime.now().strftime("%d %b %Y")


def try_fill_first_matching(locator_list, value):
    for loc in locator_list:
        try:
            if loc.count() > 0:
                loc.first.fill(value)
                return True
        except Exception:
            pass
    return False


def login_and_fetch_html(diary_date: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.goto(PORTAL_URL, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")

        # Try a few common login selectors
        username_candidates = [
            page.locator("input[type='text']"),
            page.locator("input[type='email']"),
            page.locator("input[name*='user' i]"),
            page.locator("input[id*='user' i]"),
            page.locator("input[id*='login' i]"),
        ]

        password_candidates = [
            page.locator("input[type='password']"),
            page.locator("input[name*='pass' i]"),
            page.locator("input[id*='pass' i]"),
        ]

        filled_user = try_fill_first_matching(username_candidates, MCB_USERNAME)
        filled_pass = try_fill_first_matching(password_candidates, MCB_PASSWORD)

        if not filled_user or not filled_pass:
            page.screenshot(path="login_debug.png", full_page=True)
            browser.close()
            raise RuntimeError("Could not find login fields. Check login_debug.png in the GitHub Actions artifact/logs.")

        submit_buttons = page.locator("button, input[type='submit']")
        if submit_buttons.count() > 0:
            submit_buttons.first.click()
        else:
            page.keyboard.press("Enter")

        try:
            page.wait_for_load_state("networkidle", timeout=60000)
        except PlaywrightTimeoutError:
            pass

        html = page.evaluate(
            """
            async ({url, diaryDate}) => {
                const res = await fetch(url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: new URLSearchParams({ DiaryDate: diaryDate }).toString()
                });
                return await res.text();
            }
            """,
            {"url": DIARY_URL, "diaryDate": diary_date},
        )

        browser.close()
        return html


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def extract_entries(html: str, diary_date: str):
    soup = BeautifulSoup(html, "html.parser")
    page_text = clean_text(soup.get_text(" ", strip=True))

    if "No diary entries are found!" in page_text:
        return []

    entries = []
    current_subject = None

    # Walk through cards in order
    for node in soup.find_all(["h6", "div"]):
        if node.name == "h6":
            subject_span = node.find("span")
            if subject_span:
                current_subject = clean_text(subject_span.get_text(" ", strip=True))

        if node.name == "div" and "card-body" in (node.get("class") or []):
            badge = node.find("span", class_=lambda c: c and "badge" in c)
            teacher = node.find("span", style=lambda s: s and "darkgray" in s)
            summary_div = node.find("div", class_="summery-class")
            submit_btn = node.find("span", onclick=True)
            attachment_link = node.find("a", onclick=re.compile(r"ViewFile\("))

            if not badge or not teacher or not summary_div:
                continue

            entry_type = clean_text(badge.get_text(" ", strip=True))
            teacher_name = clean_text(teacher.get_text(" ", strip=True))
            summary = clean_text(summary_div.get_text(" ", strip=True))

            diary_id = None
            subject_id = None
            unique_key = None

            if submit_btn:
                onclick = submit_btn.get("onclick", "")
                m = re.search(r"\((\d+),\s*(-?\d+)\)", onclick)
                if m:
                    diary_id = int(m.group(1))
                    subject_id = int(m.group(2))
                    unique_key = f"{diary_id}:{subject_id}:{entry_type}:{current_subject}"

            attachment_name = None
            attachment_url = None
            if attachment_link:
                attachment_name = clean_text(attachment_link.get_text(" ", strip=True))
                onclick = attachment_link.get("onclick", "")
                m = re.search(r"ViewFile\('([^']+)'\s*,\s*'([^']+)'", onclick)
                if m:
                    attachment_url = m.group(2)

            if not unique_key:
                unique_key = f"{current_subject}:{entry_type}:{teacher_name}:{summary[:60]}"

            entries.append(
                {
                    "subject": current_subject or "Unknown",
                    "type": entry_type,
                    "teacher": teacher_name,
                    "summary": summary,
                    "attachment_name": attachment_name,
                    "attachment_url": attachment_url,
                    "diary_id": diary_id,
                    "subject_id": subject_id,
                    "unique_key": unique_key,
                    "date": diary_date,
                }
            )

    return entries


def already_exists(unique_key: str) -> bool:
    res = notion.databases.query(
        database_id=NOTION_DATABASE_ID,
        filter={
            "property": "Unique Key",
            "rich_text": {"equals": unique_key},
        },
    )
    return len(res.get("results", [])) > 0


def create_notion_page(entry: dict):
    title = f"{entry['subject']} - {entry['type']}"
    if entry["summary"]:
        title = f"{title} - {entry['summary'][:40]}"

    properties = {
        "Name": {
            "title": [{"text": {"content": title}}]
        },
        "Subject": {
            "select": {"name": entry["subject"]}
        },
        "Type": {
            "select": {"name": entry["type"]}
        },
        "Teacher": {
            "rich_text": [{"text": {"content": entry["teacher"]}}]
        },
        "Date": {
            "date": {
                "start": datetime.strptime(entry["date"], "%d %b %Y").date().isoformat()
            }
        },
        "Summary": {
            "rich_text": [{"text": {"content": entry["summary"]}}]
        },
        "Diary ID": {
            "number": entry["diary_id"] if entry["diary_id"] is not None else 0
        },
        "Unique Key": {
            "rich_text": [{"text": {"content": entry["unique_key"]}}]
        },
    }

    if entry["attachment_url"]:
        properties["Attachment"] = {"url": entry["attachment_url"]}

    notion.pages.create(
        parent={"database_id": NOTION_DATABASE_ID},
        properties=properties,
    )


def main():
    diary_date = today_diary_date()
    html = login_and_fetch_html(diary_date)
    entries = extract_entries(html, diary_date)

    print(f"Found {len(entries)} entries for {diary_date}")

    new_count = 0
    for entry in entries:
        if not already_exists(entry["unique_key"]):
            create_notion_page(entry)
            new_count += 1
            print(f"Added: {entry['subject']} / {entry['type']}")
        else:
            print(f"Skipped duplicate: {entry['subject']} / {entry['type']}")

    print(f"Inserted {new_count} new entries")


if __name__ == "__main__":
    main()
