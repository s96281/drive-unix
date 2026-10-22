import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Server,
  FolderGit2,
  RefreshCw,
  Clock,
  Settings,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Layers,
} from 'lucide-react';
import { useUiStore } from '@/stores/ui-store';
import { zhTW } from '@/i18n/zh-TW';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { ConnectionIndicator } from './ConnectionIndicator';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

export function Sidebar() {
  const { sidebarCollapsed, toggleSidebar } = useUiStore();

  const navItems = [
    { to: '/', label: zhTW.nav.dashboard, icon: LayoutDashboard },
    { to: '/remotes', label: zhTW.nav.remotes, icon: Server },
    { to: '/files', label: zhTW.nav.files, icon: FolderGit2 },
    { to: '/sync', label: zhTW.nav.sync, icon: RefreshCw },
    { to: '/schedule', label: zhTW.nav.schedule, icon: Clock },
    { to: '/settings', label: zhTW.nav.settings, icon: Settings },
  ];

  return (
    <aside
      className={cn(
        'relative flex flex-col border-r border-border bg-card/50 backdrop-blur-md transition-all duration-300 ease-in-out shrink-0 select-none z-30',
        sidebarCollapsed ? 'w-18' : 'w-64',
      )}
    >
      {/* Brand Header */}
      <div className="flex h-16 items-center px-4 border-b border-border/80 justify-between">
        <div className="flex items-center gap-3 overflow-hidden">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-primary/10 border border-primary/20 text-primary shadow-xs">
            <Layers className="h-5 w-5" />
          </div>
          {!sidebarCollapsed && (
            <div className="flex flex-col truncate">
              <span className="font-bold text-sm tracking-tight text-foreground">{zhTW.app.title}</span>
              <span className="text-[10px] text-muted-foreground truncate">{zhTW.app.subtitle}</span>
            </div>
          )}
        </div>

        <Button
          variant="ghost"
          size="iconSm"
          onClick={toggleSidebar}
          className="text-muted-foreground hover:text-foreground hidden md:flex"
        >
          {sidebarCollapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </Button>
      </div>

      {/* Nav List */}
      <nav className="flex-1 space-y-1.5 p-3 overflow-y-auto">
        <TooltipProvider delayDuration={150}>
          {navItems.map((item) => {
            const Icon = item.icon;
            const linkContent = (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  cn(
                    'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-all group cursor-pointer',
                    isActive
                      ? 'bg-primary/15 text-primary border border-primary/20 font-semibold shadow-xs'
                      : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground',
                    sidebarCollapsed && 'justify-center px-0',
                  )
                }
              >
                <Icon className="h-4 w-4 shrink-0 transition-transform group-hover:scale-110" />
                {!sidebarCollapsed && <span>{item.label}</span>}
              </NavLink>
            );

            if (sidebarCollapsed) {
              return (
                <Tooltip key={item.to}>
                  <TooltipTrigger asChild>{linkContent}</TooltipTrigger>
                  <TooltipContent side="right" className="font-medium">
                    {item.label}
                  </TooltipContent>
                </Tooltip>
              );
            }

            return linkContent;
          })}
        </TooltipProvider>
      </nav>

      {/* Footer Info */}
      <div className="p-3 border-t border-border/80 flex flex-col gap-2">
        <div className={cn('flex items-center', sidebarCollapsed ? 'justify-center' : 'justify-between')}>
          {!sidebarCollapsed ? (
            <ConnectionIndicator />
          ) : (
            <div className="flex justify-center w-full py-1">
              <ConnectionIndicator />
            </div>
          )}
        </div>

        {!sidebarCollapsed && (
          <a
            href="/legacy.html"
            className="flex items-center justify-between px-2.5 py-1.5 rounded-md text-xs text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
          >
            <span>{zhTW.nav.legacy}</span>
            <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
    </aside>
  );
}
