import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const badgeVariants = cva(
  'inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold border transition-colors',
  {
    variants: {
      variant: {
        default:     'bg-primary/10 text-primary border-primary/20',
        secondary:   'bg-secondary text-secondary-foreground border-transparent',
        outline:     'border-border text-foreground bg-transparent',
        success:     'bg-emerald-50 text-emerald-700 border-emerald-200',
        warning:     'bg-amber-50 text-amber-700 border-amber-200',
        destructive: 'bg-red-50 text-red-700 border-red-200',
        muted:       'bg-muted text-muted-foreground border-transparent',
      },
    },
    defaultVariants: { variant: 'default' },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant, className }))} {...props} />;
}
