export type EntryType = 'diary' | 'worksheet' | 'announcement';

export interface Entry {
  id: string | number;
  type: EntryType;
  title: string;
  content: string;
  date: string;
  teacher?: string;
  attachment_url?: string;
}
