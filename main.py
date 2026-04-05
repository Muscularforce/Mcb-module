import os
import re
from datetime import datetime
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from notion_client import Client
from notion_client.errors import APIResponseError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

PORTAL_URLS = [
    "https://rainbow.myclassboard.com/StudentERP/Master_Student",
    "https://rainbow.myclassboard.com/StudentERP/Master_Student/",
    "https://rainbow.myclassboard.com/",
]

DIARY_URL = "https://rainbow.myclassboard.com/StudentERP/StaffDiaryToStudent_CalenderView_AllActivities"
PORTAL_BASE_URL = "https://rainbow.myclassboard.com"

load_dotenv()


def require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Set it in your environment or create a .env file in this project folder."
        )
    return val


NOTION_TOKEN = require_env("NOTION_TOKEN")
NOTION_DATABASE_ID = require_env("NOTION_DATABASE_ID")
MCB_USERNAME = require_env("MCB_USERNAME")
MCB_PASSWORD = require_env("MCB_PASSWORD")

notion = Client(auth=NOTION_TOKEN)


def get_diary_date() -> str:
    override = os.getenv("DIARY_DATE_OVERRIDE", "").strip()
    if override:
        return override
    return datetime.now().strftime("%d %b %Y")


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def set_input_value(input_locator, value: str) -> bool:
    """
    Best-effort input fill.

    Sometimes inputs exist in the DOM but aren't considered "visible" by Playwright
    (common with SSO pages / dynamic render). We first try normal .fill(), and
    if that fails, we set the value via JS and trigger input/change events.
    """
    try:
        target = input_locator.first
        try:
            target.scroll_into_view_if_needed()
        except Exception:
            pass
        try:
            target.click(timeout=3000)
        except Exception:
            pass
        target.fill(value)
        return True
    except Exception:
        try:
            input_locator.first.evaluate(
                "(el, val) => { el.focus(); el.value = ''; el.value = val; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }",
                value,
            )
            return True
        except Exception:
            return False


def try_fill_first_matching(locators, value) -> bool:
    for loc in locators:
        try:
            if loc.count() > 0:
                if set_input_value(loc, value):
                    return True
                return True
        except Exception:
            pass
    return False


def send_discord_message(content: str = None, entry: dict = None):
    webhook = os.getenv("DISCORD_WEBHOOK", "").strip()
    if not webhook:
        return

    try:
        if entry is not None:
            payload = {
                "embeds": [
                    {
                        "title": f"{entry['subject']} — {entry['type']}",
                        "description": entry["summary"],
                        "color": 3447003,
                        "fields": [
                            {"name": "Teacher", "value": entry["teacher"], "inline": True},
                            {"name": "Date", "value": entry["date"], "inline": True},
                        ],
                    }
                ]
            }

            if entry.get("attachment_url"):
                payload["embeds"][0]["fields"].append(
                    {
                        "name": "Attachment",
                        "value": entry["attachment_url"],
                        "inline": False,
                    }
                )
        else:
            payload = {"content": content or ""}

        r = requests.post(webhook, json=payload, timeout=20)
        print(f"Discord response: {r.status_code}")
        if r.status_code >= 400:
            print(r.text[:500])
    except Exception as e:
        print(f"Discord notification failed: {e}")


def send_discord_error(message: str):
    webhook = os.getenv("DISCORD_WEBHOOK", "").strip()
    if not webhook:
        return

    try:
        text = (message or "").strip()
        if len(text) > 1800:
            text = text[:1800] + "…"
        content = f"⚠ MyClassboard automation failed:\n{text}"
        requests.post(webhook, json={"content": content}, timeout=20)
    except Exception as e:
        print(f"Discord error alert failed: {e}")


def find_visible_match(scope, selectors):
    for selector in selectors:
        try:
            loc = scope.locator(selector)
            if loc.count() > 0:
                for i in range(min(loc.count(), 5)):
                    item = loc.nth(i)
                    try:
                        if item.is_visible():
                            return item
                    except Exception:
                        pass
        except Exception:
            pass
    return None


def find_first_match(scope, selectors):
    """Return the first attached match (no visibility requirement)."""
    for selector in selectors:
        try:
            loc = scope.locator(selector)
            if loc.count() > 0:
                return loc.first
        except Exception:
            pass
    return None


def find_login_scope(page):
    """
    Try to locate the iframe that contains the login form.

    The previous implementation returned the first frame that had *any* inputs,
    which can cause us to search the wrong frame for username/password fields.
    """
    password_hint_selectors = [
        "input[type='password']",
        "input#txtPassword",
        "input#txtPass",
        "input#txtPwd",
        "input[id*='pass' i]",
        "input[name*='pass' i]",
        "input[placeholder*='pass' i]",
        "input[placeholder*='pwd' i]",
    ]

    for frame in page.frames:
        try:
            if any(frame.locator(sel).count() > 0 for sel in password_hint_selectors):
                return frame
        except Exception:
            pass
    return page


def login_and_fetch_html(diary_date: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.set_default_navigation_timeout(180000)
        page.set_default_timeout(60000)

        loaded = False
        for url in PORTAL_URLS:
            try:
                page.goto(url, wait_until="commit", timeout=180000)
                loaded = True
                break
            except Exception:
                continue

        if not loaded:
            browser.close()
            raise RuntimeError("Could not open the MyClassboard portal.")

        page.wait_for_timeout(12000)

        # Sometimes the portal lands on a generic error screen with a single
        # "Click here to Login" button (no username/password inputs yet).
        # Handle that by clicking through, then retry login-field detection.
        for _ in range(3):
            try:
                # Don't depend on exact error text/spacing; rely on the button itself.
                login_link_selectors = [
                    "text=Click here to Login",
                    "button:has-text('Click here to Login')",
                    "a:has-text('Click here to Login')",
                ]
                login_link = find_first_match(page, login_link_selectors)
                if login_link is not None:
                    try:
                        login_link.click(timeout=15000)
                    except Exception:
                        # Best-effort fallback in case the element isn't "actionable"
                        login_link.evaluate("(el) => el.click()")

                    # Wait for SSO login inputs to appear (the click usually
                    # redirects to ssolive.myclassboard.com /Account/Login).
                    for __ in range(20):
                        try:
                            if page.locator("input[type='password']").count() > 0:
                                break
                        except Exception:
                            pass
                        page.wait_for_timeout(1000)
                    page.wait_for_timeout(2000)
                    continue
            except Exception:
                pass
            break

        scope = find_login_scope(page)

        username_selectors = [
            "input#txtUserName",
            "input#txtUsername",
            "input#txtUser",
            "input#username",
            "input#UserName",
            "input#LoginID",
            "input#txtLoginId",
            "input#txtEmail",
            "input[type='text']",
            "input[type='email']",
            "input[autocomplete='username' i]",
            "input[autocomplete='email' i]",
            "input[aria-label*='user' i]",
            "input[aria-label*='email' i]",
            "input[aria-label*='login' i]",
            "input[placeholder*='user' i]",
            "input[placeholder*='username' i]",
            "input[name*='user' i]",
            "input[id*='user' i]",
            "input[name*='login' i]",
            "input[id*='login' i]",
        ]

        password_selectors = [
            "input#txtPassword",
            "input#txtPass",
            "input#txtPwd",
            "input#password",
            "input#Password",
            "input[type='password']",
            "input[autocomplete='current-password' i]",
            "input[aria-label*='password' i]",
            "input[placeholder*='pass' i]",
            "input[name*='pass' i]",
            "input[id*='pass' i]",
        ]

        scope_used = None
        # Try the guessed scope first, then fall back to page + all iframes.
        # Some portals render an outer page with multiple inputs/iframes before
        # the real login iframe becomes visible.
        scope_candidates = [scope, page] + list(page.frames)
        seen = set()
        unique_scopes = []
        for s in scope_candidates:
            if id(s) in seen:
                continue
            seen.add(id(s))
            unique_scopes.append(s)

        for candidate in unique_scopes:
            username_locators = [candidate.locator(sel) for sel in username_selectors]
            password_locators = [candidate.locator(sel) for sel in password_selectors]

            username_ok = try_fill_first_matching(username_locators, MCB_USERNAME)
            password_ok = try_fill_first_matching(password_locators, MCB_PASSWORD)

            if username_ok and password_ok:
                scope_used = candidate
                break

        if scope_used is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            debug_png_path = os.path.join(script_dir, "login_debug.png")
            debug_html_path = os.path.join(script_dir, "login_debug.html")
            page.screenshot(path=debug_png_path, full_page=True)
            with open(debug_html_path, "w", encoding="utf-8") as f:
                f.write(page.content())
            browser.close()
            raise RuntimeError("Could not find login fields. Check login_debug.png.")

        login_selectors = [
            "#LogID",
            "#btnLogin",
            "button:has-text('Login')",
            "button:has-text('Sign In')",
            "input[type='submit']",
            "button[type='submit']",
        ]

        login_button = find_first_match(scope_used, login_selectors)
        if login_button is not None:
            login_button.evaluate("(el) => el.click()")
        else:
            page.keyboard.press("Enter")

        page.wait_for_timeout(10000)

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


def extract_entries(html: str, diary_date: str):
    soup = BeautifulSoup(html, "html.parser")
    page_text = clean_text(soup.get_text(" ", strip=True))

    if "No diary entries are found!" in page_text:
        return []

    entries = []
    current_subject = None

    for node in soup.find_all(["h6", "div"]):
        if node.name == "h6":
            subject_span = node.find("span")
            if subject_span:
                subject_text = clean_text(subject_span.get_text(" ", strip=True))
                if subject_text:
                    current_subject = subject_text

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

            if submit_btn:
                onclick = submit_btn.get("onclick", "")
                m = re.search(r"\((\d+),\s*(-?\d+)\)", onclick)
                if m:
                    diary_id = int(m.group(1))
                    subject_id = int(m.group(2))

            attachment_name = None
            attachment_url = None
            if attachment_link:
                attachment_name = clean_text(attachment_link.get_text(" ", strip=True))
                onclick = attachment_link.get("onclick", "")
                # MCB's ViewFile(...) argument order can vary, so parse all
                # quoted args and pick the one that looks like a file URL/path.
                args = re.findall(r"'([^']*)'", onclick)
                for arg in args:
                    candidate = clean_text(arg)
                    if not candidate:
                        continue
                    if any(
                        token in candidate.lower()
                        for token in [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".jpg", ".jpeg", ".png", ".zip", "/uploads/", "download", "file"]
                    ):
                        attachment_url = urljoin(PORTAL_BASE_URL, candidate)
                        break

            unique_key = f"{diary_date}|{current_subject}|{entry_type}|{diary_id}|{subject_id}|{summary[:80]}"

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


def notion_database_reachable() -> None:
    try:
        notion.databases.retrieve(database_id=NOTION_DATABASE_ID)
    except Exception as e:
        raise RuntimeError(
            "Notion cannot access the database. Share the database with your integration and verify NOTION_DATABASE_ID."
        ) from e


def already_exists(unique_key: str) -> bool:
    try:
        res = notion.databases.query(
            database_id=NOTION_DATABASE_ID,
            filter={
                "property": "Unique Key",
                "rich_text": {"equals": unique_key},
            },
        )
        return len(res.get("results", [])) > 0
    except APIResponseError as e:
        raise RuntimeError(
            "Notion database query failed. Check that the database has a 'Unique Key' rich text property."
        ) from e


def create_notion_page(entry: dict):
    title = f"{entry['subject']} - {entry['type']}"
    if entry["summary"]:
        title = f"{title} - {entry['summary'][:40]}"

    properties = {
        "Name": {"title": [{"text": {"content": title}}]},
        "Subject": {"select": {"name": entry["subject"]}},
        "Type": {"select": {"name": entry["type"]}},
        "Teacher": {"rich_text": [{"text": {"content": entry["teacher"]}}]},
        "Date": {
            "date": {
                "start": datetime.strptime(entry["date"], "%d %b %Y").date().isoformat()
            }
        },
        "Summary": {"rich_text": [{"text": {"content": entry["summary"]}}]},
        "Diary ID": {"number": entry["diary_id"] if entry["diary_id"] is not None else 0},
        "Unique Key": {"rich_text": [{"text": {"content": entry["unique_key"]}}]},
    }

    if entry["attachment_url"]:
        properties["Attachment"] = {"url": entry["attachment_url"]}

    notion.pages.create(
        parent={"database_id": NOTION_DATABASE_ID},
        properties=properties,
    )


def main():
    notion_database_reachable()

    diary_date = get_diary_date()
    html = login_and_fetch_html(diary_date)
    entries = extract_entries(html, diary_date)

    print(f"Found {len(entries)} entries for {diary_date}")

    new_count = 0
    for entry in entries:
        if not already_exists(entry["unique_key"]):
            create_notion_page(entry)
            send_discord_message(entry=entry)
            new_count += 1
            print(f"Added: {entry['subject']} / {entry['type']}")
        else:
            print(f"Skipped duplicate: {entry['subject']} / {entry['type']}")

    summary = f"Diary checked for {diary_date}. Found {len(entries)} entries. Added {new_count} new entries."
    print(summary)
    send_discord_message(content=summary)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Script failed: {e}")
        send_discord_error(str(e))
        raise