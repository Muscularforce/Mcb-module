import ast
import json
import os
import subprocess
import sys
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import requests

import mcb_import as importer


ROOT = Path(__file__).resolve().parents[1]
SCRATCH = ROOT / 'webapp' / 'scratch'


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=''):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        if self._payload is None:
            raise ValueError('no JSON body')
        return self._payload


class FakeSession:
    def __init__(self, post_responses=None, get_responses=None, post_error=None, get_error=None):
        self.post_responses = list(post_responses or [FakeResponse()])
        self.get_responses = list(get_responses or [FakeResponse(payload=[{'source_id': 'test'}])])
        self.post_error = post_error
        self.get_error = get_error
        self.posts = []
        self.gets = []
        self.closed = False

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append({'url': url, 'json': json, 'headers': headers, 'timeout': timeout})
        if self.post_error is not None:
            raise self.post_error
        if len(self.post_responses) > 1:
            return self.post_responses.pop(0)
        return self.post_responses[0]

    def get(self, url, headers=None, timeout=None):
        self.gets.append({'url': url, 'headers': headers, 'timeout': timeout})
        if self.get_error is not None:
            raise self.get_error
        if len(self.get_responses) > 1:
            return self.get_responses.pop(0)
        return self.get_responses[0]

    def close(self):
        self.closed = True


def modern_row(entry):
    canonical = importer.canonicalize_entry(entry)
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
    }


def local_row(entry):
    canonical = importer.canonicalize_entry(entry)
    return {
        'id': 1,
        'entry_type': canonical['type'],
        'date': canonical['date'],
        'subject': canonical['subject'],
        'teacher': canonical['teacher'],
        'summary': canonical['summary'],
        'attachment_url': canonical['attachment_url'],
    }


DIARY_ENTRY = importer.canonicalize_entry({
    'source_id': 'test',
    'type': 'DiaryEntry',
    'date': '2026-06-03',
    'subject': 'Subject',
    'label': 'General',
    'teacher': 'Teacher',
    'summary': 'Summary',
    'attachments': [{'name': 'file.pdf', 'url': 'https://example.test/file.pdf'}],
})


class FakeLocator:
    def __init__(self, count=0, text=''):
        self._count = count
        self._text = text
        self.filled = []
        self.clicks = []
        self.presses = []

    @property
    def first(self):
        return self

    def count(self):
        return self._count

    def scroll_into_view_if_needed(self):
        return None

    def click(self, timeout=None):
        self.clicks.append(timeout)

    def fill(self, value, timeout=None):
        self.filled.append(value)

    def inner_text(self, timeout=None):
        return self._text

    def evaluate(self, script, argument=None):
        return None

    def wait_for(self, timeout=None):
        return None


class FakeLoginPage:
    def __init__(self, ready_urls=(), login_link=False, portal_links=True):
        self.ready_urls = set(ready_urls)
        self.login_link = login_link
        self.portal_links = portal_links
        self.frames = []
        self.url = ''
        self.goto_calls = []
        self.selector_calls = []
        self.authenticated = False

    def goto(self, url, wait_until=None, timeout=None):
        self.goto_calls.append((url, timeout))
        self.url = url
        self.authenticated = False

    def wait_for_load_state(self, state=None, timeout=None):
        return None

    def wait_for_timeout(self, delay_ms):
        return None

    def wait_for_selector(self, selector, timeout=None):
        return None

    def content(self):
        if self.authenticated:
            return '<html><body>Logout Diary Worksheets Announcements</body></html>'
        return '<html><body>Sign in username password</body></html>'

    def evaluate(self, script, arguments=None):
        self.authenticated = True
        return None

    @property
    def keyboard(self):
        return FakeKeyboard(self)

    def locator(self, selector):
        self.selector_calls.append(selector)
        lowered = selector.lower()
        ready = self.url in self.ready_urls
        if selector == 'body':
            return FakeLocator(1, text='Logout Diary Worksheets Announcements' if self.authenticated else 'Sign in username password')
        if 'click here to login' in lowered:
            return FakeLocator(1 if self.login_link and ready else 0)
        if 'password' in lowered:
            return FakeLocator(1 if ready and not self.authenticated else 0)
        if self.login_link and not ready:
            return FakeLocator(0)
        return FakeLocator(1 if ready and 'user' in lowered else 0)


class FakeKeyboard:
    def __init__(self, page):
        self.page = page

    def press(self, key, timeout=None):
        self.page.authenticated = True


class FakeContext:
    def __init__(self, page):
        self.page = page
        self.closed = False

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, page):
        self.page = page
        self.contexts = []
        self.closed = False

    def new_context(self):
        context = FakeContext(self.page)
        self.contexts.append(context)
        return context

    def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self, browser):
        self.browser = browser

    def launch(self, headless=True):
        return self.browser


class FakePlaywright:
    def __init__(self, browser):
        self.chromium = FakeChromium(browser)

    def __call__(self):
        return self


class FakeAjaxPage:
    def __init__(self, responses=None, html='', error=None):
        self.responses = list(responses or [])
        self.html = html
        self.error = error
        self.calls = []

    def evaluate(self, script, arguments):
        self.calls.append((script, arguments))
        if self.error is not None:
            raise self.error
        if self.responses:
            return self.responses.pop(0)
        return {'status': 200, 'ok': True, 'body': self.html, 'aborted': False}

    def content(self):
        return self.html

    def goto(self, url, wait_until=None, timeout=None):
        self.calls.append(('goto', {'url': url, 'timeout': timeout}))

    def url(self):
        return 'https://rainbow.myclassboard.com/StudentERP/Master_Student'

    def wait_for_timeout(self, delay_ms):
        return None

    def wait_for_selector(self, selector, timeout=None):
        return None

    def locator(self, selector):
        return FakeLocator(0)


class ImporterTests(unittest.TestCase):
    def test_import_does_not_require_credentials_or_playwright(self):
        environment = os.environ.copy()
        environment.pop('MCB_USERNAME', None)
        environment.pop('MCB_PASSWORD', None)
        result = subprocess.run(
            [sys.executable, '-c', 'import mcb_import; print("ok")'],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('ok', result.stdout)

    def test_viewfile_parsing_and_attachment_serialization(self):
        name, url = importer.parse_viewfile_call(
            "ViewFile('friendly.pdf', 'files/internal-name.pdf', 1)",
            'https://rainbow.myclassboard.com/StudentERP/',
        )
        self.assertEqual(name, 'friendly.pdf')
        self.assertEqual(url, 'https://rainbow.myclassboard.com/StudentERP/files/internal-name.pdf')
        serialized = importer.serialize_attachments([{'name': name, 'url': url}])
        self.assertEqual(importer.normalize_attachments(serialized), [{'name': name, 'url': url}])
        self.assertIsInstance(json.loads(serialized), list)

    def test_attachment_collection_ignores_icons_and_non_files(self):
        html = '''
        <div>
          <a href="https://example.test/icon.png">icon</a>
          <a href="https://example.test/readme.txt" title="Notes">Notes</a>
          <span onclick="ViewFile('shown.pdf', 'https://example.test/files/1', 1)"></span>
          <span>shown.pdf</span>
          <span onclick="ViewFile('shown.pdf', 'https://example.test/files/1', 1)"></span>
        </div>
        '''
        soup = importer.BeautifulSoup(html, 'html.parser')
        attachments = importer.collect_attachments(soup)
        self.assertEqual(
            attachments,
            [
                {'name': 'Notes', 'url': 'https://example.test/readme.txt'},
                {'name': 'shown.pdf', 'url': 'https://example.test/files/1'},
            ],
        )

    def test_announcement_fixture_metadata_and_cleanup(self):
        html = (SCRATCH / 'announcements.html').read_text(encoding='utf-8')
        entries = importer.extract_announcements(html, '03 Jun 2026')
        self.assertGreaterEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry['type'], 'Announcement')
        self.assertEqual(entry['source_id'], '83208')
        self.assertEqual(entry['teacher'], 'ASHWINI RASAL')
        self.assertEqual(entry['label'], 'General')
        self.assertEqual(entry['date'], '2026-06-03')
        self.assertIn('SILENT MESSAGE ART COMPETITION GR.X', entry['subject'])
        self.assertIn('Dear Parents', entry['summary'])
        self.assertNotIn('0306261559442858.pdf', entry['summary'])
        self.assertNotIn('Art competition 26-27 FINAL.pdf', entry['summary'])
        self.assertEqual(len(entry['attachments']), 1)
        self.assertEqual(entry['attachments'][0]['name'], 'Art competition 26-27 FINAL.pdf')

    def test_worksheet_fixture_uses_rno_and_detail_content(self):
        listing = (SCRATCH / 'detail_view_0.html').read_text(encoding='utf-8')
        detail = (SCRATCH / 'real_detail_clicked.html').read_text(encoding='utf-8')
        rows = importer.extract_assignment_records(listing, '06 Jun 2026')
        self.assertEqual(len(rows), 31)
        self.assertEqual(rows[0]['rno'], '1')
        entries = importer.extract_worksheet_entries(
            [{'rno': '1', 'html': detail}],
            rows[:1],
            '06 Jun 2026',
        )
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry['source_id'], 'worksheet:74364:0:1')
        self.assertEqual(entry['subject'], 'Math Revision Sheet Answerkey')
        self.assertEqual(entry['label'], 'Maths')
        self.assertEqual(entry['date'], '2026-06-06')
        self.assertEqual(sorted(entry), sorted(importer.CANONICAL_FIELDS))
        self.assertIn('PFA Math Revision sheet Answerkey', entry['summary'])
        self.assertEqual(len(entry['attachments']), 1)
        self.assertNotIn('favicon.png', json.dumps(entry['attachments']))

    def test_scrape_worksheets_uses_mcb_detail_endpoint(self):
        listing = (SCRATCH / 'detail_view_0.html').read_text(encoding='utf-8')
        detail = (SCRATCH / 'real_detail_clicked.html').read_text(encoding='utf-8')

        class FakePage:
            def __init__(self):
                self.calls = []

            def content(self):
                return listing

            def evaluate(self, script, arguments):
                self.calls.append(arguments)
                return {'status': 200, 'ok': True, 'body': detail}

        page = FakePage()
        entries = importer.scrape_worksheets(page, '06 Jun 2026')
        self.assertEqual(len(entries), 31)
        self.assertEqual(len(page.calls), 31)
        self.assertTrue(all(
            call['url'].endswith('/ViewOnlineAssignmentQuestions_student')
            for call in page.calls
        ))
        self.assertEqual(page.calls[0]['method'], 'POST')
        self.assertEqual(page.calls[0]['payload']['SubjectName'], 'all')
        self.assertEqual(page.calls[0]['payload']['Type'], '0')
        self.assertEqual(page.calls[0]['payload']['RNo'], '1')

    def test_worksheet_details_do_not_match_positionally_or_return_partials(self):
        assignments = [
            {'assignment_id': '1', 'qb_question_id': '0', 'rno': '10', 'subject': 'First'},
            {'assignment_id': '2', 'qb_question_id': '0', 'rno': '20', 'subject': 'Second'},
        ]
        details = [
            {'rno': '20', 'html': '<div><h4>Second detail</h4><p>Second description</p></div>'},
            {'rno': '10', 'html': '<div><h4>First detail</h4><p>First description</p></div>'},
        ]
        entries = importer.extract_worksheet_entries(details, assignments)
        self.assertEqual([entry['subject'] for entry in entries], ['First detail', 'Second detail'])
        with self.assertRaises(RuntimeError):
            importer.extract_worksheet_entries(details[:1], assignments)

    def test_deduplication_uses_explicit_id_or_full_content_and_merges_files(self):
        first = {
            'type': 'DiaryEntry',
            'date': '2026-06-03',
            'subject': 'Same subject',
            'teacher': 'Teacher',
            'summary': 'A shared summary',
            'attachments': [{'name': 'one.pdf', 'url': 'https://example.test/one.pdf'}],
        }
        second = {
            'type': 'DiaryEntry',
            'date': '2026-06-03',
            'subject': 'Same subject',
            'teacher': 'Teacher',
            'summary': 'A shared summary',
            'attachments': [{'name': 'two.pdf', 'url': 'https://example.test/two.pdf'}],
        }
        merged = importer.deduplicate_entries([first, second])
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(merged[0]['attachments']), 2)
        self.assertEqual(len(first['attachments']), 1)
        explicit = {'source_id': 'same', 'type': 'Announcement', 'summary': 'one'}
        explicit_again = {'source_id': 'same', 'type': 'Announcement', 'summary': 'two'}
        self.assertEqual(len(importer.deduplicate_entries([explicit, explicit_again])), 1)

    def test_smart_title_preserves_original_subject(self):
        entry = {
            'type': 'Worksheet',
            'subject': 'Math Worksheet',
            'teacher': 'Ms Rao',
            'summary': 'Complete details',
        }
        updated = importer.apply_smart_worksheet_titles([entry])[0]
        self.assertEqual(updated['subject'], 'Ms Rao: Math Worksheet')
        self.assertIn('Original title: Math Worksheet', updated['summary'])
        self.assertIn('Complete details', updated['summary'])

    def test_empty_push_does_not_write(self):
        session = FakeSession()
        result = importer.push_to_api([], session=session)
        self.assertEqual(result['pushed'], 0)
        self.assertEqual(session.posts, [])
        self.assertFalse(result.get('fresh_success', False))

    def test_modern_push_uses_json_array_and_verifies(self):
        entry = dict(DIARY_ENTRY, source_id='local/id?x=1&y=2')
        session = FakeSession(
            post_responses=[FakeResponse(status_code=201)],
            get_responses=[FakeResponse(payload=[modern_row(entry)])],
        )
        result = importer.push_to_api(
            [entry], api_url='http://api.test/api/entries', session=session
        )
        self.assertTrue(result['success'])
        self.assertEqual(result['verified'], 1)
        self.assertEqual(len(session.posts), 1)
        self.assertIn('on_conflict=content_key', session.posts[0]['url'])
        self.assertEqual(session.posts[0]['json']['entry_type'], entry['type'])
        self.assertNotIn('type', session.posts[0]['json'])
        self.assertNotIn('content_key', session.posts[0]['json'])
        self.assertIsInstance(json.loads(session.posts[0]['json']['attachment_url']), list)
        query = parse_qs(urlparse(session.gets[0]['url']).query)
        self.assertEqual(query['source_id'], [entry['source_id']])
        self.assertEqual(query['entry_type'], [entry['type']])
        self.assertEqual(query['select'], [importer.VERIFY_SELECT])
        self.assertNotIn('eq.', query['source_id'][0])
        self.assertIn('source_id=local%2Fid%3Fx%3D1%26y%3D2', session.gets[0]['url'])

    def test_missing_content_key_is_a_modern_schema_error(self):
        cases = (
            ('text', FakeResponse(
                status_code=400,
                text='column "content_key" does not exist',
            )),
            ('json', FakeResponse(
                status_code=422,
                payload={'message': 'column content_key does not exist'},
            )),
        )
        for name, response in cases:
            with self.subTest(format=name):
                self.assertTrue(importer._modern_column_error(response))
        self.assertFalse(importer._modern_column_error(
            FakeResponse(status_code=201, text='content_key')
        ))

    def test_modern_schema_failure_falls_back_to_legacy_fields(self):
        session = FakeSession(
            post_responses=[
                FakeResponse(status_code=400, text='unknown column source_id'),
                FakeResponse(status_code=201),
            ],
            get_responses=[FakeResponse(payload=[local_row(DIARY_ENTRY)])],
        )
        result = importer.push_to_api(
            [DIARY_ENTRY], api_url='http://api.test/api/entries', session=session
        )
        self.assertTrue(result['success'])
        self.assertEqual(result['verified'], 1)
        self.assertEqual(len(session.posts), 2)
        self.assertIn('on_conflict=content_key', session.posts[0]['url'])
        self.assertIn('on_conflict=entry_type,date,subject,summary', session.posts[1]['url'])
        self.assertNotIn('source_id', session.posts[1]['json'])
        self.assertIn('entry_type', session.posts[1]['json'])
        self.assertIn('entry_type=DiaryEntry', session.gets[0]['url'])

    def test_missing_content_key_falls_back_to_legacy_fields(self):
        session = FakeSession(
            post_responses=[
                FakeResponse(status_code=400, text='column "content_key" does not exist'),
                FakeResponse(status_code=201),
            ],
            get_responses=[FakeResponse(payload=[local_row(DIARY_ENTRY)])],
        )
        result = importer.push_to_api(
            [DIARY_ENTRY], api_url='http://api.test/api/entries', session=session
        )
        self.assertTrue(result['success'])
        self.assertEqual(result['verified'], 1)
        self.assertEqual(len(session.posts), 2)
        self.assertIn('on_conflict=content_key', session.posts[0]['url'])
        self.assertIn('on_conflict=entry_type,date,subject,summary', session.posts[1]['url'])
        self.assertNotIn('content_key', session.posts[0]['json'])
        self.assertNotIn('source_id', session.posts[1]['json'])
        self.assertNotIn('content_key', session.gets[0]['url'])

    def test_push_failure_is_structured_and_raises(self):
        session = FakeSession(post_responses=[FakeResponse(status_code=500, text='failed')])
        with self.assertRaises(importer.PersistenceError) as context:
            importer.push_to_api(
                [DIARY_ENTRY],
                session=session,
                verify=False,
            )
        self.assertFalse(context.exception.result['success'])
        self.assertGreaterEqual(context.exception.result['pushed'], 0)

    def test_scrape_date_aggregates_required_section_failures(self):
        page = object()
        with patch.object(importer, 'scrape_diary', return_value=[]), patch.object(
            importer, 'scrape_worksheets', side_effect=RuntimeError('detail failed')
        ), patch.object(importer, 'scrape_announcements', return_value=[]):
            with self.assertRaisesRegex(RuntimeError, 'detail failed'):
                importer.scrape_date(page, '03 Jun 2026')
    def test_supabase_push_uses_rest_auth_and_endpoint(self):
        entry = dict(DIARY_ENTRY, source_id='supabase/id?x=1&y=2')
        session = FakeSession(
            post_responses=[FakeResponse(status_code=201)],
            get_responses=[FakeResponse(payload=[modern_row(entry)])],
        )
        with patch.dict(
            os.environ,
            {
                'API_URL': '',
                'SUPABASE_URL': 'https://project.supabase.co/',
                'SUPABASE_KEY': 'test-key',
                'SUPABASE_LEGACY_SCHEMA': '',
            },
        ):
            result = importer.push_to_api([entry], session=session)
        self.assertTrue(result['success'])
        self.assertEqual(result['verified'], 1)
        self.assertEqual(result['transport'], 'supabase')
        self.assertEqual(
            session.posts[0]['url'],
            'https://project.supabase.co/rest/v1/entries?on_conflict=content_key',
        )
        self.assertEqual(session.posts[0]['json']['entry_type'], entry['type'])
        self.assertNotIn('type', session.posts[0]['json'])
        self.assertEqual(session.posts[0]['headers']['apikey'], 'test-key')
        self.assertEqual(session.posts[0]['headers']['Authorization'], 'Bearer test-key')
        self.assertTrue(session.gets[0]['url'].startswith('https://project.supabase.co/rest/v1/entries?'))
        query = parse_qs(urlparse(session.gets[0]['url']).query)
        self.assertEqual(query['source_id'], [f'eq.{entry["source_id"]}'])
        self.assertEqual(query['entry_type'], [f'eq.{entry["type"]}'])
        self.assertEqual(query['select'], [importer.VERIFY_SELECT])
        self.assertIn('source_id=eq.supabase%2Fid%3Fx%3D1%26y%3D2', session.gets[0]['url'])

    def test_original_helpers_accept_legacy_arguments(self):
        self.assertEqual(importer.extract_worksheet_title('M Maths Sat ,06 Jun 2026'), 'Maths')
        self.assertEqual(importer.detect_subject('Maths Worksheet', '', ''), 'Maths')
        self.assertEqual(importer.detect_properties('Maths Revision WK 3 Answer Key', '', ''), (True, True))
        self.assertEqual(importer.extract_number('Maths Revision WK 3', ''), 3)
        html = '''
        <div class="card">
          <div class="card-header"><label>Teacher</label><span>03 Jun 2026</span></div>
          <div class="card-body"><h6>Notice</h6><p>A complete announcement body.</p></div>
        </div>
        '''
        entries = importer.extract_generic_cards(html, '03 Jun 2026', 'Announcement')
        self.assertEqual(entries[0]['type'], 'Announcement')
        self.assertEqual(entries[0]['subject'], 'Notice')
        self.assertEqual(entries[0]['date'], '2026-06-03')

    def test_canonical_entry_is_exact_and_complete(self):
        entry = importer.canonicalize_entry({
            'entry_type': 'Announcement',
            'title': 'Notice title',
            'subject': 'Notice',
            'category': 'General',
            'author': 'Teacher',
            'description': 'Body',
            'attachment_url': json.dumps([{'name': 'a.pdf', 'url': 'https://example.test/a.pdf'}]),
            'date': '03 Jun 2026',
            'portal_id': '83208',
            'role': 'Principal',
            'time': '10:00 AM',
            'rno': '1',
            'submission_date': '2026-06-13',
        })
        self.assertEqual(sorted(entry), sorted(importer.CANONICAL_FIELDS))
        self.assertTrue(importer.validate_canonical_entry(entry))
        self.assertEqual(entry['type'], 'Announcement')
        self.assertEqual(entry['label'], 'General')
        self.assertEqual(entry['subject'], 'Notice')
        self.assertEqual(entry['attachments'], [{'name': 'a.pdf', 'url': 'https://example.test/a.pdf'}])
        self.assertEqual(
            entry['attachment_url'],
            importer.serialize_attachments(entry['attachments']),
        )
        self.assertNotIn('rno', entry)
        self.assertNotIn('submission_date', entry)

    def test_canonical_validation_rejects_incomplete_or_extra_shapes(self):
        entry = importer.canonicalize_entry(DIARY_ENTRY)
        for mutate in (
            lambda value: value.pop('subject'),
            lambda value: value.update({'title': 'not a canonical subject'}),
            lambda value: value.update({'subject': ''}),
            lambda value: value.update({'date': 'not-a-date'}),
            lambda value: value.update({'attachments': 'not-a-list'}),
            lambda value: value.update({'attachments': [{'url': 'https://example.test/a.pdf'}]}),
            lambda value: value.update({'attachment_url': '[]'}),
            lambda value: value.update({'type': 'Unknown'}),
        ):
            broken = json.loads(json.dumps(entry))
            mutate(broken)
            with self.assertRaises(importer.MCBImportError):
                importer.validate_canonical_entry(broken)

    def test_push_requires_a_complete_canonical_result(self):
        session = FakeSession(post_responses=[FakeResponse(status_code=201)])
        for broken in (
            {'source_id': 'x', 'type': 'DiaryEntry', 'date': '2026-06-03', 'title': 'Only a title', 'summary': 's'},
            {'source_id': 'x', 'type': 'DiaryEntry', 'date': '2026-06-03', 'subject': 's', 'summary': 's', 'extra': 1},
        ):
            with self.assertRaises(importer.MCBImportError):
                importer.push_to_api([broken], api_url='http://api.test/api/entries', session=session)
        self.assertEqual(session.posts, [])
        self.assertEqual(session.gets, [])

    def test_modern_verification_fails_closed(self):
        cases = {
            'malformed body': FakeResponse(status_code=200, payload=None),
            'http failure': FakeResponse(status_code=500, payload=[]),
            'non list body': FakeResponse(status_code=200, payload={'data': [modern_row(DIARY_ENTRY)]}),
            'empty body': FakeResponse(status_code=200, payload=[]),
            'unusable rows': FakeResponse(status_code=200, payload=['not-a-row']),
            'other source id': FakeResponse(status_code=200, payload=[modern_row(dict(DIARY_ENTRY, source_id='other'))]),
        }
        for name, response in cases.items():
            session = FakeSession(
                post_responses=[FakeResponse(status_code=201)],
                get_responses=[response],
            )
            with self.subTest(case=name):
                with self.assertRaises(importer.PersistenceError) as context:
                    importer.push_to_api(
                        [DIARY_ENTRY], api_url='http://api.test/api/entries', session=session
                    )
                self.assertFalse(context.exception.result['success'])
                self.assertEqual(context.exception.result['verified'], 0)
                self.assertTrue(context.exception.result['errors'])

    def test_modern_verification_validates_every_persisted_field(self):
        mutations = {
            'source_id': dict(DIARY_ENTRY, source_id='other-source'),
            'subject': dict(DIARY_ENTRY, subject='Other subject'),
            'label': dict(DIARY_ENTRY, label='Other label'),
            'teacher': dict(DIARY_ENTRY, teacher='Other teacher'),
            'summary': dict(DIARY_ENTRY, summary='Other summary'),
            'entry_type': dict(DIARY_ENTRY, type='Announcement'),
            'date': dict(DIARY_ENTRY, date='2026-06-04'),
        }
        for field, mutated in mutations.items():
            row = modern_row(DIARY_ENTRY)
            row[field] = modern_row(mutated)[field]
            session = FakeSession(
                post_responses=[FakeResponse(status_code=201)],
                get_responses=[FakeResponse(status_code=200, payload=[row])],
            )
            with self.subTest(field=field):
                with self.assertRaises(importer.PersistenceError) as context:
                    importer.push_to_api(
                        [DIARY_ENTRY], api_url='http://api.test/api/entries', session=session
                    )
                self.assertIn(field, str(context.exception))
        for field, value in (
            ('attachments', []),
            ('attachment_url', '[]'),
        ):
            row = modern_row(DIARY_ENTRY)
            row[field] = value
            session = FakeSession(
                post_responses=[FakeResponse(status_code=201)],
                get_responses=[FakeResponse(status_code=200, payload=[row])],
            )
            with self.subTest(field=field):
                with self.assertRaises(importer.PersistenceError) as context:
                    importer.push_to_api(
                        [DIARY_ENTRY], api_url='http://api.test/api/entries', session=session
                    )
                self.assertIn(field, str(context.exception))

    def test_legacy_local_verification_fails_closed(self):
        other = local_row(dict(DIARY_ENTRY, subject='Different', source_id='different'))
        cases = {
            'empty list': FakeResponse(status_code=200, payload=[]),
            'malformed': FakeResponse(status_code=200, payload=None),
            'non list': FakeResponse(status_code=200, payload={'entries': [local_row(DIARY_ENTRY)]}),
            'missing row': FakeResponse(status_code=200, payload=[other]),
            'bad summary': FakeResponse(
                status_code=200,
                payload=[dict(local_row(DIARY_ENTRY), summary='Other summary')],
            ),
            'bad attachments': FakeResponse(
                status_code=200,
                payload=[dict(local_row(DIARY_ENTRY), attachment_url='[]')],
            ),
            'http failure': FakeResponse(status_code=503, payload=[]),
        }
        for name, response in cases.items():
            session = FakeSession(
                post_responses=[FakeResponse(status_code=400, text='unknown column source_id'), FakeResponse(status_code=201)],
                get_responses=[response],
            )
            with self.subTest(case=name):
                with self.assertRaises(importer.PersistenceError):
                    importer.push_to_api(
                        [DIARY_ENTRY], api_url='http://api.test/api/entries', session=session
                    )

    def test_supabase_legacy_verification_filters_and_validates(self):
        row = local_row(DIARY_ENTRY)
        session = FakeSession(
            post_responses=[FakeResponse(status_code=201)],
            get_responses=[FakeResponse(status_code=200, payload=[row])],
        )
        with patch.dict(
            os.environ,
            {
                'API_URL': '',
                'SUPABASE_URL': 'https://project.supabase.co',
                'SUPABASE_KEY': 'test-key',
                'SUPABASE_LEGACY_SCHEMA': '1',
            },
        ):
            result = importer.push_to_api([DIARY_ENTRY], session=session)
            self.assertTrue(result['success'])
            self.assertIn('entry_type=eq.DiaryEntry', session.gets[0]['url'])
            self.assertIn('date=eq.2026-06-03', session.gets[0]['url'])
            bad = FakeSession(
                post_responses=[FakeResponse(status_code=201)],
                get_responses=[FakeResponse(status_code=200, payload=[dict(row, summary='Other')])],
            )
            with self.assertRaises(importer.PersistenceError):
                importer.push_to_api([DIARY_ENTRY], session=bad)

    def test_every_session_call_carries_a_finite_timeout(self):
        session = FakeSession(
            post_responses=[FakeResponse(status_code=201)],
            get_responses=[FakeResponse(payload=[modern_row(DIARY_ENTRY)])],
        )
        importer.push_to_api([DIARY_ENTRY], api_url='http://api.test/api/entries', session=session)
        self.assertEqual(session.posts[0]['timeout'], (importer.DEFAULT_CONNECT_TIMEOUT, importer.DEFAULT_READ_TIMEOUT))
        self.assertEqual(session.gets[0]['timeout'], (importer.DEFAULT_CONNECT_TIMEOUT, importer.DEFAULT_READ_TIMEOUT))
        with patch.dict(os.environ, {'MCB_HTTP_TIMEOUT': '3,7'}):
            tuned = FakeSession(
                post_responses=[FakeResponse(status_code=201)],
                get_responses=[FakeResponse(payload=[modern_row(DIARY_ENTRY)])],
            )
            importer.push_to_api([DIARY_ENTRY], api_url='http://api.test/api/entries', session=tuned)
            self.assertEqual(tuned.posts[0]['timeout'], (3.0, 7.0))
            self.assertEqual(tuned.gets[0]['timeout'], (3.0, 7.0))
            self.assertEqual(importer.http_timeouts(), (3.0, 7.0))

    def test_timeout_configuration_is_validated(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('MCB_HTTP_TIMEOUT', None)
            os.environ.pop('API_HTTP_TIMEOUT', None)
            os.environ.pop('IMPORT_HTTP_TIMEOUT', None)
            self.assertEqual(
                importer.http_timeouts(),
                (importer.DEFAULT_CONNECT_TIMEOUT, importer.DEFAULT_READ_TIMEOUT),
            )
        for raw in ('0', '-4', 'abc', 'inf', 'nan', '5,0'):
            with self.subTest(value=raw):
                with patch.dict(os.environ, {'MCB_HTTP_TIMEOUT': raw}):
                    with self.assertRaises(importer.MCBImportError):
                        importer.http_timeouts()

    def test_module_never_issues_an_unbounded_request(self):
        source = (ROOT / 'mcb_import.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        http_receivers = {'session', 'active_session', 'http_requests'}
        http_methods = {'get', 'post', 'put', 'patch', 'delete', 'head', 'request'}
        bounded = {'goto', 'wait_for_selector', 'wait_for_load_state'}
        bounded_receivers = {'page', 'page.keyboard'}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            receiver = ast.unparse(node.func.value)
            keywords = {keyword.arg for keyword in node.keywords}
            if node.func.attr in http_methods and receiver in http_receivers:
                self.assertIn('timeout', keywords, f'{receiver}.{node.func.attr} has no timeout')
            if node.func.attr in bounded and receiver in bounded_receivers:
                self.assertIn('timeout', keywords, f'{receiver}.{node.func.attr} has no timeout')

    def test_module_http_calls_use_the_timeout_helper(self):
        fake_requests = Mock()
        fake_requests.get.return_value = FakeResponse(status_code=200, payload=[])
        with patch.dict(os.environ, {'SUPABASE_URL': '', 'SUPABASE_KEY': ''}):
            with patch.object(importer, 'http_requests', fake_requests):
                self.assertEqual(importer.fetch_existing_worksheets(), [])
        self.assertIn('timeout', fake_requests.get.call_args.kwargs)
        self.assertEqual(fake_requests.get.call_args.kwargs['timeout'], (10.0, 30.0))
        supabase_requests = Mock()
        supabase_requests.get.return_value = FakeResponse(status_code=200, payload=[])
        with patch.dict(
            os.environ,
            {'SUPABASE_URL': 'https://project.supabase.co', 'SUPABASE_KEY': 'key'},
        ):
            with patch.object(importer, 'http_requests', supabase_requests):
                self.assertEqual(importer.fetch_existing_worksheets(), [])
        self.assertIn('timeout', supabase_requests.get.call_args.kwargs)

    def test_existing_worksheet_lookup_does_not_report_false_success(self):
        fake_requests = Mock()
        fake_requests.get.side_effect = requests.exceptions.ConnectionError('refused')
        with patch.dict(os.environ, {'SUPABASE_URL': '', 'SUPABASE_KEY': ''}):
            with patch.object(importer, 'http_requests', fake_requests):
                with self.assertRaises(importer.MCBImportError):
                    importer.fetch_existing_worksheets()
        fake_requests.get.side_effect = requests.exceptions.ReadTimeout('read timed out')
        with patch.dict(os.environ, {'SUPABASE_URL': '', 'SUPABASE_KEY': ''}):
            with patch.object(importer, 'http_requests', fake_requests):
                with self.assertRaises(importer.ImportTimeoutError):
                    importer.fetch_existing_worksheets()

    def test_push_timeout_fails_with_a_clear_error(self):
        session = FakeSession(post_error=requests.exceptions.ReadTimeout('read timed out'))
        with self.assertRaises(importer.PersistenceError) as context:
            importer.push_to_api([DIARY_ENTRY], api_url='http://api.test/api/entries', session=session)
        self.assertIn('timed out', str(context.exception))
        session = FakeSession(
            post_responses=[FakeResponse(status_code=201)],
            get_error=requests.exceptions.ConnectTimeout('connect timed out'),
        )
        with self.assertRaises(importer.PersistenceError) as context:
            importer.push_to_api([DIARY_ENTRY], api_url='http://api.test/api/entries', session=session)
        self.assertIn('timed out', str(context.exception))
        self.assertEqual(context.exception.result['verified'], 0)

    def test_ajax_requests_are_bounded_and_report_timeouts(self):
        page = FakeAjaxPage(html='<div>ok</div>')
        importer._ajax_request(page, 'https://portal.test/x')
        script, arguments = page.calls[0]
        self.assertIn('AbortController', script)
        self.assertEqual(arguments['timeout'], importer.AJAX_TIMEOUT_MS)
        aborted = FakeAjaxPage(responses=[{'status': 0, 'ok': False, 'body': '', 'aborted': True, 'error': 'aborted'}])
        with self.assertRaises(importer.ImportTimeoutError) as context:
            importer._ajax_request(aborted, 'https://portal.test/x')
        self.assertIn('timed out', str(context.exception))
        failing = FakeAjaxPage(error=TimeoutError('Timeout 30000ms exceeded'))
        with self.assertRaises(importer.ImportTimeoutError):
            importer._ajax_request(failing, 'https://portal.test/x')
        empty = FakeAjaxPage(html='   ')
        with self.assertRaises(importer.MCBImportError):
            importer._ajax_request(empty, 'https://portal.test/x')
        error_page = FakeAjaxPage(responses=[{'status': 500, 'ok': False, 'body': 'boom', 'aborted': False}])
        with self.assertRaises(importer.MCBImportError) as context:
            importer._ajax_request(error_page, 'https://portal.test/x')
        self.assertIn('500', str(context.exception))

    def test_scrape_dates_collects_each_section_once(self):
        calls = {'worksheets': [], 'announcements': [], 'diary': []}

        def fake_worksheets(page, diary_date, scrape_all=False):
            calls['worksheets'].append((diary_date, scrape_all))
            return [importer.canonicalize_entry({
                'type': 'Worksheet', 'subject': 'Worksheet one', 'label': 'Maths',
                'teacher': 'Teacher', 'summary': 'Detail', 'date': '2026-06-02',
                'source_id': 'worksheet:1:0:1',
            })]

        def fake_announcements(page, diary_date):
            calls['announcements'].append(diary_date)
            return [importer.canonicalize_entry({
                'type': 'Announcement', 'subject': 'Notice', 'label': 'General',
                'teacher': 'Teacher', 'summary': 'Body', 'date': '2026-06-01',
                'source_id': 'announcement-1',
            })]

        def fake_diary(page, diary_date):
            key = diary_date.isoformat() if hasattr(diary_date, 'isoformat') else str(diary_date)
            calls['diary'].append(key)
            return [importer.canonicalize_entry({
                'type': 'DiaryEntry', 'subject': f'Diary {key}', 'label': 'General',
                'teacher': 'Teacher', 'summary': 'Body', 'date': key,
                'source_id': f'diary-{key}',
            })]

        with patch.object(importer, 'scrape_worksheets', side_effect=fake_worksheets), patch.object(
            importer, 'scrape_announcements', side_effect=fake_announcements
        ), patch.object(importer, 'scrape_diary', side_effect=fake_diary):
            results = importer.scrape_dates(
                start_date='2026-06-01', end_date='2026-06-03', page=object()
            )
        self.assertEqual(len(calls['worksheets']), 1)
        self.assertTrue(calls['worksheets'][0][1])
        self.assertEqual(len(calls['announcements']), 1)
        self.assertEqual(
            calls['diary'], ['2026-06-01', '2026-06-02', '2026-06-03']
        )
        self.assertEqual(
            [current.isoformat() for current, _ in results],
            ['2026-06-01', '2026-06-02', '2026-06-03'],
        )
        by_date = {current.isoformat(): entries for current, entries in results}
        self.assertEqual(len(by_date['2026-06-01']), 2)
        self.assertEqual(len(by_date['2026-06-02']), 2)
        self.assertEqual(len(by_date['2026-06-03']), 1)
        with patch.object(importer, 'scrape_worksheets', side_effect=fake_worksheets), patch.object(
            importer, 'scrape_announcements', side_effect=fake_announcements
        ), patch.object(importer, 'scrape_diary', side_effect=fake_diary):
            flat = importer.scrape_data(
                start_date='2026-06-01', end_date='2026-06-03', page=object()
            )
        self.assertEqual(len(flat), 5)

    def test_scrape_dates_clamps_entries_outside_the_range(self):
        far_entry = importer.canonicalize_entry({
            'type': 'Announcement', 'subject': 'Old notice', 'label': 'General',
            'teacher': 'Teacher', 'summary': 'Body', 'date': '2026-01-01',
            'source_id': 'announcement-old',
        })
        with patch.object(importer, 'scrape_worksheets', return_value=[]), patch.object(
            importer, 'scrape_announcements', return_value=[far_entry]
        ), patch.object(importer, 'scrape_diary', return_value=[]):
            results = importer.scrape_dates(
                start_date='2026-06-01', end_date='2026-06-02', page=object()
            )
        grouped = dict(results)
        first, second = grouped[date(2026, 6, 1)], grouped[date(2026, 6, 2)]
        self.assertEqual([entry['source_id'] for entry in first], ['announcement-old'])
        self.assertEqual(second, [])

    def test_scrape_dates_reports_failures_instead_of_no_ops(self):
        with patch.object(importer, 'scrape_worksheets', side_effect=importer.MCBImportError('listing failed')), patch.object(
            importer, 'scrape_announcements', return_value=[]
        ), patch.object(importer, 'scrape_diary', return_value=[]):
            with self.assertRaisesRegex(importer.MCBImportError, 'listing failed'):
                importer.scrape_dates(start_date='2026-06-01', end_date='2026-06-02', page=object())
        with patch.object(importer, 'scrape_worksheets', return_value=[]), patch.object(
            importer, 'scrape_announcements', return_value=[]
        ), patch.object(
            importer, 'scrape_diary', side_effect=[importer.ImportTimeoutError('diary timed out'), []]
        ):
            with self.assertRaisesRegex(importer.MCBImportError, 'timed out'):
                importer.scrape_dates(start_date='2026-06-01', end_date='2026-06-02', page=object())

    def test_single_date_range_keeps_per_date_scrape(self):
        with patch.object(importer, 'scrape_date', return_value=[importer.canonicalize_entry(DIARY_ENTRY)]) as single:
            results = importer.scrape_dates(start_date='2026-06-03', end_date='2026-06-03', page=object())
        self.assertEqual(single.call_count, 1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], date(2026, 6, 3))
        self.assertEqual(len(results[0][1]), 1)

    def test_diary_crawl_accepts_known_empty_state_and_fails_closed_otherwise(self):
        page = FakeAjaxPage(html='<div>No diary entries for 03 Jun 2026</div>')
        self.assertEqual(importer.scrape_diary(page, '03 Jun 2026'), [])
        changed = FakeAjaxPage(html='<html><body><div class="panel">Redesigned layout</div></body></html>')
        with self.assertRaises(importer.MCBImportError):
            importer.scrape_diary(changed, '03 Jun 2026')
        aborted = FakeAjaxPage(responses=[{'status': 0, 'ok': False, 'body': '', 'aborted': True, 'error': 'aborted'}])
        with self.assertRaises(importer.ImportTimeoutError):
            importer.scrape_diary(aborted, '03 Jun 2026')

    def test_announcement_crawl_accepts_known_empty_state_and_fails_closed_otherwise(self):
        page = FakeAjaxPage(html='<div>No announcements</div>')
        with patch.object(importer, '_open_announcements_page'), patch.object(
            importer, 'ensure_authenticated', return_value=True
        ):
            self.assertEqual(importer.scrape_announcements(page, '03 Jun 2026'), [])
        changed = FakeAjaxPage(html='<html><body><section>Completely new markup</section></body></html>')
        with patch.object(importer, '_open_announcements_page'), patch.object(
            importer, 'ensure_authenticated', return_value=True
        ):
            with self.assertRaises(importer.MCBImportError):
                importer.scrape_announcements(changed, '03 Jun 2026')

    def test_worksheet_listing_does_not_swallow_transport_failures(self):
        page = FakeAjaxPage(html='<html><body>no ViewQuestion markup</body></html>')
        with patch.object(importer, 'fetch_ajax_data', side_effect=importer.ImportTimeoutError('listing timed out')):
            with self.assertRaises(importer.ImportTimeoutError):
                importer._worksheet_listing(page, '03 Jun 2026')
        with patch.object(importer, 'fetch_ajax_data', side_effect=importer.MCBImportError('worksheet AJAX request returned HTTP 503')):
            with self.assertRaises(importer.MCBImportError) as context:
                importer._worksheet_listing(page, '03 Jun 2026')
        self.assertIn('503', str(context.exception))
        with patch.object(importer, 'fetch_ajax_data', return_value='unexpected payload markup'):
            with self.assertRaisesRegex(importer.MCBImportError, 'did not contain assignments'):
                importer._worksheet_listing(page, '03 Jun 2026')
        with patch.object(importer, 'fetch_ajax_data', return_value='No records found'):
            self.assertEqual(importer._worksheet_listing(page, '03 Jun 2026'), [])

    def test_worksheet_listing_uses_the_enrollment_endpoint_without_swallowing(self):
        page = FakeAjaxPage(html='<html><body>StudentEnrollmentID: 55</body></html>')
        seen = []

        def fake_fetch(page_arg, endpoint, params=None, method='GET', rno=None, source='worksheet'):
            seen.append(endpoint)
            if endpoint == 'MyAssignments_Get':
                return 'unexpected payload markup'
            return [{'assignment_id': '1', 'qb_question_id': '0', 'rno': '1'}]

        with patch.object(importer, 'fetch_ajax_data', side_effect=fake_fetch):
            records = importer._worksheet_listing(page, '03 Jun 2026')
        self.assertEqual(seen, ['MyAssignments_Get', 'Master_Student/GetStudentAssignmentQuestionList'])
        self.assertEqual(len(records), 1)

    def test_quiet_hours_window(self):
        self.assertTrue(importer.in_quiet_hours(datetime(2026, 6, 3, 0, 0)))
        self.assertTrue(importer.in_quiet_hours(datetime(2026, 6, 3, 5, 59)))
        self.assertFalse(importer.in_quiet_hours(datetime(2026, 6, 3, 6, 0)))
        self.assertFalse(importer.in_quiet_hours(datetime(2026, 6, 3, 23, 59)))

    def test_main_skips_quiet_hours_but_force_and_all_bypass(self):
        with patch.object(importer, 'in_quiet_hours', return_value=True), patch.object(
            importer, 'scrape_dates'
        ) as scrape, patch.object(importer, 'push_to_api') as push:
            self.assertEqual(importer.main([]), 0)
            self.assertFalse(scrape.called)
            self.assertFalse(push.called)
        for argv in (['--force'], ['--all']):
            with patch.object(importer, 'in_quiet_hours', return_value=True), patch.object(
                importer, 'scrape_dates', return_value=[(date(2026, 6, 3), [])]
            ) as scrape, patch.object(importer, 'push_to_api') as push:
                self.assertEqual(importer.main(argv), 0)
                self.assertTrue(scrape.called)
                self.assertFalse(push.called)

    def test_main_loads_environment_before_selecting_dates(self):
        captured = {}

        def fake_load():
            os.environ['MCB_END_DATE'] = '2026-01-02'

        def fake_scrape(start_date=None, end_date=None, page=None):
            captured['start'] = start_date
            captured['end'] = end_date
            return []

        environment = {'MCB_START_DATE': '2026-01-01', 'MCB_END_DATE': ''}
        with patch.dict(os.environ, environment, clear=False):
            with patch.object(importer, '_load_runtime_env', side_effect=fake_load), patch.object(
                importer, 'scrape_dates', side_effect=fake_scrape
            ):
                self.assertEqual(importer.main(['--all']), 0)
        self.assertEqual(captured['start'], date(2026, 1, 1))
        self.assertEqual(captured['end'], date(2026, 1, 2))

    def test_all_defaults_run_through_today(self):
        captured = {}

        def fake_scrape(start_date=None, end_date=None, page=None):
            captured['start'] = start_date
            captured['end'] = end_date
            return []

        for name in ('MCB_START_DATE', 'MCB_END_DATE', 'IMPORT_START_DATE', 'IMPORT_END_DATE'):
            os.environ.pop(name, None)
        with patch.object(importer, '_load_runtime_env', return_value=None), patch.object(
            importer, 'scrape_dates', side_effect=fake_scrape
        ):
            self.assertEqual(importer.main(['--all']), 0)
        today = date.today()
        self.assertEqual(captured['end'], today)
        self.assertEqual(
            captured['start'], today - timedelta(days=importer.DEFAULT_HISTORY_DAYS)
        )
        with patch.object(importer, '_load_runtime_env', return_value=None), patch.object(
            importer, 'scrape_data', side_effect=fake_scrape
        ):
            entries = importer.scrape_mcb(scrape_all=True)
        self.assertEqual(captured['end'], today)
        self.assertEqual(entries, [])

    def test_scrape_mcb_single_date_defaults_to_today(self):
        captured = {}

        def fake_scrape(start_date=None, end_date=None, page=None):
            captured['start'] = start_date
            captured['end'] = end_date
            return []

        with patch.object(importer, '_load_runtime_env', return_value=None), patch.object(
            importer, 'scrape_data', side_effect=fake_scrape
        ):
            importer.scrape_mcb()
        self.assertEqual(captured['start'], date.today())
        self.assertEqual(captured['end'], date.today())

    def test_main_exit_codes_are_truthful(self):
        entries = [importer.canonicalize_entry(DIARY_ENTRY)]
        with patch.object(
            importer, 'in_quiet_hours', return_value=False
        ), patch.object(
            importer, 'scrape_dates', side_effect=importer.MCBImportError('portal unavailable')
        ):
            self.assertEqual(importer.main([]), 1)
        with patch.dict(
            os.environ,
            {'API_URL': 'http://api.test', 'SUPABASE_URL': '', 'SUPABASE_KEY': ''},
        ), patch.object(importer, 'in_quiet_hours', return_value=False), patch.object(
            importer, 'scrape_dates', return_value=[(date(2026, 6, 3), entries)]
        ), patch.object(importer, 'push_to_api', return_value={'success': False, 'message': 'nope', 'pushed': 0, 'verified': 0}):
            self.assertEqual(importer.main([]), 1)
        with patch.dict(
            os.environ,
            {'API_URL': 'http://api.test', 'SUPABASE_URL': '', 'SUPABASE_KEY': ''},
        ), patch.object(importer, 'in_quiet_hours', return_value=False), patch.object(
            importer, 'scrape_dates', return_value=[(date(2026, 6, 3), [])]
        ), patch.object(importer, 'push_to_api') as push:
            self.assertEqual(importer.main([]), 0)
            self.assertFalse(push.called)
        with patch.dict(
            os.environ,
            {'API_URL': 'http://api.test', 'SUPABASE_URL': '', 'SUPABASE_KEY': ''},
        ), patch.object(importer, 'in_quiet_hours', return_value=False), patch.object(
            importer, 'scrape_dates', return_value=[(date(2026, 6, 3), entries)]
        ), patch.object(
            importer, 'push_to_api', return_value={'success': True, 'pushed': 1, 'verified': 1}
        ):
            self.assertEqual(importer.main([]), 0)

    def test_main_rejects_unparsable_dates(self):
        with patch.object(importer, 'in_quiet_hours', return_value=False):
            self.assertEqual(importer.main(['not-a-date']), 1)

    def test_login_uses_the_next_portal_url_and_reports_all_failures(self):
        page = FakeLoginPage(ready_urls=set(importer.PORTAL_URLS[1:]), login_link=True)
        browser = FakeBrowser(page)
        with patch.dict(os.environ, {'MCB_USERNAME': 'user', 'MCB_PASSWORD': 'pass'}), patch.object(
            importer, 'sync_playwright', lambda: FakePlaywright(browser)
        ):
            returned_browser, returned_context, returned_page = importer.login_to_mcb()
        self.assertEqual([url for url, _ in page.goto_calls], list(importer.PORTAL_URLS[:2]))
        self.assertIs(returned_page, page)
        self.assertFalse(browser.closed)
        self.assertFalse(returned_context.closed)
        self.assertTrue(all(timeout for _, timeout in page.goto_calls))

        failing = FakeLoginPage(ready_urls=set())
        failing_browser = FakeBrowser(failing)
        with patch.dict(os.environ, {'MCB_USERNAME': 'user', 'MCB_PASSWORD': 'pass'}), patch.object(
            importer, 'sync_playwright', lambda: FakePlaywright(failing_browser)
        ):
            with self.assertRaises(importer.MCBImportError) as context:
                importer.login_to_mcb()
        message = str(context.exception)
        for url in importer.PORTAL_URLS:
            self.assertIn(url, message)
        self.assertTrue(failing_browser.closed)
        self.assertTrue(failing_browser.contexts[0].closed)

    def test_login_readiness_retries_before_failing(self):
        attempts = {'count': 0}

        def flaky(page):
            attempts['count'] += 1
            if attempts['count'] < 3:
                raise importer.MCBImportError('MCB session is still on the login page')
            return True

        with patch.object(importer, 'ensure_authenticated', side_effect=flaky):
            self.assertTrue(importer._wait_until_ready(lambda: importer.ensure_authenticated(object())))

        def always_fails(page):
            raise importer.MCBImportError('MCB login was not accepted')

        page = FakeLoginPage(ready_urls=set(importer.PORTAL_URLS))
        with patch.object(importer, 'ensure_authenticated', side_effect=always_fails):
            with self.assertRaisesRegex(importer.MCBImportError, 'MCB login was not accepted'):
                importer._wait_until_ready(lambda: importer.ensure_authenticated(page), page=page)

    def test_ensure_authenticated_detects_login_and_session_loss(self):
        login_page = FakeLoginPage(ready_urls=set(), login_link=True)
        with self.assertRaises(importer.MCBImportError):
            importer.ensure_authenticated(login_page)
        ready_page = FakeLoginPage(ready_urls=set(importer.PORTAL_URLS))
        ready_page.url = importer.PORTAL_URLS[0]
        ready_page.authenticated = True
        self.assertTrue(importer.ensure_authenticated(ready_page))


if __name__ == '__main__':
    unittest.main()
