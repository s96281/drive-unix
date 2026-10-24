import React, { useState, useEffect } from 'react';
import {
  RefreshCw,
  FolderPlus,
  UploadCloud,
  CheckSquare,
  Settings,
  CircleEllipsis,
  Edit3,
  FolderInput,
  Copy,
  Trash2,
  Link2,
  Download,
  XCircle,
  ArrowUpToLine,
  Columns,
} from 'lucide-react';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { useUiStore } from '@/stores/ui-store';

interface RightToolbarProps {
  isRootMountView: boolean;
  onRefresh: () => void;
  onMkdir: () => void;
  onUpload: () => void;
  onToggleDualPane: () => void;
  isDualPane: boolean;
}

export function RightToolbar({
  isRootMountView,
  onRefresh,
  onMkdir,
  onUpload,
  onToggleDualPane,
  isDualPane,
}: RightToolbarProps) {
  const [isOpen, setIsOpen] = useState<boolean>(() => {
    if (typeof window === 'undefined') return true;
    return localStorage.getItem('du.moreOpen') !== 'false';
  });
  const [showBackTop, setShowBackTop] = useState(false);

  const { checkboxOpen, toggleCheckboxOpen, setLocalSettingsOpen } = useUiStore();

  const toggleOpen = () => {
    const next = !isOpen;
    setIsOpen(next);
    localStorage.setItem('du.moreOpen', String(next));
  };

  useEffect(() => {
    const onScroll = () => {
      setShowBackTop(window.scrollY > 200);
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  const scrollToTop = () => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  return (
    <TooltipProvider delayDuration={120}>
      <div className="fixed right-4 bottom-5 z-30 flex flex-col items-center gap-2 select-none">
        {showBackTop && (
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                onClick={scrollToTop}
                className="h-9 w-9 rounded-xl bg-[var(--alist-card-bg)] shadow-lg border border-border/60 flex items-center justify-center text-[var(--alist-main)] hover:bg-[var(--alist-main)] hover:text-white active:scale-95 transition-all cursor-pointer"
                aria-label="回到頂部"
              >
                <ArrowUpToLine className="h-4 w-4" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="left">回到頂部</TooltipContent>
          </Tooltip>
        )}

        {!isOpen ? (
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                onClick={toggleOpen}
                className="h-10 w-10 rounded-xl bg-[var(--alist-card-bg)] shadow-lg border border-border/60 flex items-center justify-center text-[var(--alist-main)] hover:bg-[var(--alist-main)] hover:text-white active:scale-95 transition-all cursor-pointer"
                aria-label="展開工具欄"
              >
                <CircleEllipsis className="h-5 w-5" />
              </button>
            </TooltipTrigger>
            <TooltipContent side="left">展開工具欄 (More)</TooltipContent>
          </Tooltip>
        ) : (
          <div className="p-1.5 rounded-xl bg-[var(--alist-card-bg)] shadow-[0_10px_30px_-5px_rgba(0,0,0,0.28)] border border-border/60 flex flex-col items-center gap-1 animate-in fade-in zoom-in-95 duration-150">
            <RightIconButton icon={RefreshCw} label="重新整理 (Refresh)" onClick={onRefresh} />

            {!isRootMountView && (
              <>
                <RightIconButton icon={FolderPlus} label="新增資料夾 (Mkdir)" onClick={onMkdir} />
                <RightIconButton icon={UploadCloud} label="上傳檔案 (Upload)" onClick={onUpload} />
              </>
            )}

            <RightIconButton
              icon={Columns}
              label={isDualPane ? '切換為單欄瀏覽' : '開啟雙欄同步模式 (Dual Pane)'}
              active={isDualPane}
              onClick={onToggleDualPane}
            />

            {!isRootMountView && (
              <RightIconButton
                icon={CheckSquare}
                label={checkboxOpen ? '隱藏勾選框 (Toggle Checkbox)' : '顯示勾選框 (Toggle Checkbox)'}
                active={checkboxOpen}
                onClick={toggleCheckboxOpen}
              />
            )}

            <RightIconButton
              icon={Settings}
              label="本機設定 (Local Settings)"
              onClick={() => setLocalSettingsOpen(true)}
            />

            <div className="w-5 h-px bg-border/70 my-0.5" />

            <RightIconButton icon={CircleEllipsis} label="收合工具欄" onClick={toggleOpen} />
          </div>
        )}
      </div>
    </TooltipProvider>
  );
}

function RightIconButton({
  icon: Icon,
  label,
  onClick,
  active,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  onClick: () => void;
  active?: boolean;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={onClick}
          aria-label={label}
          className={`h-8 w-8 rounded-lg flex items-center justify-center transition-all active:scale-90 cursor-pointer ${
            active
              ? 'bg-[var(--alist-main)] text-white shadow-xs'
              : 'text-[var(--alist-main)] hover:bg-[var(--alist-main)] hover:text-white'
          }`}
        >
          <Icon className="h-[18px] w-[18px]" />
        </button>
      </TooltipTrigger>
      <TooltipContent side="left">{label}</TooltipContent>
    </Tooltip>
  );
}

interface CenterToolbarProps {
  selectedCount: number;
  canRename: boolean;
  onRename: () => void;
  onMove: () => void;
  onCopy: () => void;
  onDelete: () => void;
  onCopyLink: () => void;
  onDownload: () => void;
  onClearSelect: () => void;
}

export function CenterToolbar({
  selectedCount,
  canRename,
  onRename,
  onMove,
  onCopy,
  onDelete,
  onCopyLink,
  onDownload,
  onClearSelect,
}: CenterToolbarProps) {
  if (selectedCount === 0) return null;

  return (
    <TooltipProvider delayDuration={100}>
      <div className="fixed bottom-5 left-1/2 -translate-x-1/2 z-30 animate-in fade-in slide-in-from-bottom-3 duration-200">
        <div className="px-2.5 py-1.5 rounded-xl bg-white/90 dark:bg-[#141618]/90 backdrop-blur-md shadow-[0_10px_30px_-5px_rgba(0,0,0,0.35)] border border-border/60 flex items-center gap-1">
          {canRename && (
            <CenterIconButton
              icon={Edit3}
              label="重新命名 (Rename)"
              colorClass="text-amber-500"
              onClick={onRename}
            />
          )}
          <CenterIconButton
            icon={FolderInput}
            label="移動至... (Move)"
            colorClass="text-amber-500"
            onClick={onMove}
          />
          <CenterIconButton
            icon={Copy}
            label="複製 / 跨節點傳輸 (Copy)"
            colorClass="text-sky-500"
            onClick={onCopy}
          />
          <CenterIconButton
            icon={Trash2}
            label="刪除所選 (Delete)"
            colorClass="text-rose-500"
            onClick={onDelete}
          />
          <CenterIconButton
            icon={Link2}
            label="複製直鏈 (Copy Link)"
            colorClass="text-violet-500"
            onClick={onCopyLink}
          />
          <CenterIconButton
            icon={Download}
            label="下載 (Download)"
            colorClass="text-[var(--alist-main)]"
            onClick={onDownload}
          />
          <div className="w-px h-5 bg-border/80 mx-0.5" />
          <CenterIconButton
            icon={XCircle}
            label={`取消選擇 (${selectedCount} 項)`}
            colorClass="text-muted-foreground hover:text-foreground"
            onClick={onClearSelect}
          />
        </div>
      </div>
    </TooltipProvider>
  );
}

function CenterIconButton({
  icon: Icon,
  label,
  colorClass,
  onClick,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  colorClass: string;
  onClick: () => void;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          onClick={onClick}
          aria-label={label}
          className={`h-8 w-8 rounded-lg flex items-center justify-center hover:bg-[var(--alist-hover)] active:scale-90 transition-all cursor-pointer ${colorClass}`}
        >
          <Icon className="h-[18px] w-[18px]" />
        </button>
      </TooltipTrigger>
      <TooltipContent side="top">{label}</TooltipContent>
    </Tooltip>
  );
}
