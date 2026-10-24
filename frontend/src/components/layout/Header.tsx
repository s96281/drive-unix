import React, { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import {
  Search,
  List,
  LayoutGrid,
  Image as ImageIcon,
  UploadCloud,
  Sparkles,
  Database,
  Menu,
  LogOut,
  Layers,
  Columns,
  Settings2,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ThemeToggle } from './ThemeToggle';
import { ConnectionIndicator } from './ConnectionIndicator';
import { isDemoMode, setDemoMode } from '@/api';
import { useTransferQueue } from '@/stores/transfer-queue';
import { useUiStore, type DisplayLayout } from '@/stores/ui-store';
import { Badge } from '@/components/ui/badge';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@radix-ui/react-dropdown-menu';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

interface HeaderProps {
  mode: 'home' | 'manage';
  onOpenMobileMenu?: () => void;
}

export function Header({ mode, onOpenMobileMenu }: HeaderProps) {
  if (mode === 'home') {
    return <HomeHeader />;
  }
  return <ManageHeader onOpenMobileMenu={onOpenMobileMenu} />;
}

/**
 * AList Home Header (`src/pages/home/header/Header.tsx` & `layout.tsx`)
 * Centered container with Logo on left, Search trigger pill (Ctrl+K) + Layout Switcher on right
 */
function HomeHeader() {
  const navigate = useNavigate();
  const {
    displayLayout,
    setDisplayLayout,
    viewMode,
    setViewMode,
    headerStickyMode,
    setSearchModalOpen,
  } = useUiStore();
  const { jobs, setDrawerOpen } = useTransferQueue();
  const activeUploads = jobs.filter((j) => j.status === 'uploading' || j.status === 'pending').length;

  const isSticky = headerStickyMode === 'sticky';
  const isMac = typeof navigator !== 'undefined' && /Mac|iPod|iPhone|iPad/.test(navigator.platform);

  const LayoutIcon =
    displayLayout === 'list' ? List : displayLayout === 'grid' ? LayoutGrid : ImageIcon;

  return (
    <header
      className={`w-full bg-background flex justify-center transition-all ${
        isSticky ? 'sticky top-0 z-30 backdrop-blur-md bg-background/90' : ''
      }`}
    >
      <div
        className={`w-full ${
          viewMode === 'dual' ? 'max-w-[1440px]' : 'max-w-[980px]'
        } px-[calc(2%+0.5rem)] py-2.5 flex items-center justify-between gap-3`}
      >
        {/* Header Left: AList Brand Logo & Title */}
        <div className="flex items-center gap-3 h-[44px]">
          <Link
            to="/"
            className="flex items-center gap-2.5 group focus:outline-none"
            title="回到虛擬根目錄首頁"
          >
            <div className="h-9 w-9 rounded-xl bg-[var(--alist-main-subtle)] text-[var(--alist-main)] flex items-center justify-center shadow-xs group-hover:scale-105 transition-transform">
              <Layers className="h-5 w-5" />
            </div>
            <div className="flex flex-col">
              <span className="font-bold text-base tracking-tight text-foreground leading-tight">
                drive-unix
              </span>
              <span className="text-[10px] text-muted-foreground hidden sm:inline">
                AList Multi-Cloud Explorer
              </span>
            </div>
          </Link>

          {/* Subtle Demo Mode Pill */}
          <TooltipProvider delayDuration={150}>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  onClick={() => setDemoMode(!isDemoMode)}
                  className="hidden md:inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium cursor-pointer transition-colors bg-[var(--alist-main-subtle)] text-[var(--alist-main)] hover:bg-[var(--alist-main-subtle-hover)]"
                >
                  {isDemoMode ? <Sparkles className="h-3 w-3" /> : <Database className="h-3 w-3" />}
                  <span>{isDemoMode ? 'Demo' : 'Live'}</span>
                </button>
              </TooltipTrigger>
              <TooltipContent side="bottom">
                {isDemoMode ? '目前為前端模擬資料模式 (點擊切換)' : '目前連線至真實後端 API'}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>

        {/* Header Right: Search Box (Ctrl+K) + Layout Switcher + Manage Link */}
        <div className="flex items-center gap-2">
          {/* AList Search Trigger Pill */}
          <button
            type="button"
            onClick={() => setSearchModalOpen(true)}
            className="w-32 sm:w-36 px-2.5 py-1.5 rounded-lg flex items-center justify-between cursor-pointer transition-colors bg-[var(--alist-main-subtle)] hover:bg-[var(--alist-main-subtle-hover)] text-[var(--alist-main)] active:scale-95"
            title="搜尋檔案与節點 (Ctrl+K)"
          >
            <Search className="h-4 w-4 shrink-0" />
            <div className="flex items-center gap-1 text-[11px] font-mono">
              <kbd className="px-1.5 py-0.5 rounded bg-background/70 text-foreground/80 shadow-2xs text-[10px]">
                {isMac ? 'Cmd' : 'Ctrl'}
              </kbd>
              <kbd className="px-1.5 py-0.5 rounded bg-background/70 text-foreground/80 shadow-2xs text-[10px]">
                K
              </kbd>
            </div>
          </button>

          {/* Active Upload Queue Badge Button (if jobs exist) */}
          {jobs.length > 0 && (
            <button
              type="button"
              onClick={() => setDrawerOpen(true)}
              className="h-9 px-2.5 rounded-lg flex items-center gap-1.5 bg-[var(--alist-main-subtle)] hover:bg-[var(--alist-main-subtle-hover)] text-[var(--alist-main)] text-xs font-medium cursor-pointer active:scale-95 transition-all"
              title="檢視傳輸佇列"
            >
              <UploadCloud className="h-4 w-4" />
              {activeUploads > 0 && (
                <span className="px-1.5 py-0.2 rounded-full bg-[var(--alist-main)] text-white text-[10px]">
                  {activeUploads}
                </span>
              )}
            </button>
          )}

          {/* AList Layout Menu Switcher (`src/pages/home/header/layout.tsx`) */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label="切換視圖佈局"
                className="h-9 w-9 rounded-lg flex items-center justify-center cursor-pointer transition-all bg-[var(--alist-main-subtle)] hover:bg-[var(--alist-main-subtle-hover)] text-[var(--alist-main)] active:scale-95 focus:outline-none"
              >
                <LayoutIcon className="h-4 w-4" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              sideOffset={6}
              className="z-50 min-w-[160px] rounded-xl bg-[var(--alist-card-bg)] p-1.5 shadow-xl border border-border/60 text-xs space-y-0.5 animate-in fade-in zoom-in-95 duration-150"
            >
              {(
                [
                  { id: 'list', label: '列表視圖 (List)', icon: List },
                  { id: 'grid', label: '網格視圖 (Grid)', icon: LayoutGrid },
                  { id: 'image', label: '圖片視圖 (Image)', icon: ImageIcon },
                ] as const
              ).map((item) => {
                const Icon = item.icon;
                const active = displayLayout === item.id;
                return (
                  <DropdownMenuItem
                    key={item.id}
                    onSelect={() => setDisplayLayout(item.id as DisplayLayout)}
                    className={`flex items-center gap-2.5 px-2.5 py-2 rounded-lg cursor-pointer outline-none transition-colors ${
                      active
                        ? 'bg-[var(--alist-info4)] text-[var(--alist-info11)] font-semibold'
                        : 'text-foreground hover:bg-[var(--alist-hover)]'
                    }`}
                  >
                    <Icon className="h-4 w-4" />
                    <span>{item.label}</span>
                  </DropdownMenuItem>
                );
              })}

              <DropdownMenuSeparator className="h-px bg-border/60 my-1" />

              <DropdownMenuItem
                onSelect={() => setViewMode(viewMode === 'dual' ? 'single' : 'dual')}
                className={`flex items-center gap-2.5 px-2.5 py-2 rounded-lg cursor-pointer outline-none transition-colors ${
                  viewMode === 'dual'
                    ? 'bg-[var(--alist-info4)] text-[var(--alist-info11)] font-semibold'
                    : 'text-foreground hover:bg-[var(--alist-hover)]'
                }`}
              >
                <Columns className="h-4 w-4" />
                <span>{viewMode === 'dual' ? '關閉雙欄對比' : '開啟雙欄對比 (Dual)'}</span>
              </DropdownMenuItem>

              <DropdownMenuItem
                onSelect={() => navigate('/@manage')}
                className="flex items-center gap-2.5 px-2.5 py-2 rounded-lg cursor-pointer outline-none text-foreground hover:bg-[var(--alist-hover)] transition-colors"
              >
                <Settings2 className="h-4 w-4 text-[var(--alist-main)]" />
                <span>進入後台管理 (@manage)</span>
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>
  );
}

/**
 * AList Manage Header (`src/pages/manage/Header.tsx`)
 * Sticky 64px top bar with shadow-md, $info9 title on left, quick actions + Exit to Home on right
 */
function ManageHeader({ onOpenMobileMenu }: { onOpenMobileMenu?: () => void }) {
  const navigate = useNavigate();
  const { jobs, setDrawerOpen } = useTransferQueue();
  const activeUploads = jobs.filter((j) => j.status === 'uploading' || j.status === 'pending').length;

  return (
    <header className="sticky top-0 left-0 right-0 z-30 h-16 shrink-0 shadow-md px-4 bg-[var(--alist-manage-bg)] border-b border-border/50 flex items-center justify-between">
      {/* Left: Hamburger (mobile) + Manage Title ($info9) */}
      <div className="flex items-center gap-2.5">
        <Button
          variant="subtle"
          size="iconSm"
          className="sm:hidden h-8 w-8"
          onClick={onOpenMobileMenu}
          aria-label="開啟選單"
        >
          <Menu className="h-4 w-4" />
        </Button>

        <div
          onClick={() => navigate('/@manage')}
          className="flex items-center gap-2.5 cursor-pointer group"
        >
          <div className="h-8 w-8 rounded-lg bg-[var(--alist-main-subtle)] text-[var(--alist-main)] flex items-center justify-center">
            <Layers className="h-4 w-4" />
          </div>
          <h1 className="text-xl font-bold text-[var(--alist-main)] tracking-tight group-hover:opacity-90 transition-opacity">
            drive-unix 管理
          </h1>
        </div>
      </div>

      {/* Right: Connection Status, Demo Mode, Upload Queue, Return to Home (IoExit style) */}
      <div className="flex items-center gap-2">
        <div className="hidden md:block">
          <ConnectionIndicator />
        </div>

        <TooltipProvider delayDuration={150}>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                onClick={() => setDemoMode(!isDemoMode)}
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium cursor-pointer transition-colors ${
                  isDemoMode
                    ? 'bg-amber-500/15 text-amber-500 hover:bg-amber-500/25'
                    : 'bg-[var(--alist-main-subtle)] text-[var(--alist-main)] hover:bg-[var(--alist-main-subtle-hover)]'
                }`}
              >
                {isDemoMode ? <Sparkles className="h-3.5 w-3.5" /> : <Database className="h-3.5 w-3.5" />}
                <span className="hidden sm:inline">{isDemoMode ? 'Demo 模式' : '正式環境'}</span>
              </button>
            </TooltipTrigger>
            <TooltipContent side="bottom">
              {isDemoMode ? '點擊切換至真實後端 API' : '點擊切換為純前端模擬模式'}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>

        <Button
          variant="subtle"
          size="sm"
          onClick={() => setDrawerOpen(true)}
          className="gap-1.5 h-8"
          title="檢視本機上傳佇列"
        >
          <UploadCloud className="h-4 w-4" />
          <span className="hidden sm:inline text-xs">傳輸佇列</span>
          {activeUploads > 0 && (
            <Badge variant="default" className="h-4 min-w-4 px-1 text-[10px] bg-[var(--alist-main)] text-white">
              {activeUploads}
            </Badge>
          )}
        </Button>

        <ThemeToggle />

        <TooltipProvider delayDuration={150}>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="subtle"
                size="iconSm"
                className="h-8 w-8"
                onClick={() => navigate('/')}
                aria-label="返回前台首頁"
              >
                <LogOut className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom">返回前台檔案瀏覽器 (/)</TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>
    </header>
  );
}
