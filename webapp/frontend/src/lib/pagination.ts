export const DEFAULT_PAGE_SIZE = 1000;

export interface PageResult<T> {
  data: T[] | null;
  error?: unknown;
}

export type PageFetcher<T> = (from: number, to: number) => Promise<PageResult<T>>;

export interface PageRange {
  from: number;
  to: number;
}

export const pageRange = (pageIndex: number, pageSize = DEFAULT_PAGE_SIZE): PageRange => {
  if (!Number.isInteger(pageIndex) || pageIndex < 0) {
    throw new Error('Page index must be a non-negative integer.');
  }
  if (!Number.isInteger(pageSize) || pageSize <= 0) {
    throw new Error('Page size must be a positive integer.');
  }
  const from = pageIndex * pageSize;
  return { from, to: from + pageSize - 1 };
};

export const collectAllPages = async <T>(
  fetchPage: PageFetcher<T>,
  pageSize = DEFAULT_PAGE_SIZE,
): Promise<T[]> => {
  if (!Number.isInteger(pageSize) || pageSize <= 0) {
    throw new Error('Page size must be a positive integer.');
  }

  const rows: T[] = [];
  let pageIndex = 0;

  let hasMore = true;
  while (hasMore) {
    const { from, to } = pageRange(pageIndex, pageSize);
    const result = await fetchPage(from, to);
    if (result.error) throw result.error;
    if (!Array.isArray(result.data)) {
      throw new Error(`Supabase page ${pageIndex} returned no row array.`);
    }
    if (result.data.length > pageSize) {
      throw new Error(`Supabase page ${pageIndex} returned more than ${pageSize} rows.`);
    }

    rows.push(...result.data);
    hasMore = result.data.length === pageSize;
    if (hasMore) pageIndex += 1;
  }

  return rows;
};

export const fetchAllPages = collectAllPages;
export const paginateRows = collectAllPages;
