"""
MCB   Web App Importer
======================
Logs into MyClassboard, scrapes ALL diary entries, worksheets (assignments),
and announcements, then posts them to the local FastAPI backend so they
appear on the web dashboard.

Usage:
    python mcb_import.py              # scrape today's date
    python mcb_import.py "10 Jun 2026" # scrape a specific date
"""

import os
import re
import sys
import json
import requests as http_requests
from datetime import datetime, timedelta
from urllib.parse import unquote, urljoin


from dotenv import load_dotenv
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

# ---------------- Config ----------------

PORTAL_URLS = [
    "https://rainbow.myclassboard.com/StudentERP/Master_Student",
    "https://rainbow.myclassboard.com/StudentERP/Master_Student/",
    "https://rainbow.myclassboard.com/",
]
DIARY_URL = "https://rainbow.myclassboard.com/StudentERP/StaffDiaryToStudent_CalenderView_AllActivities"
PORTAL_BASE_URL = "https://rainbow.myclassboard.com"
API_URL = "http://localhost:8000/api/entries"

# Load environment
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

MCB_USERNAME = os.getenv("MCB_USERNAME")
MCB_PASSWORD = os.getenv("MCB_PASSWORD")

if not MCB_USERNAME or not MCB_PASSWORD:
    print("ERROR: MCB_USERNAME and MCB_PASSWORD must be set in .env")
    sys.exit(1)


# ---------------- Helpers ----------------

def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def _score_attachment_candidate(s):
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
    for ext in (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".jpg", ".jpeg", ".png", ".zip"):
        if low.endswith(ext) or f"{ext}?" in low or f"{ext}#" in low:
            score += 8
            break
    if re.match(r"^[a-z0-9_.-]+$", low, re.I) and "." in s:
        score += 3
    return score


def _attachment_url_from_onclick(onclick):
    if not onclick or "viewfile" not in onclick.lower():
        return None
    args = re.findall(r"""['"]([^'"]*)['"]""", onclick)
    best, best_score = None, -1
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
    if best.lower().startswith("http"):
        return best
    return urljoin(PORTAL_BASE_URL, best)


def _parse_attachment_link(link):
    if not link:
        return None, None
    name = clean_text(link.get_text(" ", strip=True)) or None
    href = (link.get("href") or "").strip()
    if href and not href.lower().startswith(("javascript:", "#", "void")):
        href = unquote(href.split("#")[0])
        abs_url = urljoin(PORTAL_BASE_URL, href)
        if abs_url.lower().startswith("http"):
            return name, abs_url
    onclick = link.get("onclick") or ""
    return name, _attachment_url_from_onclick(onclick)


# ---------------- Login ----------------

def set_input_value(input_locator, value):
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
                "(el, val) => { el.focus(); el.value = ''; el.value = val; "
                "el.dispatchEvent(new Event('input', { bubbles: true })); "
                "el.dispatchEvent(new Event('change', { bubbles: true })); }",
                value,
            )
            return True
        except Exception:
            return False


def try_fill_first_matching(locators, value):
    for loc in locators:
        try:
            if loc.count() > 0:
                if set_input_value(loc, value):
                    return True
        except Exception:
            pass
    return False


def find_first_match(scope, selectors):
    for selector in selectors:
        try:
            loc = scope.locator(selector)
            if loc.count() > 0:
                return loc.first
        except Exception:
            pass
    return None


def find_login_scope(page):
    password_selectors = [
        "input[type='password']",
        "input#txtPassword",
        "input#txtPass",
        "input[id*='pass' i]",
        "input[name*='pass' i]",
    ]
    for frame in page.frames:
        try:
            if any(frame.locator(sel).count() > 0 for sel in password_selectors):
                return frame
        except Exception:
            pass
    return page


# ---------------- Extraction ----------------

def extract_diary_entries(html, diary_date):
    """Extract diary entries from the AJAX response HTML."""
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
            attachment_link = node.find("a", onclick=re.compile(r"ViewFile\(", re.I))
            if not attachment_link:
                for a in node.find_all("a", href=True):
                    h = (a.get("href") or "").strip()
                    if not h or h.lower().startswith("javascript:"):
                        continue
                    if re.search(r"\.(pdf|doc|docx|xls|xlsx|ppt|pptx?|jpe?g|png|gif|zip)(\?|#|$)", h, re.I):
                        attachment_link = a
                        break

            if not badge or not teacher or not summary_div:
                continue

            entry_type = clean_text(badge.get_text(" ", strip=True))
            teacher_name = clean_text(teacher.get_text(" ", strip=True))
            summary = clean_text(summary_div.get_text(" ", strip=True))

            attachment_name, attachment_url = None, None
            if attachment_link:
                attachment_name, attachment_url = _parse_attachment_link(attachment_link)

            entries.append({
                "subject": current_subject or "Unknown",
                "type": entry_type,
                "teacher": teacher_name,
                "summary": summary,
                "attachment_url": attachment_url,
                "date": diary_date,
            })

    return entries


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


def extract_generic_cards(html, diary_date, default_type):
    """Extract cards from Announcements or Assignments tabs."""
    soup = BeautifulSoup(html, "html.parser")
    entries = []

    for node in soup.find_all("div", class_=lambda c: c and "card-body" in c):
        text = clean_text(node.get_text(" ", strip=True))
        if not text or len(text) < 10:
            continue

        summary = text[:500]
        title = default_type
        if default_type == "Worksheet":
            title = extract_worksheet_title(text)
        else:
            title_node = node.find(["h6", "strong", "b", "h5"])
            if title_node:
                title = clean_text(title_node.get_text(" ", strip=True)) or default_type

        # Try to get teacher name
        teacher_span = node.find("span", style=lambda s: s and "darkgray" in s)
        teacher_name = clean_text(teacher_span.get_text(" ", strip=True)) if teacher_span else ""

        # Try to get attachment
        attachment_url = None
        attachment_link = node.find("a", onclick=re.compile(r"ViewFile\(", re.I))
        if not attachment_link:
            for a in node.find_all("a", href=True):
                h = (a.get("href") or "").strip()
                if h and not h.lower().startswith("javascript:"):
                    if re.search(r"\.(pdf|doc|docx|xls|xlsx|ppt|pptx?|jpe?g|png|gif|zip)(\?|#|$)", h, re.I):
                        attachment_link = a
                        break
        if attachment_link:
            _, attachment_url = _parse_attachment_link(attachment_link)

        # Try to extract date from card
        date_match = re.search(r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+\w{3}\s+\d{4})", text)
        entry_date = diary_date
        if date_match:
            try:
                for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%m/%d/%Y"):
                    try:
                        parsed = datetime.strptime(date_match.group(1), fmt)
                        entry_date = parsed.strftime("%d %b %Y")
                        break
                    except ValueError:
                        continue
            except Exception:
                pass

        entries.append({
            "subject": title,
            "type": default_type,
            "teacher": teacher_name or ("System" if default_type == "Announcement" else "Teacher"),
            "summary": summary,
            "attachment_url": attachment_url,
            "date": entry_date,
        })

    return entries


# ---------------- Main Scraper ----------------

def scrape_mcb(diary_date, scrape_all=False):
    """Log in to MCB, scrape all tabs, return list of entries."""
    mode_str = "ALL HISTORICAL DATA" if scrape_all else f"date: {diary_date}"
    print(f"\n{'='*60}")
    print(f"  MCB IMPORTER - Scraping {mode_str}")
    print(f"{'='*60}\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        page.set_default_navigation_timeout(180000)
        page.set_default_timeout(60000)

        # --- Navigate to portal ---
        print("[1/5] Navigating to MCB portal...")
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

        # --- Handle pre-login screen ---
        for _ in range(3):
            try:
                login_link = find_first_match(page, [
                    "text=Click here to Login",
                    "button:has-text('Click here to Login')",
                    "a:has-text('Click here to Login')",
                ])
                if login_link is not None:
                    try:
                        login_link.click(timeout=15000)
                    except Exception:
                        login_link.evaluate("(el) => el.click()")
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

        # --- Login ---
        print("[2/5] Logging in...")
        scope = find_login_scope(page)

        username_selectors = [
            "input#txtUserName", "input#txtUsername", "input#txtUser",
            "input#username", "input#UserName", "input#LoginID",
            "input#txtLoginId", "input#txtEmail", "input[type='text']",
            "input[type='email']", "input[autocomplete='username' i]",
            "input[placeholder*='user' i]", "input[name*='user' i]",
        ]
        password_selectors = [
            "input#txtPassword", "input#txtPass", "input#txtPwd",
            "input#password", "input[type='password']",
            "input[autocomplete='current-password' i]",
            "input[placeholder*='pass' i]", "input[name*='pass' i]",
        ]

        scope_candidates = [scope, page] + list(page.frames)
        seen = set()
        scope_used = None

        for candidate in scope_candidates:
            if id(candidate) in seen:
                continue
            seen.add(id(candidate))

            u_ok = try_fill_first_matching([candidate.locator(s) for s in username_selectors], MCB_USERNAME)
            p_ok = try_fill_first_matching([candidate.locator(s) for s in password_selectors], MCB_PASSWORD)

            if u_ok and p_ok:
                scope_used = candidate
                break

        if scope_used is None:
            page.screenshot(path="login_debug.png", full_page=True)
            browser.close()
            raise RuntimeError("Could not find login fields. Check login_debug.png.")

        login_btn = find_first_match(scope_used, [
            "#LogID", "#btnLogin",
            "button:has-text('Login')", "button:has-text('Sign In')",
            "input[type='submit']", "button[type='submit']",
        ])
        if login_btn:
            login_btn.evaluate("(el) => el.click()")
        else:
            page.keyboard.press("Enter")

        page.wait_for_timeout(10000)
        print("   [OK] Login successful")

        all_entries = []

        # --- Fetch diary entries via AJAX ---
        if scrape_all:
            # Generate the last 90 dates (approx the full history since March 15, 2026)
            print("[3/5] Generating and fetching diary entries for the last 90 days...")
            dates = [(datetime.now() - timedelta(days=x)).strftime("%d %b %Y") for x in range(90)]
            
            try:
                results = page.evaluate(
                    """
                    async ({url, dates}) => {
                        const resList = [];
                        for (const date of dates) {
                            try {
                                const res = await fetch(url, {
                                    method: 'POST',
                                    headers: {
                                        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                                        'X-Requested-With': 'XMLHttpRequest'
                                    },
                                    body: new URLSearchParams({ DiaryDate: date }).toString()
                                });
                                const html = await res.text();
                                resList.push({ date, html });
                            } catch (e) {
                                resList.push({ date, html: '', error: e.message });
                            }
                        }
                        return resList;
                    }
                    """,
                    {"url": DIARY_URL, "dates": dates},
                )
                
                success_count = 0
                for res in results:
                    if res["html"] and "No diary entries are found!" not in res["html"]:
                        day_entries = extract_diary_entries(res["html"], res["date"])
                        for e in day_entries:
                            e["_source"] = "DiaryEntry"
                        all_entries.extend(day_entries)
                        success_count += len(day_entries)
                print(f"   [OK] Found {success_count} diary entries across the last 90 days")
            except Exception as e:
                print(f"   [FAIL] Diary historical fetch failed: {e}")
        else:
            print("[3/5] Fetching diary entries for a single date...")
            try:
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
                diary_entries = extract_diary_entries(html, diary_date)
                for e in diary_entries:
                    e["_source"] = "DiaryEntry"
                all_entries.extend(diary_entries)
                print(f"   [OK] Found {len(diary_entries)} diary entries")
            except Exception as e:
                print(f"   [FAIL] Diary fetch failed: {e}")

        # --- Fetch announcements ---
        print("[4/5] Fetching announcements...")
        try:
            ann_tab = page.locator("a:has-text('Announcements'), li:has-text('Announcements'), button:has-text('Announcements')").first
            ann_tab.click(timeout=15000)
            page.wait_for_timeout(5000)

            if scrape_all:
                print("   Scrolling down to load ALL older announcements...")
                for i in range(50):
                    page.evaluate("""
                        window.scrollTo(0, document.body.scrollHeight);
                        document.querySelectorAll('div').forEach(el => {
                            if (el.scrollHeight > el.clientHeight) {
                                el.scrollTop = el.scrollHeight;
                            }
                        });
                    """)
                    page.wait_for_timeout(1200)

            ann_html = page.content()
            ann_entries = extract_generic_cards(ann_html, diary_date, "Announcement")
            for e in ann_entries:
                e["_source"] = "Announcement"
            all_entries.extend(ann_entries)
            print(f"   [OK] Found {len(ann_entries)} announcements")
        except Exception as e:
            print(f"   [FAIL] Announcements fetch failed: {e}")

        # --- Fetch assignments/worksheets ---
        print("[5/5] Fetching worksheets/assignments...")
        try:
            ass_tab = page.locator("a:has-text('Assignments'), li:has-text('Assignments'), button:has-text('Assignments')").first
            ass_tab.click(timeout=15000)
            page.wait_for_timeout(5000)

            if scrape_all:
                print("   Scrolling down to load ALL older worksheets...")
                for i in range(50):
                    page.evaluate("""
                        window.scrollTo(0, document.body.scrollHeight);
                        document.querySelectorAll('div').forEach(el => {
                            if (el.scrollHeight > el.clientHeight) {
                                el.scrollTop = el.scrollHeight;
                            }
                        });
                    """)
                    page.wait_for_timeout(1200)

            ass_html = page.content()
            ws_entries = extract_generic_cards(ass_html, diary_date, "Worksheet")
            for e in ws_entries:
                e["_source"] = "Worksheet"
            all_entries.extend(ws_entries)
            print(f"   [OK] Found {len(ws_entries)} worksheets")
        except Exception as e:
            print(f"   [FAIL] Worksheets fetch failed: {e}")

        browser.close()

    return all_entries


# ---------------- Push to API ----------------

def push_to_api(entries):
    """Post scraped entries to Supabase (if configured) or the local FastAPI backend."""
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_KEY")

    if supabase_url and supabase_key:
        print(f"\nPushing {len(entries)} entries directly to Supabase at {supabase_url}...")
        try:
            from supabase import create_client, Client
            supabase: Client = create_client(supabase_url, supabase_key)
            
            success = 0
            failed = 0

            for entry in entries:
                source = entry.pop("_source", "DiaryEntry")

                try:
                    parsed_date = datetime.strptime(entry["date"], "%d %b %Y")
                    api_date = parsed_date.strftime("%Y-%m-%d")
                except ValueError:
                    api_date = entry["date"]

                payload = {
                    "entry_type": source,
                    "subject": entry.get("subject", "Unknown"),
                    "teacher": entry.get("teacher", ""),
                    "date": api_date,
                    "summary": entry.get("summary", ""),
                    "attachment_url": entry.get("attachment_url"),
                }

                try:
                    # Insert row
                    res = supabase.table("entries").insert(payload).execute()
                    if len(res.data) > 0:
                        success += 1
                        print(f"  [OK] [{source}] {payload['subject']}")
                    else:
                        failed += 1
                        print(f"  [FAIL] [{source}] {payload['subject']} - Empty response")
                except Exception as e:
                    failed += 1
                    print(f"  [FAIL] [{source}] {payload['subject']} - {e}")

            print(f"\n{'='*60}")
            print(f"  SUPABASE IMPORT COMPLETE: {success} added, {failed} failed")
            print(f"{'='*60}\n")
            return
        except ImportError:
            print("WARNING: 'supabase' library is not installed. Falling back to local FastAPI backend...")
        except Exception as e:
            print(f"WARNING: Supabase connection failed: {e}. Falling back to local FastAPI backend...")

    # Fallback to local FastAPI backend
    print(f"\nPushing {len(entries)} entries to local API at {API_URL}...")

    success = 0
    failed = 0

    for entry in entries:
        source = entry.pop("_source", "DiaryEntry")

        try:
            parsed_date = datetime.strptime(entry["date"], "%d %b %Y")
            api_date = parsed_date.strftime("%Y-%m-%d")
        except ValueError:
            api_date = entry["date"]

        payload = {
            "entry_type": source,
            "subject": entry.get("subject", "Unknown"),
            "teacher": entry.get("teacher", ""),
            "date": api_date,
            "summary": entry.get("summary", ""),
            "attachment_url": entry.get("attachment_url"),
        }

        try:
            r = http_requests.post(API_URL, json=payload, timeout=10)
            if r.status_code == 200:
                success += 1
                print(f"  [OK] [{source}] {payload['subject']}")
            else:
                failed += 1
                print(f"  [FAIL] [{source}] {payload['subject']} - HTTP {r.status_code}")
        except Exception as e:
            failed += 1
            print(f"  [FAIL] [{source}] {payload['subject']} - {e}")

    print(f"\n{'='*60}")
    print(f"  LOCAL IMPORT COMPLETE: {success} added, {failed} failed")
    print(f"{'='*60}\n")



# ---------------- Entry Point ----------------

if __name__ == "__main__":
    scrape_all = "--all" in sys.argv
    
    # Filter out --all from sys.argv for date parsing
    args = [a for a in sys.argv if a != "--all"]
    
    diary_date = args[1] if len(args) > 1 else datetime.now().strftime("%d %b %Y")

    entries = scrape_mcb(diary_date, scrape_all=scrape_all)

    if entries:
        # Deduplicate entries in Python based on type + date + subject + summary
        seen = set()
        unique_entries = []
        for e in entries:
            key = (e.get("type"), e.get("date"), e.get("subject"), (e.get("summary") or "")[:100])
            if key not in seen:
                seen.add(key)
                unique_entries.append(e)
        
        print(f"\nFound {len(entries)} raw entries. Deduplicated down to {len(unique_entries)} unique entries.")

        # Wipe existing entries from Supabase to start a clean sync if doing a full sync
        if scrape_all:
            print("Wiping existing entries from Supabase to start a clean sync...")
            supabase_url = os.getenv("SUPABASE_URL")
            supabase_key = os.getenv("SUPABASE_KEY")
            if supabase_url and supabase_key:
                try:
                    from supabase import create_client
                    supabase = create_client(supabase_url, supabase_key)
                    supabase.table("entries").delete().neq("id", 0).execute()
                    print("   [OK] Supabase table cleared.")
                except Exception as ex:
                    print(f"   [FAIL] Could not clear Supabase database: {ex}")
            else:
                print("   [WARNING] Supabase credentials not set in environment. Skipping DB wipe.")

        push_to_api(unique_entries)
    else:
        print("\nNo entries found.")
