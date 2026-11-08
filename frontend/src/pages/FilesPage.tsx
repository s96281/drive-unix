import React, { useState, useRef, useMemo, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Folder,
  FolderPlus,
  Upload,
  RefreshCw,
  Trash2,
  ArrowRightLeft,
  Columns,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
  Download,
  Eye,
  Edit,
  ArrowUp,
  ArrowDown,
  HardDrive,
  Link2,
  FolderInput,
  Copy,
  Home,
  BookOpen,
} from 'lucide-react';
import { api } from '@/api';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { formatBytes, formatRelativeTime } from '@/lib/format';
import { downloadUrl, rawUrl, getFileKind } from '@/lib/file-types';
import { useTransferQueueStore } from '@/stores/transfer-queue';
import { useUiStore } from '@/stores/ui-store';
import { FilePreviewDialog } from '@/components/files/FilePreviewDialog';
import { FileTypeIcon } from '@/components/files/FileTypeIcon';
import { FileOpsDialog, type FileOpType } from '@/components/files/FileOpsDialog';
import { RightToolbar, CenterToolbar } from '@/components/files/FloatingToolbars';
import { FileSearchModal } from '@/components/files/FileSearchModal';
import { toast } from 'sonner';
import type { RemoteListResponse, FsListResponse, FsItem, RemoteItem, SettingsResponse, MetaRule } from '@/api/types';

type SortField = 'name' | 'size' | 'modified';

export function FilesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { viewMode, setViewMode } = useUiStore();
  const isDualPane = viewMode === 'dual';

  const { data: remotesData, isLoading: remotesLoading, refetch: refetchRemotes } = useQuery<RemoteListResponse>({
    queryKey: ['remotes'],
    queryFn: () => api.request('GET', '/remotes'),
  });

  const remotes = remotesData?.remotes || [];
  const defaultRemote = remotesData?.default_remote || remotes[0]?.name || 'gdrive';

  const queryRemote = searchParams.get('remote');
  const queryPath = searchParams.get('path') || '/';

  const handleSelectRemoteFromRoot = (remoteName: string, path = '/') => {
    setSearchParams({ remote: remoteName, path });
  };

  const handleGoRoot = () => {
    setSearchParams({});
  };

  return (
    <div
      className={`w-full ${
        isDualPane ? 'max-w-[1440px]' : 'max-w-[980px]'
      } px-[2%] py-2 mt-1 min-h-[80vh] flex flex-col gap-4 transition-all`}
    >
      <div className={`grid gap-5 flex-1 min-h-0 ${isDualPane ? 'grid-cols-1 lg:grid-cols-2' : 'grid-cols-1'}`}>
        <FileBrowserPane
          paneId="pane-left"
          isPrimaryPane
          initialRemote={queryRemote}
          initialPath={queryPath}
          defaultRemote={defaultRemote}
          availableRemotes={remotes}
          remotesLoading={remotesLoading}
          onRefetchRemotes={() => void refetchRemotes()}
          onSyncUrl={(rem, p) => {
            if (!rem) {
              handleGoRoot();
            } else {
              setSearchParams({ remote: rem, path: p });
            }
          }}
          isDualPane={isDualPane}
          onToggleDualPane={() => setViewMode(isDualPane ? 'single' : 'dual')}
        />

        {isDualPane && (
          <FileBrowserPane
            paneId="pane-right"
            isPrimaryPane={false}
            initialRemote={remotes[1]?.name || defaultRemote}
            initialPath="/"
            defaultRemote={remotes[1]?.name || defaultRemote}
            availableRemotes={remotes}
            remotesLoading={remotesLoading}
            onRefetchRemotes={() => void refetchRemotes()}
            isDualPane={isDualPane}
            onToggleDualPane={() => setViewMode('single')}
          />
        )}
      </div>
    </div>
  );
}

interface FileBrowserPaneProps {
  paneId: string;
  isPrimaryPane: boolean;
  initialRemote: string | null;
  initialPath: string;
  defaultRemote: string;
  availableRemotes: RemoteItem[];
  remotesLoading: boolean;
  onRefetchRemotes: () => void;
  onSyncUrl?: (remote: string | null, path: string) => void;
  isDualPane: boolean;
  onToggleDualPane: () => void;
}

function FileBrowserPane({
  isPrimaryPane,
  initialRemote,
  initialPath,
  availableRemotes,
  remotesLoading,
  onRefetchRemotes,
  onSyncUrl,
  isDualPane,
  onToggleDualPane,
}: FileBrowserPaneProps) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const enqueueUpload = useTransferQueueStore((s) => s.enqueue);

  const {
    displayLayout,
    checkboxOpen,
    gridItemSize,
    filenameOverflow,
    headerStickyMode,
    readmeAutoRender,
  } = useUiStore();

  // null currentRemote means we are at the AList Virtual Root (`🏠 首頁`) showing all mounted Remotes
  const [currentRemote, setCurrentRemote] = useState<string | null>(initialRemote);
  const [currentPath, setCurrentPath] = useState<string>(initialPath || '/');
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());
  const [isDragOver, setIsDragOver] = useState(false);

  // Sorting state (matches AList ListTitle sortCallback)
  const [sortBy, setSortBy] = useState<SortField>('name');
  const [sortReverse, setSortReverse] = useState<boolean>(false);

  // Pagination state
  const [page, setPage] = useState<number>(1);
  const [pageSize, setPageSize] = useState<number>(50);

  // Modals & Context Menu state
  const [previewItem, setPreviewItem] = useState<FsItem | null>(null);
  const [opsType, setOpsType] = useState<FileOpType | null>(null);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; item: FsItem } | null>(null);

  // Sync with URL query changes on primary pane
  useEffect(() => {
    if (isPrimaryPane) {
      setCurrentRemote(initialRemote);
      setCurrentPath(initialPath || '/');
      setSelectedPaths(new Set());
      setPage(1);
    }
  }, [isPrimaryPane, initialRemote, initialPath]);

  // Close context menu on global click
  useEffect(() => {
    if (!contextMenu) return;
    const close = () => setContextMenu(null);
    window.addEventListener('click', close);
    return () => window.removeEventListener('click', close);
  }, [contextMenu]);

  const isRootMountView = !currentRemote;
  const offset = pageSize > 0 ? (page - 1) * pageSize : 0;
  const limit = pageSize > 0 ? pageSize : undefined;

  const { data: listData, isLoading, isFetching, isPlaceholderData, refetch } = useQuery<FsListResponse>({
    queryKey: ['fs-list', currentRemote, currentPath, page, pageSize],
    queryFn: () =>
      api.request('GET', `/fs/${currentRemote}/ls`, {
        query: {
          path: currentPath,
          offset,
          ...(limit !== undefined ? { limit } : {}),
        },
      }),
    enabled: !!currentRemote,
    placeholderData: (previousData, previousQuery) => {
      const prevKey = previousQuery?.queryKey;
      if (prevKey && prevKey[1] === currentRemote && prevKey[2] === currentPath) {
        return previousData;
      }
      return undefined;
    },
  });

  // Load site settings & metas
  const { data: settingsData } = useQuery<SettingsResponse>({
    queryKey: ['settings'],
    queryFn: () => api.request('GET', '/settings'),
    staleTime: 60_000,
  });

  const metas = useMemo(() => {
    return (settingsData?.settings?.extra_options?.metas as MetaRule[]) || [];
  }, [settingsData]);

  const activeMeta = useMemo(() => {
    if (!currentRemote) return null;
    const fullPath = `/${currentRemote}${currentPath === '/' ? '' : currentPath}`;
    return (
      metas.find((m) => {
        if (m.path === fullPath) return true;
        if (fullPath.startsWith(m.path.endsWith('/') ? m.path : `${m.path}/`)) {
          return m.p_sub || m.h_sub || m.r_sub || m.header_sub;
        }
        return false;
      }) || null
    );
  }, [metas, currentRemote, currentPath]);

  const rawItems = listData?.items || [];
  const totalCount = listData?.total_count ?? (isLoading ? 0 : rawItems.length);
  const totalPages = pageSize > 0 && totalCount > 0 ? Math.max(1, Math.ceil(totalCount / pageSize)) : 1;

  // Sort items client-side with directories first & apply meta hide regex
  const items = useMemo(() => {
    let copy = [...rawItems];

    if (activeMeta?.hide) {
      try {
        const re = new RegExp(activeMeta.hide);
        copy = copy.filter((it) => !re.test(it.name));
      } catch {
        // ignore invalid regex
      }
    }

    copy.sort((a, b) => {
      if (a.is_dir !== b.is_dir) return a.is_dir ? -1 : 1;
      let cmp = 0;
      if (sortBy === 'name') {
        cmp = a.name.localeCompare(b.name, 'zh-Hant', { numeric: true });
      } else if (sortBy === 'size') {
        cmp = (a.size || 0) - (b.size || 0);
      } else if (sortBy === 'modified') {
        cmp = new Date(a.modified_at || 0).getTime() - new Date(b.modified_at || 0).getTime();
      }
      return sortReverse ? -cmp : cmp;
    });
    return copy;
  }, [rawItems, sortBy, sortReverse, activeMeta]);

  // Detect README.md in current directory for AList Readme auto-rendering card
  const readmeItem = useMemo(() => {
    if (!readmeAutoRender || isRootMountView) return null;
    return (
      rawItems.find(
        (it) =>
          !it.is_dir &&
          ['readme.md', 'header.md', 'index.md'].includes(it.name.toLowerCase()),
      ) || null
    );
  }, [rawItems, readmeAutoRender, isRootMountView]);

  const { data: readmeData, isLoading: readmeLoading } = useQuery<{ content: string }>({
    queryKey: ['file-content-readme', currentRemote, readmeItem?.path],
    queryFn: () =>
      api.request('GET', `/fs/${encodeURIComponent(currentRemote!)}/read`, {
        query: { path: readmeItem!.path, max_bytes: 65536 },
      }),
    enabled: !!currentRemote && !!readmeItem,
    staleTime: 60_000,
    retry: false,
  });

  useEffect(() => {
    if (listData && !isLoading && !isPlaceholderData) {
      if (page > totalPages && totalPages > 0) {
        setPage(totalPages);
      }
    }
  }, [page, totalPages, listData, isLoading, isPlaceholderData]);

  // Prefetch next page
  useEffect(() => {
    if (pageSize > 0 && page < totalPages && currentRemote) {
      const nextPage = page + 1;
      const nextOffset = (nextPage - 1) * pageSize;
      queryClient.prefetchQuery({
        queryKey: ['fs-list', currentRemote, currentPath, nextPage, pageSize],
        queryFn: () =>
          api.request('GET', `/fs/${currentRemote}/ls`, {
            query: {
              path: currentPath,
              offset: nextOffset,
              limit: pageSize,
            },
          }),
      });
    }
  }, [page, totalPages, pageSize, currentRemote, currentPath, queryClient]);

  const navigateToRemotePath = (remoteName: string | null, path = '/') => {
    setCurrentRemote(remoteName);
    setCurrentPath(path);
    setPage(1);
    setSelectedPaths(new Set());
    onSyncUrl?.(remoteName, path);
  };

  const handleNavigate = (path: string) => {
    navigateToRemotePath(currentRemote, path);
  };

  const handleColumnSort = (field: SortField) => {
    if (sortBy === field) {
      setSortReverse(!sortReverse);
    } else {
      setSortBy(field);
      setSortReverse(false);
    }
  };

  const showCheckboxes = !isRootMountView && (checkboxOpen || selectedPaths.size > 0);

  const toggleSelectAll = () => {
    if (selectedPaths.size === items.length && items.length > 0) {
      setSelectedPaths(new Set());
    } else {
      setSelectedPaths(new Set(items.map((i) => i.path)));
    }
  };

  const toggleSelectItem = (path: string) => {
    const next = new Set(selectedPaths);
    if (next.has(path)) {
      next.delete(path);
    } else {
      next.add(path);
    }
    setSelectedPaths(next);
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0 || !currentRemote) return;
    enqueueUpload(currentRemote, currentPath, Array.from(files));
    toast.success(`已加入 ${files.length} 個檔案至背景傳輸佇列`);
    e.target.value = '';
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    if (!currentRemote) return;
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      enqueueUpload(currentRemote, currentPath, Array.from(files));
      toast.success(`拖放加入 ${files.length} 個檔案至背景傳輸佇列`);
    }
  };

  const selectedItems = items.filter((i) => selectedPaths.has(i.path));
  const selectedTotalBytes = useMemo(
    () => selectedItems.reduce((acc, item) => acc + (item.size || 0), 0),
    [selectedItems],
  );

  const pathSegments = currentPath.split('/').filter(Boolean);

  const isNavSticky =
    headerStickyMode === 'sticky' || headerStickyMode === 'only_navbar_sticky';

  const handleCopyLinks = (targets: FsItem[]) => {
    if (!currentRemote || targets.length === 0) return;
    const urls = targets
      .map((t) => `${window.location.origin}${rawUrl(currentRemote, t.path)}`)
      .join('\n');
    void navigator.clipboard?.writeText(urls).then(
      () => toast.success(`已複製 ${targets.length} 個直鏈網址至剪貼簿`),
      () => toast.error('複製直鏈失敗'),
    );
  };

  const handleDownloadItems = (targets: FsItem[]) => {
    if (!currentRemote || targets.length === 0) return;
    const filesOnly = targets.filter((t) => !t.is_dir);
    if (filesOnly.length === 0) {
      toast.info('資料夾請進入內部選擇檔案下載或使用跨端同步功能');
      return;
    }
    for (const f of filesOnly) {
      window.open(downloadUrl(currentRemote, f.path), '_blank');
    }
    toast.success(`已觸發下載 ${filesOnly.length} 個檔案`);
  };

  return (
    <div
      className="flex flex-col gap-3.5 w-full relative"
      onDragOver={(e) => {
        if (!currentRemote) return;
        e.preventDefault();
        setIsDragOver(true);
      }}
      onDragLeave={() => setIsDragOver(false)}
      onDrop={handleDrop}
    >
      {/* Hidden File Upload Input */}
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileUpload}
        multiple
        className="hidden"
      />

      {/* AList Top-Right Fixed SelectionStats Pill (`src/pages/home/folder/ListItem.tsx`) */}
      {isPrimaryPane && selectedPaths.size > 0 && (
        <div className="fixed top-16 right-4 z-40 px-3 py-1.5 rounded-lg bg-[var(--alist-main)] text-white shadow-md text-xs font-medium flex items-center gap-2.5 animate-in fade-in duration-150">
          <span>已選擇 {selectedPaths.size} 項</span>
          <span className="opacity-75">•</span>
          <span>總大小 {formatBytes(selectedTotalBytes)}</span>
        </div>
      )}

      {/* ========== 1. AList Breadcrumb Nav (`src/pages/home/Nav.tsx`) ========== */}
      <nav
        aria-label="路徑麵包屑導覽"
        className={`w-full flex flex-wrap items-center justify-between gap-2 py-1 px-1 transition-all ${
          isNavSticky
            ? `${
                headerStickyMode === 'sticky' ? 'sticky top-[60px]' : 'sticky top-0'
              } z-20 bg-background/90 backdrop-blur-md`
            : ''
        }`}
      >
        {/* Left: Breadcrumb Trail */}
        <ol className="flex flex-wrap items-center gap-0.5 text-sm">
          {/* Root Home Item (`🏠 首頁`) */}
          <li className="flex items-center">
            <button
              type="button"
              onClick={() => navigateToRemotePath(null, '/')}
              className={`alist-nav-link px-2 py-1 flex items-center gap-1.5 cursor-pointer ${
                isRootMountView
                  ? 'font-bold text-foreground'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
            >
              <Home className="h-4 w-4 text-[var(--alist-main)] shrink-0" />
              <span>首頁</span>
            </button>
          </li>

          {/* Mounted Remote Segment */}
          {currentRemote && (
            <li className="flex items-center">
              <span className="text-muted-foreground/50 px-0.5 select-none">/</span>
              <button
                type="button"
                onClick={() => navigateToRemotePath(currentRemote, '/')}
                className={`alist-nav-link px-2 py-1 flex items-center gap-1 cursor-pointer ${
                  pathSegments.length === 0
                    ? 'font-bold text-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                }`}
              >
                <span>{currentRemote}</span>
              </button>
            </li>
          )}

          {/* Subfolder Segments */}
          {pathSegments.map((seg, idx) => {
            const segPath = '/' + pathSegments.slice(0, idx + 1).join('/');
            const isLast = idx === pathSegments.length - 1;
            return (
              <li key={segPath} className="flex items-center">
                <span className="text-muted-foreground/50 px-0.5 select-none">/</span>
                <button
                  type="button"
                  onClick={() => handleNavigate(segPath)}
                  className={`alist-nav-link px-2 py-1 cursor-pointer break-all ${
                    isLast
                      ? 'font-bold text-foreground'
                      : 'text-muted-foreground hover:text-foreground'
                  }`}
                >
                  {seg}
                </button>
              </li>
            );
          })}
        </ol>

        {/* Right: Quick Storage Switcher & Action Pills */}
        <div className="flex items-center gap-1.5">
          <Select
            value={currentRemote || '__root__'}
            onValueChange={(val) => {
              if (val === '__root__') {
                navigateToRemotePath(null, '/');
              } else {
                navigateToRemotePath(val, '/');
              }
            }}
          >
            <SelectTrigger className="h-7 w-auto min-w-[130px] text-xs bg-[var(--alist-card-bg)] border-border/60 shadow-2xs rounded-lg px-2.5">
              <SelectValue placeholder="切換掛載節點" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__root__">🏠 虛擬根目錄 (全部節點)</SelectItem>
              {availableRemotes.map((r) => (
                <SelectItem key={r.name} value={r.name}>
                  {r.name} ({r.type})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {!isRootMountView && (
            <>
              <Button
                variant="subtle"
                size="sm"
                className="h-7 px-2.5 text-xs gap-1"
                onClick={() => fileInputRef.current?.click()}
              >
                <Upload className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">上傳</span>
              </Button>
              <Button
                variant="subtle"
                size="sm"
                className="h-7 px-2.5 text-xs gap-1"
                onClick={() => setOpsType('mkdir')}
              >
                <FolderPlus className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">新增資料夾</span>
              </Button>
            </>
          )}
        </div>
      </nav>

      {/* ========== 2. AList Main ObjBox (`src/pages/home/Obj.tsx`) ========== */}
      <div
        className={`w-full alist-obj-box p-2.5 sm:p-3 space-y-2 transition-all ${
          isDragOver ? 'ring-2 ring-[var(--alist-main)] ring-offset-2' : ''
        }`}
      >
        {/* AList Meta Header Markdown Card */}
        {activeMeta?.header && !isRootMountView && (
          <div className="p-3 mb-2 rounded-lg bg-primary/5 border border-primary/20 text-xs text-foreground/90 space-y-1">
            {activeMeta.header.split('\n').map((line, idx) => (
              <p key={idx} className={line.startsWith('#') ? 'font-bold text-sm text-foreground' : ''}>
                {line.replace(/^#+\s*/, '')}
              </p>
            ))}
          </div>
        )}
        {isRootMountView ? (
          /* ----- AList Virtual Root Storage Mounts View ----- */
          remotesLoading ? (
            <div className="py-16 flex flex-col items-center justify-center gap-2 text-muted-foreground text-sm">
              <RefreshCw className="h-6 w-6 animate-spin text-[var(--alist-main)]" />
              <span>載入掛載儲存節點中...</span>
            </div>
          ) : availableRemotes.length === 0 ? (
            <div className="py-16 text-center space-y-3">
              <HardDrive className="h-10 w-10 text-muted-foreground/40 mx-auto" />
              <p className="text-sm text-muted-foreground">尚未掛載任何儲存節點</p>
              <Button variant="subtle" size="sm" onClick={() => navigate('/remotes')}>
                前往後台新增儲存節點
              </Button>
            </div>
          ) : displayLayout === 'grid' || displayLayout === 'image' ? (
            /* Grid View for Mounted Remotes */
            <div
              className="grid gap-2 pt-1"
              style={{
                gridTemplateColumns: `repeat(auto-fill, minmax(${gridItemSize + 30}px, 1fr))`,
              }}
            >
              {availableRemotes.map((rem) => (
                <div
                  key={rem.name}
                  onClick={() => navigateToRemotePath(rem.name, '/')}
                  className="alist-grid-item p-2.5 flex flex-col items-center gap-1.5 cursor-pointer select-none"
                >
                  <div
                    className="w-full flex items-center justify-center relative"
                    style={{ height: `${gridItemSize}px` }}
                  >
                    <Folder
                      className="text-[var(--alist-main)] fill-[var(--alist-main)]/20"
                      style={{
                        width: `${Math.max(40, gridItemSize - 26)}px`,
                        height: `${Math.max(40, gridItemSize - 26)}px`,
                      }}
                    />
                  </div>
                  <span className="text-sm font-medium text-foreground truncate w-full text-center">
                    {rem.name}
                  </span>
                  <Badge variant="default" className="text-[10px] px-1.5 py-0">
                    {rem.type}
                  </Badge>
                </div>
              ))}
            </div>
          ) : (
            /* List View for Mounted Remotes (`List.tsx` + `ListItem.tsx`) */
            <div className="space-y-1">
              <div className="flex items-center px-2.5 py-1.5 text-xs font-bold text-muted-foreground select-none">
                <div className="flex-1">名稱 (掛載路徑)</div>
                <div className="hidden md:block w-44 text-left">驅動類型 (Driver)</div>
                <div className="w-24 text-right">大小</div>
                <div className="hidden sm:block w-36 text-right">連線狀態</div>
              </div>

              {availableRemotes.map((rem) => (
                <div
                  key={rem.name}
                  onClick={() => navigateToRemotePath(rem.name, '/')}
                  className="alist-list-item px-2.5 py-2 flex items-center gap-2 cursor-pointer select-none"
                >
                  <div className="flex-1 min-w-0 flex items-center gap-2.5">
                    <FileTypeIcon name={rem.name} isDir className="h-6 w-6" />
                    <span className="text-sm font-medium text-foreground truncate">
                      {rem.name}
                    </span>
                    {rem.is_default && (
                      <Badge variant="default" className="text-[10px] px-1.5 py-0">
                        預設
                      </Badge>
                    )}
                  </div>

                  <div className="hidden md:flex w-44 items-center">
                    <Badge variant="info" className="text-[11px] font-mono">
                      {rem.type}
                    </Badge>
                  </div>

                  <div className="w-24 text-right text-sm text-muted-foreground font-mono">
                    -
                  </div>

                  <div className="hidden sm:flex w-36 justify-end items-center gap-1.5 text-xs text-muted-foreground">
                    <span
                      className={`h-2 w-2 rounded-full ${
                        rem.health?.status === 'success' ? 'bg-emerald-500' : 'bg-amber-500'
                      }`}
                    />
                    <span className="font-mono">
                      {rem.health?.status === 'success' ? `${rem.health.latency_ms}ms` : '就緒'}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )
        ) : isLoading ? (
          /* ----- Directory Loading State ----- */
          <div className="py-16 flex flex-col items-center justify-center gap-2 text-muted-foreground text-sm">
            <RefreshCw className="h-6 w-6 animate-spin text-[var(--alist-main)]" />
            <span>讀取目錄內容中...</span>
          </div>
        ) : items.length === 0 ? (
          /* ----- Empty Folder State ----- */
          <div className="py-16 flex flex-col items-center justify-center text-center text-muted-foreground space-y-2">
            <Folder className="h-10 w-10 text-[var(--alist-main)]/40" />
            <p className="text-sm font-medium text-foreground/80">此資料夾為空</p>
            <p className="text-xs text-muted-foreground">
              拖放檔案至此處，或使用右下角懸浮工具欄上傳與建立資料夾
            </p>
          </div>
        ) : displayLayout === 'grid' ? (
          /* ----- 2A. AList Grid Layout (`src/pages/home/folder/Grid.tsx` & `GridItem.tsx`) ----- */
          <div
            className={`grid gap-1.5 pt-1 transition-opacity ${
              isPlaceholderData ? 'opacity-50 pointer-events-none' : ''
            }`}
            style={{
              gridTemplateColumns: `repeat(auto-fill, minmax(${gridItemSize + 24}px, 1fr))`,
            }}
          >
            {items.map((item) => {
              const isSelected = selectedPaths.has(item.path);
              return (
                <div
                  key={item.path}
                  onClick={() => {
                    if (item.is_dir) {
                      handleNavigate(item.path);
                    } else {
                      setPreviewItem(item);
                    }
                  }}
                  onContextMenu={(e) => {
                    e.preventDefault();
                    setSelectedPaths(new Set([item.path]));
                    setContextMenu({ x: e.clientX, y: e.clientY, item });
                  }}
                  className={`alist-grid-item p-2 flex flex-col items-center gap-1.5 cursor-pointer select-none group relative ${
                    isSelected ? 'selected' : ''
                  }`}
                >
                  {/* Top-left ItemCheckbox */}
                  <div
                    onClick={(e) => e.stopPropagation()}
                    className={`absolute left-2 top-2 z-10 transition-opacity ${
                      showCheckboxes || isSelected
                        ? 'opacity-100'
                        : 'opacity-0 group-hover:opacity-100'
                    }`}
                  >
                    <Checkbox
                      checked={isSelected}
                      onCheckedChange={() => toggleSelectItem(item.path)}
                    />
                  </div>

                  {/* Center Thumbnail / Large Icon */}
                  <div
                    className="w-full flex items-center justify-center overflow-hidden"
                    style={{ height: `${gridItemSize}px` }}
                  >
                    {item.thumbnail_url ? (
                      <img
                        src={item.thumbnail_url}
                        alt={item.name}
                        loading="lazy"
                        className="max-h-full max-w-full rounded-lg shadow-md object-contain"
                      />
                    ) : (
                      <FileTypeIcon
                        name={item.name}
                        isDir={item.is_dir}
                        className="transition-transform"
                      />
                    )}
                  </div>

                  {/* Filename & Size */}
                  <div className="w-full flex flex-col items-center gap-0.5">
                    <span
                      className="text-xs sm:text-sm text-foreground truncate w-full text-center"
                      title={item.name}
                    >
                      {item.name}
                    </span>
                    {!item.is_dir && (
                      <span className="text-[10px] text-muted-foreground font-mono">
                        {formatBytes(item.size)}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        ) : displayLayout === 'image' ? (
          /* ----- 2B. AList Image Gallery Layout (`src/pages/home/folder/Images.tsx`) ----- */
          <div className="space-y-4 p-1">
            {/* Folders on top */}
            {items.some((i) => i.is_dir) && (
              <div
                className="grid gap-1.5"
                style={{
                  gridTemplateColumns: 'repeat(auto-fill, minmax(110px, 1fr))',
                }}
              >
                {items
                  .filter((i) => i.is_dir)
                  .map((folder) => (
                    <div
                      key={folder.path}
                      onClick={() => handleNavigate(folder.path)}
                      className="alist-grid-item p-2 flex flex-col items-center gap-1 cursor-pointer"
                    >
                      <FileTypeIcon name={folder.name} isDir className="h-10 w-10" />
                      <span className="text-xs text-foreground truncate w-full text-center">
                        {folder.name}
                      </span>
                    </div>
                  ))}
              </div>
            )}

            {/* Images & Media Cards */}
            {items.filter((i) => !i.is_dir).length === 0 ? (
              <div className="py-10 text-center text-sm text-muted-foreground">
                此目錄下尚無圖片或媒體檔案
              </div>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3">
                {items
                  .filter((i) => !i.is_dir)
                  .map((file) => {
                    const isImage = getFileKind(file.name) === 'image';
                    const imgSrc =
                      file.thumbnail_url ||
                      (isImage && currentRemote ? rawUrl(currentRemote, file.path) : '');
                    return (
                      <div
                        key={file.path}
                        onClick={() => setPreviewItem(file)}
                        className="group relative rounded-xl overflow-hidden border border-border/50 bg-muted/20 aspect-[4/3] flex flex-col items-center justify-center cursor-pointer shadow-xs hover:shadow-md transition-all"
                      >
                        {imgSrc ? (
                          <img
                            src={imgSrc}
                            alt={file.name}
                            loading="lazy"
                            className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                          />
                        ) : (
                          <FileTypeIcon name={file.name} className="h-12 w-12" />
                        )}
                        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/75 via-black/40 to-transparent p-2 text-white">
                          <p className="text-xs font-medium truncate">{file.name}</p>
                          <p className="text-[10px] opacity-80 font-mono">{formatBytes(file.size)}</p>
                        </div>
                      </div>
                    );
                  })}
              </div>
            )}
          </div>
        ) : (
          /* ----- 2C. AList List Layout (`src/pages/home/folder/List.tsx` & `ListItem.tsx`) ----- */
          <div className="space-y-1">
            {/* ListTitle Header Row */}
            <div className="flex items-center px-2.5 py-1.5 text-xs font-bold text-muted-foreground select-none">
              <div className="flex-1 min-w-0 flex items-center gap-2.5">
                {showCheckboxes && (
                  <Checkbox
                    checked={selectedPaths.size === items.length && items.length > 0}
                    onCheckedChange={toggleSelectAll}
                  />
                )}
                <button
                  type="button"
                  onClick={() => handleColumnSort('name')}
                  className="inline-flex items-center gap-1 hover:text-foreground cursor-pointer"
                >
                  <span>名稱</span>
                  {sortBy === 'name' &&
                    (sortReverse ? (
                      <ArrowDown className="h-3 w-3 text-[var(--alist-main)]" />
                    ) : (
                      <ArrowUp className="h-3 w-3 text-[var(--alist-main)]" />
                    ))}
                </button>
              </div>

              <div className="w-24 sm:w-28 text-right pr-2">
                <button
                  type="button"
                  onClick={() => handleColumnSort('size')}
                  className="inline-flex items-center justify-end gap-1 hover:text-foreground cursor-pointer"
                >
                  <span>大小</span>
                  {sortBy === 'size' &&
                    (sortReverse ? (
                      <ArrowDown className="h-3 w-3 text-[var(--alist-main)]" />
                    ) : (
                      <ArrowUp className="h-3 w-3 text-[var(--alist-main)]" />
                    ))}
                </button>
              </div>

              <div className="hidden md:block w-36 text-right">
                <button
                  type="button"
                  onClick={() => handleColumnSort('modified')}
                  className="inline-flex items-center justify-end gap-1 hover:text-foreground cursor-pointer"
                >
                  <span>修改時間</span>
                  {sortBy === 'modified' &&
                    (sortReverse ? (
                      <ArrowDown className="h-3 w-3 text-[var(--alist-main)]" />
                    ) : (
                      <ArrowUp className="h-3 w-3 text-[var(--alist-main)]" />
                    ))}
                </button>
              </div>
            </div>

            {/* List Items */}
            <div
              className={`space-y-0.5 transition-opacity duration-150 ${
                isPlaceholderData ? 'opacity-50 pointer-events-none' : ''
              }`}
            >
              {items.map((item) => {
                const isSelected = selectedPaths.has(item.path);
                return (
                  <div
                    key={item.path}
                    onClick={(e) => {
                      if (
                        (e.target as HTMLElement).tagName.toLowerCase() === 'input' ||
                        (e.target as HTMLElement).closest('button')
                      ) {
                        return;
                      }
                      if (item.is_dir) {
                        handleNavigate(item.path);
                      } else {
                        setPreviewItem(item);
                      }
                    }}
                    onContextMenu={(e) => {
                      e.preventDefault();
                      setSelectedPaths(new Set([item.path]));
                      setContextMenu({ x: e.clientX, y: e.clientY, item });
                    }}
                    className={`alist-list-item px-2.5 py-2 flex items-center gap-2 cursor-pointer group select-none ${
                      isSelected ? 'selected' : ''
                    }`}
                  >
                    {/* Name Column */}
                    <div className="flex-1 min-w-0 flex items-center gap-2.5">
                      {showCheckboxes && (
                        <div onClick={(e) => e.stopPropagation()}>
                          <Checkbox
                            checked={isSelected}
                            onCheckedChange={() => toggleSelectItem(item.path)}
                          />
                        </div>
                      )}

                      <FileTypeIcon name={item.name} isDir={item.is_dir} className="h-6 w-6" />

                      <div
                        className={`min-w-0 flex-1 ${
                          filenameOverflow === 'scrollable'
                            ? 'overflow-hidden whitespace-nowrap alist-marquee-hover'
                            : filenameOverflow === 'multi_line'
                            ? 'whitespace-normal break-words leading-snug'
                            : 'truncate'
                        }`}
                        title={item.name}
                      >
                        <span className="text-sm font-medium text-foreground alist-marquee-inner">
                          {item.name}
                        </span>
                      </div>
                    </div>

                    {/* Quick Hover Actions (subtle inline icons on hover) */}
                    <div
                      onClick={(e) => e.stopPropagation()}
                      className="hidden sm:flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      {!item.is_dir && (
                        <button
                          type="button"
                          onClick={() => setPreviewItem(item)}
                          className="h-7 w-7 rounded-md flex items-center justify-center text-muted-foreground hover:text-[var(--alist-main)] hover:bg-[var(--alist-hover)] cursor-pointer"
                          title="預覽"
                        >
                          <Eye className="h-3.5 w-3.5" />
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedPaths(new Set([item.path]));
                          setOpsType('rename');
                        }}
                        className="h-7 w-7 rounded-md flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-[var(--alist-hover)] cursor-pointer"
                        title="重新命名"
                      >
                        <Edit className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedPaths(new Set([item.path]));
                          setOpsType('delete_batch');
                        }}
                        className="h-7 w-7 rounded-md flex items-center justify-center text-muted-foreground hover:text-rose-500 hover:bg-[var(--alist-hover)] cursor-pointer"
                        title="刪除"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>

                    {/* Size Column */}
                    <div className="w-24 sm:w-28 text-right pr-2 text-xs sm:text-sm text-muted-foreground font-mono shrink-0">
                      {item.is_dir ? '-' : formatBytes(item.size)}
                    </div>

                    {/* Modified Date Column */}
                    <div className="hidden md:block w-36 text-right text-xs sm:text-sm text-muted-foreground shrink-0 whitespace-nowrap">
                      {formatRelativeTime(item.modified_at)}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ========== AList Pager (`src/pages/home/folder/Pager.tsx`) ========== */}
        {!isRootMountView && items.length > 0 && (
          <div className="pt-2 border-t border-border/40 flex flex-wrap items-center justify-center sm:justify-between gap-2 text-xs text-muted-foreground select-none">
            <div className="flex items-center gap-2">
              <span>
                共 <strong className="text-foreground">{totalCount}</strong> 項
              </span>
              {selectedPaths.size > 0 && (
                <Badge variant="default" className="text-[11px] h-5 px-2">
                  已選 {selectedPaths.size} 項
                </Badge>
              )}
            </div>

            <div className="flex items-center gap-2">
              <Select
                value={String(pageSize)}
                onValueChange={(val) => {
                  setPageSize(Number(val));
                  setPage(1);
                  setSelectedPaths(new Set());
                }}
              >
                <SelectTrigger className="w-20 h-7 text-xs font-medium bg-input/70 border-transparent">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="20">20 / 頁</SelectItem>
                  <SelectItem value="50">50 / 頁</SelectItem>
                  <SelectItem value="100">100 / 頁</SelectItem>
                  <SelectItem value="200">200 / 頁</SelectItem>
                  <SelectItem value="0">全部</SelectItem>
                </SelectContent>
              </Select>

              {pageSize > 0 && totalPages > 1 && (
                <div className="flex items-center gap-1">
                  <Button
                    variant="subtle"
                    size="iconSm"
                    onClick={() => {
                      setPage(1);
                      setSelectedPaths(new Set());
                    }}
                    disabled={page <= 1 || isFetching}
                  >
                    <ChevronsLeft className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    variant="subtle"
                    size="iconSm"
                    onClick={() => {
                      setPage((p) => Math.max(1, p - 1));
                      setSelectedPaths(new Set());
                    }}
                    disabled={page <= 1 || isFetching}
                  >
                    <ChevronLeft className="h-3.5 w-3.5" />
                  </Button>
                  <span className="px-2 font-mono text-xs text-foreground">
                    {page} / {totalPages}
                  </span>
                  <Button
                    variant="subtle"
                    size="iconSm"
                    onClick={() => {
                      setPage((p) => Math.min(totalPages, p + 1));
                      setSelectedPaths(new Set());
                    }}
                    disabled={page >= totalPages || isFetching}
                  >
                    <ChevronRight className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    variant="subtle"
                    size="iconSm"
                    onClick={() => {
                      setPage(totalPages);
                      setSelectedPaths(new Set());
                    }}
                    disabled={page >= totalPages || isFetching}
                  >
                    <ChevronsRight className="h-3.5 w-3.5" />
                  </Button>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* ========== 3. AList Auto-Rendered README Card (`src/pages/home/Readme.tsx`) ========== */}
      {readmeItem ? (
        <div className="w-full alist-obj-box p-4 sm:p-5 space-y-2 animate-in fade-in duration-200">
          <div className="flex items-center gap-2 pb-2 border-b border-border/50 text-xs font-semibold text-muted-foreground">
            <BookOpen className="h-4 w-4 text-[var(--alist-main)]" />
            <span>{readmeItem.name}</span>
          </div>
          {readmeLoading ? (
            <div className="py-6 text-xs text-muted-foreground">載入說明文件中...</div>
          ) : (
            <div className="prose prose-sm max-w-none text-sm text-foreground/90 leading-relaxed space-y-2">
              {(readmeData?.content || '').split('\n').map((line, idx) => {
                if (line.startsWith('# ')) {
                  return (
                    <h3 key={idx} className="text-lg font-bold text-foreground mt-1">
                      {line.slice(2)}
                    </h3>
                  );
                }
                if (line.startsWith('## ')) {
                  return (
                    <h4 key={idx} className="text-base font-semibold text-foreground mt-2">
                      {line.slice(3)}
                    </h4>
                  );
                }
                if (line.startsWith('- ')) {
                  return (
                    <li key={idx} className="ml-4 list-disc text-xs sm:text-sm text-foreground/85">
                      {line.slice(2)}
                    </li>
                  );
                }
                if (!line.trim()) return null;
                return (
                  <p key={idx} className="text-xs sm:text-sm text-muted-foreground">
                    {line}
                  </p>
                );
              })}
            </div>
          )}
        </div>
      ) : activeMeta?.readme && !isRootMountView ? (
        <div className="w-full alist-obj-box p-4 sm:p-5 space-y-2 animate-in fade-in duration-200">
          <div className="flex items-center gap-2 pb-2 border-b border-border/50 text-xs font-semibold text-muted-foreground">
            <BookOpen className="h-4 w-4 text-[var(--alist-main)]" />
            <span>README.md (元資料說明)</span>
          </div>
          <div className="prose prose-sm max-w-none text-xs text-foreground/90 leading-relaxed space-y-1">
            {activeMeta.readme.split('\n').map((line, idx) => (
              <p key={idx}>{line}</p>
            ))}
          </div>
        </div>
      ) : null}

      {/* ========== 4. AList Right-Click Context Menu (`src/pages/home/folder/context-menu.tsx`) ========== */}
      {contextMenu && (
        <div
          style={{
            top: Math.min(contextMenu.y, window.innerHeight - 240),
            left: Math.min(contextMenu.x, window.innerWidth - 190),
          }}
          onClick={(e) => e.stopPropagation()}
          className="fixed z-50 w-44 rounded-xl bg-[var(--alist-card-bg)] p-1.5 shadow-2xl border border-border/60 text-xs space-y-0.5 animate-in fade-in zoom-in-95 duration-100"
        >
          <button
            type="button"
            onClick={() => {
              const target = contextMenu.item;
              setContextMenu(null);
              if (target.is_dir) handleNavigate(target.path);
              else setPreviewItem(target);
            }}
            className="w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg hover:bg-[var(--alist-hover)] text-foreground cursor-pointer"
          >
            <Eye className="h-4 w-4 text-[var(--alist-main)]" />
            <span>{contextMenu.item.is_dir ? '進入目錄' : '預覽檔案'}</span>
          </button>

          {!contextMenu.item.is_dir && (
            <>
              <button
                type="button"
                onClick={() => {
                  const target = contextMenu.item;
                  setContextMenu(null);
                  handleDownloadItems([target]);
                }}
                className="w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg hover:bg-[var(--alist-hover)] text-foreground cursor-pointer"
              >
                <Download className="h-4 w-4 text-emerald-500" />
                <span>下載檔案</span>
              </button>

              <button
                type="button"
                onClick={() => {
                  const target = contextMenu.item;
                  setContextMenu(null);
                  handleCopyLinks([target]);
                }}
                className="w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg hover:bg-[var(--alist-hover)] text-foreground cursor-pointer"
              >
                <Link2 className="h-4 w-4 text-violet-500" />
                <span>複製直鏈</span>
              </button>
            </>
          )}

          <div className="h-px bg-border/60 my-1" />

          <button
            type="button"
            onClick={() => {
              setSelectedPaths(new Set([contextMenu.item.path]));
              setContextMenu(null);
              setOpsType('rename');
            }}
            className="w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg hover:bg-[var(--alist-hover)] text-foreground cursor-pointer"
          >
            <Edit className="h-4 w-4 text-amber-500" />
            <span>重新命名</span>
          </button>

          <button
            type="button"
            onClick={() => {
              setSelectedPaths(new Set([contextMenu.item.path]));
              setContextMenu(null);
              setOpsType('transfer');
            }}
            className="w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg hover:bg-[var(--alist-hover)] text-foreground cursor-pointer"
          >
            <Copy className="h-4 w-4 text-sky-500" />
            <span>複製 / 跨節點移動</span>
          </button>

          <button
            type="button"
            onClick={() => {
              setSelectedPaths(new Set([contextMenu.item.path]));
              setContextMenu(null);
              setOpsType('delete_batch');
            }}
            className="w-full flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg hover:bg-rose-500/15 text-rose-500 cursor-pointer"
          >
            <Trash2 className="h-4 w-4" />
            <span>刪除</span>
          </button>
        </div>
      )}

      {/* ========== 5. Primary Pane Floating Toolbars & Search Modal ========== */}
      {isPrimaryPane && (
        <>
          <RightToolbar
            isRootMountView={isRootMountView}
            onRefresh={() => {
              if (isRootMountView) onRefetchRemotes();
              else void refetch();
            }}
            onMkdir={() => setOpsType('mkdir')}
            onUpload={() => fileInputRef.current?.click()}
            onToggleDualPane={onToggleDualPane}
            isDualPane={isDualPane}
          />

          <CenterToolbar
            selectedCount={selectedPaths.size}
            canRename={selectedPaths.size === 1}
            onRename={() => setOpsType('rename')}
            onMove={() => setOpsType('transfer')}
            onCopy={() => setOpsType('transfer')}
            onDelete={() => setOpsType('delete_batch')}
            onCopyLink={() => handleCopyLinks(selectedItems)}
            onDownload={() => handleDownloadItems(selectedItems)}
            onClearSelect={() => setSelectedPaths(new Set())}
          />

          <FileSearchModal
            currentRemote={currentRemote}
            currentItems={items}
            remotes={availableRemotes}
            onSelectRemote={(remoteName) => navigateToRemotePath(remoteName, '/')}
            onSelectItem={(item) => {
              if (item.is_dir) handleNavigate(item.path);
              else setPreviewItem(item);
            }}
          />
        </>
      )}

      {/* ========== 6. Preview & File Operation Modals ========== */}
      {currentRemote && (
        <>
          <FilePreviewDialog
            open={!!previewItem}
            onOpenChange={(open) => !open && setPreviewItem(null)}
            item={previewItem}
            remote={currentRemote}
          />

          <FileOpsDialog
            open={!!opsType}
            onOpenChange={(open) => !open && setOpsType(null)}
            type={opsType}
            remote={currentRemote}
            currentPath={currentPath}
            items={selectedItems.length > 0 ? selectedItems : items.slice(0, 1)}
            availableRemotes={availableRemotes}
          />
        </>
      )}
    </div>
  );
}
