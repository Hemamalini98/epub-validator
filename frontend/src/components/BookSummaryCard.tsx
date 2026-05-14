import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useQuery } from '@tanstack/react-query';
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  Loader2,
  FileText,
} from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { getBookSummary, type BookSummaryRow } from '@/lib/api';
import { cn } from '@/lib/utils';

type Status = 'PASS' | 'FAIL' | 'PARTIAL' | 'SKIP';

const statusStyles: Record<Status, { bg: string; text: string; ring: string; icon: any }> = {
  FAIL: {
    bg: 'bg-red-50 dark:bg-red-950/30',
    text: 'text-red-700 dark:text-red-300',
    ring: 'ring-1 ring-red-200 dark:ring-red-900/60',
    icon: XCircle,
  },
  PARTIAL: {
    bg: 'bg-amber-50 dark:bg-amber-950/30',
    text: 'text-amber-700 dark:text-amber-300',
    ring: 'ring-1 ring-amber-200 dark:ring-amber-900/60',
    icon: AlertTriangle,
  },
  PASS: {
    bg: 'bg-emerald-50 dark:bg-emerald-950/30',
    text: 'text-emerald-700 dark:text-emerald-300',
    ring: 'ring-1 ring-emerald-200 dark:ring-emerald-900/60',
    icon: CheckCircle2,
  },
  SKIP: {
    bg: 'bg-slate-50 dark:bg-slate-900/40',
    text: 'text-slate-600 dark:text-slate-400',
    ring: 'ring-1 ring-slate-200 dark:ring-slate-800',
    icon: FileText,
  },
};

function StatusBadge({ status }: { status: Status }) {
  const s = statusStyles[status];
  const Icon = s.icon;
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[11px] font-semibold tracking-wide uppercase',
        s.bg,
        s.text,
        s.ring,
      )}
    >
      <Icon className="w-3 h-3" />
      {status}
    </span>
  );
}

function SummaryRow({ row }: { row: BookSummaryRow }) {
  const status = row.status as Status;
  const showCount = status !== 'PASS' && row.count > 1;
  const files = row.files ?? [];
  const hasFiles = files.length > 0;
  const [open, setOpen] = useState(false);
  return (
    <div className="py-2.5 px-3 hover:bg-muted/40 rounded-md transition-colors">
      <div className="grid grid-cols-[200px_100px_1fr] gap-4 items-start">
        <div className="font-medium text-sm text-foreground">{row.check}</div>
        <div>
          <StatusBadge status={status} />
        </div>
        <div className="text-sm text-muted-foreground leading-relaxed">
          {showCount && (
            <span className="font-semibold text-foreground mr-1.5">{row.count}×</span>
          )}
          {row.detail || (status === 'PASS' ? 'No issues detected.' : '—')}
          {hasFiles && (
            <button
              onClick={() => setOpen((v) => !v)}
              className="ml-2 text-xs text-primary hover:underline inline-flex items-center gap-1"
            >
              {open ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
              {open ? 'Hide' : 'Show'} {files.length} chapter{files.length === 1 ? '' : 's'}
            </button>
          )}
        </div>
      </div>
      {hasFiles && open && (
        <ul className="mt-2 ml-[212px] space-y-0.5 text-xs font-mono text-muted-foreground">
          {files.map((f) => (
            <li key={f.file_path} className="flex items-baseline gap-2">
              <span className="tabular-nums text-foreground/80 min-w-[2.5rem]">{f.count}×</span>
              <span className="break-all">{f.file_path}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

interface Props {
  folderName: string;
}

export function BookSummaryCard({ folderName }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [statusFilter, setStatusFilter] = useState<Status | null>(null);

  const { data, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['summary', folderName],
    queryFn: () => getBookSummary(folderName),
    enabled: !!folderName,
    staleTime: 5 * 60_000,
    retry: 1,
  });

  if (isLoading) {
    return (
      <Card>
        <CardContent className="py-5 flex items-center gap-3 text-sm text-muted-foreground">
          <Loader2 className="w-4 h-4 animate-spin" />
          Building book summary… (first run takes ~60 s for a large PDF; subsequent runs are instant)
        </CardContent>
      </Card>
    );
  }

  if (isError || !data) {
    return (
      <Card>
        <CardContent className="py-5 flex items-center justify-between text-sm">
          <span className="text-muted-foreground">Could not load book summary.</span>
          <Button size="sm" variant="outline" onClick={() => refetch()}>
            <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> Retry
          </Button>
        </CardContent>
      </Card>
    );
  }

  const { totals, rows } = data;
  const failingRows = rows.filter((r) => r.status === 'FAIL' || r.status === 'PARTIAL');
  const passingRows = rows.filter((r) => r.status === 'PASS');
  const filteredRows = statusFilter ? rows.filter((r) => r.status === statusFilter) : null;
  const defaultRows = expanded ? rows : failingRows.slice(0, 6);
  const visibleRows = filteredRows ?? defaultRows;
  const hiddenCount = rows.length - visibleRows.length;
  const toggleFilter = (s: Status) => setStatusFilter((prev) => (prev === s ? null : s));

  return (
    <Card>
      <CardContent className="pt-5 pb-4">
        {/* Header strip with totals */}
        <div className="flex items-center justify-between flex-wrap gap-3 mb-4 pb-3 border-b border-border">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-foreground">Book Summary</span>
            <span className="text-xs text-muted-foreground">
              (PDF ↔ EPUB structural + style checks)
            </span>
          </div>
          <div className="flex items-center gap-2">
            <TotalPill
              label="PASS"
              count={totals.PASS}
              status="PASS"
              isActive={statusFilter === 'PASS'}
              onClick={() => toggleFilter('PASS')}
            />
            <TotalPill
              label="PARTIAL"
              count={totals.PARTIAL}
              status="PARTIAL"
              isActive={statusFilter === 'PARTIAL'}
              onClick={() => toggleFilter('PARTIAL')}
            />
            <TotalPill
              label="FAIL"
              count={totals.FAIL}
              status="FAIL"
              isActive={statusFilter === 'FAIL'}
              onClick={() => toggleFilter('FAIL')}
            />
            <Button
              size="icon"
              variant="ghost"
              className="h-7 w-7"
              onClick={() => refetch()}
              disabled={isFetching}
              title="Refresh summary"
            >
              {isFetching ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <RefreshCw className="w-3.5 h-3.5" />
              )}
            </Button>
          </div>
        </div>

        {/* Column headers */}
        <div className="grid grid-cols-[200px_100px_1fr] gap-4 px-3 pb-2 mb-1 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground border-b border-border/50">
          <div>Check</div>
          <div>Status</div>
          <div>Result</div>
        </div>

        {/* Active filter indicator */}
        {statusFilter && (
          <div className="flex items-center justify-between text-xs text-muted-foreground px-3 pb-2">
            <span>
              Showing <span className="font-medium text-foreground">{visibleRows.length}</span>{' '}
              {statusFilter.toLowerCase()} check{visibleRows.length === 1 ? '' : 's'}
            </span>
            <button
              onClick={() => setStatusFilter(null)}
              className="text-primary hover:underline"
            >
              Clear filter
            </button>
          </div>
        )}

        {/* Rows */}
        <AnimatePresence initial={false}>
          <motion.div layout className="divide-y divide-border/40">
            {visibleRows.length === 0 && (
              <div className="py-6 text-center text-sm text-muted-foreground">
                {statusFilter
                  ? `No ${statusFilter.toLowerCase()} checks.`
                  : 'No failures or warnings detected.'}
              </div>
            )}
            {visibleRows.map((row) => (
              <motion.div
                key={row.check}
                layout
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -4 }}
                transition={{ duration: 0.15 }}
              >
                <SummaryRow row={row} />
              </motion.div>
            ))}
          </motion.div>
        </AnimatePresence>

        {/* Toggle (only when no filter is active) */}
        {!statusFilter && (hiddenCount > 0 || expanded) && (
          <div className="pt-3 mt-1 border-t border-border/50">
            <button
              onClick={() => setExpanded((v) => !v)}
              className="flex items-center gap-1.5 text-xs text-primary hover:underline w-full justify-center py-1"
            >
              {expanded ? (
                <>
                  <ChevronUp className="w-3.5 h-3.5" />
                  Hide passing checks ({passingRows.length})
                </>
              ) : (
                <>
                  <ChevronDown className="w-3.5 h-3.5" />
                  Show all {rows.length} checks ({passingRows.length} passing hidden)
                </>
              )}
            </button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function TotalPill({
  label,
  count,
  status,
  isActive,
  onClick,
}: {
  label: string;
  count: number;
  status: Status;
  isActive?: boolean;
  onClick?: () => void;
}) {
  const s = statusStyles[status];
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={!onClick || count === 0}
      aria-pressed={!!isActive}
      className={cn(
        'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] font-semibold transition-all',
        s.bg,
        s.text,
        s.ring,
        onClick && count > 0 && 'cursor-pointer hover:brightness-95 dark:hover:brightness-110',
        isActive && 'ring-2 ring-offset-1 ring-offset-background',
        (!onClick || count === 0) && 'cursor-default opacity-70',
      )}
    >
      <span className="tabular-nums">{count}</span>
      <span className="opacity-75">{label}</span>
    </button>
  );
}
