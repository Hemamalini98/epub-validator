import { motion } from 'framer-motion';
import { LucideIcon } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: { label: string; onClick: () => void };
}

export function EmptyState({ icon: Icon, title, description, action }: EmptyStateProps) {
  return (
    <motion.div
      className="flex flex-col items-center justify-center py-20 px-6 text-center"
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35 }}
    >
      <div className="w-16 h-16 rounded-2xl bg-muted flex items-center justify-center mb-5">
        <Icon className="w-8 h-8 text-muted-foreground" />
      </div>
      <h3 className="text-base font-semibold text-foreground mb-2">{title}</h3>
      <p className="text-sm text-muted-foreground max-w-xs leading-relaxed mb-6">{description}</p>
      {action && (
        <Button onClick={action.onClick} className="gap-2">
          {action.label}
        </Button>
      )}
    </motion.div>
  );
}
