import { Entry } from './types';
import { supabase } from './lib/supabase';

export const fetchEntries = async (): Promise<Entry[]> => {
  try {
    // Fetch directly from Supabase
    const { data, error } = await supabase
      .from('entries')
      .select('*')
      .order('date', { ascending: false });

    if (error) {
      throw error;
    }

    if (!data) return [];

    return data.map((item: any) => {
      let mappedType: 'diary' | 'worksheet' | 'announcement' = 'diary';
      if (item.entry_type === 'Worksheet') mappedType = 'worksheet';
      else if (item.entry_type === 'Announcement') mappedType = 'announcement';
      else if (item.entry_type === 'DiaryEntry') mappedType = 'diary';

      return {
        id: item.id,
        type: mappedType,
        title: item.subject || 'Untitled',
        content: item.summary || '',
        date: item.date || '',
        teacher: item.teacher || '',
        attachment_url: item.attachment_url || undefined
      };
    });
  } catch (error) {
    console.error('Failed to fetch from Supabase. Returning empty list.', error);
    return [];
  }
};
