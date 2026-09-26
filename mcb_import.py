import argparse
import copy
import hashlib
import html as html_lib
import json
import math
import os
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from urllib.parse import unquote, urlencode, urljoin, urlparse

try:
    import requests as http_requests
except ImportError:
    http_requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


PORTAL_URLS = [
    'https://rainbow.myclassboard.com/StudentERP/Master_Student',
    'https://rainbow.myclassboard.com/StudentERP/Master_Student/',
    'https://rainbow.myclassboard.com/',
]
DIARY_URL = 'https://rainbow.myclassboard.com/StudentERP/StaffDiaryToStudent_CalenderView_AllActivities'
PORTAL_BASE_URL = 'https://rainbow.myclassboard.com'
API_URL = 'http://localhost:8000/api/entries'
MCB_USERNAME = os.getenv('MCB_USERNAME', '')
MCB_PASSWORD = os.getenv('MCB_PASSWORD', '')
sync_playwright = None

CANONICAL_TYPES = {'DiaryEntry', 'Worksheet', 'Announcement'}
FILE_EXTENSIONS = (
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'jpg', 'jpeg',
    'png', 'gif', 'webp', 'bmp', 'tif', 'tiff', 'zip', 'rar', '7z',
    'txt', 'csv',
)
FILE_EXTENSION_RE = re.compile(
    r'\.(?:' + '|'.join(re.escape(ext) for ext in FILE_EXTENSIONS) + r')(?:$|[?#\s])',
    re.IGNORECASE,
)
DATE_RE = re.compile(
    r'\b\d{1,2}(?:st|nd|rd|th)?\s+'
    r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|'
    r'Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|'
    r'Nov(?:ember)?|Dec(?:ember)?)\s*,?\s*\d{4}\b',
    re.IGNORECASE,
)
ISO_DATE_RE = re.compile(r'\b\d{4}-\d{2}-\d{2}\b')
NUMERIC_DATE_RE = re.compile(r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b')
TIME_RE = re.compile(r'\b\d{1,2}:\d{2}\s*(?:AM|PM)\b', re.IGNORECASE)

CANONICAL_FIELDS = (
    'type',
    'source_id',
    'date',
    'subject',
    'label',
    'teacher',
    'summary',
    'attachments',
    'attachment_url',
)
CANONICAL_TEXT_FIELDS = (
    'source_id',
    'date',
    'subject',
    'label',
    'teacher',
    'summary',
)
VERIFY_SELECT = 'source_id,entry_type,date,subject,label,teacher,summary,attachments,attachment_url'

DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_READ_TIMEOUT = 30.0
HTTP_TIMEOUT_ENV_VARS = ('MCB_HTTP_TIMEOUT', 'API_HTTP_TIMEOUT', 'IMPORT_HTTP_TIMEOUT')
NAVIGATION_TIMEOUT_MS = 30000
ACTION_TIMEOUT_MS = 15000
AJAX_TIMEOUT_MS = 30000
PAGE_TEXT_TIMEOUT_MS = 3000
READY_ATTEMPTS = 4
READY_DELAY_MS = 1000

QUIET_HOURS_START_HOUR = 0
QUIET_HOURS_END_HOUR = 6
DEFAULT_HISTORY_DAYS = 89

EMPTY_STATE_PATTERNS = {
    'diary': (
        r'no\s+diary\s+entr(?:y|ies)',
        r'there\s+are\s+no\s+diary',
        r'no\s+entr(?:y|ies)\s+(?:found|available|for)',
        r'no\s+records?\s+(?:found|available)',
        r'no\s+(?:data|results?|items?)\s+(?:found|available)?',
        r'nothing\s+to\s+show',
    ),
    'announcement': (
        r'no\s+announcements?\s*(?:found|available|for)?',
        r'there\s+are\s+no\s+announcements?',
        r'no\s+notices?\s*(?:found|available)?',
        r'no\s+records?\s+(?:found|available)',
        r'no\s+(?:data|results?|items?|entries)\s+(?:found|available)?',
        r'nothing\s+to\s+show',
    ),
    'worksheet': (
        r'no\s+(?:records?|data|questions?|assignments?|results?|items?)\s*'
        r'(?:found|available)?',
        r'no\s+questions?\s+found',
        r'no\s+worksheets?\s+(?:found|available)?',
        r'nothing\s+to\s+show',
    ),
}


class MCBImportError(RuntimeError):
    pass


class ImportTimeoutError(MCBImportError):
    pass


class PersistenceError(MCBImportError):
    def __init__(self, result):
        self.result = result
        super().__init__(result.get('message', 'Persistence failed'))


def _load_runtime_env():
    if load_dotenv is not None:
        try:
            load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
        except Exception:
            pass


def _runtime_credentials():
    global MCB_USERNAME, MCB_PASSWORD
    _load_runtime_env()
    username = (MCB_USERNAME or os.getenv('MCB_USERNAME') or '').strip()
    password = (MCB_PASSWORD or os.getenv('MCB_PASSWORD') or '').strip()
    if not username or not password:
        raise RuntimeError('MCB_USERNAME and MCB_PASSWORD must be set in .env')
    return username, password


def _require_soup():
    if BeautifulSoup is None:
        raise RuntimeError('beautifulsoup4 is required for scraping')


def _runtime_playwright():
    global sync_playwright
    if sync_playwright is None:
        try:
            from playwright.sync_api import sync_playwright as playwright_factory
        except ImportError as exc:
            raise RuntimeError('Playwright is required for scraping') from exc
        sync_playwright = playwright_factory
    return sync_playwright


def _is_timeout_error(exc):
    if isinstance(exc, TimeoutError):
        return True
    exceptions = getattr(http_requests, 'exceptions', None) if http_requests else None
    for name in ('Timeout', 'ConnectTimeout', 'ReadTimeout'):
        error_type = getattr(exceptions, name, None) if exceptions is not None else None
        if isinstance(error_type, type) and isinstance(exc, error_type):
            return True
    if type(exc).__name__ == 'TimeoutError':
        return True
    return bool(re.search(r'timed?\s*out|timeout', str(exc), re.IGNORECASE))


def _request_error(exc, method, target, timeout):
    if _is_timeout_error(exc):
        return ImportTimeoutError(
            f'{method.upper()} {target} timed out after {timeout}: {exc}'
        )
    return MCBImportError(f'{method.upper()} {target} failed: {exc}')


def http_timeouts():
    raw = ''
    for name in HTTP_TIMEOUT_ENV_VARS:
        raw = clean_text(os.getenv(name))
        if raw:
            break
    if not raw:
        return (DEFAULT_CONNECT_TIMEOUT, DEFAULT_READ_TIMEOUT)
    parts = [part for part in re.split(r'[,;x:\s]+', raw) if part]
    values = []
    for part in parts:
        try:
            value = float(part)
        except ValueError:
            raise MCBImportError(
                f'invalid HTTP timeout configuration {raw!r} in '
                f'{" or ".join(HTTP_TIMEOUT_ENV_VARS)}'
            ) from None
        if not math.isfinite(value) or value <= 0:
            raise MCBImportError(
                f'HTTP timeouts must be positive and finite, got {raw!r}'
            )
        values.append(value)
    connect = values[0]
    read = values[1] if len(values) > 1 else values[0]
    return (connect, read)


def _session_call(session, method, target, timeout=None, **kwargs):
    if session is None and http_requests is None:
        raise MCBImportError('requests is required for HTTP access')
    active = session if session is not None else http_requests
    if timeout is None:
        timeout = http_timeouts()
    try:
        return getattr(active, method)(target, timeout=timeout, **kwargs)
    except Exception as exc:
        raise _request_error(exc, method, target, timeout) from exc


def _known_empty_state(source, text):
    patterns = EMPTY_STATE_PATTERNS.get(source, ())
    return any(re.search(pattern, text or '', re.IGNORECASE) for pattern in patterns)


def _require_collected_entries(source, html, entries):
    if entries:
        return list(entries)
    text = html if isinstance(html, str) else json.dumps(html, default=str)
    if _known_empty_state(source, clean_text(text)):
        return []
    raise MCBImportError(
        f'{source} page returned no entries and no recognised empty state'
    )


def _page_content(page):
    try:
        return page.content()
    except Exception as exc:
        raise MCBImportError(f'page content was unavailable: {exc}') from exc


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
    for locator in locators or []:
        try:
            if locator.count() > 0 and set_input_value(locator, value):
                return True
        except Exception:
            continue
    return False


def find_first_match(scope, selectors):
    for selector in selectors or []:
        try:
            locator = scope.locator(selector)
            if locator.count() > 0:
                return locator.first
        except Exception:
            continue
    return None


def find_login_scope(page):
    password_selectors = (
        "input[type='password']",
        "input#txtPassword",
        "input#txtPass",
        "input[id*='pass' i]",
        "input[name*='pass' i]",
    )
    frames = getattr(page, 'frames', None) or [page]
    for frame in frames:
        try:
            if any(frame.locator(selector).count() > 0 for selector in password_selectors):
                return frame
        except Exception:
            continue
    return page


def clean_text(text):
    if text is None:
        return ''
    return re.sub(r'\s+', ' ', str(text)).strip()


def class_tokens(node):
    raw = node.get('class') or []
    if isinstance(raw, str):
        return raw.split()
    return list(raw)


def has_class(node, name):
    return name in class_tokens(node)


def _class_contains(node, name):
    return any(name.lower() in token.lower() for token in class_tokens(node))


def parse_date_value(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    text = clean_text(value)
    if not text:
        return None
    iso_match = ISO_DATE_RE.search(text)
    if iso_match:
        try:
            return datetime.strptime(iso_match.group(0), '%Y-%m-%d').date()
        except ValueError:
            pass
    date_match = DATE_RE.search(text)
    if date_match:
        raw = re.sub(r'(\d)(st|nd|rd|th)\b', r'\1', date_match.group(0), flags=re.I)
        raw = re.sub(r'\s+', ' ', raw.replace(',', ' ')).strip()
        for fmt in ('%d %b %Y', '%d %B %Y'):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
    numeric_match = NUMERIC_DATE_RE.search(text)
    if numeric_match:
        raw = numeric_match.group(0)
        formats = ['%d/%m/%Y', '%d-%m-%Y', '%m/%d/%Y', '%m-%d-%Y']
        if re.fullmatch(r'\d{1,2}[/-]\d{1,2}[/-]\d{2}', raw):
            formats = [fmt + '%y' for fmt in formats]
        for fmt in formats:
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
    return None


def normalize_date(value, default=None):
    parsed = parse_date_value(value)
    if parsed is not None:
        return parsed.isoformat()
    if default is not None:
        return normalize_date(default)
    return None


def format_portal_date(value):
    parsed = parse_date_value(value)
    return parsed.strftime('%d %b %Y') if parsed else clean_text(value)


def extract_time(value):
    match = TIME_RE.search(clean_text(value))
    return match.group(0).upper() if match else ''


def to_date_obj(date_str):
    return parse_date_value(date_str) or date.today()


def extract_worksheet_title(summary):
    title = clean_text(summary)
    title = re.sub(r'^[A-Z]\s+', '', title)
    weekday = re.search(r'\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s*,', title, re.IGNORECASE)
    if weekday:
        title = title[:weekday.start()].strip()
    else:
        date_match = re.search(
            r'\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b',
            title,
            re.IGNORECASE,
        )
        if date_match:
            title = title[:date_match.start()].strip()
    title = re.sub(r'\bExpired\b\s*$', '', title, flags=re.IGNORECASE).strip()
    subjects = (
        'Information Technology', 'Social Studies', 'Physical Education',
        'General Knowledge', 'Computer Science', 'Mathematics', 'Science',
        'English', 'Social Study', 'Sanskrit', 'Kannada', 'Computer', 'Maths',
        'Physics', 'Chemistry', 'Biology', 'Hindi', 'French', 'Social',
        'Music', 'Art', 'Math', 'IT', 'GK', 'PE',
    )
    subject_pattern = r'[\s\-,]+(?:' + '|'.join(re.escape(value) for value in subjects) + r')\s*$'
    title = re.sub(subject_pattern, '', title, flags=re.IGNORECASE).strip()
    title = re.sub(subject_pattern, '', title, flags=re.IGNORECASE).strip()
    title = re.sub(r'[\-, \t]+$', '', title).strip()
    return re.sub(r'\s+', ' ', title).strip()


def detect_subject(title, summary, teacher):
    combined = ' '.join(clean_text(value) for value in (title, summary, teacher)).casefold()
    if any(value in combined for value in ('hindi', 'savita vyas', 'साखी', 'पाठ', 'पद्य')):
        return 'Hindi'
    if any(value in combined for value in ('sanskrit', 'संस्कृत')):
        return 'Sanskrit'
    if 'kannada' in combined:
        return 'Kannada'
    if 'french' in combined:
        return 'French'
    if any(value in combined for value in (
        'social science', 'social studies', 'social study', 'riddhi shah',
        'history', 'geography', 'civics', 'economics', 'sst',
    )):
        return 'Social Studies'
    if any(value in combined for value in ('math', 'mathematics', 'maths')):
        return 'Maths'
    if any(value in combined for value in ('science', 'physics', 'chemistry', 'biology', 'sneha nair', 'sneha')):
        return 'Science'
    if any(value in combined for value in ('information technology', 'computer', 'programming')) or re.search(r'\bit\b', combined):
        return 'IT'
    if 'english' in combined:
        return 'English'
    subject_words = (
        ('maths', 'Maths'), ('mathematics', 'Maths'), ('math', 'Maths'),
        ('science', 'Science'), ('physics', 'Science'), ('chemistry', 'Science'),
        ('biology', 'Science'), ('english', 'English'), ('social', 'Social Studies'),
        ('sst', 'Social Studies'), ('hindi', 'Hindi'), ('it', 'IT'),
        ('computer', 'IT'), ('sanskrit', 'Sanskrit'), ('kannada', 'Kannada'),
        ('french', 'French'),
    )
    title_text = clean_text(title).casefold()
    for word, subject in subject_words:
        if re.search(r'(?<!\w)' + re.escape(word) + r'(?!\w)', title_text):
            return subject
    return clean_text(title) or 'General'


def detect_properties(title, summary, attachment_url):
    combined = ' '.join(clean_text(value) for value in (title, summary, attachment_url)).casefold()
    is_answer_key = any(re.search(pattern, combined) for pattern in (
        r'\banswer\s*key\b', r'\banswerkey\b', r'\bans\s*key\b',
        r'\banskey\b', r'\bak\b', r'\bak[\._]',
    ))
    is_revision = any(re.search(pattern, combined) for pattern in (
        r'\brevision\b', r'\bpa\s*[-–_]?\s*[i1]\b', r'\brs\b',
        r'\brevision\s*sheet\b', r'\brevision\s*worksheet\b',
    ))
    return is_revision, is_answer_key


def extract_number(title, summary):
    title_text = clean_text(title).casefold()
    summary_text = clean_text(summary).casefold()
    title_text = re.sub(r'\b[oO](\d+)\b', r'0\1', title_text)
    prefixes = r'worksheet|ws|sheet|wk|revision|rs|pa'
    title_patterns = (
        rf'(?:{prefixes})\s*(?:-|–|_|\b)?\s*0*([1-9]\d*)\b',
        r'\b0*([1-9]\d*)\b',
    )
    for pattern in title_patterns:
        matches = re.findall(pattern, title_text)
        if matches:
            return int(matches[0])
    roman_map = {'i': 1, 'ii': 2, 'iii': 3, 'iv': 4, 'v': 5, 'vi': 6, 'vii': 7, 'viii': 8, 'ix': 9, 'x': 10}
    for text, allow_plain in ((title_text, False), (summary_text, True)):
        patterns = [rf'(?:{prefixes})\s*(?:-|–|_|\b)?\s*\b([ivx]+)\b']
        if text is title_text and allow_plain:
            patterns.append(r'\b0*([1-9]\d*)\b')
        for pattern in patterns:
            matches = re.findall(pattern, text)
            if matches:
                value = matches[0]
                if value in roman_map:
                    return roman_map[value]
                if value.isdigit():
                    return int(value)
        if not allow_plain:
            matches = re.findall(rf'(?:{prefixes})\s*(?:-|–|_|\b)?\s*0*([1-9]\d*)\b', text)
            if matches:
                return int(matches[0])
    return None


def _supabase_config():
    _load_runtime_env()
    return (
        clean_text(os.getenv('SUPABASE_URL')),
        clean_text(os.getenv('SUPABASE_KEY') or os.getenv('SUPABASE_SERVICE_ROLE_KEY')),
    )


def _supabase_entries_url(base_url=None, table='entries'):
    if base_url is None:
        base_url, _ = _supabase_config()
    base_url = clean_text(base_url).rstrip('/')
    if not base_url:
        return ''
    path = urlparse(base_url).path.rstrip('/')
    if path.endswith('/rest/v1'):
        return f'{base_url}/{table}'
    if path.endswith('/rest/v1/entries') and table == 'entries':
        return base_url
    return f'{base_url}/rest/v1/{table}'


def _supabase_headers(supabase_key, headers=None):
    request_headers = dict(headers or {})
    request_headers.setdefault('apikey', supabase_key)
    request_headers.setdefault('Authorization', f'Bearer {supabase_key}')
    return request_headers


def _supabase_rows_to_entries(rows):
    entries = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        entry = canonicalize_entry({
            'subject': row.get('subject'),
            'summary': row.get('summary'),
            'date': row.get('date'),
            'teacher': row.get('teacher'),
            'attachment_url': row.get('attachment_url'),
            'attachments': row.get('attachments'),
            'type': row.get('entry_type') or row.get('type'),
            'source_id': row.get('source_id'),
            '_source': 'Worksheet',
        })
        if entry['subject']:
            entries.append(entry)
    return entries


def fetch_existing_worksheets(session=None):
    _load_runtime_env()
    supabase_url, supabase_key = _supabase_config()
    failures = []
    if supabase_url and supabase_key:
        try:
            query = urlencode({
                'entry_type': 'eq.Worksheet',
                'select': 'id,source_id,entry_type,subject,summary,date,teacher,attachments,attachment_url',
                'limit': '1000',
            })
            response = _session_call(
                session,
                'get',
                f'{_supabase_entries_url(supabase_url)}?{query}',
                headers=_supabase_headers(supabase_key),
            )
            status = getattr(response, 'status_code', 0)
            if 200 <= status < 300:
                rows = _response_json(response)
                if not isinstance(rows, list):
                    raise MCBImportError('supabase worksheet lookup returned a malformed body')
                return _supabase_rows_to_entries(rows)
            failures.append(f'supabase returned HTTP {status}')
        except ImportTimeoutError:
            raise
        except Exception as exc:
            failures.append(f'supabase failed: {exc}')
    if http_requests is None and session is None:
        if failures:
            raise MCBImportError('; '.join(failures))
        return []
    try:
        target = API_URL.rstrip('/') + '?' + urlencode({'entry_type': 'Worksheet', 'limit': 1000})
        response = _session_call(session, 'get', target)
        status = getattr(response, 'status_code', 0)
        if 200 <= status < 300:
            rows = _response_json(response)
            if not isinstance(rows, list):
                raise MCBImportError('local worksheet lookup returned a malformed body')
            return _supabase_rows_to_entries(rows)
        failures.append(f'local API returned HTTP {status}')
    except ImportTimeoutError:
        raise
    except Exception as exc:
        failures.append(f'local API failed: {exc}')
    raise MCBImportError('existing worksheet lookup failed: ' + '; '.join(failures))


def _score_attachment_candidate(value):
    low = clean_text(value).lower().replace('\\', '/')
    score = 0
    if low.startswith(('http://', 'https://', '//')):
        score += 25
    if 'cdn-mcb' in low or 'myclassboard.com' in low:
        score += 20
    if 'studenterp' in low:
        score += 18
    if '/upload' in low or 'uploads' in low or 'download' in low or '/content/' in low:
        score += 12
    if '/' in low:
        score += 10
    path = low.split('?', 1)[0].split('#', 1)[0]
    if FILE_EXTENSION_RE.search(path + ' '):
        score += 8
    if re.match(r'^[a-z0-9_. -]+$', low, re.I) and '.' in low:
        score += 3
    return score


def _looks_like_filename(value):
    if not value:
        return False
    low = clean_text(value).lower().replace('\\', '/')
    path = low.split('?', 1)[0].split('#', 1)[0]
    return bool(FILE_EXTENSION_RE.search(path + ' '))


def _looks_like_url_or_path(value):
    text = clean_text(value).replace('\\', '/')
    if not text:
        return False
    low = text.lower()
    return (
        low.startswith(('http://', 'https://', '//', '/', './', '../', '~/'))
        or '/' in text
        or _looks_like_filename(text)
    )


def _attachment_base(context=None):
    return str(context) if context else f'{PORTAL_BASE_URL.rstrip("/")}/StudentERP/'


def _normalize_attachment_url(candidate, context=None):
    candidate = html_lib.unescape(clean_text(candidate)).strip()
    if not candidate:
        return None
    low = candidate.lower()
    if low.startswith(('javascript:', 'void', '#', 'mailto:', 'tel:', 'data:')):
        return None
    if low.startswith('//'):
        candidate = 'https:' + candidate
    elif not low.startswith(('http://', 'https://')):
        if candidate.startswith('~/'):
            candidate = candidate[1:]
        candidate = urljoin(_attachment_base(context), candidate)
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {'http', 'https'} or not parsed.netloc:
        return None
    return candidate


def _function_body(text, function_name):
    if not text:
        return None
    match = re.search(r'\b' + re.escape(function_name) + r'\s*\(', text, re.IGNORECASE)
    if not match:
        return None
    start = match.end()
    depth = 1
    quote = None
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
        elif char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
            if depth == 0:
                return text[start:index]
    return None


def _split_arguments(body):
    if body is None:
        return []
    args = []
    current = []
    quote = None
    escaped = False
    for char in body:
        if quote:
            current.append(char)
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ("'", '"'):
            quote = char
            current.append(char)
        elif char == ',':
            args.append(''.join(current))
            current = []
        else:
            current.append(char)
    args.append(''.join(current))
    decoded = []
    for arg in args:
        value = clean_text(arg)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
            value = value.replace("\\'", "'").replace('\\"', '"').replace('\\\\', '\\')
        decoded.append(html_lib.unescape(value))
    return decoded


def _call_arguments(text, function_name):
    return _split_arguments(_function_body(text, function_name))


def _url_filename(url):
    if not url:
        return ''
    return clean_text(unquote(urlparse(url).path).rsplit('/', 1)[-1])


def parse_viewfile_call(onclick, context=None):
    if not onclick or 'viewfile' not in onclick.lower():
        return None, None
    args = _split_arguments(_function_body(onclick, 'ViewFile'))
    if not args:
        return None, None
    name = None
    url = None
    if len(args) >= 2:
        first, second = args[0], args[1]
        first_is_url = first.lower().startswith(('http://', 'https://', '//', '/', './', '../'))
        second_is_url = second.lower().startswith(('http://', 'https://', '//', '/', './', '../'))
        if not first_is_url or (first_is_url and not second_is_url):
            name = first
        url = _normalize_attachment_url(second, context)
        if url is None:
            for candidate in args[1:]:
                url = _normalize_attachment_url(candidate, context)
                if url:
                    break
        if name is None and not _looks_like_url_or_path(first):
            name = first
    if url is None:
        candidates = []
        for index, candidate in enumerate(args):
            candidate_url = _normalize_attachment_url(candidate, context)
            if candidate_url:
                candidates.append((_score_attachment_candidate(candidate) - index, candidate_url))
        if candidates:
            url = max(candidates, key=lambda item: item[0])[1]
    if name is None:
        for candidate in args:
            if candidate.lower() in {'1', '0', 'true', 'false'}:
                continue
            if _looks_like_filename(candidate) and not _looks_like_url_or_path(candidate):
                name = candidate
                break
    if not name:
        name = _url_filename(url) or None
    return clean_text(name) if name else None, url


def _attachment_url_from_onclick(onclick, context=None):
    return parse_viewfile_call(onclick, context)[1]


def _is_generic_attachment_name(name):
    return clean_text(name).lower().rstrip(':') in {
        '', 'attachment', 'attachments', 'file', 'download', 'view file',
    }


def _visible_attachment_name(element, fallback=None):
    if element is not None:
        for attr in ('data-filename', 'data-file-name', 'title', 'download'):
            value = element.get(attr)
            if value and not _is_generic_attachment_name(value):
                return clean_text(value)
        text = clean_text(element.get_text(' ', strip=True)) if hasattr(element, 'get_text') else ''
        if text and not _is_generic_attachment_name(text) and (
            _looks_like_filename(text) or element.name in {'a', 'button'}
        ):
            return text
        sibling = element.find_next_sibling()
        checked = 0
        while sibling is not None and checked < 8:
            sibling_text = clean_text(sibling.get_text(' ', strip=True)) if hasattr(sibling, 'get_text') else clean_text(str(sibling))
            if sibling_text and not _is_generic_attachment_name(sibling_text):
                if _looks_like_filename(sibling_text) or sibling.name in {'span', 'a', 'small'}:
                    return sibling_text
            sibling = sibling.find_next_sibling()
            checked += 1
    if fallback and not _is_generic_attachment_name(fallback):
        return clean_text(fallback)
    return None


def _is_icon_url(url):
    path = clean_text(url).lower().split('?', 1)[0].split('#', 1)[0]
    return bool(re.search(r'(?:^|[/_-])(?:favicon|icon|logo)(?:[/_.-]|$)', path))


def _href_is_attachment(href):
    if not href:
        return False
    low = html_lib.unescape(href).strip().lower()
    if low.startswith(('javascript:', '#', 'void', 'mailto:', 'tel:', 'data:')):
        return False
    path = low.split('?', 1)[0].split('#', 1)[0]
    if _is_icon_url(low):
        return False
    return bool(
        FILE_EXTENSION_RE.search(path + ' ')
        or '/download' in path
        or '/upload' in path
        or 'docviewer/fileread' in path
    )


def _parse_attachment_link(link, context=None):
    if link is None:
        return None, None
    name = _visible_attachment_name(link)
    href = html_lib.unescape((link.get('href') or '').strip())
    if href and not href.lower().startswith(('javascript:', '#', 'void', 'mailto:', 'tel:')):
        href = unquote(href.split('#', 1)[0])
        if _href_is_attachment(href):
            url = _normalize_attachment_url(href, context)
            if url:
                return name or _url_filename(url) or 'Attachment', url
    view_name, view_url = parse_viewfile_call(link.get('onclick') or '', context)
    return name or view_name, view_url


def collect_attachments(node, context=None):
    if node is None:
        return []
    found = []
    by_url = {}
    elements = [node] + list(node.find_all(True)) if hasattr(node, 'find_all') else []
    for element in elements:
        onclick = element.get('onclick', '') if hasattr(element, 'get') else ''
        if onclick and 'viewfile' in onclick.lower():
            name, url = parse_viewfile_call(onclick, context)
            visible_name = _visible_attachment_name(element, name)
            if url:
                normalized = _normalize_attachment_url(url, context)
                if normalized:
                    display = visible_name or name or _url_filename(normalized) or 'Attachment'
                    if normalized not in by_url:
                        by_url[normalized] = {'name': display, 'url': normalized}
                        found.append(by_url[normalized])
                    elif _is_generic_attachment_name(by_url[normalized].get('name')):
                        by_url[normalized]['name'] = display
        href = element.get('href', '') if hasattr(element, 'get') else ''
        if href and _href_is_attachment(href):
            name, url = _parse_attachment_link(element, context)
            if url:
                normalized = _normalize_attachment_url(url, context)
                if normalized and normalized not in by_url:
                    by_url[normalized] = {'name': name or _url_filename(normalized) or 'Attachment', 'url': normalized}
                    found.append(by_url[normalized])
    return found


def normalize_attachments(value):
    if value is None or value == '':
        return []
    if isinstance(value, str):
        text = value.strip()
        if text.startswith('[') or text.startswith('{'):
            try:
                value = json.loads(text)
            except (TypeError, ValueError):
                value = [{'name': '', 'url': text}]
        else:
            value = [{'name': '', 'url': text}]
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    result = []
    seen = set()
    for item in value:
        if isinstance(item, str):
            item = {'url': item}
        if not isinstance(item, dict):
            continue
        url = _normalize_attachment_url(item.get('url') or item.get('href') or item.get('path'))
        if not url or url in seen or _is_icon_url(url):
            continue
        seen.add(url)
        name = clean_text(item.get('name') or item.get('filename') or '')
        if _is_generic_attachment_name(name):
            name = ''
        result.append({'name': name or _url_filename(url) or 'Attachment', 'url': url})
    return result


def serialize_attachments(attachments):
    normalized = normalize_attachments(attachments)
    return json.dumps(normalized, ensure_ascii=False, separators=(',', ':')) if normalized else None


def _normalized_identity_text(value):
    text = unicodedata.normalize('NFKC', clean_text(value)).casefold()
    return re.sub(r'\s+', ' ', text).strip()


def _fingerprint(fields):
    payload = {
        'type': fields.get('type') or '',
        'date': fields.get('date') or '',
        'subject': _normalized_identity_text(fields.get('subject')),
        'label': _normalized_identity_text(fields.get('label')),
        'teacher': _normalized_identity_text(fields.get('teacher')),
        'summary': _normalized_identity_text(fields.get('summary')),
        'attachments': [
            {
                'name': _normalized_identity_text(item.get('name')),
                'url': item.get('url'),
            }
            for item in fields.get('attachments', [])
        ],
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return 'fingerprint:' + hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _canonical_type(value, source=None):
    raw = clean_text(value)
    if raw in CANONICAL_TYPES:
        return raw
    source_value = clean_text(source)
    if source_value in CANONICAL_TYPES:
        return source_value
    if source_value in {'Announcement', 'Announcements'}:
        return 'Announcement'
    if source_value in {'Worksheet', 'Assignment', 'Assignments'}:
        return 'Worksheet'
    return 'DiaryEntry'


def canonicalize_entry(entry, fallback_date=None):
    original = dict(entry or {})
    entry_type = _canonical_type(
        original.get('type') or original.get('entry_type'),
        original.get('_source'),
    )
    subject = clean_text(original.get('subject') or original.get('title') or '')
    label = clean_text(original.get('label') or original.get('category') or '')
    teacher = clean_text(original.get('teacher') or original.get('author') or '')
    if teacher.lower() == 'attachments':
        teacher = ''
    if not teacher:
        teacher = 'Unknown'
    summary = clean_text(original.get('summary') or original.get('description') or '')
    attachments = normalize_attachments(original.get('attachments') or original.get('attachment_url'))
    date_value = normalize_date(original.get('date'), fallback_date) or ''
    source_id = clean_text(original.get('source_id') or '')
    if not source_id:
        source_id = _fingerprint({
            'type': entry_type,
            'date': date_value,
            'subject': subject,
            'label': label,
            'teacher': teacher,
            'summary': summary,
            'attachments': attachments,
        })
    result = {
        'type': entry_type,
        'source_id': source_id,
        'date': date_value,
        'subject': subject,
        'label': label,
        'teacher': teacher,
        'summary': summary,
        'attachments': copy.deepcopy(attachments),
        'attachment_url': serialize_attachments(attachments),
    }
    return result


def validate_canonical_entry(entry):
    if not isinstance(entry, dict):
        raise MCBImportError('canonical entry must be a mapping')
    missing = [field for field in CANONICAL_FIELDS if field not in entry]
    unexpected = sorted(set(entry) - set(CANONICAL_FIELDS))
    if missing or unexpected:
        raise MCBImportError(
            'canonical entry is not exact and complete '
            f'(missing: {missing or "none"}; unexpected: {unexpected or "none"})'
        )
    if entry['type'] not in CANONICAL_TYPES:
        raise MCBImportError(f'canonical type is not recognised: {entry["type"]!r}')
    for field in CANONICAL_TEXT_FIELDS:
        if not isinstance(entry[field], str):
            raise MCBImportError(f'canonical field {field} must be a string')
    if entry['attachment_url'] is not None and not isinstance(entry['attachment_url'], str):
        raise MCBImportError('canonical field attachment_url must be text or null')
    for field in ('source_id', 'date', 'subject'):
        if not clean_text(entry[field]):
            raise MCBImportError(f'canonical field {field} must not be empty')
    if normalize_date(entry['date']) is None:
        raise MCBImportError(f'canonical date is not a valid date: {entry["date"]!r}')
    attachments = entry['attachments']
    if not isinstance(attachments, list):
        raise MCBImportError('canonical field attachments must be a list')
    for item in attachments:
        if not isinstance(item, dict) or set(item) != {'name', 'url'}:
            raise MCBImportError(
                'canonical attachments must be objects with exactly name and url'
            )
        if not isinstance(item['name'], str) or not isinstance(item['url'], str):
            raise MCBImportError('canonical attachment fields must be strings')
        if not clean_text(item['url']):
            raise MCBImportError('canonical attachment url must not be empty')
    if entry['attachment_url'] != serialize_attachments(attachments):
        raise MCBImportError(
            'canonical attachment_url does not match the canonical attachments'
        )
    return True


def _entry_key(entry):
    raw = dict(entry or {})
    explicit_source_id = clean_text(raw.get('source_id'))
    normalized = canonicalize_entry(raw)
    if explicit_source_id:
        return 'source', normalized['type'], explicit_source_id
    return (
        'content',
        normalized['type'],
        normalized['date'],
        _normalized_identity_text(normalized['subject']),
        _normalized_identity_text(normalized['teacher']),
        _normalized_identity_text(normalized['summary']),
    )


def _merge_entry_values(first, second):
    merged = canonicalize_entry(first)
    other = canonicalize_entry(second)
    for field in ('subject', 'label', 'date', 'source_id'):
        if not clean_text(merged.get(field)) and clean_text(other.get(field)):
            merged[field] = other[field]
    if other.get('teacher') not in {'', 'Unknown', merged.get('teacher')}:
        merged['teacher'] = other['teacher']
    first_summary = clean_text(merged.get('summary'))
    second_summary = clean_text(other.get('summary'))
    if second_summary and second_summary not in first_summary and first_summary not in second_summary:
        merged['summary'] = clean_text((first_summary + ' | ' + second_summary).strip(' |'))
    merged['attachments'] = normalize_attachments(
        list(merged.get('attachments', [])) + list(other.get('attachments', []))
    )
    for key, value in other.items():
        if key not in merged or merged[key] in (None, '', []):
            merged[key] = copy.deepcopy(value)
    return canonicalize_entry(merged)


def deduplicate_entries(entries):
    unique = []
    positions = {}
    for entry in entries or []:
        key = _entry_key(entry)
        if key not in positions:
            positions[key] = len(unique)
            unique.append(canonicalize_entry(entry))
        else:
            index = positions[key]
            unique[index] = _merge_entry_values(unique[index], entry)
    return unique


def _remove_attachment_artifacts(text, attachments):
    result = clean_text(text)
    if not result:
        return ''
    result = re.sub(r'\battachments?\s*:\s*', '', result, flags=re.IGNORECASE)
    candidates = []
    for item in attachments or []:
        candidates.extend([item.get('name', ''), _url_filename(item.get('url', ''))])
    for candidate in sorted(set(value for value in candidates if value), key=len, reverse=True):
        result = re.sub(
            r'(?i)(?<![\w])' + re.escape(clean_text(candidate)) + r'(?![\w])',
            '',
            result,
        )
    for item in attachments or []:
        if item.get('url'):
            result = result.replace(item['url'], '')
    return clean_text(result)


def _card_for_node(node):
    current = node
    while current is not None:
        if _class_contains(current, 'card'):
            return current
        current = current.parent
    return node


def _node_has_call(node, function_name):
    if node is None:
        return False
    values = []
    if hasattr(node, 'get'):
        values.append(node.get('onclick', ''))
    if hasattr(node, 'find_all'):
        values.extend(element.get('onclick', '') for element in node.find_all(onclick=True))
    return any(function_name.lower() in (value or '').lower() for value in values)


def extract_diary_entries(html, diary_date):
    _require_soup()
    soup = BeautifulSoup(html or '', 'html.parser')
    page_text = clean_text(soup.get_text(' ', strip=True))
    if re.search(r'no diary entries|no diary entry|there are no diary', page_text, re.I):
        return []
    entries = []
    bodies = soup.find_all(
        'div',
        class_=lambda value: value and 'card-body' in (
            value.split() if isinstance(value, str) else value
        ),
    )
    for body in bodies:
        summary_node = body.find('div', class_='summery-class')
        if summary_node is None:
            summary_node = body.find(class_=re.compile(r'summery-class', re.I))
        if summary_node is None:
            continue
        card = _card_for_node(body)
        badge = body.find(
            'span',
            class_=lambda value: value and 'badge' in (
                value.split() if isinstance(value, str) else value
            ),
        )
        if badge is None:
            badge = card.find(
                'span',
                class_=lambda value: value and 'badge' in (
                    value.split() if isinstance(value, str) else value
                ),
            )
        teacher_node = body.find(
            'span', style=lambda value: value and 'darkgray' in value.lower()
        )
        if teacher_node is None:
            teacher_node = card.find(
                'span', style=lambda value: value and 'darkgray' in value.lower()
            )
        subject_node = body.find_previous(['h6', 'h5', 'h4'])
        subject = clean_text(subject_node.get_text(' ', strip=True)) if subject_node else ''
        attachments = collect_attachments(card)
        summary = _remove_attachment_artifacts(
            summary_node.get_text(' ', strip=True), attachments
        )
        label = clean_text(badge.get_text(' ', strip=True)) if badge else ''
        teacher = clean_text(teacher_node.get_text(' ', strip=True)) if teacher_node else ''
        source_id = None
        for element in [card, body] + list(card.find_all(True)):
            onclick = element.get('onclick', '') if hasattr(element, 'get') else ''
            match = re.search(
                r'(?:Submit|Diary|ViewDiary)[^(]*\(?\s*[\'\"]?(-?\d+)[\'\"]?\s*,\s*[\'\"]?(-?\d+)',
                onclick,
                re.I,
            )
            if match:
                source_id = f'diary:{match.group(1)}:{match.group(2)}'
                break
            identifier = clean_text(element.get('id'))
            if identifier and re.search(r'diary|entry', identifier, re.I):
                source_id = identifier
                break
        entry = {
            'type': 'DiaryEntry',
            'subject': subject or 'Unknown',
            'label': label,
            'teacher': teacher,
            'summary': summary,
            'attachments': attachments,
            'date': normalize_date(diary_date),
        }
        if source_id:
            entry['source_id'] = source_id
        entries.append(canonicalize_entry(entry))
    return entries


def _announcement_nodes(soup):
    nodes = []
    seen = set()
    for node in soup.find_all(id=re.compile(r'^divRow[_-]?', re.I)):
        if not _node_has_call(node, 'fnAnnouncemetDiv'):
            continue
        marker = id(node)
        if marker not in seen:
            seen.add(marker)
            nodes.append(node)
    if nodes:
        return nodes
    for node in soup.find_all(True):
        if _node_has_call(node, 'fnAnnouncemetDiv') and (
            _class_contains(node, 'card') or node.name in {'article', 'li'}
        ):
            marker = id(node)
            if marker not in seen:
                seen.add(marker)
                nodes.append(node)
    return nodes


def _announcement_metadata(node):
    call_args = []
    for element in [node] + list(node.find_all(True)):
        onclick = element.get('onclick', '') if hasattr(element, 'get') else ''
        if onclick and 'fnannouncemetdiv' in onclick.lower():
            parsed = _call_arguments(onclick, 'fnAnnouncemetDiv')
            if len(parsed) >= 3:
                call_args = parsed
                break
    author = call_args[2] if len(call_args) > 2 else ''
    role = call_args[3] if len(call_args) > 3 else ''
    category = call_args[4] if len(call_args) > 4 else ''
    header = node.find(
        'div',
        class_=lambda value: value and 'card-header' in (
            value.split() if isinstance(value, str) else value
        ),
    ) or node
    if not author:
        for label in header.find_all('label'):
            text = clean_text(label.get_text(' ', strip=True))
            if text and not re.match(r'attachments?', text, re.I):
                author = text
                break
    if not category:
        label_nodes = header.find_all(class_=re.compile(r'label', re.I))
        for label_node in label_nodes:
            text = clean_text(label_node.get_text(' ', strip=True))
            if text and text.lower() not in {'general', 'attachments'}:
                category = text
                break
        if not category:
            for label_node in label_nodes:
                text = clean_text(label_node.get_text(' ', strip=True))
                if text:
                    category = text
                    break
    if not role:
        header_text = clean_text(header.get_text(' ', strip=True))
        role_match = re.search(r'([^,]+?)\s*,', header_text)
        if role_match and clean_text(role_match.group(1)).lower() not in {
            clean_text(author).lower(), 'attachments'
        }:
            role = clean_text(role_match.group(1))
    date_text = ''
    time_text = ''
    for span in node.find_all('span'):
        text = clean_text(span.get_text(' ', strip=True))
        if DATE_RE.search(text):
            date_text = text
            time_text = extract_time(text)
            if time_text:
                break
    if not date_text:
        date_text = clean_text(node.get_text(' ', strip=True))
    portal_id = call_args[0] if call_args else ''
    if not portal_id and hasattr(node, 'get'):
        identifier = clean_text(node.get('id'))
        match = re.search(r'divRow[_-]?(.+)$', identifier, re.I)
        portal_id = match.group(1) if match else identifier
    return {
        'portal_id': clean_text(portal_id),
        'author': clean_text(author),
        'role': clean_text(role),
        'category': clean_text(category),
        'date_text': date_text,
        'time': time_text,
    }


def _attachment_ancestor(text_node, content):
    current = text_node.parent
    while current is not None and current is not content:
        if current.name in {'script', 'style'}:
            return True
        if 'viewfile' in clean_text(current.get('onclick', '')).lower():
            if current.find(onclick=re.compile(r'ViewFile', re.I)) is not None:
                return True
        labels = current.find_all(
            ['label', 'span', 'div'],
            string=re.compile(r'attachments?\s*:', re.I),
        )
        if labels and current.find(onclick=re.compile(r'ViewFile', re.I)) is not None:
            return True
        current = current.parent
    return False


def _announcement_description(node, title_node, attachments):
    content = title_node.parent if title_node is not None else None
    if content is None:
        for element in node.find_all(True):
            if _node_has_call(element, 'fnAnnouncemetDiv') and element.find(['h4', 'h5', 'h6']):
                content = element
                break
    if content is None:
        content = node
    pieces = []
    for text_node in content.find_all(string=True):
        text = clean_text(str(text_node))
        if not text:
            continue
        if title_node is not None and (text_node is title_node or title_node in text_node.parents):
            continue
        if _attachment_ancestor(text_node, content):
            continue
        pieces.append(text)
    return _remove_attachment_artifacts(clean_text(' '.join(pieces)), attachments)


def _announcement_title(node):
    candidates = []
    for selector in (
        ['h4', 'h5', 'h6'],
        ['strong', 'b'],
        {'class': re.compile(r'title|heading', re.I)},
    ):
        for candidate in node.find_all(selector):
            text = clean_text(candidate.get_text(' ', strip=True))
            if text and not re.match(r'attachments?', text, re.I) and len(text) > 1:
                candidates.append((len(text), text, candidate))
    if not candidates:
        return None, None
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2], candidates[0][1]


def extract_announcements(html, diary_date):
    _require_soup()
    soup = BeautifulSoup(html or '', 'html.parser')
    entries = []
    for node in _announcement_nodes(soup):
        metadata = _announcement_metadata(node)
        title_node, title = _announcement_title(node)
        if not title:
            continue
        attachments = collect_attachments(node)
        description = _announcement_description(node, title_node, attachments)
        if not description:
            description = title
        teacher = metadata['author'] or 'Unknown'
        entry = {
            'type': 'Announcement',
            'subject': title,
            'label': metadata['category'] or metadata['role'] or 'General',
            'category': metadata['category'],
            'role': metadata['role'],
            'author': teacher,
            'teacher': teacher,
            'summary': description,
            'attachments': attachments,
            'date': normalize_date(metadata['date_text'], diary_date) or normalize_date(diary_date) or '',
            'time': metadata['time'],
        }
        if metadata['portal_id']:
            entry['source_id'] = metadata['portal_id']
        entries.append(canonicalize_entry(entry))
    return entries


def _view_question_records(soup):
    records = []
    seen = set()
    for element in soup.find_all(onclick=re.compile(r'ViewQuestion', re.I)):
        args = _call_arguments(element.get('onclick', ''), 'ViewQuestion')
        if len(args) < 3:
            continue
        key = tuple(clean_text(value) for value in args[:3])
        if key in seen:
            continue
        seen.add(key)
        records.append({
            'element': element,
            'assignment_id': key[0],
            'qb_question_id': key[1],
            'rno': key[2],
        })
    return records


def _worksheet_source_id(assignment):
    values = [
        clean_text(assignment.get(name))
        for name in ('assignment_id', 'qb_question_id', 'rno')
        if clean_text(assignment.get(name))
    ]
    return 'worksheet:' + ':'.join(values) if values else ''


def _metadata_value(text, labels):
    flat = clean_text(text)
    for label in labels:
        match = re.search(
            re.escape(label) + r'\s*:\s*(.*?)(?=\s+(?:[A-Za-z][A-Za-z ]{1,30})\s*:|$)',
            flat,
            re.IGNORECASE,
        )
        if match:
            return clean_text(match.group(1))
    return ''


def _assignment_row_info(record, diary_date):
    element = record['element']
    card = _card_for_node(element)
    title_node = card.find(attrs={'title': True})
    title = clean_text(title_node.get('title')) if title_node else ''
    if not title:
        for heading in card.find_all(['h6', 'h5', 'h4', 'strong']):
            text = clean_text(heading.get_text(' ', strip=True))
            if text and len(text) > 1 and not re.fullmatch(r'[A-Za-z]', text):
                title = text
                break
    subject = ''
    badge_subject = card.find(class_=re.compile(r'badge-primary', re.I))
    if badge_subject:
        subject = clean_text(badge_subject.get_text(' ', strip=True))
    if not subject:
        for paragraph in card.find_all('p'):
            text = clean_text(paragraph.get_text(' ', strip=True))
            if text and not re.search(r'submission|assignment date|due date|expired', text, re.I):
                subject = text
                break
    if not subject:
        subject = _metadata_value(card.get_text(' ', strip=True), ('Subject', 'Subject Name'))
    card_text = clean_text(card.get_text(' ', strip=True))
    teacher = _metadata_value(card_text, ('Teacher', 'Teacher Name', 'Created By', 'Author'))
    if not teacher:
        teacher_node = card.find(attrs={'title': re.compile(r'teacher|faculty|author', re.I)})
        teacher = clean_text(teacher_node.get('title')) if teacher_node else ''
    date_text = ''
    date_node = card.find(attrs={'title': re.compile(r'assignment date', re.I)})
    if date_node:
        date_text = clean_text(date_node.get_text(' ', strip=True))
    if not date_text:
        match = DATE_RE.search(card_text)
        date_text = match.group(0) if match else ''
    due_text = ''
    due_node = card.find(attrs={'title': re.compile(r'due date|submission', re.I)})
    if due_node:
        due_text = clean_text(due_node.get_text(' ', strip=True))
    if not due_text:
        due_match = re.search(r'submission due date\s*(.*?)(?:\s{2,}|$)', card_text, re.I)
        due_text = clean_text(due_match.group(1)) if due_match else ''
    attachments = collect_attachments(card)
    return {
        'subject': title or subject or 'Worksheet',
        'label': subject,
        'teacher': teacher,
        'summary': _remove_attachment_artifacts(card_text, attachments),
        'attachments': attachments,
        'date': normalize_date(date_text, diary_date) or normalize_date(diary_date) or '',
        'submission_date': normalize_date(due_text) or '',
        'assignment_id': record['assignment_id'],
        'qb_question_id': record['qb_question_id'],
        'rno': record['rno'],
        'source_id': _worksheet_source_id(record),
    }


def extract_assignment_records(html, diary_date):
    _require_soup()
    soup = BeautifulSoup(html or '', 'html.parser')
    return [_assignment_row_info(record, diary_date) for record in _view_question_records(soup)]


def _detail_rno(detail):
    if not isinstance(detail, dict):
        return ''
    return clean_text(detail.get('rno') or detail.get('Rno') or detail.get('RNo') or '')


def _detail_html(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get('html') or value.get('body') or value.get('content') or ''
    return ''


def _detail_succeeded(value):
    if isinstance(value, dict):
        if value.get('error') or value.get('failed') or value.get('timeout'):
            return False
        if value.get('ok') is False or value.get('success') is False:
            return False
    return True


def _detail_rno_from_html(detail_html, fallback=''):
    for pattern in (
        r'\brno\s*[:=]\s*[\'\"]?([A-Za-z0-9_.-]+)',
        r'ViewQuestion\([^\)]*?[\'\"]([A-Za-z0-9_.-]+)[\'\"]\s*\)',
        r'QuestionAssignment/([A-Za-z0-9_.-]+)',
    ):
        match = re.search(pattern, detail_html or '', re.IGNORECASE)
        if match:
            return clean_text(match.group(1))
    return clean_text(fallback)


def _detail_root(soup):
    for selector in ('#DivMarksAssignments', '#divfirstAssignment'):
        root = soup.select_one(selector)
        if root is not None:
            return root
    return soup


def _detail_description(soup, attachments):
    root = _detail_root(soup)
    description_node = None
    for text_node in root.find_all(string=True):
        text = clean_text(str(text_node))
        if re.search(r'assignment\s+description\s*:', text, re.I):
            description_node = text_node.find_parent('p')
            if description_node is None:
                description_node = text_node.parent
                if description_node is not None and len(clean_text(description_node.get_text(' ', strip=True))) <= len(text):
                    description_node = description_node.parent
            break
    if description_node is not None:
        result = clean_text(description_node.get_text(' ', strip=True))
        result = re.sub(r'^assignment\s+description\s*:\s*', '', result, flags=re.I)
    else:
        pieces = []
        for text_node in root.find_all(string=True):
            text = clean_text(str(text_node))
            if not text:
                continue
            if re.search(r'attachments?\s*:', text, re.I):
                continue
            if re.search(r'assignment date|submission date|max marks|chapters|of\s+\d+', text, re.I):
                continue
            if _attachment_ancestor(text_node, root):
                continue
            parent_name = text_node.parent.name if text_node.parent else ''
            if parent_name in {'script', 'style', 'button', 'label'}:
                continue
            pieces.append(text)
        result = clean_text(' '.join(pieces))
    return _remove_attachment_artifacts(result, attachments)


def _detail_title(soup):
    root = _detail_root(soup)
    for selector in ('h1 label', 'h2 label', 'h3 label', 'h4 label', 'h5 label', 'h6 label'):
        label = root.select_one(selector)
        if label:
            text = clean_text(label.get_text(' ', strip=True))
            if text:
                return text
    for tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
        heading = root.find(tag)
        if heading:
            text = clean_text(heading.get_text(' ', strip=True))
            text = re.sub(r'\s+(?:Maths|Science|English|Hindi|IT|Offline|Online)\b', '', text, flags=re.I)
            if text:
                return clean_text(text)
    return ''


def _detail_metadata(soup, fallback_date=None):
    root = _detail_root(soup)
    text = clean_text(root.get_text(' ', strip=True))
    title_node = root.find(attrs={'title': re.compile(r'teacher|faculty|author', re.I)})
    teacher = clean_text(title_node.get('title')) if title_node else ''
    teacher = re.sub(r'^(?:teacher|faculty|author)\s*:\s*', '', teacher, flags=re.I)
    if not teacher:
        teacher = _metadata_value(text, ('Teacher', 'Teacher Name', 'Author', 'Created By'))
    date_text = ''
    date_node = root.find(attrs={'title': re.compile(r'assignment date', re.I)})
    if date_node:
        date_text = clean_text(date_node.get_text(' ', strip=True))
    if not date_text:
        match = re.search(r'assignment\s+date\s*:\s*(' + DATE_RE.pattern + ')', text, re.I)
        date_text = match.group(1) if match else ''
    if not date_text:
        match = DATE_RE.search(text)
        date_text = match.group(0) if match else ''
    submission_match = re.search(
        r'submission\s+(?:due\s+)?date\s*:\s*(' + DATE_RE.pattern + ')',
        text,
        re.IGNORECASE,
    )
    submission = submission_match.group(1) if submission_match else _metadata_value(
        text, ('Submission Due Date', 'Due Date', 'Submission Date')
    )
    return {
        'teacher': teacher,
        'date': normalize_date(date_text, fallback_date) or '',
        'submission_date': normalize_date(submission) or '',
    }


def _normalized_detail_map(details):
    if isinstance(details, dict):
        source = details.items()
    else:
        source = enumerate(details or [])
    result = {}
    for key, value in source:
        detail_html = _detail_html(value)
        rno = _detail_rno(value) or clean_text(key) or _detail_rno_from_html(detail_html)
        if rno in {'', '0', 'none', 'null'}:
            continue
        result[clean_text(rno)] = value
    return result


def _require_detail_response(details, assignments):
    if not _detail_succeeded(details):
        raise RuntimeError('worksheet detail request failed')
    detail_html = _detail_html(details)
    if not detail_html or not clean_text(detail_html):
        raise RuntimeError('worksheet detail response was empty')
    if re.search(r'no\s+(?:data|records|questions?)\s+(?:found|available)', detail_html, re.I):
        raise RuntimeError('worksheet detail response contained no questions')


def extract_worksheet_entries(details, assignments, diary_date=None):
    _require_soup()
    assignments = list(assignments or [])
    detail_map = _normalized_detail_map(details)
    entries = []
    failures = []
    if isinstance(details, (list, tuple)) and len(details) == 1 and len(assignments) == 1:
        only_rno = clean_text(assignments[0].get('rno'))
        if only_rno and only_rno not in detail_map:
            detail_map[only_rno] = details[0]
    for assignment in assignments:
        rno = clean_text(assignment.get('rno'))
        if not rno:
            failures.append('assignment is missing rno')
            continue
        detail = detail_map.get(rno)
        if detail is None:
            failures.append(f'no detail response for rno {rno}')
            continue
        try:
            _require_detail_response(detail, assignments)
            detail_html = _detail_html(detail)
            soup = BeautifulSoup(detail_html, 'html.parser')
            detail_root = _detail_root(soup)
            detail_attachments = collect_attachments(detail_root, context=assignment.get('detail_url'))
            description = _detail_description(detail_root, detail_attachments)
            metadata = _detail_metadata(detail_root, diary_date)
            detail_title = _detail_title(detail_root)
            if not description and not detail_title:
                failures.append(f'empty detail response for rno {rno}')
                continue
            row_attachments = normalize_attachments(assignment.get('attachments'))
            attachments = normalize_attachments(detail_attachments + row_attachments)
            original_subject = clean_text(assignment.get('subject') or assignment.get('label') or 'Worksheet')
            summary_parts = []
            if description:
                summary_parts.append(description)
            if original_subject and original_subject not in description:
                summary_parts.append('Worksheet listing: ' + original_subject)
            if assignment.get('teacher') and assignment.get('teacher') not in description:
                summary_parts.append('Teacher: ' + clean_text(assignment['teacher']))
            entry = dict(assignment)
            entry.update({
                'type': 'Worksheet',
                'subject': detail_title or original_subject,
                'label': clean_text(assignment.get('label') or assignment.get('subject') or 'Worksheet'),
                'teacher': clean_text(metadata.get('teacher') or assignment.get('teacher') or 'Unknown'),
                'date': clean_text(metadata.get('date') or assignment.get('date') or normalize_date(diary_date)),
                'summary': clean_text(' '.join(summary_parts)),
                'attachments': attachments,
                'source_id': _worksheet_source_id(assignment),
            })
            if metadata.get('submission_date'):
                entry['submission_date'] = metadata['submission_date']
            entries.append(canonicalize_entry(entry))
        except RuntimeError as exc:
            failures.append(f'rno {rno}: {exc}')
    if failures:
        raise RuntimeError('worksheet detail extraction failed: ' + '; '.join(failures))
    return entries


def smart_worksheet_title(entry):
    subject = clean_text(entry.get('subject') or entry.get('label') or 'Worksheet')
    summary = clean_text(entry.get('summary'))
    teacher = clean_text(entry.get('teacher'))
    if re.match(r'^(?:worksheet|assignment)\s*[:#-]\s*', subject, re.I):
        subject = re.sub(r'^(?:worksheet|assignment)\s*[:#-]\s*', '', subject, flags=re.I)
    if not subject or subject.casefold() in {'unknown', 'worksheet', 'assignment'}:
        first_sentence = re.split(r'(?<=[.!?])\s+', summary)[0] if summary else ''
        subject = clean_text(first_sentence)[:120] or 'Worksheet'
    if teacher and teacher.lower() != 'unknown' and teacher.casefold() not in subject.casefold():
        subject = f'{teacher}: {subject}'
    if len(subject) > 120:
        subject = subject[:117].rstrip() + '...'
    return subject


def apply_smart_worksheet_titles(entries, scrape_all=False):
    result = []
    for entry in entries or []:
        updated = canonicalize_entry(entry)
        if updated.get('type') == 'Worksheet':
            original_subject = clean_text(updated.get('subject'))
            original_summary = clean_text(updated.get('summary'))
            generated = smart_worksheet_title(updated)
            if original_subject and generated != original_subject and original_subject not in original_summary:
                updated['summary'] = clean_text(
                    'Original title: ' + original_subject + (' | ' + original_summary if original_summary else '')
                )
            updated['subject'] = generated
        result.append(updated)
    return result


def _generic_card_entries(html, diary_date, entry_type):
    _require_soup()
    soup = BeautifulSoup(html or '', 'html.parser')
    cards = soup.find_all(
        'div',
        class_=lambda value: value and 'card' in (
            value.split() if isinstance(value, str) else value
        ),
    )
    if not cards:
        cards = soup.find_all(
            'div',
            class_=lambda value: value and 'card-body' in (
                value.split() if isinstance(value, str) else value
            ),
        )
    result = []
    for card in cards:
        body = card if _class_contains(card, 'card-body') else card.find(
            'div',
            class_=lambda value: value and 'card-body' in (
                value.split() if isinstance(value, str) else value
            ),
        )
        if body is None:
            body = card
        body_text = clean_text(body.get_text(' ', strip=True))
        if not body_text or len(body_text) < 10:
            continue
        full_text = clean_text(card.get_text(' ', strip=True)).upper()
        if '23RIS0154' in full_text or 'JOVAN' in full_text:
            continue
        if entry_type == 'Worksheet':
            title = extract_worksheet_title(body_text)
        else:
            heading = body.find(['h6', 'h5', 'h4', 'strong', 'b'])
            title = clean_text(heading.get_text(' ', strip=True)) if heading else entry_type
        header = card.find(
            'div',
            class_=lambda value: value and 'card-header' in (
                value.split() if isinstance(value, str) else value
            ),
        ) or card
        teacher = ''
        label = header.find('label')
        if label:
            teacher = clean_text(label.get_text(' ', strip=True))
        if not teacher:
            dark_teacher = body.find('span', style=lambda value: value and 'darkgray' in value.lower())
            teacher = clean_text(dark_teacher.get_text(' ', strip=True)) if dark_teacher else ''
        entry_date = normalize_date(diary_date) or ''
        date_match = DATE_RE.search(clean_text(header.get_text(' ', strip=True)))
        if date_match:
            entry_date = normalize_date(date_match.group(0), diary_date) or entry_date
        if not entry_date:
            date_match = DATE_RE.search(body_text)
            if date_match:
                entry_date = normalize_date(date_match.group(0), diary_date) or entry_date
        result.append(canonicalize_entry({
            'subject': title or entry_type,
            'type': entry_type,
            'teacher': teacher or ('System' if entry_type == 'Announcement' else 'Teacher'),
            'summary': body_text[:500],
            'attachments': collect_attachments(card),
            'date': entry_date,
        }))
    return result


def extract_generic_cards(html, diary_date, default_type=None):
    if default_type is None:
        default_type = 'DiaryEntry'
    if diary_date in CANONICAL_TYPES and parse_date_value(default_type) is not None:
        diary_date, default_type = default_type, diary_date
    entry_type = _canonical_type(default_type, default_type)
    if entry_type == 'Announcement':
        specialized = extract_announcements(html, diary_date)
    elif entry_type == 'DiaryEntry':
        specialized = extract_diary_entries(html, diary_date)
    else:
        specialized = []
    return specialized or _generic_card_entries(html, diary_date, entry_type)


def _safe_page_text(page):
    try:
        return clean_text(
            page.locator('body').inner_text(timeout=PAGE_TEXT_TIMEOUT_MS)
        )
    except Exception:
        try:
            return clean_text(page.content())
        except Exception:
            return ''


def ensure_authenticated(page):
    text = _safe_page_text(page).lower()
    login_markers = (
        'invalid username', 'invalid password', 'login failed', 'sign in',
        'username', 'password',
    )
    auth_markers = (
        'logout', 'log out', 'student dashboard', 'diary', 'worksheet',
        'announcement', 'master_student',
    )
    if any(marker in text for marker in login_markers) and not any(
        marker in text for marker in auth_markers
    ):
        raise MCBImportError('MCB login was not accepted')
    try:
        password_inputs = page.locator('input[type="password"]').count()
    except Exception:
        password_inputs = 0
    if password_inputs and not any(marker in text for marker in ('logout', 'log out')):
        raise MCBImportError('MCB session is still on the login page')
    try:
        has_portal = page.locator('a[href*="StudentERP"], a[href*="Master_Student"]').count() > 0
    except Exception:
        has_portal = False
    if not has_portal and not any(marker in text for marker in ('diary', 'worksheet', 'announcement', 'logout')):
        raise MCBImportError('Unable to verify an authenticated MCB page')
    return True


def _sleep(page, delay_ms):
    try:
        page.wait_for_timeout(delay_ms)
    except Exception:
        pass


def _wait_until_ready(check, page=None, attempts=READY_ATTEMPTS, delay_ms=READY_DELAY_MS):
    last_error = None
    for attempt in range(max(1, attempts)):
        try:
            if check():
                return True
        except MCBImportError as exc:
            last_error = exc
        if attempt + 1 < max(1, attempts) and page is not None:
            _sleep(page, delay_ms)
    if last_error is not None:
        raise last_error
    raise MCBImportError('MCB portal did not reach a ready state')


LOGIN_LINK_SELECTORS = (
    "text=Click here to Login",
    "button:has-text('Click here to Login')",
    "a:has-text('Click here to Login')",
)
USERNAME_SELECTORS = (
    'input#txtUserName', 'input#txtUsername', 'input#txtUser',
    'input#username', 'input#UserName', 'input#LoginID',
    'input#txtLoginId', 'input#txtEmail', 'input[type="text"]',
    'input[type="email"]', 'input[autocomplete="username" i]',
    'input[placeholder*="user" i]', 'input[name*="user" i]',
)
PASSWORD_SELECTORS = (
    'input#txtPassword', 'input#txtPass', 'input#txtPwd',
    'input#password', 'input[type="password"]',
    'input[autocomplete="current-password" i]',
    'input[placeholder*="pass" i]', 'input[name*="pass" i]',
)
SUBMIT_SELECTORS = (
    '#LogID', '#btnLogin', "button:has-text('Login')",
    "button:has-text('Sign In')", 'input[type="submit"]',
    'button[type="submit"]',
)


def _open_login_link(page):
    for _ in range(3):
        login_link = find_first_match(page, LOGIN_LINK_SELECTORS)
        if login_link is None:
            return
        try:
            login_link.click(timeout=ACTION_TIMEOUT_MS)
        except Exception:
            login_link.evaluate('(el) => el.click()')
        _sleep(page, 1000)


def _login_scopes(page):
    frames = list(getattr(page, 'frames', None) or [])
    scopes = []
    for candidate in [find_login_scope(page), page] + frames:
        if all(candidate is not item for item in scopes):
            scopes.append(candidate)
    return scopes


def _login_fields_present(page):
    for candidate in _login_scopes(page):
        try:
            if find_first_match(candidate, USERNAME_SELECTORS) is not None and (
                find_first_match(candidate, PASSWORD_SELECTORS) is not None
            ):
                return True
        except Exception:
            continue
    return False


def _submit_credentials(page, username, password):
    for candidate in _login_scopes(page):
        username_locators = [candidate.locator(selector) for selector in USERNAME_SELECTORS]
        password_locators = [candidate.locator(selector) for selector in PASSWORD_SELECTORS]
        if try_fill_first_matching(username_locators, username) and try_fill_first_matching(password_locators, password):
            return candidate
    return None


def _attempt_portal_login(page, username, password):
    _wait_until_ready(
        lambda: (
            find_first_match(page, LOGIN_LINK_SELECTORS) is not None
            or _login_fields_present(page)
        ),
        page=page,
    )
    _open_login_link(page)
    scope_used = _submit_credentials(page, username, password)
    if scope_used is None:
        raise MCBImportError('Could not find MCB login fields')
    submit = find_first_match(scope_used, SUBMIT_SELECTORS)
    if submit is not None:
        try:
            submit.click(timeout=ACTION_TIMEOUT_MS)
        except Exception:
            submit.evaluate('(el) => el.click()')
    else:
        page.keyboard.press('Enter', timeout=ACTION_TIMEOUT_MS)
    try:
        page.wait_for_load_state('domcontentloaded', timeout=NAVIGATION_TIMEOUT_MS)
    except Exception:
        pass
    _sleep(page, 2000)
    _wait_until_ready(lambda: ensure_authenticated(page), page=page)


def login_to_mcb():
    username, password = _runtime_credentials()
    playwright_factory = _runtime_playwright()
    playwright = playwright_factory()
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()
    try:
        failures = []
        for portal_url in PORTAL_URLS:
            try:
                page.goto(
                    portal_url,
                    wait_until='domcontentloaded',
                    timeout=NAVIGATION_TIMEOUT_MS,
                )
            except Exception as exc:
                failures.append(f'{portal_url}: {exc}')
                continue
            try:
                _wait_until_ready(lambda: ensure_authenticated(page), page=page)
                return browser, context, page
            except MCBImportError as exc:
                failures.append(f'{portal_url}: {exc}')
            try:
                _attempt_portal_login(page, username, password)
                return browser, context, page
            except Exception as exc:
                failures.append(f'{portal_url}: {exc}')
        raise MCBImportError(
            'Could not open an authenticated MyClassboard session: '
            + '; '.join(failures)
        )
    except Exception:
        try:
            context.close()
        finally:
            browser.close()
        raise


def _ajax_request(page, url, method='GET', payload=None, source='worksheet', timeout=None):
    if timeout is None:
        timeout = AJAX_TIMEOUT_MS
    script = '''async ({url, method, payload, timeout}) => {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeout);
        const init = {method, credentials: 'include', signal: controller.signal, headers: {'X-Requested-With': 'XMLHttpRequest'}};
        if (method !== 'GET' && method !== 'HEAD' && payload !== null && payload !== undefined) {
            init.headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8';
            init.body = new URLSearchParams(payload).toString();
        }
        try {
            const response = await fetch(url, init);
            const body = await response.text();
            return {status: response.status, ok: response.ok, body, aborted: false};
        } catch (error) {
            const aborted = String(error && error.name) === 'AbortError';
            return {status: 0, ok: false, body: '', aborted: aborted,
                    error: String((error && error.message) || error)};
        } finally {
            clearTimeout(timer);
        }
    }'''
    try:
        result = page.evaluate(script, {
            'url': url,
            'method': method,
            'payload': payload,
            'timeout': timeout,
        })
    except Exception as exc:
        raise _request_error(exc, method, url, f'{timeout}ms') from exc
    if isinstance(result, dict) and result.get('aborted'):
        raise ImportTimeoutError(
            f'{source} AJAX request to {url} timed out after {timeout}ms'
        )
    if not isinstance(result, dict) or not result.get('ok'):
        status = result.get('status') if isinstance(result, dict) else 'unknown'
        detail = result.get('error') if isinstance(result, dict) else None
        suffix = f' ({detail})' if detail else ''
        raise MCBImportError(
            f'{source} AJAX request returned HTTP {status}{suffix}'
        )
    body = result.get('body')
    if body is None or not clean_text(body):
        raise MCBImportError(f'{source} AJAX request returned an empty body')
    if _known_empty_state(source, clean_text(body)):
        return []
    try:
        parsed = json.loads(body)
    except (TypeError, ValueError):
        return body
    if parsed in (None, [], {}, ''):
        return []
    if isinstance(parsed, dict):
        for key in ('data', 'records', 'results', 'items'):
            if key in parsed:
                return parsed[key]
    return parsed


def fetch_ajax_data(page, endpoint, params=None, method='GET', rno=None, source='worksheet'):
    url = urljoin(f'{PORTAL_BASE_URL}/StudentERP/', endpoint)
    if rno is not None:
        payload = dict(params or {})
        payload['RNo'] = rno
        return _ajax_request(page, url, method='POST', payload=payload, source=source)
    if '?' not in url and params:
        url = f'{url}?{urlencode(params)}'
    return _ajax_request(page, url, method=method, payload=params, source=source)


def _valid_empty_historical(value, source='worksheet'):
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    if isinstance(value, str) and _known_empty_state(source, value):
        return True
    return False


def _assignment_records_from_ajax(value):
    if isinstance(value, list):
        records = []
        for item in value:
            if isinstance(item, dict):
                records.append(item)
        return records
    if isinstance(value, dict):
        for key in ('records', 'results', 'items', 'data'):
            if isinstance(value.get(key), list):
                return value[key]
        return [value]
    return []


def _rno_from_record(record):
    if not isinstance(record, dict):
        return ''
    for key in ('rno', 'Rno', 'RNo', 'question_rno'):
        if record.get(key) is not None:
            return clean_text(record.get(key))
    return ''


def _record_assignment(record, diary_date):
    if not isinstance(record, dict):
        return {}
    assignment_id = clean_text(record.get('assignment_id') or record.get('AssignmentId'))
    qb_id = clean_text(record.get('qb_question_id') or record.get('qbquestionid') or record.get('question_id'))
    rno = _rno_from_record(record)
    if not (assignment_id and qb_id and rno):
        return {}
    subject = clean_text(record.get('subject') or record.get('title') or record.get('assignment_name') or 'Worksheet')
    teacher = clean_text(record.get('teacher') or record.get('faculty') or record.get('author') or 'Unknown')
    date_value = normalize_date(record.get('date') or record.get('assignment_date'), diary_date) or normalize_date(diary_date) or ''
    return {
        'assignment_id': assignment_id,
        'qb_question_id': qb_id,
        'rno': rno,
        'subject': subject,
        'label': subject,
        'teacher': teacher,
        'summary': clean_text(record.get('description') or record.get('summary') or ''),
        'attachments': normalize_attachments(record.get('attachments')),
        'date': date_value,
        'source_id': _worksheet_source_id({'assignment_id': assignment_id, 'qb_question_id': qb_id, 'rno': rno}),
    }


def _open_assignments_page(page):
    current_url = ''
    try:
        current_url = str(getattr(page, 'url', '') or '')
    except Exception:
        pass
    if '/MyAssignments' not in current_url:
        link = find_first_match(page, (
            "a:has-text('Assignments')",
            "li:has-text('Assignments')",
            "button:has-text('Assignments')",
        ))
        if link is not None:
            try:
                link.click(timeout=ACTION_TIMEOUT_MS)
            except Exception:
                link.evaluate('(el) => el.click()')
        else:
            page.goto(
                urljoin(f'{PORTAL_BASE_URL}/StudentERP/', 'MyAssignments/'),
                wait_until='domcontentloaded',
                timeout=NAVIGATION_TIMEOUT_MS,
            )
    try:
        page.wait_for_selector('[onclick*="ViewQuestion"]', timeout=ACTION_TIMEOUT_MS)
    except Exception:
        _sleep(page, 3000)


def _assignment_enrollment_id(html):
    match = re.search(
        r'(?:StudentEnrollmentID|studentenrolid)\s*[:=]\s*[\'\"]?(\d+)',
        html or '',
        re.IGNORECASE,
    )
    return match.group(1) if match else ''


def _assignment_listing_from_ajax(listing, diary_date):
    if _valid_empty_historical(listing):
        return []
    records = _assignment_records_from_ajax(listing)
    if not records and isinstance(listing, str):
        records = extract_assignment_records(listing, diary_date)
    if records:
        return records
    text = listing if isinstance(listing, str) else json.dumps(listing, default=str)
    if _known_empty_state('worksheet', text):
        return []
    return None


def _worksheet_listing(page, diary_date):
    failures = []
    listing_html = _page_content(page)
    records = extract_assignment_records(listing_html, diary_date) if listing_html else []
    if records:
        return records
    _open_assignments_page(page)
    listing_html = _page_content(page)
    records = extract_assignment_records(listing_html, diary_date) if listing_html else []
    if records:
        return records
    enrollment_id = _assignment_enrollment_id(listing_html)
    if enrollment_id:
        try:
            listing = fetch_ajax_data(
                page,
                'MyAssignments_Get',
                params={
                    'StudentEnrollmentID': enrollment_id,
                    'Type': '0',
                    'SubjectName': '',
                    'SubmittedBit': '0',
                },
            )
        except ImportTimeoutError:
            raise
        except Exception as exc:
            failures.append(f'MyAssignments_Get: {exc}')
            listing = None
        if listing is not None:
            records = _assignment_listing_from_ajax(listing, diary_date)
            if records is not None:
                return records
            failures.append('MyAssignments_Get returned no usable assignment records')
    try:
        listing = fetch_ajax_data(
            page,
            'Master_Student/GetStudentAssignmentQuestionList',
            params={'date': format_portal_date(diary_date)},
        )
    except ImportTimeoutError:
        raise
    except Exception as exc:
        failures.append(f'GetStudentAssignmentQuestionList: {exc}')
        raise MCBImportError(
            'worksheet listing request failed: ' + '; '.join(failures + [str(exc)])
        ) from exc
    records = _assignment_listing_from_ajax(listing, diary_date)
    if records is not None:
        return records
    raise MCBImportError(
        'worksheet listing response did not contain assignments'
        + ('; ' + '; '.join(failures) if failures else '')
    )


def scrape_worksheets(page, diary_date, scrape_all=False):
    records = _worksheet_listing(page, diary_date)
    if not records:
        return []
    assignments = []
    for record in records:
        assignment = _record_assignment(record, diary_date)
        if assignment:
            assignments.append(assignment)
    if not assignments:
        raise MCBImportError('worksheet listing contained no usable rno records')
    details = []
    for assignment in assignments:
        detail = fetch_ajax_data(
            page,
            'ViewOnlineAssignmentQuestions_student',
            params={
                'SubjectName': 'all',
                'Type': assignment.get('assignment_type') or '0',
            },
            method='POST',
            rno=assignment['rno'],
        )
        if _valid_empty_historical(detail):
            raise MCBImportError(
                f'worksheet detail response for rno {assignment["rno"]} was empty'
            )
        details.append({
            'rno': assignment['rno'],
            'html': detail if isinstance(detail, str) else json.dumps(detail),
        })
    return apply_smart_worksheet_titles(
        extract_worksheet_entries(details, assignments, diary_date),
        scrape_all=scrape_all,
    )


def scrape_mcb(diary_date=None, scrape_all=False):
    _load_runtime_env()
    selected = parse_date_value(diary_date) or date.today()
    if not scrape_all:
        return scrape_data(start_date=selected, end_date=selected)
    start = (
        parse_date_value(os.getenv('MCB_START_DATE') or os.getenv('IMPORT_START_DATE'))
        or selected - timedelta(days=DEFAULT_HISTORY_DAYS)
    )
    end = (
        parse_date_value(os.getenv('MCB_END_DATE') or os.getenv('IMPORT_END_DATE'))
        or selected
    )
    return scrape_data(start_date=start, end_date=end)


def scrape_diary(page, diary_date):
    try:
        result = _ajax_request(
            page,
            DIARY_URL,
            method='POST',
            payload={'DiaryDate': format_portal_date(diary_date)},
            source='diary',
        )
        if result in (None, [], {}, ''):
            return []
        html = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        return _require_collected_entries('diary', html, extract_diary_entries(html, diary_date))
    except ImportTimeoutError:
        raise
    except MCBImportError:
        pass
    url = f'{DIARY_URL}?{urlencode({"date": format_portal_date(diary_date)})}'
    page.goto(url, wait_until='domcontentloaded', timeout=NAVIGATION_TIMEOUT_MS)
    _wait_until_ready(lambda: ensure_authenticated(page), page=page)
    page_html = _page_content(page)
    return _require_collected_entries(
        'diary', page_html, extract_diary_entries(page_html, diary_date)
    )


def _open_announcements_page(page):
    link = find_first_match(page, (
        "a:has-text('Announcements')",
        "li:has-text('Announcements')",
        "button:has-text('Announcements')",
    ))
    if link is not None:
        try:
            link.click(timeout=ACTION_TIMEOUT_MS)
        except Exception:
            link.evaluate('(el) => el.click()')
    else:
        page.goto(
            urljoin(f'{PORTAL_BASE_URL}/StudentERP/', 'StudentAnnouncements/'),
            wait_until='domcontentloaded',
            timeout=NAVIGATION_TIMEOUT_MS,
        )
    _sleep(page, 3000)


def scrape_announcements(page, diary_date):
    _open_announcements_page(page)
    _wait_until_ready(lambda: ensure_authenticated(page), page=page)
    html = _page_content(page)
    return _require_collected_entries(
        'announcement', html, extract_announcements(html, diary_date)
    )


def scrape_date(page, diary_date):
    entries = []
    failures = []
    for name, scraper in (
        ('diary', scrape_diary),
        ('worksheets', lambda current_page, value: scrape_worksheets(current_page, value)),
        ('announcements', scrape_announcements),
    ):
        try:
            result = scraper(page, diary_date)
            if result is None:
                failures.append(f'{name} returned no response')
            else:
                entries.extend(result)
        except Exception as exc:
            failures.append(f'{name}: {exc}')
    if failures:
        raise MCBImportError('scrape failed: ' + '; '.join(failures))
    return deduplicate_entries(apply_smart_worksheet_titles(entries))


def _date_range(start_date=None, end_date=None):
    start = parse_date_value(start_date) or date.today()
    end = parse_date_value(end_date) or start
    if end < start:
        raise ValueError('end date must not be before start date')
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _group_date_key(value, dates):
    parsed = parse_date_value(value)
    if parsed is None:
        return dates[-1].isoformat()
    if parsed < dates[0]:
        return dates[0].isoformat()
    if parsed > dates[-1]:
        return dates[-1].isoformat()
    return parsed.isoformat()


def scrape_dates(start_date=None, end_date=None, page=None):
    dates = list(_date_range(start_date, end_date))
    if not dates:
        raise MCBImportError('no dates were selected for scraping')
    owned_browser = None
    owned_context = None
    if page is None:
        owned_browser, owned_context, page = login_to_mcb()
    if len(dates) == 1:
        try:
            return [(dates[0], scrape_date(page, dates[0]))]
        finally:
            if owned_context is not None:
                owned_context.close()
            if owned_browser is not None:
                owned_browser.close()
    failures = []
    worksheets = []
    announcements = []
    diary_by_date = {current.isoformat(): [] for current in dates}
    try:
        try:
            worksheets = scrape_worksheets(page, dates[-1], scrape_all=True)
        except Exception as exc:
            failures.append(f'worksheets: {exc}')
        try:
            announcements = scrape_announcements(page, dates[-1])
        except Exception as exc:
            failures.append(f'announcements: {exc}')
        for current in dates:
            try:
                diary_by_date[current.isoformat()].extend(scrape_diary(page, current) or [])
            except Exception as exc:
                failures.append(f'diary {current.isoformat()}: {exc}')
    finally:
        if owned_context is not None:
            owned_context.close()
        if owned_browser is not None:
            owned_browser.close()
    if failures:
        raise MCBImportError('scrape did not complete: ' + '; '.join(failures))
    grouped = {key: list(value) for key, value in diary_by_date.items()}
    for entry in list(worksheets) + list(announcements):
        grouped.setdefault(_group_date_key(entry.get('date'), dates), []).append(entry)
    return [
        (
            current,
            deduplicate_entries(apply_smart_worksheet_titles(grouped.get(current.isoformat(), []))),
        )
        for current in dates
    ]


def scrape_data(start_date=None, end_date=None, page=None):
    return deduplicate_entries([
        entry
        for _, entries in scrape_dates(start_date, end_date, page)
        for entry in entries
    ])


def _http_session():
    if http_requests is None:
        raise MCBImportError('requests is required for persistence')
    return http_requests.Session()


def _response_json(response):
    try:
        return response.json()
    except (AttributeError, TypeError, ValueError):
        return None


def _modern_entry_payload(entry, updated_at):
    canonical = canonicalize_entry(entry)
    return {
        'source_id': canonical['source_id'],
        'entry_type': canonical['type'],
        'date': canonical['date'],
        'subject': canonical['subject'],
        'label': canonical['label'],
        'teacher': canonical['teacher'],
        'summary': canonical['summary'],
        'attachments': canonical['attachments'],
        'attachment_url': canonical['attachment_url'],
        'updated_at': updated_at,
    }


def _legacy_entry_payload(entry, updated_at):
    canonical = canonicalize_entry(entry)
    return {
        'entry_type': canonical['type'],
        'date': canonical['date'],
        'subject': canonical['subject'],
        'teacher': canonical['teacher'],
        'summary': canonical['summary'],
        'attachment_url': canonical['attachment_url'],
    }


def _modern_column_error(response):
    status = getattr(response, 'status_code', 0)
    if status not in {400, 409, 415, 422}:
        return False
    text = getattr(response, 'text', '') or ''
    payload = _response_json(response)
    if payload is not None:
        try:
            text += ' ' + json.dumps(payload, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            pass
    lowered = text.lower()
    return any(column in lowered for column in (
        'source_id', 'content_key', 'label', 'attachments', 'attachment_url', 'updated_at',
        'entry_type', 'field required', 'extra_forbidden', 'not permitted',
    )) or any(column in lowered for column in (
        'column', 'schema', 'relation', 'unknown field',
    ))


def _post_entry(session, url, payload, conflict, headers, timeout=None):
    target = f'{url}?on_conflict={conflict}'
    return _session_call(session, 'post', target, timeout=timeout, json=payload, headers=headers)


def _verification_rows(response, source):
    status = getattr(response, 'status_code', 0)
    if not 200 <= status < 300:
        raise MCBImportError(f'{source} returned HTTP {status or "unknown"}')
    data = _response_json(response)
    if data is None:
        raise MCBImportError(f'{source} returned a malformed response body')
    if not isinstance(data, list):
        raise MCBImportError(
            f'{source} returned {type(data).__name__} instead of a list of rows'
        )
    if not data:
        raise MCBImportError(f'{source} returned no rows for the persisted entry')
    rows = [row for row in data if isinstance(row, dict)]
    if not rows:
        raise MCBImportError(f'{source} returned no usable rows')
    return rows


def _verify_stored_field(row, field, expected, required=True):
    if field not in row:
        if required:
            raise MCBImportError(f'persisted row is missing {field}')
        return
    actual = row.get(field)
    if field == 'date':
        actual = normalize_date(actual) or ''
    if expected is None:
        if actual is not None:
            raise MCBImportError(
                f'persisted {field} did not match: {actual!r} != {expected!r}'
            )
        return
    if not isinstance(actual, str):
        raise MCBImportError(f'persisted {field} is not text')
    if actual != expected:
        raise MCBImportError(
            f'persisted {field} did not match: {actual!r} != {expected!r}'
        )


def _verify_stored_attachments(row, canonical, require_fields=False):
    if require_fields and 'attachments' not in row:
        raise MCBImportError('persisted row is missing attachments')
    if 'attachments' in row:
        stored = row.get('attachments')
    elif 'attachment_url' in row:
        stored = row.get('attachment_url')
    else:
        raise MCBImportError('persisted row is missing attachments')
    if require_fields:
        if not isinstance(stored, list):
            raise MCBImportError('persisted attachments are not a list')
        for item in stored:
            if (
                not isinstance(item, dict)
                or set(item) != {'name', 'url'}
                or not isinstance(item.get('name'), str)
                or not isinstance(item.get('url'), str)
            ):
                raise MCBImportError('persisted attachments have an invalid shape')
        if stored != canonical['attachments']:
            raise MCBImportError('persisted attachments did not match')
    elif normalize_attachments(stored) != canonical['attachments']:
        raise MCBImportError('persisted attachments did not match')
    if require_fields and 'attachment_url' not in row:
        raise MCBImportError('persisted row is missing attachment_url')


def _verify_modern(session, url, entry, headers, supabase=False, timeout=None):
    canonical = canonicalize_entry(entry)
    validate_canonical_entry(canonical)
    filter_prefix = 'eq.' if supabase else ''
    query = urlencode({
        'source_id': f'{filter_prefix}{canonical["source_id"]}',
        'entry_type': f'{filter_prefix}{canonical["type"]}',
        'select': VERIFY_SELECT,
    })
    response = _session_call(
        session, 'get', f'{url}?{query}', timeout=timeout, headers=headers,
    )
    rows = _verification_rows(response, 'verification')
    matches = [
        row for row in rows
        if row.get('source_id') == canonical['source_id']
    ]
    if not matches:
        raise MCBImportError('persisted row source_id did not match')
    row = matches[0]
    _verify_stored_field(row, 'source_id', canonical['source_id'])
    _verify_stored_field(row, 'entry_type', canonical['type'])
    _verify_stored_field(row, 'date', canonical['date'])
    _verify_stored_field(row, 'subject', canonical['subject'])
    _verify_stored_field(row, 'label', canonical['label'])
    _verify_stored_field(row, 'teacher', canonical['teacher'])
    _verify_stored_field(row, 'summary', canonical['summary'])
    _verify_stored_attachments(row, canonical, require_fields=True)
    _verify_stored_field(row, 'attachment_url', canonical['attachment_url'])
    return True


def _verify_legacy(session, url, entry, headers, supabase=False, timeout=None):
    canonical = canonicalize_entry(entry)
    validate_canonical_entry(canonical)
    if supabase:
        query = urlencode({
            'entry_type': f'eq.{canonical["type"]}',
            'date': f'eq.{canonical["date"]}',
            'subject': f'eq.{canonical["subject"]}',
            'select': 'entry_type,date,subject,summary,attachment_url',
        })
    else:
        query = urlencode({'entry_type': canonical['type'], 'limit': '1000'})
    response = _session_call(
        session, 'get', f'{url}?{query}', timeout=timeout, headers=headers,
    )
    source = 'legacy verification' if supabase else 'local verification'
    rows = _verification_rows(response, source)
    matches = [
        row for row in rows
        if _canonical_type(row.get('entry_type') or row.get('type')) == canonical['type']
        and (normalize_date(row.get('date')) or '') == canonical['date']
        and clean_text(row.get('subject')) == canonical['subject']
    ]
    if not matches:
        raise MCBImportError('persisted row was not found')
    row = matches[0]
    _verify_stored_field(row, 'summary', canonical['summary'])
    _verify_stored_field(row, 'label', canonical['label'], required=False)
    _verify_stored_attachments(row, canonical)
    return True


def push_to_api(entries, api_url=None, session=None, verify=True, headers=None, timeout=None):
    entries = list(entries or [])
    if not entries:
        return {
            'success': True,
            'skipped': True,
            'fresh_success': False,
            'pushed': 0,
            'verified': 0,
            'requested': 0,
            'entries': [],
            'message': 'No entries to persist',
        }
    for position, entry in enumerate(entries):
        try:
            validate_canonical_entry(entry)
        except MCBImportError as exc:
            raise MCBImportError(f'entry {position} is not a canonical result: {exc}') from exc
    entries = deduplicate_entries(entries)
    _load_runtime_env()
    configured_url = clean_text(api_url or os.getenv('API_URL'))
    supabase_url, supabase_key = _supabase_config()
    use_supabase = not configured_url and bool(supabase_url and supabase_key)
    if use_supabase:
        target_url = _supabase_entries_url(supabase_url)
    else:
        configured_url = (configured_url or API_URL).split('?', 1)[0].rstrip('/')
        target_url = (
            configured_url if configured_url.endswith('/api/entries')
            else configured_url + '/api/entries'
        )
    owned_session = session is None
    active_session = session or _http_session()
    request_timeout = http_timeouts() if timeout is None else timeout
    request_headers = dict(headers or {})
    request_headers.setdefault('Content-Type', 'application/json')
    request_headers.setdefault('Prefer', 'resolution=merge-duplicates,return=representation')
    if use_supabase:
        request_headers = _supabase_headers(supabase_key, request_headers)
    modern = os.getenv('SUPABASE_LEGACY_SCHEMA', '').strip().lower() not in {'1', 'true', 'yes'}
    updated_at = datetime.now(timezone.utc).isoformat()
    pushed = 0
    verified = 0
    errors = []
    try:
        for entry in entries:
            entry_mode = modern
            response = None
            for attempt in range(2):
                payload = (
                    _modern_entry_payload(entry, updated_at)
                    if entry_mode else _legacy_entry_payload(entry, updated_at)
                )
                conflict = (
                    'content_key' if entry_mode else 'entry_type,date,subject,summary'
                )
                try:
                    response = _post_entry(
                        active_session,
                        target_url,
                        payload,
                        conflict,
                        request_headers,
                        timeout=request_timeout,
                    )
                except Exception as exc:
                    errors.append(f'{entry["source_id"]}: {exc}')
                    response = None
                    break
                if 200 <= getattr(response, 'status_code', 0) < 300:
                    break
                if attempt == 0 and entry_mode and _modern_column_error(response):
                    modern = False
                    entry_mode = False
                    continue
                break
            if response is None:
                continue
            if not (200 <= getattr(response, 'status_code', 0) < 300):
                errors.append(
                    f'{entry["source_id"]}: HTTP {getattr(response, "status_code", "unknown")}'
                )
                continue
            pushed += 1
            if verify:
                try:
                    if entry_mode:
                        _verify_modern(
                            active_session, target_url, entry, request_headers,
                            supabase=use_supabase, timeout=request_timeout,
                        )
                    else:
                        _verify_legacy(
                            active_session, target_url, entry, request_headers,
                            supabase=use_supabase, timeout=request_timeout,
                        )
                except Exception as exc:
                    errors.append(f'{entry["source_id"]}: {exc}')
                else:
                    verified += 1
    finally:
        if owned_session:
            active_session.close()
    result = {
        'success': not errors,
        'skipped': False,
        'pushed': pushed,
        'verified': verified,
        'requested': len(entries),
        'errors': errors,
        'entries': entries,
        'transport': 'supabase' if use_supabase else 'api',
        'message': (
            'Persisted and verified' if not errors and verify else
            'Persisted' if not errors else '; '.join(errors)
        ),
    }
    if errors:
        raise PersistenceError(result)
    return result


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='Import MCB entries into the local dashboard')
    parser.add_argument('date', nargs='?', help='date to scrape, for example 10 Jun 2026')
    parser.add_argument('--all', action='store_true', help='scrape the configured date range without clearing data')
    parser.add_argument('--force', action='store_true', help='allow the import even when the source is unchanged')
    return parser.parse_args(argv)


def in_quiet_hours(now=None):
    current = now or datetime.now()
    if current.tzinfo is not None:
        current = current.astimezone()
    return QUIET_HOURS_START_HOUR <= current.hour < QUIET_HOURS_END_HOUR


def _selected_range(args):
    selected_date = parse_date_value(args.date) if args.date else None
    if args.date and selected_date is None:
        raise MCBImportError(f'unrecognized date: {args.date!r}')
    if args.all:
        selected = selected_date or date.today()
        start_date = (
            parse_date_value(os.getenv('MCB_START_DATE') or os.getenv('IMPORT_START_DATE'))
            or selected - timedelta(days=DEFAULT_HISTORY_DAYS)
        )
        end_date = (
            parse_date_value(os.getenv('MCB_END_DATE') or os.getenv('IMPORT_END_DATE'))
            or selected
        )
    else:
        start_date = end_date = selected_date or date.today()
    if end_date < start_date:
        raise MCBImportError('end date must not be before start date')
    return start_date, end_date


def main(argv=None):
    args = parse_args(argv)
    try:
        _load_runtime_env()
        if not (args.force or args.all) and in_quiet_hours():
            print(
                'Skipping run: local time is inside the quiet window '
                f'({QUIET_HOURS_START_HOUR:02d}:00-{QUIET_HOURS_END_HOUR:02d}:00).'
            )
            return 0
        start_date, end_date = _selected_range(args)
        results = scrape_dates(start_date=start_date, end_date=end_date)
        collected = [entry for _, entries in results for entry in entries]
        for current_date, entries in results:
            print(f'{current_date.isoformat()}: {len(entries)} entries')
        if not collected:
            print('No entries found for the selected range; nothing to persist.')
            return 0
        result = push_to_api(collected)
        if not result.get('success'):
            print(f'Import failed: {result.get("message")}', file=sys.stderr)
            return 1
        if args.force:
            result['forced'] = True
        print(f'Imported {result["pushed"]} entries; verified {result["verified"]}.')
        return 0
    except Exception as exc:
        print(f'Import failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
