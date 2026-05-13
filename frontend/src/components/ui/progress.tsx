import { motion } from 'framer-motion';
import { cn } from '@/lib/utils';

interface ProgressProps {
  value: number;
  className?: string;
  barClassName?: string;
}

export function Progress({ value, className, barClassName }: ProgressProps) {
  const pct = Math.min(100, Math.max(0, value));
  return (
    <div
      className={cn('relative h-2 w-full overflow-hidden rounded-full bg-muted', className)}
      role="progressbar"
      aria-valuenow={pct}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <motion.div
        className={cn('h-full rounded-full bg-primary', barClassName)}
        initial={{ width: '0%' }}
        animate={{ width: `${pct}%` }}
        transition={{ duration: 0.45, ease: 'easeOut' }}
      />
    </div>
  );
}
