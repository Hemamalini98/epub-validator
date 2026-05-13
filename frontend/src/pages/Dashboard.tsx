import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Plus, BookOpen } from 'lucide-react';
import { BookCard, cardVariants } from '@/components/BookCard';
import { EmptyState } from '@/components/EmptyState';
import { Button } from '@/components/ui/button';
import { useBookStore } from '@/hooks/useBookStore';

const containerVariants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.07, delayChildren: 0.1 } },
};

export default function Dashboard() {
  const navigate = useNavigate();
  const { books } = useBookStore();

  return (
    <motion.div
      className="flex flex-col min-h-full"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.22 }}
    >
      {/* Sticky header */}
      <header className="sticky top-0 z-10 bg-background/80 backdrop-blur border-b border-border px-8 py-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-foreground tracking-tight">Books & Jobs</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Open a job to inspect its chapters and run validation.
          </p>
        </div>

        <Button onClick={() => navigate('/upload')} className="gap-2 shadow-sm">
          <Plus className="w-4 h-4" />
          Add Job
        </Button>
      </header>

      {/* Content */}
      <div className="flex-1 px-8 py-8">
        {books.length === 0 ? (
          <EmptyState
            icon={BookOpen}
            title="No books uploaded yet"
            description="Upload an EPUB or ZIP file to create your first validation job and inspect its XHTML files."
            action={{ label: '+ Add Job', onClick: () => navigate('/upload') }}
          />
        ) : (
          <motion.div
            className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4"
            variants={containerVariants}
            initial="hidden"
            animate="show"
          >
            {books.map((book, i) => (
              <motion.div key={book.folder_name} variants={cardVariants} custom={i}>
                <BookCard book={book} index={i} />
              </motion.div>
            ))}
          </motion.div>
        )}
      </div>
    </motion.div>
  );
}
