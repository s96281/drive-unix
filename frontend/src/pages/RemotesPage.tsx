import React, { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Server,
  Plus,
  Activity,
  Trash2,
  RefreshCw,
  FolderOpen,
  Edit2,
} from 'lucide-react';
import { api } from '@/api';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Switch } from '@/components/ui/switch';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { formatBytes } from '@/lib/format';
import { toast } from 'sonner';
import { RemoteFormModal } from '@/components/remotes/RemoteFormModal';
import type { RemoteListResponse, QuotaResponse, TestRemoteResponse } from '@/api/types';

/**
 * AList Manage Storages Page (`src/pages/manage/storages/Storages.tsx` & `Storage.tsx`)
 */
export function RemotesPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [testingRemote, setTestingRemote] = useState<string | null>(null);
  const [isTestingAll, setIsTestingAll] = useState(false);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [driverFilter, setDriverFilter] = useState<string>('__all__');
  const [layout, setLayout] = useState<'grid' | 'table'>(() => {
    if (typeof window === 'undefined') return 'grid';
    return (localStorage.getItem('du.storagesLayout') as 'grid' | 'table') || 'grid';
  });

  const handleToggleLayout = (checked: boolean) => {
    const next = checked ? 'table' : 'grid';
    setLayout(next);
    localStorage.setItem('du.storagesLayout', next);
  };

  const { data: remotesData, isLoading, isFetching, refetch } = useQuery<RemoteListResponse>({
    queryKey: ['remotes'],
    queryFn: () => api.request('GET', '/remotes'),
  });

  const testMutation = useMutation({
    mutationFn: async (name: string) => {
      setTestingRemote(name);
      return api.request<TestRemoteResponse>('POST', `/remotes/${name}/test`, {
        body: { write: false },
      });
    },
    onSuccess: (res, name) => {
      setTestingRemote(null);
      queryClient.invalidateQueries({ queryKey: ['remotes'] });
      toast.success(`儲存節點 [/${name}] 連線正常 (${res.latency_ms}ms)`);
    },
    onError: (err: any, name) => {
      setTestingRemote(null);
      toast.error(`儲存節點 [/${name}] 連線測試失敗: ${err.message}`);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (name: string) => api.request('DELETE', `/remotes/${name}`),
    onSuccess: (_, name) => {
      queryClient.invalidateQueries({ queryKey: ['remotes'] });
      toast.success(`已刪除儲存節點 [/${name}]`);
    },
    onError: (err: any) => {
      toast.error(`刪除節點失敗: ${err.message}`);
    },
  });

  const remotes = remotesData?.remotes || [];

  const availableDrivers = useMemo(() => {
    const set = new Set<string>();
    for (const r of remotes) {
      if (r.type) set.add(r.type);
    }
    return Array.from(set);
  }, [remotes]);

  const shownRemotes = useMemo(() => {
    if (driverFilter === '__all__') return remotes;
    return remotes.filter((r) => r.type === driverFilter);
  }, [remotes, driverFilter]);

  const handleTestAll = async () => {
    if (remotes.length === 0) return;
    setIsTestingAll(true);
    try {
      for (const r of remotes) {
        await api.request('POST', `/remotes/${r.name}/test`, { body: { write: false } });
      }
      await queryClient.invalidateQueries({ queryKey: ['remotes'] });
      toast.success(`已完成全部 ${remotes.length} 個儲存節點健康度檢測`);
    } catch (err: any) {
      toast.error(`部分節點檢測異常: ${err.message}`);
    } finally {
      setIsTestingAll(false);
    }
  };

  return (
    <div className="space-y-4 w-full">
      {/* AList Storages Top Action Bar (`HStack spacing="$2" wrap="wrap"`) */}
      <div className="flex flex-wrap items-center gap-2.5">
        <Button
          variant="subtle"
          size="sm"
          onClick={() => void refetch()}
          disabled={isFetching}
          className="gap-1.5"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${isFetching ? 'animate-spin' : ''}`} />
          <span>重新整理</span>
        </Button>

        <Button
          variant="default"
          size="sm"
          onClick={() => navigate('/@manage/storages/add')}
          className="gap-1.5"
        >
          <Plus className="h-4 w-4" />
          <span>新增</span>
        </Button>

        <Button
          variant="warning"
          size="sm"
          onClick={() => void handleTestAll()}
          disabled={isTestingAll || remotes.length === 0}
          className="gap-1.5"
        >
          <Activity className={`h-3.5 w-3.5 ${isTestingAll ? 'animate-spin' : ''}`} />
          <span>全部測試載入</span>
        </Button>

        {availableDrivers.length > 0 && (
          <Select value={driverFilter} onValueChange={setDriverFilter}>
            <SelectTrigger className="w-44 h-8 text-xs bg-input/80 border-transparent">
              <SelectValue placeholder="依驅動類型篩選" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__all__">全部驅動類型 ({remotes.length})</SelectItem>
              {availableDrivers.map((d) => (
                <SelectItem key={d} value={d}>
                  {d}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        <label className="flex items-center gap-2 text-xs font-medium text-foreground cursor-pointer select-none ml-1">
          <Switch checked={layout === 'table'} onCheckedChange={handleToggleLayout} />
          <span>表格佈局 (Table Layout)</span>
        </label>
      </div>

      {/* Main Content: Grid vs Table */}
      {isLoading ? (
        <div className="py-20 text-center text-sm text-muted-foreground">載入儲存節點清單中...</div>
      ) : shownRemotes.length === 0 ? (
        <div className="py-20 border border-dashed border-border rounded-xl text-center space-y-3 bg-[var(--alist-card-bg)]">
          <Server className="h-10 w-10 text-muted-foreground/40 mx-auto" />
          <h3 className="font-semibold text-foreground">尚未設定符合條件的儲存節點</h3>
          <p className="text-xs text-muted-foreground max-w-sm mx-auto">
            請點擊上方「新增」按鈕掛載 Google Drive、OneDrive、SharePoint、WebDAV、PikPak 或本機目錄。
          </p>
        </div>
      ) : layout === 'grid' ? (
        /* AList StorageGridItem Grid (`repeat(auto-fill, minmax(324px, 1fr))`) */
        <div
          className="grid gap-3.5 w-full"
          style={{
            gridTemplateColumns: 'repeat(auto-fill, minmax(324px, 1fr))',
          }}
        >
          {shownRemotes.map((remote) => (
            <StorageGridItem
              key={remote.name}
              remote={remote}
              isTesting={testingRemote === remote.name}
              onExplore={() => navigate(`/files?remote=${encodeURIComponent(remote.name)}&path=/`)}
              onEdit={() => navigate(`/@manage/storages/edit/${encodeURIComponent(remote.name)}`)}
              onTest={() => testMutation.mutate(remote.name)}
              onDelete={() => {
                if (confirm(`確定要刪除儲存節點 [/${remote.name}] 嗎？`)) {
                  deleteMutation.mutate(remote.name);
                }
              }}
            />
          ))}
        </div>
      ) : (
        /* AList StorageListItem Table (`Table highlightOnHover dense`) */
        <div className="w-full overflow-x-auto rounded-xl border border-border/70 bg-[var(--alist-card-bg)] shadow-xs">
          <table className="w-full text-left text-xs border-collapse">
            <thead className="bg-muted/50 border-b border-border/70 text-muted-foreground select-none">
              <tr>
                <th className="py-2.5 px-4 font-semibold">掛載路徑 (Mount Path)</th>
                <th className="py-2.5 px-4 font-semibold">驅動類型 (Driver)</th>
                <th className="py-2.5 px-4 font-semibold">狀態 (Status)</th>
                <th className="py-2.5 px-4 font-semibold">空間配額 / 備註</th>
                <th className="py-2.5 px-4 font-semibold text-right">操作 (Operations)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/40">
              {shownRemotes.map((remote) => (
                <StorageListItem
                  key={remote.name}
                  remote={remote}
                  isTesting={testingRemote === remote.name}
                  onExplore={() => navigate(`/files?remote=${encodeURIComponent(remote.name)}&path=/`)}
                  onEdit={() => navigate(`/@manage/storages/edit/${encodeURIComponent(remote.name)}`)}
                  onTest={() => testMutation.mutate(remote.name)}
                  onDelete={() => {
                    if (confirm(`確定要刪除儲存節點 [/${remote.name}] 嗎？`)) {
                      deleteMutation.mutate(remote.name);
                    }
                  }}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <RemoteFormModal open={isAddModalOpen} onOpenChange={setIsAddModalOpen} />
    </div>
  );
}

function StorageGridItem({
  remote,
  isTesting,
  onExplore,
  onEdit,
  onTest,
  onDelete,
}: {
  remote: any;
  isTesting: boolean;
  onExplore: () => void;
  onEdit: () => void;
  onTest: () => void;
  onDelete: () => void;
}) {
  const { data: quota } = useQuery<QuotaResponse>({
    queryKey: ['quota', remote.name],
    queryFn: () => api.request('GET', `/remotes/${remote.name}/quota`),
    staleTime: 300000,
  });

  const percentUsed =
    quota?.supported && quota.total > 0 ? Math.round((quota.used / quota.total) * 100) : 0;

  return (
    <div className="rounded-xl border border-border/80 bg-[var(--alist-card-bg)] p-4 flex flex-col items-center justify-between gap-2.5 hover:border-[var(--alist-main)] transition-colors shadow-2xs">
      {/* Row 1: Mount Path & Driver Badge (centered like AList StorageGridItem) */}
      <div className="flex items-center justify-center gap-2 flex-wrap">
        <span
          onClick={onExplore}
          className="font-semibold text-base text-foreground hover:text-[var(--alist-main)] cursor-pointer break-all"
        >
          /{remote.name}
        </span>
        <Badge variant="info" className="text-xs font-mono">
          {remote.type}
        </Badge>
        {remote.is_default && (
          <Badge variant="default" className="text-[10px]">
            預設
          </Badge>
        )}
      </div>

      {/* Row 2: Status line (`狀態: work`) */}
      <div className="flex items-center gap-1.5 text-xs">
        <span className="text-muted-foreground">狀態:</span>
        {remote.health?.status === 'success' ? (
          <span className="text-emerald-500 font-medium font-mono">
            work ({remote.health.latency_ms}ms)
          </span>
        ) : (
          <span className="text-amber-500 font-medium">standby</span>
        )}
      </div>

      {/* Row 3: Quota Bar */}
      <div className="w-full space-y-1 px-2 py-1.5 rounded-lg bg-muted/40">
        <div className="flex items-center justify-between text-[11px]">
          <span className="text-muted-foreground">空間用量</span>
          <span className="font-mono text-foreground">
            {quota?.supported
              ? `${formatBytes(quota.used)} / ${formatBytes(quota.total)} (${percentUsed}%)`
              : '無配額統計'}
          </span>
        </div>
        {quota?.supported && <Progress value={percentUsed} className="h-1.5" />}
      </div>

      {/* Row 4: AList StorageOp Subtle Buttons */}
      <div className="flex items-center justify-center gap-1.5 pt-1 flex-wrap">
        <Button variant="subtle" size="sm" onClick={onExplore} className="h-8 text-xs gap-1">
          <FolderOpen className="h-3.5 w-3.5" />
          <span>瀏覽</span>
        </Button>

        <Button variant="subtle" size="sm" onClick={onEdit} className="h-8 text-xs gap-1">
          <Edit2 className="h-3.5 w-3.5" />
          <span>編輯</span>
        </Button>

        <Button
          variant="warning"
          size="sm"
          onClick={onTest}
          disabled={isTesting}
          className="h-8 text-xs gap-1"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${isTesting ? 'animate-spin' : ''}`} />
          <span>測試</span>
        </Button>

        <Button variant="destructive" size="sm" onClick={onDelete} className="h-8 text-xs gap-1">
          <Trash2 className="h-3.5 w-3.5" />
          <span>刪除</span>
        </Button>
      </div>
    </div>
  );
}

function StorageListItem({
  remote,
  isTesting,
  onExplore,
  onEdit,
  onTest,
  onDelete,
}: {
  remote: any;
  isTesting: boolean;
  onExplore: () => void;
  onEdit: () => void;
  onTest: () => void;
  onDelete: () => void;
}) {
  const { data: quota } = useQuery<QuotaResponse>({
    queryKey: ['quota', remote.name],
    queryFn: () => api.request('GET', `/remotes/${remote.name}/quota`),
    staleTime: 300000,
  });

  return (
    <tr className="hover:bg-[var(--alist-hover)] transition-colors">
      <td className="py-2.5 px-4 font-semibold text-foreground">
        <button
          type="button"
          onClick={onExplore}
          className="hover:text-[var(--alist-main)] cursor-pointer font-mono"
        >
          /{remote.name}
        </button>
      </td>
      <td className="py-2.5 px-4">
        <Badge variant="info" className="font-mono text-[11px]">
          {remote.type}
        </Badge>
      </td>
      <td className="py-2.5 px-4 font-mono">
        {remote.health?.status === 'success' ? (
          <span className="text-emerald-500 font-medium">work ({remote.health.latency_ms}ms)</span>
        ) : (
          <span className="text-amber-500">standby</span>
        )}
      </td>
      <td className="py-2.5 px-4 text-muted-foreground font-mono">
        {quota?.supported ? `${formatBytes(quota.used)} / ${formatBytes(quota.total)}` : '-'}
      </td>
      <td className="py-2.5 px-4 text-right">
        <div className="flex items-center justify-end gap-1.5">
          <Button variant="subtle" size="sm" onClick={onExplore} className="h-7 px-2.5 text-xs">
            瀏覽
          </Button>
          <Button variant="subtle" size="sm" onClick={onEdit} className="h-7 px-2.5 text-xs">
            編輯
          </Button>
          <Button
            variant="warning"
            size="sm"
            onClick={onTest}
            disabled={isTesting}
            className="h-7 px-2.5 text-xs"
          >
            測試
          </Button>
          <Button variant="destructive" size="sm" onClick={onDelete} className="h-7 px-2.5 text-xs">
            刪除
          </Button>
        </div>
      </td>
    </tr>
  );
}
