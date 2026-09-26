import type { Entry, SupabaseEntryRow } from './types';
import { supabase } from './lib/supabase';
import { collectAllPages, DEFAULT_PAGE_SIZE } from './lib/pagination.ts';
import { dedupeEntries, mapSupabaseRow } from './lib/entries.ts';

export {
  applyRealtimeChange,
  applyRealtimeChangeDetailed,
  applyRealtimeEvent,
  attachmentSourceLabel,
  canonicalEntryKey,
  createdAtValue,
  dedupeEntries,
  entryDedupeKey,
  entryReadKey,
  filterSafeAttachments,
  firstVisitReadIds,
  freshnessTimestamp,
  firstVisitReadKeys,
  formatLocalDate,
  getSafeAttachments,
  hasReadMarker,
  isFreshEntry,
  isTrustedAttachmentHost,
  isTrustedAttachmentUrl,
  localDateTimestamp,
  mapEntryRow,
  mapEntryType,
  mapSupabaseRow,
  mergeEntries,
  mergeEntryValues,
  normalizeUrl,
  parseAttachments,
  parseLocalDate,
  primaryKey,
  realtimeReducer,
  reconcileRealtimeChanges,
  safeAttachments,
  sortEntries,
} from './lib/entries.ts';
export {
  collectAllPages,
  DEFAULT_PAGE_SIZE,
  fetchAllPages,
  pageRange,
  paginateRows,
} from './lib/pagination.ts';

export const fetchEntries = async (): Promise<Entry[]> => {
  const rows = await collectAllPages<SupabaseEntryRow>(async (from, to) => {
    const result = await supabase
      .from('entries')
      .select('*')
      .order('date', { ascending: false })
      .order('id', { ascending: false })
      .range(from, to);

    return {
      data: result.data as SupabaseEntryRow[] | null,
      error: result.error,
    };
  }, DEFAULT_PAGE_SIZE);

  return dedupeEntries(rows.map(row => mapSupabaseRow(row)));
};
