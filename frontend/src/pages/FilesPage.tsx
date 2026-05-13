import { useState, useMemo, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ArrowLeft,
  FileCode2,
  Braces,
  Play,
  Loader2,
  BookOpen,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Clock,
  Download,
} from 'lucide-react';
import { XHTMLCard, xhtmlCardVariants } from '@/components/XHTMLCard';
import { ValidationDetailModal } from '@/components/ValidationDetailModal';
import type { Tab as ModalTab } from '@/components/ValidationDetailModal';
import { EmptyState } from '@/components/EmptyState';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { getFiles, validateFolder, validateFile, exportEpub } from '@/lib/api';
import { useBookStore } from '@/hooks/useBookStore';
import { cn, formatDate, titleCase } from '@/lib/utils';
import type { ValidationApiResponse, XHTMLFile, XHTMLFileStatus } from '@/types';

// ─── Stagger animation ────────────────────────────────────────────────────────

const containerVariants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.04, delayChildren: 0.05 } },
};

// ─── Stat card ────────────────────────────────────────────────────────────────

interface StatCardProps {
  label: string;
  value: number;
  total: number;
  icon: React.ComponentType<{ className?: string }>;
  barColor: string;
  valueColor: string;
  isActive?: boolean;
  onClick?: () => void;
}

function StatCard({ label, value, total, icon: Icon, barColor, valueColor, isActive, onClick }: StatCardProps) {
  const pct = total > 0 ? Math.round((value / total) * 100) : 0;
  return (
    <Card
      onClick={onClick}
      className={cn(
        onClick && 'cursor-pointer transition-all duration-150',
        onClick && !isActive && 'hover:shadow-md hover:-translate-y-0.5',
        isActive && 'ring-2 ring-primary shadow-md -translate-y-0.5',
      )}
    >
      <CardContent className="pt-5 pb-4">
        <div className="flex items-center justify-between mb-3">
          <p className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
            {label}
          </p>
          <Icon className={cn('w-4 h-4', valueColor)} />
        </div>
        <p className={cn('text-4xl font-bold tabular-nums', valueColor)}>{value}</p>
        <div className="mt-4 h-1.5 w-full rounded-full bg-muted overflow-hidden">
          <motion.div
            className={cn('h-full rounded-full', barColor)}
            initial={{ width: 0 }}
            animate={{ width: `${pct}%` }}
            transition={{ duration: 0.6, ease: 'easeOut', delay: 0.1 }}
          />
        </div>
      </CardContent>
    </Card>
  );
}

// ─── Skeleton grid ────────────────────────────────────────────────────────────

function SkeletonGrid() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      {Array.from({ length: 8 }).map((_, i) => (
        <Skeleton key={i} className="h-[196px] rounded-xl" />
      ))}
    </div>
  );
}

// ─── Page ────────────────────────────────────────────────────────────────────

export default function FilesPage() {
  const { folderName = '' } = useParams<{ folderName: string }>();
  const navigate = useNavigate();
  const { books } = useBookStore();

  const book = useMemo(
    () => books.find((b) => b.folder_name === folderName),
    [books, folderName],
  );

  // ── Files from API ──────────────────────────────────────────────────────────
  const { data: filesData, isLoading, isError } = useQuery({
    queryKey: ['files', folderName],
    queryFn: () => getFiles(folderName),
    enabled: !!folderName,
    staleTime: 60_000,
    retry: 1,
  });

  const xhtmlFiles = useMemo(
    () => (filesData?.files ?? []).filter((f) => f.file_name.toLowerCase().endsWith('.xhtml')),
    [filesData],
  );

  const cssFiles = useMemo(
    () => (filesData?.files ?? []).filter((f) => f.file_name.toLowerCase().endsWith('.css')),
    [filesData],
  );

  // ── Validation state ────────────────────────────────────────────────────────
  const [validationData, setValidationData] = useState<ValidationApiResponse | null>(null);
  const [isValidating, setIsValidating] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);

  // Elapsed-time counter while validation runs
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (isValidating) {
      setElapsed(0);
      timerRef.current = setInterval(() => setElapsed((s) => s + 1), 1000);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [isValidating]);

  const fmtElapsed = (s: number) =>
    s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;

  const mergeValidation = (
    existing: ValidationApiResponse | null,
    incoming: ValidationApiResponse,
  ): ValidationApiResponse => {
    if (!existing) return incoming;
    const incomingNames = new Set(incoming.files.map((e) => e.file_details.file_name));
    return {
      ...existing,
      files: [...existing.files.filter((e) => !incomingNames.has(e.file_details.file_name)), ...incoming.files],
    };
  };

  const handleValidateAll = async () => {
    setIsValidating(true);
    setValidationError(null);
    try {
      const result = await validateFolder(folderName);
      setValidationData(result);
    } catch {
      setValidationError('Validation request failed. Is the backend running?');
    } finally {
      setIsValidating(false);
    }
  };

  // ── Per-file validation ─────────────────────────────────────────────────────
  const [validatingFiles, setValidatingFiles] = useState<Set<string>>(new Set());

  const handleValidateFile = async (fileName: string) => {
    setValidatingFiles((prev) => new Set(prev).add(fileName));
    setValidationError(null);
    try {
      const result = await validateFile(folderName, fileName);
      setValidationData((prev) => mergeValidation(prev, result));
    } catch {
      setValidationError(`Validation failed for ${fileName}. Is the backend running?`);
    } finally {
      setValidatingFiles((prev) => {
        const next = new Set(prev);
        next.delete(fileName);
        return next;
      });
    }
  };

  // ── Aggregate issues per file ───────────────────────────────────────────────
  const fileIssues = useMemo(() => {
    const map = new Map<string, { errors: number; warnings: number }>();
    if (!validationData) return map;

    for (const entry of validationData.files) {
      const name = entry.file_details.file_name;
      const agg = map.get(name) ?? { errors: 0, warnings: 0 };
      for (const issue of entry.result.issues) {
        const isError = (issue.category ?? '').toLowerCase() === 'error';
        if (isError) agg.errors++;
        else agg.warnings++;
      }
      map.set(name, agg);
    }
    return map;
  }, [validationData]);

  const getFileStatus = (fileName: string): XHTMLFileStatus => {
    const agg = fileIssues.get(fileName);
    if (agg === undefined) return 'pending';          // not yet validated
    if (agg.errors === 0 && agg.warnings === 0) return 'passed';
    if (agg.errors > 0) return 'failed';
    return 'warning';
  };

  // ── Summary stats ───────────────────────────────────────────────────────────
  const stats = useMemo(() => {
    const total = xhtmlFiles.length;
    let passed = 0, warnings = 0, failed = 0, pending = 0;
    for (const f of xhtmlFiles) {
      const agg = fileIssues.get(f.file_name);
      if (agg === undefined) { pending++; continue; }
      if (agg.errors === 0 && agg.warnings === 0) passed++;
      else if (agg.errors > 0) failed++;
      else warnings++;
    }
    return { total, passed, warnings, failed, pending };
  }, [xhtmlFiles, fileIssues]);

  const hasValidated = validationData !== null;

  // ── Status filter ───────────────────────────────────────────────────────────
  const [activeFilter, setActiveFilter] = useState<XHTMLFileStatus | null>(null);

  const toggleFilter = (status: XHTMLFileStatus) =>
    setActiveFilter((prev) => (prev === status ? null : status));

  const visibleFiles = useMemo(
    () => activeFilter ? xhtmlFiles.filter((f) => getFileStatus(f.file_name) === activeFilter) : xhtmlFiles,
    [xhtmlFiles, activeFilter, fileIssues], // eslint-disable-line react-hooks/exhaustive-deps
  );

  // ── Export state ────────────────────────────────────────────────────────────
  const [isExporting, setIsExporting] = useState(false);
  const [exportErrorMsg, setExportErrorMsg] = useState<string | null>(null);
  const [exportConfirmMsg, setExportConfirmMsg] = useState<string | null>(null);
  const [exportSuccess, setExportSuccess] = useState(false);
  const exportSuccessTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (exportSuccessTimer.current) clearTimeout(exportSuccessTimer.current); }, []);

  function triggerDownload(blob: Blob) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${folderName}.epub`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 100);
  }

  async function doExport(force: boolean) {
    setIsExporting(true);
    setExportErrorMsg(null);
    try {
      const result = await exportEpub(
        folderName,
        { failed: stats.failed, warnings: stats.warnings, pending: stats.pending },
        force,
      );
      if (result instanceof Blob) {
        triggerDownload(result);
        setExportSuccess(true);
        if (exportSuccessTimer.current) clearTimeout(exportSuccessTimer.current);
        exportSuccessTimer.current = setTimeout(() => setExportSuccess(false), 4000);
      } else if (result.status === 'confirm') {
        setExportConfirmMsg(result.message);
      }
    } catch (err) {
      setExportErrorMsg(err instanceof Error ? err.message : 'Export failed');
    } finally {
      setIsExporting(false);
    }
  }

  const handleExport = () => doExport(false);
  const handleExportConfirmed = () => { setExportConfirmMsg(null); doExport(true); };

  // ── Preview modal state ─────────────────────────────────────────────────────
  const [selectedFile, setSelectedFile] = useState<XHTMLFile | null>(null);
  const [modalInitialTab, setModalInitialTab] = useState<ModalTab>('result');
  const [modalAllowedTabs, setModalAllowedTabs] = useState<ModalTab[] | undefined>(undefined);

  const selectedEntries = useMemo(() => {
    if (!selectedFile || !validationData) return [];
    return validationData.files.filter(
      (e) => e.file_details.file_name === selectedFile.file_name,
    );
  }, [selectedFile, validationData]);

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <>
    <AnimatePresence>
      {selectedFile && (
        <ValidationDetailModal
          key={selectedFile.file_name}
          file={selectedFile}
          folderName={folderName}
          entries={selectedEntries}
          isRevalidating={validatingFiles.has(selectedFile.file_name)}
          initialTab={modalInitialTab}
          allowedTabs={modalAllowedTabs}
          onClose={() => setSelectedFile(null)}
          onRevalidate={
            modalAllowedTabs === undefined || selectedFile.file_name.endsWith('.css')
              ? () => handleValidateFile(selectedFile.file_name)
              : undefined
          }
        />
      )}
    </AnimatePresence>

    {/* ── Export error modal ────────────────────────────────────────────── */}
    <AnimatePresence>
      {exportErrorMsg && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <motion.div
            className="bg-background rounded-2xl shadow-2xl border border-border w-full max-w-md mx-4 p-6"
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ duration: 0.18 }}
          >
            <div className="flex items-start gap-3 mb-5">
              <XCircle className="w-5 h-5 text-red-500 shrink-0 mt-0.5" />
              <div>
                <h2 className="font-semibold text-foreground">Export Error</h2>
                <p className="text-sm text-muted-foreground mt-1">{exportErrorMsg}</p>
              </div>
            </div>
            <div className="flex justify-end">
              <Button onClick={() => setExportErrorMsg(null)}>Close</Button>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>

    {/* ── Export confirm modal ──────────────────────────────────────────── */}
    <AnimatePresence>
      {exportConfirmMsg && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
          <motion.div
            className="bg-background rounded-2xl shadow-2xl border border-border w-full max-w-md mx-4 p-6"
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.95 }}
            transition={{ duration: 0.18 }}
          >
            <div className="flex items-start gap-3 mb-5">
              <AlertTriangle className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
              <div>
                <h2 className="font-semibold text-foreground">Export with Issues?</h2>
                <p className="text-sm text-muted-foreground mt-1">{exportConfirmMsg}</p>
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setExportConfirmMsg(null)}>
                Cancel
              </Button>
              <Button onClick={handleExportConfirmed}>Proceed</Button>
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
    <motion.div
      className="flex flex-col min-h-full"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ duration: 0.22 }}
    >
      {/* ── Sticky header ──────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-10 bg-background/90 backdrop-blur border-b border-border px-8 py-4">
        <div className="flex items-start justify-between gap-4">
          {/* Left: back + title */}
          <div className="flex items-start gap-3 min-w-0">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => navigate('/')}
              className="mt-0.5 shrink-0"
            >
              <ArrowLeft className="w-4 h-4" />
            </Button>
            <div className="min-w-0">
              <h1
                className="text-2xl font-bold text-foreground tracking-tight truncate"
                title={folderName}
              >
                {titleCase(folderName)}
              </h1>
              <p className="text-sm text-muted-foreground mt-0.5 flex items-center gap-2 flex-wrap">
                {book && (
                  <>
                    <span className="font-mono text-xs">{folderName}</span>
                    <span className="text-border">·</span>
                    <span>{stats.total} chapters</span>
                    <span className="text-border">·</span>
                    <span>{formatDate(book.uploaded_at)}</span>
                  </>
                )}
                {!book && <span className="font-mono text-xs">{folderName}</span>}
              </p>
            </div>
          </div>

          {/* Right: actions */}
          <div className="flex items-center gap-2 shrink-0">
            <Button
              size="sm"
              className="gap-2 shadow-sm"
              onClick={handleValidateAll}
              disabled={isValidating || isLoading}
            >
              {isValidating ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Play className="w-3.5 h-3.5" />
              )}
              {isValidating ? `Validating… ${fmtElapsed(elapsed)}` : 'Validate all'}
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="gap-2 shadow-sm"
              onClick={handleExport}
              disabled={isExporting || isLoading || isValidating}
            >
              {isExporting ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Download className="w-3.5 h-3.5" />
              )}
              {isExporting ? 'Exporting…' : 'Export EPUB'}
            </Button>
          </div>
        </div>
      </header>

      {/* Indeterminate progress stripe while validating */}
      {isValidating && (
        <div className="h-0.5 w-full bg-muted overflow-hidden">
          <motion.div
            className="h-full w-1/3 bg-primary rounded-full"
            animate={{ x: ['−100%', '400%'] }}
            transition={{ repeat: Infinity, duration: 1.4, ease: 'easeInOut' }}
          />
        </div>
      )}

      {/* ── Content ────────────────────────────────────────────────────────── */}
      <div className="flex-1 px-8 py-6 space-y-6">

        {/* Validation error banner */}
        {validationError && (
          <div className="flex items-center gap-2 px-4 py-3 rounded-lg bg-destructive/10 border border-destructive/20 text-sm text-destructive">
            <XCircle className="w-4 h-4 flex-shrink-0" />
            {validationError}
          </div>
        )}

        {/* Export success banner */}
        <AnimatePresence>
          {exportSuccess && (
            <motion.div
              className="flex items-center gap-2 px-4 py-3 rounded-lg bg-emerald-50 border border-emerald-200 text-sm text-emerald-700 dark:bg-emerald-950/30 dark:border-emerald-900/40 dark:text-emerald-400"
              initial={{ opacity: 0, y: -4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.2 }}
            >
              <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
              EPUB exported successfully — check your downloads.
            </motion.div>
          )}
        </AnimatePresence>

        {/* ── 4-stat summary row ─────────────────────────────────────────── */}
        {!isLoading && xhtmlFiles.length > 0 && (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
            <StatCard
              label="Total Files"
              value={stats.total}
              total={stats.total}
              icon={BookOpen}
              barColor="bg-primary"
              valueColor="text-foreground"
            />
            <StatCard
              label="Pending"
              value={stats.pending}
              total={stats.total}
              icon={Clock}
              barColor="bg-slate-400"
              valueColor={stats.pending > 0 ? 'text-slate-500' : 'text-foreground'}
              isActive={activeFilter === 'pending'}
              onClick={() => toggleFilter('pending')}
            />
            <StatCard
              label="Passed"
              value={stats.passed}
              total={stats.total}
              icon={CheckCircle2}
              barColor="bg-emerald-500"
              valueColor={hasValidated ? 'text-emerald-600' : 'text-foreground'}
              isActive={activeFilter === 'passed'}
              onClick={() => toggleFilter('passed')}
            />
            <StatCard
              label="Warnings"
              value={stats.warnings}
              total={stats.total}
              icon={AlertTriangle}
              barColor="bg-amber-400"
              valueColor={hasValidated && stats.warnings > 0 ? 'text-amber-600' : 'text-foreground'}
              isActive={activeFilter === 'warning'}
              onClick={() => toggleFilter('warning')}
            />
            <StatCard
              label="Failed"
              value={stats.failed}
              total={stats.total}
              icon={XCircle}
              barColor="bg-red-500"
              valueColor={hasValidated && stats.failed > 0 ? 'text-red-600' : 'text-foreground'}
              isActive={activeFilter === 'failed'}
              onClick={() => toggleFilter('failed')}
            />
          </div>
        )}

        {/* ── XHTML file cards ────────────────────────────────────────────── */}
        {isLoading ? (
          <SkeletonGrid />
        ) : isError || !filesData?.status ? (
          <EmptyState
            icon={FileCode2}
            title="Could not load files"
            description="Make sure the backend is running and this folder exists."
            action={{ label: '← Back to Dashboard', onClick: () => navigate('/') }}
          />
        ) : xhtmlFiles.length === 0 ? (
          <EmptyState
            icon={FileCode2}
            title="No XHTML files found"
            description="This folder doesn't contain any .xhtml files."
            action={{ label: '← Back', onClick: () => navigate('/') }}
          />
        ) : (
          <>
          {activeFilter && (
            <div className="flex items-center justify-between text-sm text-muted-foreground">
              <span>
                Showing <span className="font-medium text-foreground">{visibleFiles.length}</span> {activeFilter} file{visibleFiles.length !== 1 ? 's' : ''}
              </span>
              <button
                onClick={() => setActiveFilter(null)}
                className="text-xs text-primary hover:underline"
              >
                Clear filter
              </button>
            </div>
          )}
          <motion.div
            className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4"
            variants={containerVariants}
            initial="hidden"
            animate="show"
          >
            {visibleFiles.map((file, i) => {
              const status = getFileStatus(file.file_name);
              const agg = fileIssues.get(file.file_name);
              return (
                <motion.div key={`${file.file_name}-${i}`} variants={xhtmlCardVariants}>
                  <XHTMLCard
                    file={file}
                    status={status}
                    errors={agg?.errors ?? 0}
                    warnings={agg?.warnings ?? 0}
                    isValidating={validatingFiles.has(file.file_name)}
                    onValidate={() => handleValidateFile(file.file_name)}
                    onOpen={() => { setModalAllowedTabs(undefined); setModalInitialTab('result'); setSelectedFile(file); }}
                    onPreview={() => { setModalAllowedTabs(undefined); setModalInitialTab('preview'); setSelectedFile(file); }}
                    index={i}
                  />
                </motion.div>
              );
            })}
          </motion.div>

          {/* ── CSS stylesheets section ────────────────────────────────── */}
          {cssFiles.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center gap-2 pt-2">
                <Braces className="w-4 h-4 text-violet-500" />
                <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-widest">
                  CSS Stylesheets
                </h2>
                <span className="text-xs text-muted-foreground">({cssFiles.length})</span>
              </div>
              <motion.div
                className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4"
                variants={containerVariants}
                initial="hidden"
                animate="show"
              >
                {cssFiles.map((file, i) => (
                  <motion.div key={`css-${file.file_name}-${i}`} variants={xhtmlCardVariants}>
                    <XHTMLCard
                      file={file}
                      variant="css"
                      status="pending"
                      onOpen={() => { setModalAllowedTabs(['result', 'source']); setModalInitialTab('result'); setSelectedFile(file); }}
                      index={i}
                    />
                  </motion.div>
                ))}
              </motion.div>
            </div>
          )}
          </>
        )}
      </div>
    </motion.div>
    </>
  );
}
