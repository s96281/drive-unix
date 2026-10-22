import React, { useState, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Folder,
  File,
  FileText,
  Image as ImageIcon,
  FolderPlus,
  Upload,
  RefreshCw,
  Trash2,
  ArrowRightLeft,
  Columns,
  Square,
  ChevronRight,
  Download,
  Eye,
  Edit,
  MoreVertical,
  ArrowUp,
  HardDrive,
} from 'lucide-react';
import { api } from '@/api';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { formatBytes, formatRelativeTime } from '@/lib/format';
import { useTransferQueueStore } from '@/stores/transfer-queue';
import { FilePreviewDialog } from '@/components/files/FilePreviewDialog';
import { FileOpsDialog, type FileOpType } from '@/components/files/FileOpsDialog';
import { toast } from 'sonner';
import type { RemoteListResponse, FsListResponse, FsItem, RemoteItem } from '@/api/types';

export function FilesPage() {
  const [isDualPane, setIsDualPane] = useState(false);

  const { data: remotesData } = useQuery<RemoteListResponse>({
    queryKey: ['remotes'],
    queryFn: () => api.request('GET', '/remotes'),
  });

  const remotes = remotesData?.remotes || [];
  const defaultRemote = remotesData?.default_remote || remotes[0]?.name || 'local';

  return (
    <div className="space-y-4 max-w-7xl mx-auto h-[calc(100vh-8rem)] flex flex-col">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 shrink-0">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-foreground">檔案瀏覽器</h2>
          <p className="text-sm text-muted-foreground mt-0.5">跨雲端網盤檔案管理、雙欄同步對比與拖曳上傳</p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant={isDualPane ? 'default' : 'outline'}
            size="sm"
            onClick={() => setIsDualPane(!isDualPane)}
            className="gap-1.5"
          >
            <Columns className="h-4 w-4" />
            {isDualPane ? '單欄檢視模式' : '雙欄同步模式 (Dual Pane)'}
          </Button>
        </div>
      </div>

      {/* Pane Layout Container */}
      <div className={`grid gap-4 flex-1 min-h-0 ${isDualPane ? 'grid-cols-1 lg:grid-cols-2' : 'grid-cols-1'}`}>
        <FileBrowserPane
          paneId="pane-left"
          defaultRemote={defaultRemote}
          availableRemotes={remotes}
          otherPaneRemote={isDualPane ? remotes[1]?.name || defaultRemote : undefined}
        />

        {isDualPane && (
          <FileBrowserPane
            paneId="pane-right"
            defaultRemote={remotes[1]?.name || defaultRemote}
            availableRemotes={remotes}
            otherPaneRemote={defaultRemote}
          />
        )}
      </div>
    </div>
  );
}

interface FileBrowserPaneProps {
  paneId: string;
  defaultRemote: string;
  availableRemotes: RemoteItem[];
  otherPaneRemote?: string;
}

function FileBrowserPane({ paneId, defaultRemote, availableRemotes }: FileBrowserPaneProps) {
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
  const enqueueUpload = useTransferQueueStore((s) => s.enqueue);

  const [currentRemote, setCurrentRemote] = useState<string>(defaultRemote);
  const [currentPath, setCurrentPath] = useState<string>('/');
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());
  const [isDragOver, setIsDragOver] = useState(false);

  // Modals state
  const [previewItem, setPreviewItem] = useState<FsItem | null>(null);
  const [opsType, setOpsType] = useState<FileOpType | null>(null);

  // Sync defaultRemote when availableRemotes load
  React.useEffect(() => {
    if (defaultRemote && !currentRemote) {
      setCurrentRemote(defaultRemote);
    }
  }, [defaultRemote, currentRemote]);

  const { data: listData, isLoading, refetch } = useQuery<FsListResponse>({
    queryKey: ['fs-list', currentRemote, currentPath],
    queryFn: () =>
      api.request('GET', `/fs/${currentRemote}/ls`, {
        query: { path: currentPath },
      }),
    enabled: !!currentRemote,
  });

  const items = listData?.items || [];

  const handleNavigate = (path: string) => {
    setCurrentPath(path);
    setSelectedPaths(new Set());
  };

  const handleUpLevel = () => {
    if (currentPath === '/') return;
    const parts = currentPath.split('/').filter(Boolean);
    parts.pop();
    const parentPath = parts.length === 0 ? '/' : `/${parts.join('/')}`;
    handleNavigate(parentPath);
  };

  const toggleSelectAll = () => {
    if (selectedPaths.size === items.length) {
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
    if (!files || files.length === 0) return;

    enqueueUpload(currentRemote, currentPath, Array.from(files));
    toast.success(`已加入 ${files.length} 個檔案至背景傳輸佇列`);
    e.target.value = '';
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    const files = e.dataTransfer.files;
    if (files && files.length > 0) {
      enqueueUpload(currentRemote, currentPath, Array.from(files));
      toast.success(`拖放加入 ${files.length} 個檔案至背景傳輸佇列`);
    }
  };

  // Selected items array
  const selectedItems = items.filter((i) => selectedPaths.has(i.path));

  // Breadcrumbs segments
  const pathSegments = currentPath.split('/').filter(Boolean);

  return (
    <Card
      className={`flex flex-col h-full border border-border shadow-xs overflow-hidden relative ${
        isDragOver ? 'ring-2 ring-primary ring-offset-2' : ''
      }`}
      onDragOver={(e) => {
        e.preventDefault();
        setIsDragOver(true);
      }}
      onDragLeave={() => setIsDragOver(false)}
      onDrop={handleDrop}
    >
      {/* Pane Toolbar Header */}
      <div className="p-3 border-b border-border bg-card/60 flex flex-wrap items-center justify-between gap-2 shrink-0">
        <div className="flex items-center gap-2">
          {/* Remote Selector */}
          <Select
            value={currentRemote}
            onValueChange={(val) => {
              setCurrentRemote(val);
              setCurrentPath('/');
              setSelectedPaths(new Set());
            }}
          >
            <SelectTrigger className="w-[170px] h-8 text-xs font-medium">
              <SelectValue placeholder="選擇儲存節點" />
            </SelectTrigger>
            <SelectContent>
              {availableRemotes.map((r) => (
                <SelectItem key={r.name} value={r.name}>
                  {r.name} ({r.type})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => refetch()} title="重新整理">
            <RefreshCw className="h-3.5 w-3.5 text-muted-foreground" />
          </Button>

          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={handleUpLevel}
            disabled={currentPath === '/'}
            title="上一層目錄"
          >
            <ArrowUp className="h-3.5 w-3.5 text-muted-foreground" />
          </Button>
        </div>

        {/* Action Buttons */}
        <div className="flex items-center gap-1.5">
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileUpload}
            multiple
            className="hidden"
          />
          <Button
            size="sm"
            variant="outline"
            className="h-8 text-xs gap-1"
            onClick={() => fileInputRef.current?.click()}
          >
            <Upload className="h-3.5 w-3.5" /> 上傳
          </Button>

          <Button
            size="sm"
            variant="outline"
            className="h-8 text-xs gap-1"
            onClick={() => setOpsType('mkdir')}
          >
            <FolderPlus className="h-3.5 w-3.5" /> 新增資料夾
          </Button>

          {selectedPaths.size > 0 && (
            <>
              <Button
                size="sm"
                variant="outline"
                className="h-8 text-xs gap-1"
                onClick={() => setOpsType('transfer')}
              >
                <ArrowRightLeft className="h-3.5 w-3.5" /> 傳輸/複製 ({selectedPaths.size})
              </Button>
              <Button
                size="sm"
                variant="destructive"
                className="h-8 text-xs gap-1"
                onClick={() => setOpsType('delete_batch')}
              >
                <Trash2 className="h-3.5 w-3.5" /> 刪除
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Path Breadcrumb Bar */}
      <div className="px-3 py-1.5 bg-muted/30 border-b border-border/60 text-xs flex items-center gap-1 text-muted-foreground overflow-x-auto whitespace-nowrap shrink-0">
        <button
          onClick={() => handleNavigate('/')}
          className="font-medium hover:text-foreground text-foreground/80 cursor-pointer flex items-center gap-1"
        >
          <HardDrive className="h-3.5 w-3.5 text-primary" />
          {currentRemote}:/
        </button>

        {pathSegments.map((seg, idx) => {
          const segPath = '/' + pathSegments.slice(0, idx + 1).join('/');
          const isLast = idx === pathSegments.length - 1;
          return (
            <React.Fragment key={segPath}>
              <ChevronRight className="h-3 w-3 text-muted-foreground/60 shrink-0" />
              <button
                onClick={() => handleNavigate(segPath)}
                className={`hover:text-foreground truncate max-w-[120px] ${
                  isLast ? 'text-foreground font-semibold' : 'text-muted-foreground'
                }`}
              >
                {seg}
              </button>
            </React.Fragment>
          );
        })}
      </div>

      {/* File Table Content Viewport */}
      <div className="flex-1 overflow-auto min-h-0">
        {isLoading ? (
          <div className="flex items-center justify-center h-48 text-xs text-muted-foreground">
            載入目錄檔案中...
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 text-center text-muted-foreground space-y-2">
            <Folder className="h-8 w-8 text-muted-foreground/40" />
            <p className="text-xs">此資料夾為空</p>
            <p className="text-[11px] text-muted-foreground/70">拖曳檔案至此處或點擊上方「上傳」開始傳輸</p>
          </div>
        ) : (
          <table className="w-full text-left text-xs border-collapse">
            <thead className="bg-muted/40 sticky top-0 border-b border-border/80 text-muted-foreground select-none z-10">
              <tr>
                <th className="w-8 py-2 px-3 text-center">
                  <Checkbox
                    checked={selectedPaths.size === items.length && items.length > 0}
                    onCheckedChange={toggleSelectAll}
                  />
                </th>
                <th className="py-2 px-2 font-medium">名稱</th>
                <th className="py-2 px-3 w-24 text-right font-medium">大小</th>
                <th className="py-2 px-3 w-32 font-medium hidden md:table-cell">修改時間</th>
                <th className="py-2 px-3 w-28 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/40">
              {items.map((item) => {
                const isSelected = selectedPaths.has(item.path);
                const isImg = /\.(png|jpe?g|gif|webp|svg)$/i.test(item.name);
                return (
                  <tr
                    key={item.path}
                    className={`hover:bg-accent/40 transition-colors group cursor-pointer ${
                      isSelected ? 'bg-primary/5' : ''
                    }`}
                    onClick={(e) => {
                      if ((e.target as HTMLElement).tagName.toLowerCase() === 'input' || (e.target as HTMLElement).closest('button')) {
                        return;
                      }
                      if (item.is_dir) {
                        handleNavigate(item.path);
                      } else {
                        setPreviewItem(item);
                      }
                    }}
                  >
                    <td className="py-2.5 px-3 text-center" onClick={(e) => e.stopPropagation()}>
                      <Checkbox
                        checked={isSelected}
                        onCheckedChange={() => toggleSelectItem(item.path)}
                      />
                    </td>
                    <td className="py-2.5 px-2">
                      <div className="flex items-center gap-2">
                        {item.is_dir ? (
                          <Folder className="h-4 w-4 text-amber-400 shrink-0 fill-amber-400/20" />
                        ) : isImg ? (
                          <ImageIcon className="h-4 w-4 text-emerald-400 shrink-0" />
                        ) : (
                          <FileText className="h-4 w-4 text-sky-400 shrink-0" />
                        )}
                        <span className="font-medium text-foreground truncate max-w-xs">{item.name}</span>
                      </div>
                    </td>
                    <td className="py-2.5 px-3 text-right text-muted-foreground font-mono text-[11px]">
                      {item.is_dir ? '-' : formatBytes(item.size)}
                    </td>
                    <td className="py-2.5 px-3 text-muted-foreground text-[11px] hidden md:table-cell">
                      {formatRelativeTime(item.modified_at)}
                    </td>
                    <td className="py-2.5 px-3 text-right" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center justify-end gap-1 opacity-80 group-hover:opacity-100">
                        {!item.is_dir && (
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7 text-muted-foreground hover:text-foreground"
                            onClick={() => setPreviewItem(item)}
                            title="預覽"
                          >
                            <Eye className="h-3.5 w-3.5" />
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-muted-foreground hover:text-foreground"
                          onClick={() => {
                            setSelectedPaths(new Set([item.path]));
                            setOpsType('rename');
                          }}
                          title="重新命名"
                        >
                          <Edit className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-muted-foreground hover:text-destructive"
                          onClick={() => {
                            setSelectedPaths(new Set([item.path]));
                            setOpsType('delete_batch');
                          }}
                          title="刪除"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Pane Footer Stats */}
      <div className="p-2.5 px-3 border-t border-border/80 bg-muted/20 text-xs text-muted-foreground flex items-center justify-between shrink-0">
        <span>共 {items.length} 個項目</span>
        {selectedPaths.size > 0 && <span>已選取 {selectedPaths.size} 個項目</span>}
      </div>

      {/* Modals */}
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
    </Card>
  );
}
