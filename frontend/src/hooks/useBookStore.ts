import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getBooks } from '@/lib/api';
import type { Book } from '@/types';

export function useBookStore() {
  const queryClient = useQueryClient();

  const { data: books = [] } = useQuery({
    queryKey: ['books'],
    queryFn: getBooks,
  });

  // Called after upload completes — backend already saved the record,
  // so just invalidate to trigger a fresh fetch.
  const upsertBook = (_book: Book) => {
    queryClient.invalidateQueries({ queryKey: ['books'] });
  };

  return { books, upsertBook };
}
