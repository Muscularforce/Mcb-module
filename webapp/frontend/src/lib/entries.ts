import type {
  Attachment,
  CanonicalEntryType,
  Entry,
  EntryId,
  EntryType,
  RealtimeChange,
  SupabaseEntryRow,
} from '../types.ts';

const canonicalEntryTypes: Record<string, CanonicalEntryType> = {
  diaryentry: 'DiaryEntry',
  diary: 'DiaryEntry',
  worksheet: 'Worksheet',
  announcement: 'Announcement',
};

const entryTypeNames: Record<CanonicalEntryType, EntryType> = {
  DiaryEntry: 'diary',
  Worksheet: 'worksheet',
  Announcement: 'announcement',
};

const trustedAttachmentHosts = ['myclassboard.com'];

const isRecord = (value: unknown): value is Record<string, unknown> => (
  typeof value === 'object' && value !== null && !Array.isArray(value)
);

const textValue = (value: unknown): string => {
  if (typeof value === 'string') return value.trim();
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return '';
};

const optionalId = (value: unknown): EntryId | undefined => {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed ? trimmed : undefined;
  }
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  return undefined;
};

const parseJsonValue = (value: unknown): unknown => {
  if (typeof value !== 'string') return value;
  const trimmed = value.trim();
  if (!trimmed) return value;
  try {
    return JSON.parse(trimmed);
  } catch {
    return value;
  }
};

const collectionValues = (value: unknown): unknown[] => {
  const parsed = parseJsonValue(value);
  if (Array.isArray(parsed)) return parsed;
  if (typeof parsed === 'string') return [parsed];
  if (isRecord(parsed)) return [parsed];
  return [];
};

const normalizedHostname = (value: string): string => value.trim().toLowerCase().replace(/\.$/, '');

const isPrivateIpv4 = (hostname: string): boolean => {
  const parts = hostname.split('.');
  if (parts.length !== 4 || parts.some(part => !/^\d{1,3}$/.test(part))) return false;
  const octets = parts.map(Number);
  if (octets.some(octet => octet < 0 || octet > 255)) return true;
  const [first, second] = octets;
  return first === 0
    || first === 10
    || first === 127
    || (first === 100 && second >= 64 && second <= 127)
    || (first === 169 && second === 254)
    || (first === 172 && second >= 16 && second <= 31)
    || (first === 192 && second === 0)
    || (first === 192 && second === 168)
    || (first === 198 && (second === 18 || second === 19))
    || (first === 198 && second === 51)
    || (first === 203 && second === 0)
    || first >= 224;
};

const isPrivateOrLocalHost = (value: string): boolean => {
  const hostname = normalizedHostname(value).replace(/^\[|\]$/g, '');
  if (!hostname) return true;
  if (hostname === 'localhost' || hostname.endsWith('.localhost')) return true;
  if (hostname.endsWith('.local') || hostname.endsWith('.internal') || hostname.endsWith('.lan')) return true;
  if (hostname === 'local' || hostname === 'internal') return true;
  if (isPrivateIpv4(hostname)) return true;
  if (hostname.includes(':')) {
    return hostname === '::1'
      || hostname.startsWith('fc')
      || hostname.startsWith('fd')
      || hostname.startsWith('fe80:')
      || hostname.startsWith('ff');
  }
  return false;
};

const hasUnsafeUrlCharacters = (value: string): boolean => Array.from(value).some(character => {
  const code = character.charCodeAt(0);
  return code < 32 || code === 127 || /\s/.test(character);
});

export const normalizeUrl = (value: unknown): string | null => {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!trimmed || hasUnsafeUrlCharacters(trimmed)) return null;
  try {
    const parsed = new URL(trimmed);
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null;
    if (parsed.username || parsed.password) return null;
    if (isPrivateOrLocalHost(parsed.hostname)) return null;
    parsed.hash = '';
    return parsed.toString();
  } catch {
    return null;
  }
};

export const isTrustedAttachmentHost = (value: string): boolean => {
  const hostname = normalizedHostname(value);
  return trustedAttachmentHosts.some(host => hostname === host || hostname.endsWith(`.${host}`));
};

export const isTrustedAttachmentUrl = (value: unknown): boolean => {
  const normalized = normalizeUrl(value);
  if (!normalized) return false;
  try {
    const parsed = new URL(normalized);
    return parsed.protocol === 'https:' && isTrustedAttachmentHost(parsed.hostname);
  } catch {
    return false;
  }
};

const decodeFilename = (value: string): string => {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
};

const filenameFromUrl = (url: string): string => {
  try {
    const parsed = new URL(url);
    const filename = parsed.pathname.split('/').filter(Boolean).pop();
    return filename ? decodeFilename(filename) : 'Attachment';
  } catch {
    return 'Attachment';
  }
};

const isGenericAttachmentName = (value: string): boolean => (
  !value || /^(attachment|attachments|file)$/i.test(value.trim())
);

const attachmentFromValue = (value: unknown): Attachment | null => {
  let name = '';
  let urlValue: unknown = value;

  if (isRecord(value)) {
    name = textValue(value.name ?? value.filename ?? value.title);
    urlValue = value.url ?? value.href ?? value.attachment_url ?? value.link;
  }

  const normalizedUrl = normalizeUrl(urlValue);
  if (!normalizedUrl) return null;

  if (isGenericAttachmentName(name)) name = filenameFromUrl(normalizedUrl);
  return { name: name || filenameFromUrl(normalizedUrl), url: normalizedUrl };
};

const parseAttachmentCollection = (value: unknown): Attachment[] => {
  const seen = new Set<string>();
  const attachments: Attachment[] = [];

  for (const item of collectionValues(value)) {
    const attachment = attachmentFromValue(item);
    if (!attachment) continue;
    const key = normalizeUrl(attachment.url);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    attachments.push(attachment);
  }

  return attachments;
};

export const parseAttachments = (value: unknown, legacyValue?: unknown): Attachment[] => {
  let currentValue = value;
  let fallbackValue = legacyValue;

  if (isRecord(value) && ('attachments' in value || 'attachment_url' in value) && legacyValue === undefined) {
    currentValue = value.attachments;
    fallbackValue = value.attachment_url;
  }

  const current = parseAttachmentCollection(currentValue);
  return current.length > 0 ? current : parseAttachmentCollection(fallbackValue);
};

export const getSafeAttachments = (value: unknown, legacyValue?: unknown): Attachment[] => (
  parseAttachments(value, legacyValue).filter(attachment => isTrustedAttachmentUrl(attachment.url))
);

export const filterSafeAttachments = getSafeAttachments;
export const safeAttachments = getSafeAttachments;
export const attachmentSourceLabel = (value: unknown): string | null => (
  isTrustedAttachmentUrl(value) ? 'MyClassboard document' : null
);

export const mapEntryType = (value: unknown): { type: EntryType; canonical: CanonicalEntryType } => {
  const key = textValue(value).replace(/[\s_-]/g, '').toLowerCase();
  const canonical = canonicalEntryTypes[key] ?? 'DiaryEntry';
  return { type: entryTypeNames[canonical], canonical };
};

export const isAnswerKeyEntry = (entry: Pick<Entry, 'type' | 'title' | 'label'>): boolean => {
  if (entry.type !== 'worksheet') return false;
  const source = `${entry.title} ${entry.label}`.toLowerCase();
  return /answer\s*key|answerkey|ans\s*key|anskey|\bak\b/.test(source);
};

const identityText = (value: unknown): string => textValue(value).replace(/\s+/g, ' ').toLowerCase();

export const canonicalEntryKey = (
  entry: Pick<Entry, 'entry_type' | 'date' | 'subject' | 'teacher' | 'summary'>,
): string => JSON.stringify([
  entry.entry_type,
  entry.date,
  identityText(entry.subject),
  identityText(entry.teacher),
  identityText(entry.summary),
]);

export const entryDedupeKey = (entry: Entry): string => {
  const sourceId = textValue(entry.source_id);
  if (sourceId) return `source:${entry.entry_type}:${sourceId}`;
  return `content:${canonicalEntryKey(entry)}`;
};

export const parseLocalDate = (value: unknown): Date | null => {
  if (value instanceof Date) return Number.isFinite(value.getTime()) ? new Date(value.getTime()) : null;
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(trimmed);
  if (match) {
    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    const parsed = new Date(year, month - 1, day, 0, 0, 0, 0);
    if (
      parsed.getFullYear() !== year
      || parsed.getMonth() !== month - 1
      || parsed.getDate() !== day
    ) return null;
    return parsed;
  }
  const parsed = new Date(trimmed);
  return Number.isFinite(parsed.getTime()) ? parsed : null;
};

export const localDateTimestamp = (value: unknown): number | null => {
  const parsed = parseLocalDate(value);
  return parsed ? parsed.getTime() : null;
};

export const formatLocalDate = (
  value: unknown,
  options: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' },
): string => {
  const text = textValue(value);
  const parsed = parseLocalDate(text);
  return parsed ? parsed.toLocaleDateString('en-US', options) : text;
};

const timestamp = (value: unknown): number | null => {
  const candidate = textValue(value);
  if (!candidate) return null;
  const parsed = Date.parse(candidate);
  return Number.isFinite(parsed) ? parsed : null;
};

const freshnessTimestamp = (entry: Pick<Entry, 'updated_at' | 'created_at' | 'date'>): number | null => (
  timestamp(entry.updated_at)
  ?? timestamp(entry.created_at)
  ?? localDateTimestamp(entry.date)
);

export const createdAtValue = (entry: Pick<Entry, 'created_at' | 'date'>): number | null => (
  timestamp(entry.created_at) ?? localDateTimestamp(entry.date)
);

const stableId = (value: EntryId): string => String(value);

const compareStable = (left: Entry, right: Entry): number => {
  const leftId = stableId(left.id);
  const rightId = stableId(right.id);
  if (leftId < rightId) return -1;
  if (leftId > rightId) return 1;
  const leftKey = canonicalEntryKey(left);
  const rightKey = canonicalEntryKey(right);
  if (leftKey < rightKey) return -1;
  if (leftKey > rightKey) return 1;
  return 0;
};

const compareFreshness = (left: Entry, right: Entry): number => {
  const leftUpdated = timestamp(left.updated_at);
  const rightUpdated = timestamp(right.updated_at);
  if (leftUpdated !== null && rightUpdated !== null && leftUpdated !== rightUpdated) {
    return leftUpdated - rightUpdated;
  }
  if (leftUpdated !== null && rightUpdated === null) return 1;
  if (leftUpdated === null && rightUpdated !== null) return -1;

  const leftCreated = timestamp(left.created_at);
  const rightCreated = timestamp(right.created_at);
  if (leftCreated !== null && rightCreated !== null && leftCreated !== rightCreated) {
    return leftCreated - rightCreated;
  }
  if (leftCreated !== null && rightCreated === null) return 1;
  if (leftCreated === null && rightCreated !== null) return -1;

  const leftDate = localDateTimestamp(left.date);
  const rightDate = localDateTimestamp(right.date);
  if (leftDate !== null && rightDate !== null && leftDate !== rightDate) {
    return leftDate - rightDate;
  }
  if (leftDate !== null && rightDate === null) return 1;
  if (leftDate === null && rightDate !== null) return -1;
  return compareStable(left, right);
};

export const isFreshEntry = (candidate: Entry, current: Entry): boolean => (
  compareFreshness(candidate, current) > 0
);

export const sortEntries = (entries: Entry[]): Entry[] => [...entries].sort((left, right) => {
  const leftDate = localDateTimestamp(left.date) ?? Number.NEGATIVE_INFINITY;
  const rightDate = localDateTimestamp(right.date) ?? Number.NEGATIVE_INFINITY;
  if (leftDate !== rightDate) return rightDate - leftDate;

  const leftUpdated = timestamp(left.updated_at) ?? timestamp(left.created_at) ?? Number.NEGATIVE_INFINITY;
  const rightUpdated = timestamp(right.updated_at) ?? timestamp(right.created_at) ?? Number.NEGATIVE_INFINITY;
  if (leftUpdated !== rightUpdated) return rightUpdated - leftUpdated;

  return compareStable(left, right);
});

const chooseText = (preferred: unknown, fallback: unknown): string => (
  textValue(preferred) || textValue(fallback)
);

const chooseContent = (preferred: Entry, fallback: Entry): string => {
  const preferredValue = chooseText(preferred.content, preferred.summary);
  const fallbackValue = chooseText(fallback.content, fallback.summary);
  if (!preferredValue) return fallbackValue;
  if (!fallbackValue) return preferredValue;
  if (preferredValue.includes(fallbackValue)) return preferredValue;
  if (fallbackValue.includes(preferredValue)) return fallbackValue;
  return preferredValue;
};

const mergeAttachmentLists = (preferred: Attachment[], fallback: Attachment[]): Attachment[] => {
  const merged: Attachment[] = [];
  const positions = new Map<string, number>();
  const attachments = [
    ...(Array.isArray(preferred) ? preferred : []),
    ...(Array.isArray(fallback) ? fallback : []),
  ];
  for (const attachment of attachments) {
    const key = normalizeUrl(attachment.url) ?? `${attachment.name}\u0000${attachment.url}`;
    const position = positions.get(key);
    if (position === undefined) {
      positions.set(key, merged.length);
      merged.push({ ...attachment });
    } else if (!merged[position].name && attachment.name) {
      merged[position] = { ...merged[position], name: attachment.name };
    }
  }
  return merged;
};

export const mergeEntryValues = (first: Entry, second: Entry): Entry => {
  const preferred = isFreshEntry(second, first) ? second : first;
  const fallback = preferred === first ? second : first;
  const subject = chooseText(preferred.subject || preferred.title, fallback.subject || fallback.title) || 'Untitled';
  const content = chooseContent(preferred, fallback);
  const updatedAt = chooseText(preferred.updated_at, fallback.updated_at) || undefined;
  const createdAt = chooseText(preferred.created_at, fallback.created_at) || undefined;
  const attachmentUrl = chooseText(preferred.attachment_url, fallback.attachment_url) || undefined;

  return {
    ...preferred,
    id: preferred.id,
    type: preferred.type,
    entry_type: preferred.entry_type,
    title: subject,
    subject,
    label: chooseText(preferred.label, fallback.label),
    content,
    summary: chooseText(preferred.summary, fallback.summary) || content,
    date: chooseText(preferred.date, fallback.date),
    teacher: chooseText(preferred.teacher, fallback.teacher) || undefined,
    attachments: mergeAttachmentLists(preferred.attachments, fallback.attachments),
    attachment_url: attachmentUrl,
    source_id: preferred.source_id ?? fallback.source_id,
    updated_at: updatedAt,
    created_at: createdAt,
  };
};

export const mergeEntries = mergeEntryValues;

export const dedupeEntries = (entries: Entry[]): Entry[] => {
  const byIdentity = new Map<string, Entry>();
  for (const entry of entries) {
    const sourceId = textValue(entry.source_id);
    const key = sourceId
      ? `source:${entry.entry_type}:${sourceId}`
      : `id:${entry.entry_type}:${stableId(entry.id)}`;
    byIdentity.set(key, mergeEntryValues(byIdentity.get(key) ?? entry, entry));
  }

  const byContent = new Map<string, Entry>();
  for (const entry of byIdentity.values()) {
    const key = entryDedupeKey(entry);
    byContent.set(key, mergeEntryValues(byContent.get(key) ?? entry, entry));
  }

  return sortEntries(Array.from(byContent.values()));
};

const announcementTeacherPlaceholder = /^(attachments?|attachment|file|files)$/i;

const teacherValue = (value: unknown, type: EntryType): string | undefined => {
  const teacher = textValue(value);
  if (!teacher) return undefined;
  if (type === 'announcement' && announcementTeacherPlaceholder.test(teacher)) return undefined;
  return teacher;
};

const attachmentUrlValue = (value: unknown): string | undefined => {
  if (typeof value === 'string') return value.trim() || undefined;
  if (Array.isArray(value) || isRecord(value)) {
    try {
      return JSON.stringify(value);
    } catch {
      return undefined;
    }
  }
  return undefined;
};

export const mapSupabaseRow = (row: SupabaseEntryRow): Entry => {
  const record = isRecord(row) ? row : {};
  const mappedType = mapEntryType(record.entry_type ?? record.type);
  const subject = textValue(record.subject ?? record.title) || 'Untitled';
  const summary = textValue(record.summary ?? record.description ?? record.content);
  const date = textValue(record.date ?? record.entry_date);
  const sourceId = optionalId(record.source_id ?? record.sourceId);
  const teacher = teacherValue(record.teacher ?? record.teacher_name, mappedType.type);
  const key = canonicalEntryKey({
    entry_type: mappedType.canonical,
    date,
    subject,
    teacher,
    summary,
  });
  const id = optionalId(record.id) ?? sourceId ?? `generated:${key}`;
  const label = textValue(record.label ?? record.entry_label);
  const updatedAt = textValue(record.updated_at) || undefined;
  const createdAt = textValue(record.created_at ?? record.createdAt) || undefined;
  const legacyUrl = attachmentUrlValue(record.attachment_url);

  return {
    id,
    type: mappedType.type,
    entry_type: mappedType.canonical,
    title: subject,
    subject,
    label,
    content: summary,
    summary,
    date,
    teacher,
    attachments: parseAttachments(record.attachments ?? record.attachment, record.attachment_url),
    attachment_url: legacyUrl,
    source_id: sourceId,
    updated_at: updatedAt,
    created_at: createdAt,
  };
};

export const mapEntryRow = mapSupabaseRow;

export const primaryKey = (row: unknown): EntryId | undefined => {
  if (!isRecord(row)) return undefined;
  return optionalId(row.id);
};

const sameId = (left: EntryId, right: EntryId): boolean => stableId(left) === stableId(right);

const sameSource = (left: EntryId, right: EntryId): boolean => stableId(left) === stableId(right);

const eventType = (change: RealtimeChange): string => (
  textValue(change.eventType ?? change.event ?? change.type).toUpperCase()
);

const hasRow = (value: unknown): value is SupabaseEntryRow => isRecord(value);

const sourceIdFromRow = (row: unknown): EntryId | undefined => {
  if (!isRecord(row)) return undefined;
  return optionalId(row.source_id ?? row.sourceId);
};

const typeFromRow = (row: unknown): CanonicalEntryType | undefined => {
  if (!isRecord(row)) return undefined;
  const value = row.entry_type ?? row.type;
  if (value === undefined || value === null || value === '') return undefined;
  return mapEntryType(value).canonical;
};

export interface RealtimeApplyResult {
  entries: Entry[];
  needsAuthoritativeRefetch: boolean;
}

const deleteEntries = (entries: Entry[], oldValue: unknown): RealtimeApplyResult => {
  if (!hasRow(oldValue)) return { entries, needsAuthoritativeRefetch: false };
  const oldId = primaryKey(oldValue);
  const oldSource = sourceIdFromRow(oldValue);
  const oldType = typeFromRow(oldValue);

  if (oldSource !== undefined) {
    const sourceMatches = entries.filter(entry => sameSource(entry.source_id ?? '', oldSource));
    if (oldType) {
      return {
        entries: entries.filter(entry => !(
          entry.entry_type === oldType && entry.source_id !== undefined && sameSource(entry.source_id, oldSource)
        )),
        needsAuthoritativeRefetch: false,
      };
    }
    const matchingTypes = new Set(sourceMatches.map(entry => entry.entry_type));
    if (matchingTypes.size === 1) {
      const onlyType = sourceMatches[0].entry_type;
      return {
        entries: entries.filter(entry => !(
          entry.entry_type === onlyType && entry.source_id !== undefined && sameSource(entry.source_id, oldSource)
        )),
        needsAuthoritativeRefetch: false,
      };
    }
    return {
      entries,
      needsAuthoritativeRefetch: sourceMatches.length > 1,
    };
  }

  const legacyMatches = oldId === undefined
    ? []
    : entries.filter(entry => sameId(entry.id, oldId) && entry.source_id === undefined);
  return {
    entries,
    needsAuthoritativeRefetch: legacyMatches.length > 0,
  };
};

export const reconcileRealtimeChanges = (
  entries: Entry[],
  changes: RealtimeChange[],
): RealtimeApplyResult => {
  let current = entries;
  let needsAuthoritativeRefetch = false;

  for (const change of changes) {
    const type = eventType(change);
    if (type === 'DELETE' || (type === 'UPDATE' && !hasRow(change.new))) {
      const result = deleteEntries(current, change.old);
      current = result.entries;
      needsAuthoritativeRefetch ||= result.needsAuthoritativeRefetch;
      continue;
    }

    if (!hasRow(change.new)) continue;
    const nextEntry = mapSupabaseRow(change.new);
    const oldType = typeFromRow(change.old);
    const oldSource = sourceIdFromRow(change.old);
    const oldId = primaryKey(change.old);
    const matchesOld = (entry: Entry): boolean => {
      if (oldSource !== undefined && oldType) {
        return entry.entry_type === oldType
          && entry.source_id !== undefined
          && sameSource(entry.source_id, oldSource);
      }
      if (oldId !== undefined && oldSource !== undefined) {
        return sameId(entry.id, oldId)
          && entry.source_id !== undefined
          && sameSource(entry.source_id, oldSource);
      }
      if (oldId !== undefined) return sameId(entry.id, oldId) && entry.source_id === undefined;
      return false;
    };
    const oldMatches = current.filter(matchesOld);
    const matchingTypes = new Set(oldMatches.map(entry => entry.entry_type));
    const nextMatchesOld = (() => {
      if (oldSource !== undefined && oldType) {
        return nextEntry.entry_type === oldType
          && nextEntry.source_id !== undefined
          && sameSource(nextEntry.source_id, oldSource);
      }
      if (oldId !== undefined && oldSource !== undefined) {
        return (nextEntry.source_id !== undefined && sameSource(nextEntry.source_id, oldSource))
          || sameId(nextEntry.id, oldId);
      }
      if (oldId !== undefined) return sameId(nextEntry.id, oldId);
      return false;
    })();

    if (type === 'UPDATE' && oldMatches.length > 0 && nextMatchesOld && matchingTypes.size <= 1) {
      const replacement = oldMatches.reduce(
        (merged, _oldEntry) => mergeEntryValues(merged, nextEntry),
        oldMatches[0],
      );
      current = dedupeEntries([
        ...current.filter(entry => !oldMatches.includes(entry)),
        replacement,
      ]);
    } else {
      current = dedupeEntries([...current, nextEntry]);
      if (type === 'UPDATE' && oldMatches.length > 0) {
        needsAuthoritativeRefetch = true;
      }
    }
  }

  return { entries: current, needsAuthoritativeRefetch };
};

export const applyRealtimeChangeDetailed = (
  entries: Entry[],
  change: RealtimeChange,
): RealtimeApplyResult => reconcileRealtimeChanges(entries, [change]);

export const applyRealtimeChange = (entries: Entry[], change: RealtimeChange): Entry[] => (
  applyRealtimeChangeDetailed(entries, change).entries
);

export const applyRealtimeEvent = applyRealtimeChange;

export const realtimeReducer = (
  entries: Entry[],
  change: RealtimeChange,
): Entry[] => applyRealtimeChange(entries, change);

export const entryReadKey = (entry: Pick<Entry, 'entry_type' | 'id' | 'source_id'>): string => {
  const source = textValue(entry.source_id);
  return source
    ? `source:${entry.entry_type}:${source}`
    : `legacy:${entry.entry_type}:${stableId(entry.id)}`;
};

const OLD_ENTRY_AGE_MS = 2 * 24 * 60 * 60 * 1000;

export const firstVisitReadKeys = (entries: Entry[]): Set<string> => {
  const timestamps = entries
    .map(entry => localDateTimestamp(entry.date))
    .filter((value): value is number => value !== null);
  if (timestamps.length === 0) return new Set(entries.map(entryReadKey));
  const cutoff = Math.max(...timestamps) - OLD_ENTRY_AGE_MS;
  return new Set(entries
    .filter(entry => {
      const value = localDateTimestamp(entry.date);
      return value === null || value < cutoff;
    })
    .map(entryReadKey));
};

export const firstVisitReadIds = (entries: Entry[]): Set<EntryId> => {
  const readKeys = firstVisitReadKeys(entries);
  return new Set(entries
    .filter(entry => readKeys.has(entryReadKey(entry)))
    .map(entry => entry.source_id ?? entry.id));
};

export const hasReadMarker = (readKeys: ReadonlySet<string>, entry: Entry): boolean => {
  if (readKeys.has(entryReadKey(entry))) return true;
  if (!textValue(entry.source_id)) {
    return readKeys.has(`legacy:${entry.entry_type}:${stableId(entry.id)}`)
      || readKeys.has(stableId(entry.id));
  }
  return false;
};

export { freshnessTimestamp };
