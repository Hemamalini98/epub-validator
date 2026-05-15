import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Calendar, FileCode2, ChevronRight, BookOpen, Trash2 } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn, formatDate, titleCase } from '@/lib/utils';
import { useBookStore } from '@/hooks/useBookStore';
import type { Book } from '@/types';

interface BookCardProps {
  book: Book;
  index?: number;
}

const COVER_COLORS = [
  '#6366f1', '#10b981', '#f59e0b', '#3b82f6',
  '#ec4899', '#14b8a6', '#f97316', '#8b5cf6',
];

function getCoverColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
  return COVER_COLORS[Math.abs(hash) % COVER_COLORS.length];
}

export const cardVariants = {
  hidden: { opacity: 0, y: 20 },
  show:   { opacity: 1, y: 0, transition: { duration: 0.3, ease: 'easeOut' } },
};

export function BookCard({ book, index = 0 }: BookCardProps) {
  const navigate = useNavigate();
  const { deleteBook } = useBookStore();
  const color = getCoverColor(book.folder_name);
  const initial = book.folder_name.charAt(0).toUpperCase();

  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);

  async function handleDelete() {
    setDeleting(true);
    try {
      await deleteBook(book.folder_name);
    } finally {
      setDeleting(false);
      setConfirming(false);
    }
  }

  return (
    <motion.div
      variants={cardVariants}
      custom={index}
      whileHover={{ y: -3, transition: { duration: 0.15 } }}
    >
      <Card className="overflow-hidden hover:shadow-md transition-shadow duration-200">
        {/* Cover strip */}
        <div
          className="h-[72px] flex items-center px-5 gap-3"
          style={{ background: `linear-gradient(135deg, ${color}22 0%, ${color}10 100%)` }}
        >
          <div
            className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 text-white font-bold text-lg shadow-sm"
            style={{ backgroundColor: color }}
          >
            {initial}
          </div>
          <div className="flex-1 min-w-0">
            <p
              className="text-sm font-semibold text-foreground truncate leading-none"
              title={book.folder_name}
            >
              {titleCase(book.folder_name)}
            </p>
            <p className="text-xs text-muted-foreground mt-0.5 font-mono truncate">
              {book.folder_name}
            </p>
          </div>
        </div>

        <CardContent className="pt-4">
          {/* Meta row */}
          <div className="flex items-center gap-3 mb-4">
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Calendar className="w-3.5 h-3.5" />
              {formatDate(book.uploaded_at)}
            </span>
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <FileCode2 className="w-3.5 h-3.5" />
              {book.total_files > 0 ? `${book.total_files} files` : 'Loading…'}
            </span>
          </div>

          {/* Status + action row */}
          {confirming ? (
            <div className="flex items-center gap-2">
              <p className="text-xs text-muted-foreground flex-1">Delete this book?</p>
              <Button
                size="sm"
                variant="destructive"
                className="h-7 px-2 text-xs"
                disabled={deleting}
                onClick={handleDelete}
              >
                {deleting ? 'Deleting…' : 'Delete'}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="h-7 px-2 text-xs"
                disabled={deleting}
                onClick={() => setConfirming(false)}
              >
                Cancel
              </Button>
            </div>
          ) : (
            <div className="flex items-center justify-between">
              <Badge variant="success" className="gap-1.5">
                <span className={cn('w-1.5 h-1.5 rounded-full bg-emerald-500')} />
                Extracted
              </Badge>

              <div className="flex items-center gap-1">
                <Button
                  size="sm"
                  variant="ghost"
                  className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                  onClick={() => setConfirming(true)}
                  aria-label={`Delete ${book.folder_name}`}
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </Button>

                <Button
                  size="sm"
                  variant="ghost"
                  className="text-primary hover:text-primary hover:bg-primary/10 gap-1 -mr-1"
                  onClick={() => navigate(`/files/${book.folder_name}`)}
                  aria-label={`Open ${book.folder_name}`}
                >
                  <BookOpen className="w-3.5 h-3.5" />
                  Open
                  <ChevronRight className="w-3 h-3 opacity-60" />
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </motion.div>
  );
}
