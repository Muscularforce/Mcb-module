import { Entry } from './types';
import { supabase } from './lib/supabase';

const mockData: Entry[] = [
  {
    id: 1, type: 'diary', title: 'Mathematics',
    teacher: 'John Doe',
    content: 'Homework: Complete exercises 1-10 on page 42 of the NCERT textbook. Show all working steps.',
    date: '2026-06-10',
    attachment_url: 'https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf'
  },
  {
    id: 2, type: 'diary', title: 'English Literature',
    teacher: 'Ms. Charlotte',
    content: 'Read Chapter 5 of "To Kill a Mockingbird". Write a 200-word character analysis of Scout Finch.',
    date: '2026-06-10'
  },
  {
    id: 3, type: 'diary', title: 'History',
    teacher: 'Mr. Gupta',
    content: 'Revise the French Revolution timeline. There will be a surprise quiz next class.',
    date: '2026-06-10'
  },
  {
    id: 4, type: 'worksheet', title: 'Physics — Newton\'s Laws',
    teacher: 'Dr. Feynman',
    content: 'Solve all 15 numerical problems on Newton\'s Laws of Motion. Use proper free body diagrams for each question. Submit by Friday.',
    date: '2026-06-11',
    attachment_url: 'https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf'
  },
  {
    id: 5, type: 'worksheet', title: 'Chemistry — Balancing Equations',
    teacher: 'Alan Turing',
    content: 'Balance 20 chemical equations provided in the worksheet. Extra credit for completing the combustion reactions section.',
    date: '2026-06-11',
    attachment_url: 'https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf'
  },
  {
    id: 6, type: 'worksheet', title: 'Biology — Cell Structure',
    teacher: 'Rosalind Franklin',
    content: 'Label the cell organelle diagram. Write one function for each organelle. Compare plant and animal cells in a table.',
    date: '2026-06-11',
    attachment_url: 'https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf'
  },
  {
    id: 7, type: 'announcement', title: 'School Holiday Notice',
    teacher: 'Principal Smith',
    content: 'School will remain closed on Friday, June 13th due to a teacher training workshop. Classes resume on Monday.',
    date: '2026-06-09',
    attachment_url: 'https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf'
  },
  {
    id: 8, type: 'announcement', title: 'Annual Sports Day',
    teacher: 'Coach Williams',
    content: 'Annual Sports Day is on June 20th. All students must register for at least one event by June 15th. Track suits are mandatory.',
    date: '2026-06-10'
  },
  {
    id: 9, type: 'announcement', title: 'Science Exhibition',
    teacher: 'Dr. Feynman',
    content: 'The Inter-School Science Exhibition will be held on June 25th. Teams of 3 can register with their class teacher. Exciting prizes await!',
    date: '2026-06-11'
  },
];

export const fetchEntries = async (): Promise<Entry[]> => {
  try {
    // Attempt to fetch from Supabase
    const { data, error } = await supabase
      .from('entries')
      .select('*')
      .order('date', { ascending: false });

    if (error) {
      throw error;
    }

    if (!data || data.length === 0) {
      // If table is empty or missing, fallback to mock data
      return mockData;
    }

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
    console.warn('Failed to fetch from Supabase. Falling back to local mock data.', error);
    return new Promise((resolve) => setTimeout(() => resolve(mockData), 500));
  }
};
