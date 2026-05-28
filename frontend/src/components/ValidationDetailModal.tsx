import { useState, useMemo, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  X,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  FileCode2,
  RotateCw,
  Save,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { getFileContent, getPdfPage, saveFileContent } from '@/lib/api';
import type { XHTMLFile, ValidationFileEntry, ValidationIssue } from '@/types';

interface Props {
  file: XHTMLFile;
  folderName: string;
  entries: ValidationFileEntry[];
  isRevalidating?: boolean;
  initialTab?: Tab;
  allowedTabs?: Tab[];
  onClose: () => void;
  onRevalidate?: () => void;
}

export type Tab = 'result' | 'preview' | 'source' | 'pdf';

type DisplayIssue = ValidationIssue & { _ruleName: string };

// ─── Rule row in left sidebar ────────────────────────────────────────────────

function RuleRow({
  entry,
  isSelected,
  selectedSubRuleName,
  onClick,
  onSubRuleClick,
}: {
  entry: ValidationFileEntry;
  isSelected: boolean;
  selectedSubRuleName: string | null;
  onClick: () => void;
  onSubRuleClick: (name: string) => void;
}) {
  const errors   = entry.result.issues.filter(i => (i.category ?? '').toLowerCase() === 'error').length;
  const warnings = entry.result.issues.filter(i => (i.category ?? '').toLowerCase() !== 'error').length;
  const passed   = entry.result.issues.length === 0;

  const subRuleNames = [...new Set(
    entry.result.issues.map(i => i.rule_name).filter((n): n is string => !!n)
  )];

  return (
    <div>
      <button
        onClick={onClick}
        className={cn(
          'w-full text-left px-3 py-2.5 rounded-lg transition-colors',
          isSelected ? 'bg-primary/10' : 'hover:bg-muted',
        )}
      >
        <div className="flex items-center justify-between gap-1.5">
          <span className={cn(
            'text-xs font-medium truncate',
            isSelected ? 'text-primary' : 'text-foreground',
          )}>
            {entry.rule_name}
          </span>
          {passed ? (
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 flex-shrink-0" />
          ) : errors > 0 ? (
            <XCircle className="w-3.5 h-3.5 text-red-500 flex-shrink-0" />
          ) : (
            <AlertTriangle className="w-3.5 h-3.5 text-amber-500 flex-shrink-0" />
          )}
        </div>
        {!passed && (
          <p className="text-[10px] text-muted-foreground mt-0.5 leading-none">
            {[
              errors   > 0 && `${errors} error${errors !== 1 ? 's' : ''}`,
              warnings > 0 && `${warnings} warning${warnings !== 1 ? 's' : ''}`,
            ].filter(Boolean).join(' · ')}
          </p>
        )}
      </button>

      {subRuleNames.length > 0 && (
        <div className="ml-3 pl-2 border-l border-border/40 mt-0.5 mb-1 space-y-0.5">
          {subRuleNames.map(name => {
            const subErrors   = entry.result.issues.filter(i => i.rule_name === name && (i.category ?? '').toLowerCase() === 'error').length;
            const subWarnings = entry.result.issues.filter(i => i.rule_name === name && (i.category ?? '').toLowerCase() !== 'error').length;
            const isSubSelected = isSelected && selectedSubRuleName === name;
            return (
              <button
                key={name}
                onClick={(e) => { e.stopPropagation(); onSubRuleClick(name); }}
                className={cn(
                  'w-full text-left px-2 py-1.5 rounded transition-colors',
                  isSubSelected ? 'bg-primary/10' : 'hover:bg-muted',
                )}
              >
                <div className="flex items-center justify-between gap-1.5">
                  <span className={cn(
                    'text-[11px] font-medium truncate',
                    isSubSelected ? 'text-primary' : 'text-foreground',
                  )}>
                    {name}
                  </span>
                  {subErrors > 0
                    ? <XCircle className="w-3 h-3 text-red-500 flex-shrink-0" />
                    : <AlertTriangle className="w-3 h-3 text-amber-500 flex-shrink-0" />}
                </div>
                <p className="text-[10px] text-muted-foreground mt-0.5 leading-none">
                  {[
                    subErrors   > 0 && `${subErrors} error${subErrors !== 1 ? 's' : ''}`,
                    subWarnings > 0 && `${subWarnings} warning${subWarnings !== 1 ? 's' : ''}`,
                  ].filter(Boolean).join(' · ')}
                </p>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ─── Issue row in right panel ────────────────────────────────────────────────

function IssueRow({ issue }: { issue: DisplayIssue }) {
  const isError = (issue.category ?? '').toLowerCase() === 'error';
  const hasDiff = issue.expected_text || issue.actual_text;
  const snippetParts = issue.snippet ? issue.snippet.split(' ⏎ ') : null;

  return (
    <div className={cn(
      'rounded-lg border text-sm overflow-hidden',
      isError
        ? 'bg-red-50 border-red-100 dark:bg-red-950/20 dark:border-red-900/30'
        : 'bg-amber-50 border-amber-100 dark:bg-amber-950/20 dark:border-amber-900/30',
    )}>
      {/* Main row */}
      <div className="flex items-start gap-3 px-4 py-3">
        {isError ? (
          <XCircle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
        ) : (
          <AlertTriangle className="w-4 h-4 text-amber-500 flex-shrink-0 mt-0.5" />
        )}
        <div className="flex-1 min-w-0">
          <p className={cn(
            'font-medium text-xs',
            isError ? 'text-red-700 dark:text-red-400' : 'text-amber-700 dark:text-amber-400',
          )}>
            {issue.rule_name || issue.type}
            {typeof issue.line_number === 'number' && (
              <span className="ml-1.5 font-mono text-[10px] opacity-70">line {issue.line_number}</span>
            )}
          </p>
          {issue.message && (
            <p className="text-xs text-muted-foreground mt-0.5 break-words">{issue.message}</p>
          )}
          {issue.href && (
            <p className="text-xs font-mono text-muted-foreground mt-0.5 break-all opacity-70">{issue.href}</p>
          )}
          {snippetParts && !hasDiff && (
            <div className="mt-2 rounded-md border border-border/60 bg-background/60 px-2.5 py-2 text-xs font-mono text-foreground/80 leading-relaxed">
              {snippetParts.length === 2 ? (
                <>
                  <span className="break-words">…{snippetParts[0].trim()}</span>
                  <span className="block my-0.5 text-[10px] uppercase tracking-widest text-muted-foreground/70 font-sans">
                    ↵ paragraph break
                  </span>
                  <span className="break-words">{snippetParts[1].trim()}…</span>
                </>
              ) : (
                <span className="break-words">…{issue.snippet}…</span>
              )}
            </div>
          )}
          <p className="text-[10px] text-muted-foreground mt-1 opacity-60">{issue._ruleName}</p>
        </div>
        {issue.category && (
          <span className={cn(
            'flex-shrink-0 text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded self-start',
            isError
              ? 'bg-red-100 text-red-600 dark:bg-red-900/40'
              : 'bg-amber-100 text-amber-600 dark:bg-amber-900/40',
          )}>
            {issue.category}
          </span>
        )}
      </div>

      {/* Expected / Actual diff block */}
      {hasDiff && (
        <div className={cn(
          'mx-3 mb-3 rounded-md border overflow-hidden text-xs font-mono',
          isError ? 'border-red-200 dark:border-red-800' : 'border-amber-200 dark:border-amber-800',
        )}>
          {issue.expected_text !== undefined && (
            <div className="flex items-start gap-2 px-3 py-2 bg-emerald-50 dark:bg-emerald-950/30 border-b border-emerald-200 dark:border-emerald-800">
              <span className="flex-shrink-0 font-bold text-emerald-600 select-none">+</span>
              <div className="min-w-0">
                <p className="text-[10px] font-sans font-semibold text-emerald-600 mb-0.5 uppercase tracking-wide">Expected</p>
                <p className="text-emerald-800 dark:text-emerald-300 break-words whitespace-pre-wrap">{String(issue.expected_text)}</p>
              </div>
            </div>
          )}
          {issue.actual_text !== undefined && (
            <div className="flex items-start gap-2 px-3 py-2 bg-red-50 dark:bg-red-950/30">
              <span className="flex-shrink-0 font-bold text-red-500 select-none">−</span>
              <div className="min-w-0">
                <p className="text-[10px] font-sans font-semibold text-red-500 mb-0.5 uppercase tracking-wide">Actual</p>
                <p className="text-red-700 dark:text-red-300 break-words whitespace-pre-wrap">{String(issue.actual_text)}</p>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function resolveRelative(filePath: string, href: string): string {
  const base = filePath.replace(/\\/g, '/');
  const dir  = base.includes('/') ? base.slice(0, base.lastIndexOf('/') + 1) : '';
  try {
    return new URL(href, `http://x/${dir}`).pathname.slice(1);
  } catch {
    return href;
  }
}

// ─── Modal ───────────────────────────────────────────────────────────────────

export function ValidationDetailModal({ file, folderName, entries, isRevalidating = false, initialTab = 'result', allowedTabs, onClose, onRevalidate }: Props) {
  const visibleTabs: Tab[] = allowedTabs ?? ['result', 'preview', 'source'];
  const [activeTab, setActiveTab]       = useState<Tab>(initialTab);
  const [selectedRuleId, setSelectedRule] = useState<string | null>(null);

  // ── Source fetch ─────────────────────────────────────────────────────────────
  const [sourceContent, setSourceContent] = useState<string | null>(null);
  const [sourceLoading, setSourceLoading] = useState(false);
  const [sourceError, setSourceError]     = useState<string | null>(null);

  // ── Source editing ────────────────────────────────────────────────────────────
  const [editedContent, setEditedContent]   = useState<string | null>(null);
  const [isSaving, setIsSaving]             = useState(false);
  const [saveSuccess, setSaveSuccess]       = useState(false);
  const [saveError, setSaveError]           = useState<string | null>(null);
  const [showCloseWarning, setShowCloseWarning] = useState(false);
  const textareaRef  = useRef<HTMLTextAreaElement>(null);
  const lineNumsRef  = useRef<HTMLDivElement>(null);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isDirty       = editedContent !== null && editedContent !== sourceContent;
  const displayContent = editedContent ?? sourceContent ?? '';
  const lineCount      = displayContent ? displayContent.split('\n').length : 0;

  useEffect(() => () => { if (saveTimerRef.current) clearTimeout(saveTimerRef.current); }, []);

  async function handleSave() {
    if (!isDirty || isSaving) return;
    setIsSaving(true);
    setSaveError(null);
    try {
      await saveFileContent(folderName, filePath, editedContent!);
      setSourceContent(editedContent);  // update baseline
      setEditedContent(null);           // mark clean
      setPreviewUrl(null);              // invalidate cached preview
      setSaveSuccess(true);
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      saveTimerRef.current = setTimeout(() => setSaveSuccess(false), 3000);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Save failed');
    } finally {
      setIsSaving(false);
    }
  }

  function handleClose() {
    if (isDirty) { setShowCloseWarning(true); } else { onClose(); }
  }

  const filePath = useMemo(() => {
    if (entries.length > 0) return entries[0].file_details.relative_path;
    return file.path ?? file.relative_path ?? file.file_name;
  }, [entries, file]);

  useEffect(() => {
    if (activeTab !== 'source') return;
    if (sourceContent !== null || sourceLoading) return;
    setSourceLoading(true);
    setSourceError(null);
    getFileContent(folderName, filePath)
      .then((text) => setSourceContent(text))
      .catch(() => setSourceError('Could not load file content. Check that the backend exposes GET /files/{folder}/{path}.'))
      .finally(() => setSourceLoading(false));
  }, [activeTab, folderName, filePath, sourceContent, sourceLoading]);

  // ── PDF page lookup ───────────────────────────────────────────────────────────
  const [pdfPage, setPdfPage]             = useState<number | null>(null);
  const [pdfEndPage, setPdfEndPage]       = useState<number | null>(null);
  const [pdfPageLoading, setPdfPageLoading] = useState(false);

  useEffect(() => {
    if (activeTab !== 'pdf' && activeTab !== 'preview') return;
    if (pdfPage !== null || pdfPageLoading) return;
    setPdfPageLoading(true);
    getPdfPage(folderName, file.file_name)
      .then(({ page, end_page }) => { setPdfPage(page); setPdfEndPage(end_page); })
      .catch(() => { setPdfPage(1); setPdfEndPage(1); })
      .finally(() => setPdfPageLoading(false));
  }, [activeTab, folderName, file.file_name, pdfPage, pdfPageLoading]);

  // ── Preview (rendered iframe with inlined CSS + fixed image URLs) ─────────────
  const [previewUrl, setPreviewUrl]         = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError]     = useState<string | null>(null);
  const previewBlobRef = useRef<string | null>(null);

  // Revoke blob URL on unmount
  useEffect(() => {
    return () => { if (previewBlobRef.current) URL.revokeObjectURL(previewBlobRef.current); };
  }, []);

  useEffect(() => {
    if (activeTab !== 'preview') return;
    if (previewUrl !== null || previewLoading) return;
    setPreviewLoading(true);
    setPreviewError(null);

    (async () => {
      try {
        let html = await getFileContent(folderName, filePath);

        const norm = filePath.replace(/\\/g, '/');
        const dir  = norm.includes('/') ? norm.slice(0, norm.lastIndexOf('/') + 1) : '';

        // ── 1. Collect all CSS hrefs from <link> tags ─────────────────────
        const cssHrefs = new Set<string>();
        html.replace(/<link\b[^>]*/gi, (tag) => {
          const isSheet = /rel=["']stylesheet["']/i.test(tag) || /type=["']text\/css["']/i.test(tag);
          if (!isSheet) return tag;
          const m = tag.match(/href=["']([^"']+)["']/i);
          if (m && !/^https?:\/\//.test(m[1])) cssHrefs.add(m[1]);
          return tag;
        });

        // ── 2. Fetch every CSS file (parallel) ───────────────────────────
        const cssMap = new Map<string, string>();
        await Promise.all(Array.from(cssHrefs).map(async (href) => {
          try {
            cssMap.set(href, await getFileContent(folderName, resolveRelative(norm, href)));
          } catch { /* skip */ }
        }));

        // ── 3. Replace <link> with <style> so MIME type is never an issue ─
        html = html.replace(/<link\b[^>]*\/?>/gi, (tag) => {
          const isSheet = /rel=["']stylesheet["']/i.test(tag) || /type=["']text\/css["']/i.test(tag);
          if (!isSheet) return tag;
          const m = tag.match(/href=["']([^"']+)["']/i);
          if (!m) return tag;
          const css = cssMap.get(m[1]);
          return css != null ? `<style type="text/css">\n${css}\n</style>` : tag;
        });

        // ── 4. <base> so images/fonts resolve via backend ─────────────────
        const baseHref = `${window.location.origin}/file-data/${folderName}/${dir}`;
        html = html.replace(/<base\b[^>]*\/?>/gi, '');
        html = html.replace(
          /(<head\b[^>]*>)/i,
          `$1\n<base href="${baseHref}"/>\n<style type="text/css">a,a:link,a:visited,a:hover,a:active{pointer-events:none!important;cursor:default!important;}</style>`,
        );

        // application/xhtml+xml preserves XML structure (no <a> tag hoisting)
        const blob = new Blob([html], { type: 'application/xhtml+xml' });
        if (previewBlobRef.current) URL.revokeObjectURL(previewBlobRef.current);
        previewBlobRef.current = URL.createObjectURL(blob);
        setPreviewUrl(previewBlobRef.current);
      } catch {
        setPreviewError('Could not generate preview. Is the backend running?');
      } finally {
        setPreviewLoading(false);
      }
    })();
  }, [activeTab, folderName, filePath, previewUrl, previewLoading]);

  const totalErrors = useMemo(
    () => entries.reduce((sum, e) => sum + e.result.issues.filter(i => (i.category ?? '').toLowerCase() === 'error').length, 0),
    [entries],
  );
  const totalWarnings = useMemo(
    () => entries.reduce((sum, e) => sum + e.result.issues.filter(i => (i.category ?? '').toLowerCase() !== 'error').length, 0),
    [entries],
  );

  const score = useMemo(() => {
    if (entries.length === 0) return 0;
    const passed = entries.filter(e => e.result.issues.length === 0).length;
    return Math.round((passed / entries.length) * 100);
  }, [entries]);

  const [issueFilter, setIssueFilter] = useState<'all' | 'error' | 'warning'>('all');
  const [ruleNameFilter, setRuleNameFilter] = useState<string | null>(null);

  const toggleIssueFilter = (f: 'error' | 'warning') =>
    setIssueFilter((prev) => (prev === f ? 'all' : f));

  const allIssues = useMemo<DisplayIssue[]>(() => {
    if (selectedRuleId) {
      const entry = entries.find(e => e.rule_id === selectedRuleId);
      return (entry?.result.issues ?? []).map(i => ({ ...i, _ruleName: entry?.rule_name ?? '' }));
    }
    return entries.flatMap(e =>
      e.result.issues.map(i => ({ ...i, _ruleName: e.rule_name })),
    );
  }, [entries, selectedRuleId]);

  const displayedIssues = useMemo<DisplayIssue[]>(() => {
    let issues = allIssues;
    if (issueFilter === 'error')   issues = issues.filter(i => (i.category ?? '').toLowerCase() === 'error');
    if (issueFilter === 'warning') issues = issues.filter(i => (i.category ?? '').toLowerCase() !== 'error');
    if (ruleNameFilter)            issues = issues.filter(i => i.rule_name === ruleNameFilter);
    return issues;
  }, [allIssues, issueFilter, ruleNameFilter]);

  const errorCount   = useMemo(() => allIssues.filter(i => (i.category ?? '').toLowerCase() === 'error').length,   [allIssues]);
  const warningCount = useMemo(() => allIssues.filter(i => (i.category ?? '').toLowerCase() !== 'error').length, [allIssues]);

  const scoreColor   = score >= 80 ? 'text-emerald-600' : score >= 60 ? 'text-amber-600' : 'text-red-600';
  const scoreBarColor = score >= 80 ? 'bg-emerald-500'  : score >= 60 ? 'bg-amber-500'  : 'bg-red-500';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <motion.div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={handleClose}
      />

      {/* Panel */}
      <motion.div
        className="relative z-10 w-full max-w-[95vw] h-[92vh] bg-card rounded-2xl shadow-2xl border border-border flex flex-col overflow-hidden"
        initial={{ opacity: 0, scale: 0.96, y: 16 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.96, y: 16 }}
        transition={{ duration: 0.2, ease: 'easeOut' }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border flex-shrink-0">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-9 h-9 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
              <FileCode2 className="w-4 h-4 text-primary" />
            </div>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-foreground truncate">{file.file_name}</p>
              <p className="text-xs text-muted-foreground flex items-center gap-1 flex-wrap">
                Validation session
                {totalErrors > 0 && (
                  <span className="text-red-500">· {totalErrors} error{totalErrors !== 1 ? 's' : ''}</span>
                )}
                {totalWarnings > 0 && (
                  <span className="text-amber-500">· {totalWarnings} warning{totalWarnings !== 1 ? 's' : ''}</span>
                )}
                {totalErrors === 0 && totalWarnings === 0 && entries.length > 0 && (
                  <span className="text-emerald-500">· all passed</span>
                )}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 flex-shrink-0">
            {/* Save feedback */}
            {saveSuccess && (
              <span className="text-xs text-emerald-600 font-medium flex items-center gap-1">
                <CheckCircle2 className="w-3.5 h-3.5" /> Saved
              </span>
            )}
            {saveError && (
              <span className="text-xs text-red-500 font-medium flex items-center gap-1" title={saveError}>
                <XCircle className="w-3.5 h-3.5" /> Save failed
              </span>
            )}
            <Button
              variant="outline"
              size="sm"
              className={cn('gap-1.5 text-xs', isDirty && 'border-primary text-primary')}
              onClick={handleSave}
              disabled={!isDirty || isSaving}
            >
              {isSaving
                ? <RotateCw className="w-3.5 h-3.5 animate-spin" />
                : <Save className="w-3.5 h-3.5" />}
              {isSaving ? 'Saving…' : isDirty ? 'Save*' : 'Save'}
            </Button>
            {onRevalidate && (
              <Button
                variant="outline"
                size="sm"
                className="gap-1.5 text-xs"
                onClick={onRevalidate}
                disabled={isRevalidating}
              >
                <RotateCw className={cn('w-3.5 h-3.5', isRevalidating && 'animate-spin')} />
                {isRevalidating ? 'Validating…' : 'Revalidate'}
              </Button>
            )}
            <Button variant="ghost" size="icon" onClick={handleClose} className="ml-1">
              <X className="w-4 h-4" />
            </Button>
          </div>
        </div>

        {/* Body */}
        <div className="flex flex-1 min-h-0">

          {/* Left sidebar — only on Validation Result tab */}
          {activeTab === 'result' && (
          <div className="w-56 flex-shrink-0 border-r border-border flex flex-col">
            <div className="px-3 pt-3 pb-1.5">
              <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground px-2">
                Validation Rules
              </p>
            </div>

            <div className="flex-1 overflow-y-auto px-2 pb-2 space-y-0.5">
              {/* All-issues shortcut */}
              <button
                onClick={() => { setSelectedRule(null); setRuleNameFilter(null); }}
                className={cn(
                  'w-full text-left px-3 py-2 rounded-lg transition-colors text-xs font-medium',
                  selectedRuleId === null
                    ? 'bg-primary/10 text-primary'
                    : 'hover:bg-muted text-muted-foreground',
                )}
              >
                All issues
                {(totalErrors + totalWarnings) > 0 && (
                  <span className="ml-1 text-[10px] opacity-70">({totalErrors + totalWarnings})</span>
                )}
              </button>

              {entries.length === 0 ? (
                <p className="px-3 py-2 text-xs text-muted-foreground/60 italic">
                  No validation data yet.
                </p>
              ) : (
                entries.map((entry) => (
                  <RuleRow
                    key={`${entry.rule_id}-${entry.file_details.file_name}`}
                    entry={entry}
                    isSelected={selectedRuleId === entry.rule_id}
                    selectedSubRuleName={selectedRuleId === entry.rule_id ? ruleNameFilter : null}
                    onClick={() => { setSelectedRule(entry.rule_id); setRuleNameFilter(null); }}
                    onSubRuleClick={(name) => { setSelectedRule(entry.rule_id); setRuleNameFilter(name); }}
                  />
                ))
              )}
            </div>

            {/* Overall score */}
            <div className="px-4 py-3 border-t border-border flex-shrink-0">
              <div className="flex items-center justify-between mb-1.5">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                  Overall score
                </p>
                <span className={cn('text-sm font-bold tabular-nums', entries.length === 0 ? 'text-muted-foreground' : scoreColor)}>
                  {entries.length === 0 ? '—' : `${score}/100`}
                </span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-muted overflow-hidden">
                <motion.div
                  className={cn('h-full rounded-full', scoreBarColor)}
                  initial={{ width: 0 }}
                  animate={{ width: entries.length === 0 ? '0%' : `${score}%` }}
                  transition={{ duration: 0.7, ease: 'easeOut', delay: 0.15 }}
                />
              </div>
            </div>
          </div>
          )}

          {/* Right panel */}
          <div className="flex-1 flex flex-col min-w-0">
            {/* Tabs */}
            <div className="flex items-center gap-0 px-4 pt-3 border-b border-border flex-shrink-0">
              {visibleTabs.map((tab) => (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className={cn(
                    'px-4 py-2 text-xs font-medium transition-colors border-b-2 -mb-px',
                    activeTab === tab
                      ? 'text-primary border-primary'
                      : 'text-muted-foreground border-transparent hover:text-foreground',
                  )}
                >
                  {tab === 'result' ? 'Validation Result'
                    : tab === 'preview' ? 'Preview'
                    : tab === 'source' ? (<>Source{isDirty && <span className="ml-1 text-amber-500">●</span>}</>)
                    : 'PDF'}
                </button>
              ))}
            </div>

            {/* Filter bar — visible only on Validation Result tab, never scrolls */}
            {activeTab === 'result' && allIssues.length > 0 && (
              <div className="flex-shrink-0 border-b border-border bg-card">
                {/* Severity filter row */}
                <div className="flex items-center gap-2 px-4 py-2.5">
                  <button
                    onClick={() => toggleIssueFilter('error')}
                    className={cn(
                      'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold border transition-colors',
                      issueFilter === 'error'
                        ? 'bg-red-500 text-white border-red-500'
                        : 'bg-red-50 text-red-600 border-red-200 hover:bg-red-100',
                    )}
                  >
                    <XCircle className="w-3 h-3" />
                    Error ({errorCount})
                  </button>
                  <button
                    onClick={() => toggleIssueFilter('warning')}
                    className={cn(
                      'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold border transition-colors',
                      issueFilter === 'warning'
                        ? 'bg-amber-500 text-white border-amber-500'
                        : 'bg-amber-50 text-amber-600 border-amber-200 hover:bg-amber-100',
                    )}
                  >
                    <AlertTriangle className="w-3 h-3" />
                    Warning ({warningCount})
                  </button>
                  {issueFilter !== 'all' && (
                    <button
                      onClick={() => setIssueFilter('all')}
                      className="text-[11px] text-muted-foreground hover:text-foreground underline ml-1"
                    >
                      Clear
                    </button>
                  )}
                </div>
              </div>
            )}

            {/* Tab content */}
            <div className="flex-1 overflow-y-auto">
              <AnimatePresence mode="wait">
                {activeTab === 'result' && (
                  <motion.div
                    key="result"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.12 }}
                    className="p-4 space-y-2"
                  >
                    {entries.length === 0 ? (
                      <div className="flex flex-col items-center justify-center py-16 text-center">
                        <FileCode2 className="w-10 h-10 text-muted-foreground/20 mb-3" />
                        <p className="text-sm font-semibold text-foreground">No validation data</p>
                        <p className="text-xs text-muted-foreground mt-1">
                          Click Revalidate to run validation for this file.
                        </p>
                      </div>
                    ) : displayedIssues.length === 0 ? (
                      <div className="flex flex-col items-center justify-center py-16 text-center">
                        <CheckCircle2 className="w-10 h-10 text-emerald-500 mb-3" />
                        <p className="text-sm font-semibold text-foreground">
                          {issueFilter === 'all' ? 'All checks passed' : `No ${issueFilter}s found`}
                        </p>
                        <p className="text-xs text-muted-foreground mt-1">
                          {issueFilter === 'all'
                            ? `No issues found${selectedRuleId ? ' for this rule' : ''}.`
                            : 'Try a different filter.'}
                        </p>
                      </div>
                    ) : (
                      displayedIssues.map((issue, i) => (
                        <IssueRow key={i} issue={issue} />
                      ))
                    )}
                  </motion.div>
                )}

                {activeTab === 'preview' && (
                  <motion.div
                    key="preview"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.12 }}
                    className="h-full flex"
                  >
                    {/* Left: PDF page */}
                    <div className="w-1/2 h-full border-r border-border flex flex-col">
                      <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground border-b border-border bg-muted/30 flex-shrink-0 flex items-center gap-2">
                        <span>PDF</span>
                        {pdfPage !== null && pdfEndPage !== null && (
                          <span className="normal-case font-normal text-muted-foreground/70">
                            {pdfPage === pdfEndPage
                              ? `p. ${pdfPage}`
                              : `pp. ${pdfPage}–${pdfEndPage}`}
                          </span>
                        )}
                      </div>
                      {pdfPageLoading && (
                        <div className="flex flex-col items-center justify-center flex-1 gap-2 text-sm text-muted-foreground">
                          <svg className="w-5 h-5 animate-spin" viewBox="0 0 24 24" fill="none">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                          </svg>
                          Finding page…
                        </div>
                      )}
                      {!pdfPageLoading && pdfPage !== null && (
                        <iframe
                          src={`/pdf/${folderName}/chapter?file=${encodeURIComponent(file.file_name)}#toolbar=0&navpanes=0&scrollbar=1&pagemode=none&view=FitH`}
                          className="flex-1 w-full border-0"
                          title={`PDF: ${folderName}`}
                        />
                      )}
                    </div>

                    {/* Right: HTML preview */}
                    <div className="w-1/2 h-full flex flex-col">
                      <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground border-b border-border bg-muted/30 flex-shrink-0">
                        HTML
                      </div>
                      {previewLoading && (
                        <div className="flex flex-col items-center justify-center flex-1 gap-2 text-sm text-muted-foreground">
                          <svg className="w-5 h-5 animate-spin" viewBox="0 0 24 24" fill="none">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                          </svg>
                          Rendering preview…
                        </div>
                      )}
                      {previewError && (
                        <div className="flex flex-col items-center justify-center flex-1 text-center px-6 gap-2">
                          <XCircle className="w-8 h-8 text-red-400" />
                          <p className="text-sm font-medium text-foreground">Preview failed</p>
                          <p className="text-xs text-muted-foreground">{previewError}</p>
                        </div>
                      )}
                      {previewUrl && !previewLoading && (
                        <iframe
                          src={previewUrl}
                          className="flex-1 w-full border-0 bg-white"
                          sandbox="allow-same-origin"
                          title={`Preview: ${file.file_name}`}
                        />
                      )}
                    </div>
                  </motion.div>
                )}

                {activeTab === 'source' && (
                  <motion.div
                    key="source"
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.12 }}
                    className="h-full"
                  >
                    {sourceLoading && (
                      <div className="flex items-center justify-center h-full py-16">
                        <div className="flex items-center gap-2 text-sm text-muted-foreground">
                          <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                          </svg>
                          Loading source…
                        </div>
                      </div>
                    )}
                    {sourceError && (
                      <div className="flex flex-col items-center justify-center h-full py-16 text-center px-6">
                        <XCircle className="w-8 h-8 text-red-400 mb-3" />
                        <p className="text-sm font-medium text-foreground mb-1">Failed to load source</p>
                        <p className="text-xs text-muted-foreground">{sourceError}</p>
                      </div>
                    )}
                    {sourceContent !== null && !sourceLoading && (
                      <div className="flex h-full font-mono text-xs bg-muted/30">
                        {/* Line numbers — scrolled in sync with textarea */}
                        <div
                          ref={lineNumsRef}
                          className="select-none text-right text-muted-foreground/40 px-3 py-1 border-r border-border/40 overflow-hidden shrink-0 min-w-[2.75rem]"
                          aria-hidden
                        >
                          {Array.from({ length: lineCount }, (_, i) => (
                            <div key={i} className="leading-5">{i + 1}</div>
                          ))}
                        </div>
                        {/* Editable content */}
                        <textarea
                          ref={textareaRef}
                          value={displayContent}
                          onChange={(e) => setEditedContent(e.target.value)}
                          onScroll={(e) => {
                            if (lineNumsRef.current)
                              lineNumsRef.current.scrollTop = e.currentTarget.scrollTop;
                          }}
                          className="flex-1 resize-none outline-none px-4 py-1 leading-5 bg-transparent text-foreground/90 overflow-auto whitespace-pre"
                          spellCheck={false}
                          autoComplete="off"
                          autoCorrect="off"
                        />
                      </div>
                    )}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>
        </div>
        {/* ── Unsaved-changes close warning ─────────────────────────────── */}
        <AnimatePresence>
          {showCloseWarning && (
            <motion.div
              className="absolute inset-0 z-20 flex items-center justify-center bg-black/40 backdrop-blur-sm rounded-2xl"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
            >
              <motion.div
                className="bg-background rounded-xl shadow-xl border border-border p-6 max-w-sm mx-4 w-full"
                initial={{ scale: 0.95, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.95, opacity: 0 }}
                transition={{ duration: 0.15 }}
              >
                <div className="flex items-start gap-3 mb-5">
                  <AlertTriangle className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
                  <div>
                    <h3 className="font-semibold text-foreground">Unsaved changes</h3>
                    <p className="text-sm text-muted-foreground mt-1">
                      You have unsaved edits in the Source tab. Close anyway and lose your changes?
                    </p>
                  </div>
                </div>
                <div className="flex justify-end gap-2">
                  <Button variant="outline" onClick={() => setShowCloseWarning(false)}>
                    Keep editing
                  </Button>
                  <Button
                    variant="destructive"
                    onClick={() => { setShowCloseWarning(false); onClose(); }}
                  >
                    Close anyway
                  </Button>
                </div>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.div>
    </div>
  );
}
