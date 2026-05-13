import {
  createContext,
  useCallback,
  useContext,
  useRef,
  useState,
} from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { XCircle, X } from 'lucide-react';

// ─── Types ────────────────────────────────────────────────────────────────────

interface Toast {
  id: number;
  message: string;
}

interface ToastCtx {
  showError: (message: string) => void;
}

// ─── Context ─────────────────────────────────────────────────────────────────

const ToastContext = createContext<ToastCtx | null>(null);

const AUTO_HIDE_MS = 4500;

// ─── Provider ────────────────────────────────────────────────────────────────

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const showError = useCallback(
    (message: string) => {
      const id = ++nextId.current;
      setToasts((prev) => [...prev, { id, message }]);
      setTimeout(() => dismiss(id), AUTO_HIDE_MS);
    },
    [dismiss],
  );

  return (
    <ToastContext.Provider value={{ showError }}>
      {children}
      {createPortal(
        <div className="fixed top-4 right-4 z-[9999] flex flex-col gap-2 pointer-events-none">
          <AnimatePresence initial={false}>
            {toasts.map((t) => (
              <motion.div
                key={t.id}
                initial={{ opacity: 0, x: 60, scale: 0.95 }}
                animate={{ opacity: 1, x: 0,  scale: 1    }}
                exit={{   opacity: 0, x: 60,  scale: 0.95 }}
                transition={{ duration: 0.22, ease: 'easeOut' }}
                className="pointer-events-auto flex items-start gap-3 w-80 rounded-xl border border-red-200 bg-white px-4 py-3 shadow-lg dark:bg-zinc-900 dark:border-red-900/40"
              >
                <XCircle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
                <p className="flex-1 text-sm text-foreground leading-snug break-words">
                  {t.message}
                </p>
                <button
                  onClick={() => dismiss(t.id)}
                  className="flex-shrink-0 text-muted-foreground hover:text-foreground transition-colors mt-0.5"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>,
        document.body,
      )}
    </ToastContext.Provider>
  );
}

// ─── Hook ─────────────────────────────────────────────────────────────────────

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>');
  return ctx;
}
