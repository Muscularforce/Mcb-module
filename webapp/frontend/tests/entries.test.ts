import test from 'node:test';
import assert from 'node:assert/strict';
import {
  applyRealtimeChange,
  applyRealtimeChangeDetailed,
  dedupeEntries,
  entryDedupeKey,
  firstVisitReadIds,
  firstVisitReadKeys,
  formatLocalDate,
  getSafeAttachments,
  mapSupabaseRow,
  parseAttachments,
  parseLocalDate,
  reconcileRealtimeChanges,
} from '../src/lib/entries.ts';
import { collectAllPages, pageRange } from '../src/lib/pagination.ts';

const row = (overrides: Record<string, unknown> = {}) => ({
  id: 1,
  entry_type: 'Worksheet',
  subject: 'Algebra',
  label: 'Mathematics',
  summary: 'Complete the worksheet.',
  teacher: 'Ms. Rao',
  date: '2026-06-03',
  source_id: 'source-1',
  updated_at: '2026-06-03T10:00:00.000Z',
  attachments: [
    { name: 'Algebra.pdf', url: 'https://cdn.example.com/algebra.pdf' },
    { name: 'Help.png', url: 'https://cdn.example.com/help.png' },
  ],
  ...overrides,
});

test('collects every deterministic page including a full final page', async () => {
  const calls: number[][] = [];
  const firstPage = Array.from({ length: 1000 }, (_, index) => ({ id: index }));
  const result = await collectAllPages(async (from, to) => {
    calls.push([from, to]);
    return from === 0
      ? { data: firstPage }
      : { data: [{ id: 1000 }, { id: 1001 }] };
  });

  assert.equal(result.length, 1002);
  assert.deepEqual(calls, [[0, 999], [1000, 1999]]);
  assert.deepEqual(pageRange(2, 1000), { from: 2000, to: 2999 });
});

test('does not return partial data when a later page fails', async () => {
  await assert.rejects(
    collectAllPages(async from => (
      from === 0
        ? { data: Array.from({ length: 1000 }, (_, id) => ({ id })) }
        : { data: null, error: new Error('page failed') }
    )),
    /page failed/,
  );
});

test('deduplicates source IDs within a type without crossing entry types', () => {
  const worksheet = mapSupabaseRow(row({ id: 1, source_id: 'shared' }));
  const worksheetDuplicate = mapSupabaseRow(row({ id: 2, source_id: 'shared' }));
  const diary = mapSupabaseRow(row({ id: 3, entry_type: 'DiaryEntry', source_id: 'shared' }));

  const result = dedupeEntries([worksheet, worksheetDuplicate, diary]);
  assert.equal(result.filter(entry => entry.entry_type === 'Worksheet').length, 1);
  assert.equal(result.filter(entry => entry.entry_type === 'DiaryEntry').length, 1);
  assert.notEqual(entryDedupeKey(worksheet), entryDedupeKey(diary));
});

test('merges fresher duplicate fields while retaining older attachments', () => {
  const older = mapSupabaseRow(row({
    id: 10,
    source_id: 'merge-1',
    updated_at: '2026-06-03T09:00:00.000Z',
    subject: 'Old title',
    label: '',
    summary: 'Old summary',
    attachments: [{ name: 'old.pdf', url: 'https://cdn-mcb.myclassboard.com/old.pdf' }],
  }));
  const newer = mapSupabaseRow(row({
    id: 11,
    source_id: 'merge-1',
    updated_at: '2026-06-03T11:00:00.000Z',
    subject: 'Fresh title',
    label: 'Fresh portal',
    summary: 'Fresh summary',
    attachments: [{ name: 'new.pdf', url: 'https://cdn-mcb.myclassboard.com/new.pdf' }],
  }));

  const [merged] = dedupeEntries([older, newer]);
  assert.equal(merged.subject, 'Fresh title');
  assert.equal(merged.label, 'Fresh portal');
  assert.equal(merged.summary, 'Fresh summary');
  assert.equal(merged.updated_at, '2026-06-03T11:00:00.000Z');
  assert.deepEqual(merged.attachments.map(attachment => attachment.name), ['new.pdf', 'old.pdf']);
});

test('maps legacy content fields used by cached entries', () => {
  const mapped = mapSupabaseRow({
    id: 25,
    entry_type: 'DiaryEntry',
    subject: 'Legacy diary',
    content: 'Legacy description',
    date: '2026-06-03',
  });
  assert.equal(mapped.content, 'Legacy description');
  assert.equal(mapped.summary, 'Legacy description');
});

test('uses legacy created_at when updated_at is absent', () => {
  const older = mapSupabaseRow(row({
    id: 20,
    source_id: 'legacy-1',
    updated_at: undefined,
    created_at: '2026-06-01T08:00:00.000Z',
  }));
  const newer = mapSupabaseRow(row({
    id: 21,
    source_id: 'legacy-1',
    updated_at: undefined,
    created_at: '2026-06-02T08:00:00.000Z',
  }));

  const [freshest] = dedupeEntries([older, newer]);
  assert.equal(freshest.id, 21);
  assert.equal(freshest.created_at, '2026-06-02T08:00:00.000Z');
});

test('parses date-only values at local calendar midnight and baselines from newest data', () => {
  const parsed = parseLocalDate('2026-06-03');
  assert.ok(parsed);
  assert.equal(parsed.getFullYear(), 2026);
  assert.equal(parsed.getMonth(), 5);
  assert.equal(parsed.getDate(), 3);
  assert.equal(parsed.getHours(), 0);
  assert.equal(formatLocalDate('2026-06-03'), 'Jun 3');

  const newest = mapSupabaseRow(row({ id: 30, date: '2026-06-10', source_id: 'date-new' }));
  const recent = mapSupabaseRow(row({ id: 31, date: '2026-06-09', source_id: 'date-recent' }));
  const old = mapSupabaseRow(row({ id: 32, date: '2026-06-01', source_id: 'date-old' }));
  const baseline = firstVisitReadKeys([old, recent, newest]);
  assert.equal(baseline.size, 1);
  assert.equal([...baseline][0], 'source:Worksheet:date-old');
  assert.deepEqual([...firstVisitReadIds([old, recent, newest])], ['date-old']);
});

test('keeps legacy attachment formats and filters unsafe hosts at action boundaries', () => {
  const current = parseAttachments([
    { name: 'Notes.pdf', url: 'https://example.com/notes.pdf' },
    { name: 'Duplicate', url: 'https://EXAMPLE.com:443/notes.pdf#page=1' },
    { name: 'Unsafe', url: 'javascript:alert(1)' },
    { name: 'Missing', url: 'not a url' },
  ]);
  assert.deepEqual(current, [
    { name: 'Notes.pdf', url: 'https://example.com/notes.pdf' },
  ]);

  const legacyJson = parseAttachments(undefined, JSON.stringify([
    'https://cdn-mcb.myclassboard.com/one.pdf',
    { name: 'Two.docx', url: 'https://cdn-mcb.myclassboard.com/two.docx' },
    'ftp://cdn-mcb.myclassboard.com/unsafe.pdf',
  ]));
  assert.deepEqual(legacyJson, [
    { name: 'one.pdf', url: 'https://cdn-mcb.myclassboard.com/one.pdf' },
    { name: 'Two.docx', url: 'https://cdn-mcb.myclassboard.com/two.docx' },
  ]);
  assert.deepEqual(parseAttachments(undefined, 'https://cdn-mcb.myclassboard.com/file.pdf'), [
    { name: 'file.pdf', url: 'https://cdn-mcb.myclassboard.com/file.pdf' },
  ]);
  assert.deepEqual(parseAttachments('[{bad json}]', 'javascript:alert(1)'), []);

  const safe = getSafeAttachments([
    { name: 'Trusted', url: 'https://cdn-mcb.myclassboard.com/trusted.pdf' },
    { name: 'External', url: 'https://example.com/external.pdf' },
    { name: 'Local', url: 'https://localhost/local.pdf' },
    { name: 'Insecure', url: 'http://cdn-mcb.myclassboard.com/insecure.pdf' },
    { name: 'Credentials', url: 'https://user:pass@cdn-mcb.myclassboard.com/secret.pdf' },
  ]);
  assert.deepEqual(safe.map(attachment => attachment.name), ['Trusted']);
});

test('realtime insert, update, duplicate, and source delete behavior stays deduplicated', () => {
  const inserted = applyRealtimeChange([], {
    eventType: 'INSERT',
    new: row({ id: 7, source_id: 'realtime-7' }),
  });
  assert.equal(inserted.length, 1);

  const updated = applyRealtimeChange(inserted, {
    eventType: 'UPDATE',
    old: { id: 7 },
    new: row({ id: 7, subject: 'Updated Algebra', source_id: 'realtime-7' }),
  });
  assert.equal(updated.length, 1);
  assert.equal(updated[0].subject, 'Updated Algebra');

  const duplicate = applyRealtimeChange(updated, {
    eventType: 'INSERT',
    new: row({ id: 8, source_id: 'realtime-7', updated_at: '2026-06-03T12:00:00.000Z' }),
  });
  assert.equal(duplicate.length, 1);
  assert.equal(duplicate[0].id, 8);

  const deleted = applyRealtimeChange(duplicate, {
    eventType: 'DELETE',
    old: { id: 8, entry_type: 'Worksheet', source_id: 'realtime-7' },
  });
  assert.equal(deleted.length, 0);
});

test('does not let an out-of-order realtime update replace fresher content', () => {
  const current = mapSupabaseRow(row({
    id: 60,
    source_id: 'stale-update',
    subject: 'Current title',
    summary: 'Current summary',
    updated_at: '2026-06-03T12:00:00.000Z',
  }));
  const result = applyRealtimeChange([current], {
    eventType: 'UPDATE',
    old: { id: 60, entry_type: 'Worksheet', source_id: 'stale-update' },
    new: row({
      id: 60,
      source_id: 'stale-update',
      subject: 'Stale title',
      summary: 'Stale summary',
      updated_at: '2026-06-03T10:00:00.000Z',
    }),
  });
  assert.equal(result[0].subject, 'Current title');
  assert.equal(result[0].summary, 'Current summary');
});

test('legacy delete requests authoritative reconciliation instead of deleting by id', () => {
  const legacy = mapSupabaseRow(row({ id: 40, source_id: undefined }));
  const result = applyRealtimeChangeDetailed([legacy], {
    eventType: 'DELETE',
    old: { id: 40 },
  });
  assert.equal(result.entries.length, 1);
  assert.equal(result.needsAuthoritativeRefetch, true);
});

test('realtime rows sort by local date and update time', () => {
  const first = mapSupabaseRow(row({ id: 1, date: '2026-06-01', source_id: 'a' }));
  const second = mapSupabaseRow(row({
    id: 2,
    date: '2026-06-03',
    source_id: 'b',
    updated_at: '2026-06-03T09:00:00.000Z',
  }));
  const third = mapSupabaseRow(row({
    id: 3,
    date: '2026-06-03',
    source_id: 'c',
    updated_at: '2026-06-03T10:00:00.000Z',
  }));
  const result = applyRealtimeChange([], { eventType: 'INSERT', new: first });
  const withSecond = applyRealtimeChange(result, { eventType: 'INSERT', new: second });
  const sorted = applyRealtimeChange(withSecond, { eventType: 'INSERT', new: third });
  assert.deepEqual(sorted.map(entry => entry.id), [3, 2, 1]);
});

test('reconciles buffered events after a fetch without cross-type deletion', () => {
  const worksheet = mapSupabaseRow(row({ id: 50, entry_type: 'Worksheet', source_id: 'buffered' }));
  const diary = mapSupabaseRow(row({ id: 50, entry_type: 'DiaryEntry', source_id: 'buffered' }));
  const result = reconcileRealtimeChanges([worksheet, diary], [{
    eventType: 'DELETE',
    old: { id: 50, entry_type: 'Worksheet', source_id: 'buffered' },
  }]);
  assert.deepEqual(result.entries.map(entry => entry.entry_type), ['DiaryEntry']);
  assert.equal(result.needsAuthoritativeRefetch, false);
});
