import { useLocation, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  LayoutDashboard,
  FileCode2,
  ShieldCheck,
  BarChart3,
  Settings,
} from 'lucide-react';
import { cn } from '@/lib/utils';

interface NavItem {
  id: string;
  label: string;
  Icon: React.ComponentType<{ className?: string }>;
  href: string;
  implemented: boolean;
}

const NAV: NavItem[] = [
  { id: 'dashboard', label: 'Dashboard',       Icon: LayoutDashboard, href: '/',        implemented: true  },
  { id: 'xhtml',     label: 'XHTML Files',     Icon: FileCode2,       href: '/xhtml',   implemented: false },
  { id: 'rules',     label: 'Validation Rules',Icon: ShieldCheck,     href: '/rules',   implemented: false },
  { id: 'reports',   label: 'Reports',         Icon: BarChart3,       href: '/reports', implemented: false },
  { id: 'settings',  label: 'Settings',        Icon: Settings,        href: '/settings',implemented: false },
];

export function Sidebar() {
  const location = useLocation();
  const navigate = useNavigate();

  const isActive = (item: NavItem) => {
    if (item.href === '/') {
      return location.pathname === '/' || location.pathname.startsWith('/files');
    }
    return location.pathname.startsWith(item.href);
  };

  return (
    <aside className="w-60 h-screen bg-card border-r border-border flex flex-col flex-shrink-0 select-none">
      {/* Logo */}
      <div className="px-5 py-4 border-b border-border flex flex-col items-center gap-1.5">
        <img
          src="/logo.png"
          alt="S4Carlisle Publishing Services"
          className="w-full max-w-[160px] h-auto object-contain"
        />
        <p className="text-xs font-semibold text-muted-foreground tracking-wide uppercase">
          EPUB Validator
        </p>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-3 space-y-0.5 overflow-y-auto">
        {NAV.map(({ id, label, Icon, href, implemented }) => {
          const active = isActive({ id, label, Icon, href, implemented });
          return (
            <motion.button
              key={id}
              onClick={() => implemented && navigate(href)}
              disabled={!implemented}
              whileHover={implemented ? { x: 2 } : {}}
              whileTap={implemented ? { scale: 0.975 } : {}}
              aria-current={active ? 'page' : undefined}
              className={cn(
                'relative w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors duration-100 text-left',
                active
                  ? 'bg-primary/10 text-primary'
                  : implemented
                  ? 'text-muted-foreground hover:bg-muted hover:text-foreground'
                  : 'text-muted-foreground/50 cursor-not-allowed',
              )}
            >
              <Icon className={cn('w-4 h-4 flex-shrink-0', active ? 'text-primary' : '')} />
              <span className="flex-1 truncate">{label}</span>

              {active && (
                <motion.span
                  layoutId="nav-dot"
                  className="w-1.5 h-1.5 rounded-full bg-primary"
                />
              )}
            </motion.button>
          );
        })}
      </nav>


    </aside>
  );
}
