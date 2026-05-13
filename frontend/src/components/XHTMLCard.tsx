import { motion } from 'framer-motion';
import { FileCode2, Eye, Play, Clock, CheckCircle2, AlertTriangle, XCircle, Loader2 } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { XHTMLFile, XHTMLFileStatus } from '@/types';

// ─── Status badge ─────────────────────────────────────────────────────────────

const STATUS_CONFIG: Record<
  XHTMLFileStatus,
  { label: string; Icon: React.ComponentType<{ className?: string }>; className: string }
> = {
  pending: {
    label: 'PENDING',
    Icon: Clock,
    className: 'bg-slate-100 text-slate-500 border-slate-200',
  },
  passed: {
    label: 'PASSED',
    Icon: CheckCircle2,
    className: 'bg-emerald-50 text-emerald-600 border-emerald-200',
  },
  warning: {
    label: 'WARNING',
    Icon: AlertTriangle,
    className: 'bg-amber-50 text-amber-600 border-amber-200',
  },
  failed: {
    label: 'FAILED',
    Icon: XCircle,
    className: 'bg-red-50 text-red-600 border-red-200',
  },
};

function StatusBadge({ status }: { status: XHTMLFileStatus }) {
  const { label, Icon, className } = STATUS_CONFIG[status];
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold border',
        className,
      )}
    >
      <Icon className="w-2.5 h-2.5" />
      {label}
    </span>
  );
}

// ─── Status body text ────────────────────────────────────────────────────────

function statusText(
  status: XHTMLFileStatus,
  errors: number,
  warnings: number,
): string {
  if (status === 'pending')  return 'Awaiting validation';
  if (status === 'passed')   return 'No issues found';
  if (status === 'failed')   return `${errors} error${errors !== 1 ? 's' : ''}`;
  return `${warnings} warning${warnings !== 1 ? 's' : ''}`;
}

// ─── Card ─────────────────────────────────────────────────────────────────────

export const xhtmlCardVariants = {
  hidden: { opacity: 0, y: 16 },
  show:   { opacity: 1, y: 0, transition: { duration: 0.25, ease: 'easeOut' } },
};

interface XHTMLCardProps {
  file: XHTMLFile;
  status: XHTMLFileStatus;
  errors?: number;
  warnings?: number;
  isValidating?: boolean;
  onValidate: () => void;
  onPreview: () => void;
  onOpen: () => void;
  index?: number;
}

export function XHTMLCard({
  file,
  status,
  errors = 0,
  warnings = 0,
  isValidating = false,
  onValidate,
  onPreview,
  onOpen,
}: XHTMLCardProps) {
  const filePath = file.path ?? file.relative_path ?? '';

  return (
    <motion.div variants={xhtmlCardVariants} whileHover={{ y: -2, transition: { duration: 0.12 } }}>
      <Card className="hover:shadow-md transition-shadow duration-200 h-full flex flex-col">
        <CardContent className="pt-4 flex-1 flex flex-col">
          {/* Icon row + status badge */}
          <div className="flex items-start justify-between mb-3">
            <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
              <FileCode2 className="w-5 h-5 text-primary" />
            </div>
            <StatusBadge status={status} />
          </div>

          {/* Filename — clickable to open result tab */}
          <p
            onClick={onOpen}
            className="text-sm font-semibold text-foreground truncate mb-0.5 cursor-pointer hover:text-primary transition-colors"
            title={file.file_name}
          >
            {file.file_name}
          </p>

          {/* Path */}
          <p
            className="text-[11px] text-muted-foreground truncate font-mono mb-3"
            title={filePath}
          >
            {filePath}
          </p>

          {/* Status text — also clickable */}
          <p
            onClick={onOpen}
            className={cn(
              'text-xs mb-4 cursor-pointer',
              status === 'failed'  ? 'text-red-500'     :
              status === 'warning' ? 'text-amber-500'   :
              status === 'passed'  ? 'text-emerald-600' :
              'text-muted-foreground',
            )}
          >
            {statusText(status, errors, warnings)}
          </p>

          {/* Buttons */}
          <div className="flex gap-2 mt-auto">
            <Button
              variant="outline"
              size="sm"
              className="flex-1 gap-1.5 text-xs"
              onClick={onPreview}
              aria-label={`Preview ${file.file_name}`}
            >
              <Eye className="w-3.5 h-3.5" />
              Preview
            </Button>
            <Button
              size="sm"
              className="flex-1 gap-1.5 text-xs"
              onClick={onValidate}
              disabled={isValidating}
              aria-label={`Validate ${file.file_name}`}
            >
              {isValidating ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Play className="w-3.5 h-3.5" />
              )}
              {isValidating ? 'Validating…' : 'Validate'}
            </Button>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
