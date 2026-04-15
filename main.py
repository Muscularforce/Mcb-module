import mimetypes
import os
import re
from datetime import datetime, timezone
from urllib.parse import unquote, urljoin

import requests
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from notion_client import Client
from notion_client.errors import APIResponseError
from playwright.sync_api import sync_playwright

PORTAL_URLS = [
    "https://rainbow.myclassboard.com/StudentERP/Master_Student",
    "https://rainbow.myclassboard.com/StudentERP/Master_Student/",
    "https://rainbow.myclassboard.com/",
]

DIARY_URL = "https://rainbow.myclassboard.com/StudentERP/StaffDiaryToStudent_CalenderView_AllActivities"
PORTAL_BASE_URL = "https://rainbow.myclassboard.com"

# Notion file uploads require a recent API version (separate from notion-client defaults).
NOTION_FILE_API_VERSION = "2026-03-11"
NOTION_MAX_UPLOAD_BYTES = 20 * 1024 * 1024

load_dotenv()

# Discord embed accents (type substring → color). Default blurple if no match.
DISCORD_TYPE_COLORS = {
    "homework": 0xE67E22,
    "assignment": 0xE67E22,
    "circular": 0x3498DB,
    "notice": 0x9B59B6,
    "announcement": 0x9B59B6,
    "holiday": 0x1ABC9C,
    "exam": 0xE74C3C,
    "test": 0xE74C3C,
    "event": 0xF1C40F,
    "reminder": 0x1ABC9C,
}
DISCORD_DEFAULT_EMBED_COLOR = 0x5865F2
DISCORD_SUCCESS_EMBED_COLOR = 0x57F287
DISCORD_ERROR_EMBED_COLOR = 0xED4245


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


def _score_attachment_candidate(s: str) -> int:
    low = s.lower().replace("\\", "/")
    score = 0
    if low.startswith("http://") or low.startswith("https://"):
        score += 25
    if "studenterp" in low:
        score += 18
    if "/upload" in low or "uploads" in low or "download" in low or "/content/" in low:
        score += 12
    if "/" in s:
        score += 10
    for ext in (
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".jpg",
        ".jpeg",
        ".png",
        ".zip",
    ):
        if low.endswith(ext) or f"{ext}?" in low or f"{ext}#" in low:
            score += 8
            break
    if re.match(r"^[a-z0-9_.-]+$", low, re.I) and "." in s:
        score += 3
    return score


def _attachment_url_from_view_file_onclick(onclick: str) -> str | None:
    if not onclick or "viewfile" not in onclick.lower():
        return None
    args = re.findall(r"""['"]([^'"]*)['"]""", onclick)
    best = None
    best_score = -1
    for raw in args:
        candidate = clean_text(raw)
        if not candidate:
            continue
        low = candidate.lower()
        if low.startswith(("javascript:", "void", "#")):
            continue
        sc = _score_attachment_candidate(candidate)
        if sc > best_score:
            best_score = sc
            best = candidate
    if best is None or best_score < 1:
        return None
    if best.lower().startswith("http://") or best.lower().startswith("https://"):
        return best
    return urljoin(PORTAL_BASE_URL, best)


def _parse_attachment_link(attachment_link) -> tuple[str | None, str | None]:
    if not attachment_link:
        return None, None
    name = clean_text(attachment_link.get_text(" ", strip=True)) or None
    href = (attachment_link.get("href") or "").strip()
    if href and not href.lower().startswith(("javascript:", "#", "void")):
        href = unquote(href.split("#")[0])
        abs_url = urljoin(PORTAL_BASE_URL, href)
        if abs_url.lower().startswith("http"):
            return name, abs_url
    onclick = attachment_link.get("onclick") or ""
    return name, _attachment_url_from_view_file_onclick(onclick)


def _is_probably_html_response(body: bytes, content_type: str) -> bool:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct == "text/html":
        return True
    head = body.lstrip()[:200].lower()
    return head.startswith(b"<!doctype") or head.startswith(b"<html")


def _safe_attachment_filename(entry: dict, source_url: str, content_type: str) -> str:
    name = (entry.get("attachment_name") or "").strip()
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    name = name.strip(" .") or ""
    if not name or len(name) > 180:
        path = source_url.split("?", 1)[0].rstrip("/").split("/")[-1]
        path = unquote(path)
        path = re.sub(r'[<>:"/\\|?*]', "_", path)
        if path and len(path) <= 180:
            name = path
    if not name:
        ext = mimetypes.guess_extension((content_type or "").split(";")[0].strip()) or ".bin"
        name = f"attachment{ext}"
    if "." not in name:
        ext = mimetypes.guess_extension((content_type or "").split(";")[0].strip()) or ""
        if ext:
            name = f"{name}{ext}"
    return name[:200]


def _try_download_mcb_attachment(request, entry: dict) -> None:
    url = entry.get("attachment_url")
    if not url:
        return
    try:
        resp = request.get(
            url,
            max_redirects=10,
            timeout=120_000,
            headers={"Referer": f"{PORTAL_BASE_URL}/"},
        )
        if resp.status != 200:
            print(f"Attachment fetch HTTP {resp.status} for {url[:120]}")
            return
        body = resp.body()
        if not body or len(body) < 32:
            return
        ct = (resp.headers.get("content-type") or "").split(";")[0].strip()
        if _is_probably_html_response(body, ct):
            print("Attachment fetch returned HTML (session or URL issue); skipping Notion upload.")
            return
        if len(body) > NOTION_MAX_UPLOAD_BYTES:
            print("Attachment larger than 20MB; skipping Notion upload (MCB URL kept).")
            return
        filename = _safe_attachment_filename(entry, url, ct)
        if not ct or ct == "application/octet-stream":
            guessed, _ = mimetypes.guess_type(filename)
            if guessed:
                ct = guessed
        entry["_attachment_download"] = {
            "bytes": body,
            "content_type": ct or "application/octet-stream",
            "filename": filename,
        }
    except Exception as e:
        print(f"Attachment download failed: {e}")


def _notion_block_for_upload(file_upload_id: str, content_type: str) -> dict:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in ("application/pdf", "application/x-pdf"):
        return {
            "object": "block",
            "type": "pdf",
            "pdf": {
                "type": "file_upload",
                "file_upload": {"id": file_upload_id},
            },
        }
    if ct.startswith("image/"):
        return {
            "object": "block",
            "type": "image",
            "image": {
                "caption": [],
                "type": "file_upload",
                "file_upload": {"id": file_upload_id},
            },
        }
    return {
        "object": "block",
        "type": "file",
        "file": {
            "type": "file_upload",
            "file_upload": {"id": file_upload_id},
        },
    }


def upload_attachment_bytes_to_notion(data: bytes, filename: str, content_type: str) -> str:
    if len(data) > NOTION_MAX_UPLOAD_BYTES:
        raise RuntimeError("Attachment exceeds Notion 20MB upload limit.")

    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Notion-Version": NOTION_FILE_API_VERSION,
    }
    create = requests.post(
        "https://api.notion.com/v1/file_uploads",
        headers={**headers, "Content-Type": "application/json"},
        json={"filename": filename, "content_type": content_type or "application/octet-stream"},
        timeout=120,
    )
    if create.status_code != 200:
        raise RuntimeError(
            f"Notion file_uploads create failed ({create.status_code}): {create.text[:800]}"
        )
    meta = create.json()
    file_upload_id = meta["id"]
    send_url = meta.get("upload_url") or f"https://api.notion.com/v1/file_uploads/{file_upload_id}/send"
    send = requests.post(
        send_url,
        headers=headers,
        files={"file": (filename, data, content_type or "application/octet-stream")},
        timeout=120,
    )
    if send.status_code != 200:
        raise RuntimeError(
            f"Notion file upload send failed ({send.status_code}): {send.text[:800]}"
        )
    return file_upload_id


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


def _discord_iso_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _discord_truncate(text: str, max_len: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _discord_color_for_entry_type(entry_type: str) -> int:
    t = (entry_type or "").lower()
    for key, color in DISCORD_TYPE_COLORS.items():
        if key in t:
            return color
    return DISCORD_DEFAULT_EMBED_COLOR


def _discord_webhook_identity() -> tuple[str, str | None]:
    name = os.getenv("DISCORD_WEBHOOK_USERNAME", "MCB → Notion").strip() or "MCB → Notion"
    avatar = os.getenv("DISCORD_WEBHOOK_AVATAR_URL", "").strip()
    if not avatar:
        avatar = "https://upload.wikimedia.org/wikipedia/commons/4/45/Notion_app_logo.png"
    return name, avatar


def send_discord_message(content: str = None, entry: dict = None):
    webhook = os.getenv("DISCORD_WEBHOOK", "").strip()
    if not webhook:
        return

    username, avatar_url = _discord_webhook_identity()

    try:
        if entry is not None:
            subject = _discord_truncate(entry.get("subject") or "Unknown", 240)
            entry_type = entry.get("type") or "—"
            summary = _discord_truncate(entry.get("summary") or "—", 3800)
            teacher = _discord_truncate(entry.get("teacher") or "—", 1024)
            date_str = _discord_truncate(entry.get("date") or "—", 256)

            embed = {
                "author": {
                    "name": "New diary entry · synced to Notion",
                    "icon_url": avatar_url,
                },
                "title": f"📚 {subject}",
                "description": f"**{_discord_truncate(entry_type, 120)}**\n\n{summary}",
                "color": _discord_color_for_entry_type(entry_type),
                "fields": [
                    {"name": "👤 Teacher", "value": teacher, "inline": True},
                    {"name": "📅 Date", "value": date_str, "inline": True},
                ],
                "footer": {"text": "Rainbow MyClassboard → Notion"},
                "timestamp": _discord_iso_timestamp(),
            }

            att = entry.get("attachment_url")
            if att:
                att = att.strip()
                can_link = (
                    att.startswith("http")
                    and ")" not in att
                    and len(att) <= 500
                )
                if can_link:
                    pretty_url = _discord_truncate(att, 220)
                    field_val = (
                        f"***Tap to access your file quickly***\n"
                        f"**[⬇️ Download]({att})**  |  **[🔗 Open URL]({att})**\n"
                        f"*`{pretty_url}`*"
                    )
                else:
                    field_val = f"***Attachment URL***\n*{_discord_truncate(att, 1024)}*"
                embed["fields"].append(
                    {
                        "name": "📎 Attachment",
                        "value": field_val,
                        "inline": False,
                    }
                )

            payload = {
                "username": username,
                "avatar_url": avatar_url,
                "embeds": [embed],
            }
        else:
            body = _discord_truncate(content or "", 3900)
            payload = {
                "username": username,
                "avatar_url": avatar_url,
                "embeds": [
                    {
                        "title": "✅ Diary sync complete",
                        "description": body or "—",
                        "color": DISCORD_SUCCESS_EMBED_COLOR,
                        "footer": {"text": "Rainbow MyClassboard → Notion"},
                        "timestamp": _discord_iso_timestamp(),
                    }
                ],
            }

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
        raw_message = (message or "").strip()
        if "Execution context was destroyed" in raw_message and "Page.evaluate" in raw_message:
            raw_message = "Its GODDAMS Mcbs fault not mine"
        text = _discord_truncate(raw_message, 3800)
        username, avatar_url = _discord_webhook_identity()
        payload = {
            "username": username,
            "avatar_url": avatar_url,
            "embeds": [
                {
                    "title": "⚠️ Sync failed",
                    "description": text or "Unknown error.",
                    "color": DISCORD_ERROR_EMBED_COLOR,
                    "footer": {"text": "MyClassboard automation · check logs"},
                    "timestamp": _discord_iso_timestamp(),
                }
            ],
        }
        requests.post(webhook, json=payload, timeout=20)
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


def fetch_diary_entries(diary_date: str):
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

        entries = extract_entries(html, diary_date)
        req = context.request
        for entry in entries:
            if not entry.get("attachment_url"):
                continue
            if already_exists(entry["unique_key"]):
                continue
            _try_download_mcb_attachment(req, entry)

        browser.close()
        return entries


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
            attachment_link = node.find("a", onclick=re.compile(r"ViewFile\(", re.I))
            if not attachment_link:
                for a in node.find_all("a", href=True):
                    h = (a.get("href") or "").strip()
                    if not h or h.lower().startswith("javascript:"):
                        continue
                    if re.search(
                        r"\.(pdf|doc|docx|xls|xlsx|ppt|pptx?|jpe?g|png|gif|zip)(\?|#|$)",
                        h,
                        re.I,
                    ):
                        attachment_link = a
                        break

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
                attachment_name, attachment_url = _parse_attachment_link(attachment_link)

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


def create_notion_page(
    entry: dict,
    *,
    notion_file_upload_id: str | None = None,
    notion_upload_content_type: str | None = None,
):
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

    # MCB attachment URLs usually require portal cookies; a plain URL in Notion often errors.
    # When upload succeeds, attach the file as a page block and omit the URL property.
    if entry.get("attachment_url") and not notion_file_upload_id:
        properties["Attachment"] = {"url": entry["attachment_url"]}

    children = []
    if notion_file_upload_id:
        children.append(
            _notion_block_for_upload(
                notion_file_upload_id,
                notion_upload_content_type or "application/octet-stream",
            )
        )

    kwargs = {
        "parent": {"database_id": NOTION_DATABASE_ID},
        "properties": properties,
    }
    if children:
        kwargs["children"] = children

    notion.pages.create(**kwargs)


def main():
    notion_database_reachable()

    diary_date = get_diary_date()
    entries = fetch_diary_entries(diary_date)

    print(f"Found {len(entries)} entries for {diary_date}")

    new_count = 0
    for entry in entries:
        if not already_exists(entry["unique_key"]):
            dl = entry.pop("_attachment_download", None)
            upload_id = None
            upload_ct = None
            if dl:
                try:
                    upload_id = upload_attachment_bytes_to_notion(
                        dl["bytes"], dl["filename"], dl["content_type"]
                    )
                    upload_ct = dl["content_type"]
                except Exception as e:
                    print(f"Notion attachment upload failed (MCB URL kept if present): {e}")
            create_notion_page(
                entry,
                notion_file_upload_id=upload_id,
                notion_upload_content_type=upload_ct,
            )
            send_discord_message(entry=entry)
            new_count += 1
            print(f"Added: {entry['subject']} / {entry['type']}")
        else:
            print(f"Skipped duplicate: {entry['subject']} / {entry['type']}")

    if new_count > 0:
        print(f"Added {new_count} new entries for {diary_date}.")
    else:
        print(f"No new entries for {diary_date}.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Script failed: {e}")
        send_discord_error(str(e))
        raise