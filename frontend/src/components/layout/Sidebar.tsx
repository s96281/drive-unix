import React, { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  Database,
  RefreshCw,
  Clock,
  Settings,
  Home,
  ChevronRight,
  ExternalLink,
  FolderKanban,
  UploadCloud,
  Sun,
  Moon,
  X,
  Users,
  BookOpen,
  Search,
  Archive,
  Info,
  Globe,
  Palette,
  Eye,
  Sliders,
  Cloud,
} from 'lucide-react';
import { useUiStore } from '@/stores/ui-store';
import { useTransferQueue } from '@/stores/transfer-queue';
import { zhTW } from '@/i18n/zh-TW';
import { cn } from '@/lib/utils';

interface SideMenuItemConfig {
  id: string;
  title: string;
  to?: string;
  matchPaths?: string[];
  icon: React.ComponentType<{ className?: string }>;
  children?: SideMenuItemConfig[];
  onClick?: () => void;
  external?: boolean;
}

interface SidebarProps {
  mobileOpen?: boolean;
  onCloseMobile?: () => void;
}

/**
 * AList Manage SideMenu (`src/pages/manage/SideMenu.tsx` & `src/pages/manage/sidemenu_items.tsx`)
 * Width: w-56 (224px), shadow-md, bg-white / dark:bg-[#1a1d1e], Hope UI $info4 / $info11 active states
 */
export function Sidebar({ mobileOpen = false, onCloseMobile }: SidebarProps) {
  const location = useLocation();
  const { theme, toggleTheme } = useUiStore();
  const { setDrawerOpen } = useTransferQueue();

  const [settingsGroupOpen, setSettingsGroupOpen] = useState(
    location.pathname.startsWith('/@manage/settings') || location.pathname.startsWith('/settings'),
  );
  const [tasksGroupOpen, setTasksGroupOpen] = useState(
    location.pathname.startsWith('/@manage/tasks') ||
      location.pathname.startsWith('/sync') ||
      location.pathname.startsWith('/schedule'),
  );

  useEffect(() => {
    if (location.pathname.startsWith('/@manage/settings') || location.pathname.startsWith('/settings')) {
      setSettingsGroupOpen(true);
    }
    if (
      location.pathname.startsWith('/@manage/tasks') ||
      location.pathname.startsWith('/sync') ||
      location.pathname.startsWith('/schedule')
    ) {
      setTasksGroupOpen(true);
    }
  }, [location.pathname]);

  const menuItems: SideMenuItemConfig[] = [
    {
      id: 'profile',
      title: '個人資料與狀態',
      to: '/@manage',
      matchPaths: ['/@manage', '/dashboard'],
      icon: LayoutDashboard,
    },
    {
      id: 'settings',
      title: '設定 (Settings)',
      icon: Settings,
      children: [
        {
          id: 'site',
          title: '站點 (Site)',
          to: '/@manage/settings/site',
          matchPaths: ['/@manage/settings/site', '/settings'],
          icon: Globe,
        },
        {
          id: 'style',
          title: '樣式 (Style)',
          to: '/@manage/settings/style',
          matchPaths: ['/@manage/settings/style'],
          icon: Palette,
        },
        {
          id: 'preview',
          title: '預覽 (Preview)',
          to: '/@manage/settings/preview',
          matchPaths: ['/@manage/settings/preview'],
          icon: Eye,
        },
        {
          id: 'global',
          title: '全域與流量 (Global)',
          to: '/@manage/settings/global',
          matchPaths: ['/@manage/settings/global'],
          icon: Sliders,
        },
        {
          id: 'other',
          title: '其他與雲端庫 (Other)',
          to: '/@manage/settings/other',
          matchPaths: ['/@manage/settings/other'],
          icon: Cloud,
        },
      ],
    },
    {
      id: 'tasks',
      title: '任務 (Tasks)',
      icon: FolderKanban,
      children: [
        {
          id: 'task-copy',
          title: '複製與跨端同步',
          to: '/@manage/tasks/copy',
          matchPaths: ['/@manage/tasks/copy', '/@manage/tasks', '/sync'],
          icon: RefreshCw,
        },
        {
          id: 'task-upload',
          title: '本機上傳佇列',
          to: '/@manage/tasks/upload',
          matchPaths: ['/@manage/tasks/upload'],
          icon: UploadCloud,
        },
        {
          id: 'task-schedules',
          title: '定時排程與守護',
          to: '/@manage/tasks/schedules',
          matchPaths: ['/@manage/tasks/schedules', '/@manage/schedules', '/schedule'],
          icon: Clock,
        },
      ],
    },
    {
      id: 'storages',
      title: '儲存 (Storages)',
      to: '/@manage/storages',
      matchPaths: ['/@manage/storages', '/remotes', '/@manage/storages/add'],
      icon: Database,
    },
    {
      id: 'users',
      title: '使用者 (Users)',
      to: '/@manage/users',
      matchPaths: ['/@manage/users'],
      icon: Users,
    },
    {
      id: 'metas',
      title: '元資料 (Metas)',
      to: '/@manage/metas',
      matchPaths: ['/@manage/metas'],
      icon: BookOpen,
    },
    {
      id: 'indexes',
      title: '搜尋索引 (Indexes)',
      to: '/@manage/indexes',
      matchPaths: ['/@manage/indexes'],
      icon: Search,
    },
    {
      id: 'backup-restore',
      title: '備份與還原',
      to: '/@manage/backup-restore',
      matchPaths: ['/@manage/backup-restore'],
      icon: Archive,
    },
    {
      id: 'about',
      title: '關於系統 (About)',
      to: '/@manage/about',
      matchPaths: ['/@manage/about'],
      icon: Info,
    },
    {
      id: 'home',
      title: '返回前台首頁 (Home)',
      to: '/',
      matchPaths: [],
      icon: Home,
    },
  ];

  const isPathActive = (item: SideMenuItemConfig) => {
    if (item.matchPaths && item.matchPaths.some((p) => location.pathname === p || location.pathname.startsWith(`${p}/`))) {
      return true;
    }
    return item.to === location.pathname;
  };

  const renderMenuContent = () => (
    <div className="flex flex-col justify-between h-full select-none">
      {/* SideMenu Navigation Stack */}
      <nav className="p-2.5 space-y-1 overflow-y-auto flex-1">
        {menuItems.map((item) => {
          const Icon = item.icon;

          if (item.children) {
            const isGroupOpen = item.id === 'settings' ? settingsGroupOpen : tasksGroupOpen;
            const toggleGroup = () => {
              if (item.id === 'settings') setSettingsGroupOpen(!settingsGroupOpen);
              else setTasksGroupOpen(!tasksGroupOpen);
            };
            const hasActiveChild = item.children.some((c) => isPathActive(c));

            return (
              <div key={item.id} className="w-full space-y-1">
                <button
                  type="button"
                  onClick={toggleGroup}
                  className={cn(
                    'w-full flex items-center justify-between px-2.5 py-2 rounded-md text-sm font-semibold cursor-pointer transition-colors',
                    hasActiveChild
                      ? 'text-[var(--alist-info11)]'
                      : 'text-muted-foreground hover:text-foreground hover:bg-[var(--alist-hover)]',
                  )}
                >
                  <div className="flex items-center gap-2.5">
                    <Icon className="h-[18px] w-[18px] shrink-0" />
                    <span>{item.title}</span>
                  </div>
                  <ChevronRight
                    className={cn(
                      'h-4 w-4 transition-transform duration-200',
                      isGroupOpen ? 'rotate-90' : '',
                    )}
                  />
                </button>

                {isGroupOpen && (
                  <div className="pl-3 space-y-0.5">
                    {item.children.map((child) => {
                      const ChildIcon = child.icon;
                      const active = isPathActive(child);

                      if (child.onClick) {
                        return (
                          <button
                            key={child.id}
                            type="button"
                            onClick={() => {
                              child.onClick?.();
                              onCloseMobile?.();
                            }}
                            className="w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-md text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-[var(--alist-hover)] cursor-pointer transition-colors"
                          >
                            <ChildIcon className="h-3.5 w-3.5 shrink-0" />
                            <span>{child.title}</span>
                          </button>
                        );
                      }

                      return (
                        <Link
                          key={child.id}
                          to={child.to || '/'}
                          onClick={onCloseMobile}
                          className={cn(
                            'w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer',
                            active
                              ? 'bg-[var(--alist-info4)] text-[var(--alist-info11)] font-semibold'
                              : 'text-muted-foreground hover:text-foreground hover:bg-[var(--alist-hover)]',
                          )}
                        >
                          <ChildIcon className="h-3.5 w-3.5 shrink-0" />
                          <span>{child.title}</span>
                        </Link>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          }

          const active = isPathActive(item);
          return (
            <Link
              key={item.id}
              to={item.to || '/'}
              onClick={onCloseMobile}
              className={cn(
                'w-full flex items-center gap-2.5 px-2.5 py-2 rounded-md text-sm font-semibold transition-colors cursor-pointer',
                active
                  ? 'bg-[var(--alist-info4)] text-[var(--alist-info11)]'
                  : 'text-muted-foreground hover:text-foreground hover:bg-[var(--alist-hover)]',
              )}
            >
              <Icon className="h-[18px] w-[18px] shrink-0" />
              <span>{item.title}</span>
            </Link>
          );
        })}
      </nav>

      {/* Bottom Center Controls (matches AList Manage SideMenu bottom Center HStack) */}
      <div className="p-3 border-t border-border/50 flex flex-col items-center gap-2">
        <div className="flex items-center justify-center gap-3 text-muted-foreground">
          <button
            type="button"
            onClick={toggleTheme}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium hover:bg-[var(--alist-hover)] hover:text-foreground transition-colors cursor-pointer"
          >
            {theme === 'dark' ? (
              <>
                <Sun className="h-4 w-4 text-amber-400" />
                <span>淺色模式</span>
              </>
            ) : (
              <>
                <Moon className="h-4 w-4 text-slate-600" />
                <span>深色模式</span>
              </>
            )}
          </button>
        </div>

        <a
          href="/legacy.html"
          className="flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[11px] text-muted-foreground hover:text-foreground hover:bg-[var(--alist-hover)] transition-colors"
        >
          <span>{zhTW.nav.legacy}</span>
          <ExternalLink className="h-3 w-3" />
        </a>
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop Permanent w-56 SideMenu */}
      <aside className="hidden sm:block w-56 h-full shrink-0 shadow-md bg-[var(--alist-manage-bg)] border-r border-border/50 overflow-y-auto z-20">
        {renderMenuContent()}
      </aside>

      {/* Mobile Drawer SideMenu */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 sm:hidden flex">
          <div
            className="fixed inset-0 bg-black/50 backdrop-blur-[1px]"
            onClick={onCloseMobile}
          />
          <aside className="relative z-10 w-64 h-full bg-[var(--alist-manage-bg)] shadow-2xl flex flex-col">
            <div className="flex items-center justify-between px-4 py-3 border-b border-border/60">
              <span className="font-bold text-base text-[var(--alist-main)]">drive-unix 管理</span>
              <button
                type="button"
                onClick={onCloseMobile}
                className="h-7 w-7 rounded-md flex items-center justify-center text-muted-foreground hover:text-foreground"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto">{renderMenuContent()}</div>
          </aside>
        </div>
      )}
    </>
  );
}
