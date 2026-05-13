import { useState, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  CloudUpload,
  FileArchive,
  CheckCircle2,
  XCircle,
  ArrowLeft,
  Loader2,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { cn, formatFileSize } from '@/lib/utils';
import { uploadFile, getFiles, resolveFolderName } from '@/lib/api';
import { useBookStore } from '@/hooks/useBookStore';
import { useToast } from '@/components/Toaster';
import type { UploadStage } from '@/types';

const ACCEPTED = ['.epub', '.zip'];

function isValidFile(f: File) {
  const ext = '.' + (f.name.split('.').pop() ?? '').toLowerCase();
  return ACCEPTED.includes(ext);
}

interface StepProps {
  label: string;
  done: boolean;
  active: boolean;
}

function Step({ label, done, active }: StepProps) {
  return (
    <div className="flex items-center gap-3">
      <div
        className={cn(
          'w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 transition-colors',
          done ? 'bg-emerald-500' : active ? 'bg-primary' : 'bg-muted',
        )}
      >
        {done ? (
          <CheckCircle2 className="w-4 h-4 text-white" />
        ) : active ? (
          <Loader2 className="w-3.5 h-3.5 text-white animate-spin" />
        ) : (
          <span className="w-2 h-2 rounded-full bg-muted-foreground/30" />
        )}
      </div>
      <span
        className={cn(
          'text-sm font-medium transition-colors',
          done ? 'text-emerald-600' : active ? 'text-foreground' : 'text-muted-foreground',
        )}
      >
        {label}
      </span>
    </div>
  );
}

export default function UploadPage() {
  const navigate = useNavigate();
  const { upsertBook } = useBookStore();
  const { showError } = useToast();

  const [stage, setStage] = useState<UploadStage>('idle');
  const [uploadPct, setUploadPct] = useState(0);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);

  const processFile = useCallback(
    async (file: File) => {
      if (!isValidFile(file)) {
        setErrorMsg(`"${file.name}" is not supported. Please use .epub or .zip files.`);
        setStage('failed');
        return;
      }
      setSelectedFile(file);
      setErrorMsg(null);
      setUploadPct(0);
      setStage('uploading');

      try {
        const response = await uploadFile(file, (pct) => {
          setUploadPct(pct);
          if (pct >= 100) setStage('extracting');
        });

        if (!response.status) {
          throw new Error(response.message || 'Upload failed');
        }

        const folderName = resolveFolderName(response, file);

        // Fetch file count in the background, then persist the book
        let totalFiles = 0;
        try {
          const filesData = await getFiles(folderName);
          if (filesData.status && filesData.total_files != null) {
            totalFiles = filesData.total_files;
          }
        } catch {
          // non-critical, continue
        }

        upsertBook({
          folder_name: folderName,
          epub_path: response.epub_path ?? response.epub_extract_path ?? '',
          uploaded_at: new Date().toISOString().split('T')[0],
          total_files: totalFiles,
        });

        setStage('completed');
        setTimeout(() => navigate(`/files/${folderName}`), 1400);
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Upload failed. Please try again.';
        setErrorMsg(msg);
        setStage('failed');
        showError(msg);
      }
    },
    [navigate, upsertBook],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setStage('idle');
      const f = e.dataTransfer.files[0];
      if (f) processFile(f);
    },
    [processFile],
  );

  const onDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    if (stage === 'idle') setStage('dragging');
  };
  const onDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    if (stage === 'dragging') setStage('idle');
  };
  const onInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (f) processFile(f);
    e.target.value = '';
  };

  const isIdle = stage === 'idle' || stage === 'dragging';
  const dragging = stage === 'dragging';
  const failed = stage === 'failed';
  const uploading = stage === 'uploading';
  const extracting = stage === 'extracting';
  const completed = stage === 'completed';
  const busy = uploading || extracting || completed;

  return (
    <motion.div
      className="flex flex-col min-h-full"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.22 }}
    >
      {/* Header */}
      <header className="sticky top-0 z-10 bg-background/80 backdrop-blur border-b border-border px-8 py-4 flex items-center gap-4">
        <Button variant="ghost" size="icon" onClick={() => navigate('/')} className="shrink-0">
          <ArrowLeft className="w-4 h-4" />
        </Button>
        <div>
          <h1 className="text-xl font-bold text-foreground tracking-tight">New Upload Job</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Upload an EPUB or ZIP file to start validation.
          </p>
        </div>
      </header>

      {/* Content */}
      <div className="flex-1 flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-lg space-y-4">
          <AnimatePresence mode="wait">
            {isIdle || failed ? (
              /* ── Drop zone ─────────────────────────────────── */
              <motion.div
                key="dropzone"
                initial={{ opacity: 0, scale: 0.97 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.97 }}
                transition={{ duration: 0.2 }}
                onDrop={onDrop}
                onDragOver={onDragOver}
                onDragLeave={onDragLeave}
                onClick={() => { if (!failed) inputRef.current?.click(); }}
                whileHover={{ boxShadow: '0 0 0 4px rgba(99,102,241,0.15)' }}
                className={cn(
                  'relative rounded-2xl border-2 border-dashed cursor-pointer transition-colors duration-200',
                  'flex flex-col items-center justify-center gap-5 py-16 px-8 text-center',
                  dragging
                    ? 'border-primary bg-primary/5'
                    : failed
                    ? 'border-destructive/40 bg-destructive/5'
                    : 'border-border bg-card hover:border-primary/50 hover:bg-primary/[0.02]',
                )}
              >
                <input
                  ref={inputRef}
                  type="file"
                  accept={ACCEPTED.join(',')}
                  className="sr-only"
                  onChange={onInputChange}
                />

                {/* Icon */}
                <motion.div
                  className={cn(
                    'w-16 h-16 rounded-2xl flex items-center justify-center',
                    dragging ? 'bg-primary/15' : failed ? 'bg-destructive/10' : 'bg-muted',
                  )}
                  animate={dragging ? { y: -6, rotate: -4 } : { y: 0, rotate: 0 }}
                  transition={{ type: 'spring', stiffness: 300, damping: 20 }}
                >
                  {failed ? (
                    <XCircle className="w-8 h-8 text-destructive" />
                  ) : (
                    <CloudUpload
                      className={cn('w-8 h-8', dragging ? 'text-primary' : 'text-muted-foreground')}
                    />
                  )}
                </motion.div>

                {/* Text */}
                <div>
                  <p className="text-base font-semibold text-foreground mb-1">
                    {failed
                      ? 'Upload failed'
                      : dragging
                      ? 'Release to upload'
                      : 'Drag & drop your file here'}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    {failed
                      ? errorMsg ?? 'Something went wrong.'
                      : 'or click to browse — accepts .epub and .zip'}
                  </p>
                </div>

                {/* CTA */}
                {failed ? (
                  <Button
                    variant="outline"
                    onClick={(e) => {
                      e.stopPropagation();
                      setStage('idle');
                      setErrorMsg(null);
                    }}
                  >
                    Try again
                  </Button>
                ) : (
                  <Button onClick={(e) => { e.stopPropagation(); inputRef.current?.click(); }}>
                    <FileArchive className="w-4 h-4" />
                    Select file
                  </Button>
                )}

                <p className="text-xs text-muted-foreground/70">Supports .epub · .zip</p>
              </motion.div>
            ) : (
              /* ── Progress card ─────────────────────────────── */
              <motion.div
                key="progress"
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -12 }}
                transition={{ duration: 0.25 }}
                className="bg-card rounded-2xl border border-border shadow-sm overflow-hidden"
              >
                {/* File info */}
                <div className="flex items-center gap-4 px-6 py-5 border-b border-border">
                  <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center flex-shrink-0">
                    <FileArchive className="w-5 h-5 text-primary" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-semibold text-foreground truncate">
                      {selectedFile?.name ?? ''}
                    </p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {selectedFile ? formatFileSize(selectedFile.size) : ''}
                    </p>
                  </div>
                  {completed && <CheckCircle2 className="w-5 h-5 text-emerald-500 flex-shrink-0" />}
                </div>

                {/* Progress bar */}
                {(uploading || extracting) && (
                  <div className="px-6 py-4">
                    <div className="flex justify-between items-center mb-2">
                      <span className="text-xs text-muted-foreground">
                        {uploading ? 'Uploading…' : 'Processing…'}
                      </span>
                      {uploading && (
                        <span className="text-xs font-bold text-primary tabular-nums">
                          {uploadPct}%
                        </span>
                      )}
                    </div>
                    <Progress
                      value={extracting ? 100 : uploadPct}
                      barClassName={cn(
                        extracting &&
                          'animate-pulse bg-gradient-to-r from-primary to-violet-500',
                      )}
                    />
                  </div>
                )}

                {/* Steps */}
                <div className="px-6 py-5 space-y-3">
                  <Step
                    label="Uploading file"
                    done={extracting || completed}
                    active={uploading}
                  />
                  <Step
                    label="Extracting EPUB"
                    done={completed}
                    active={extracting}
                  />
                  <Step
                    label={completed ? 'Complete — redirecting…' : 'Validation ready'}
                    done={false}
                    active={completed}
                  />
                </div>

                {busy && !completed && (
                  <div className="px-6 pb-5">
                    <div className="h-px bg-border" />
                  </div>
                )}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </motion.div>
  );
}
