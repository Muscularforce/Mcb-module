export type EntryId = string | number;

export type EntryType = 'diary' | 'worksheet' | 'announcement';

export type CanonicalEntryType = 'DiaryEntry' | 'Worksheet' | 'Announcement';

export interface Attachment {
  name: string;
  url: string;
}

export interface Entry {
  id: EntryId;
  type: EntryType;
  entry_type: CanonicalEntryType;
  title: string;
  subject: string;
  label: string;
  content: string;
  summary: string;
  date: string;
  teacher?: string;
  attachments: Attachment[];
  attachment_url?: string;
  source_id?: EntryId;
  updated_at?: string;
  created_at?: string;
}

export type SupabaseEntryRow = Record<string, unknown>;

export interface RealtimeChange {
  eventType?: string;
  event?: string;
  type?: string;
  new?: unknown;
  old?: unknown;
}
