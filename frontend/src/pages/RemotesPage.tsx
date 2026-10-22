import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Server, Plus, Activity, HardDrive, Trash2, CheckCircle2, AlertCircle, RefreshCw, Layers } from 'lucide-react';
import { api } from '@/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription, CardFooter } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { formatBytes } from '@/lib/format';
import { toast } from 'sonner';
import { RemoteFormModal } from '@/components/remotes/RemoteFormModal';
import type { RemoteListResponse, QuotaResponse, TestRemoteResponse } from '@/api/types';

export function RemotesPage() {
  const queryClient = useQueryClient();
  const [testingRemote, setTestingRemote] = useState<string | null>(null);
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);

  const { data: remotesData, isLoading } = useQuery<RemoteListResponse>({
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
      toast.success(`節點 [${name}] 連線正常 (${res.latency_ms}ms)`);
    },
    onError: (err: any, name) => {
      setTestingRemote(null);
      toast.error(`節點 [${name}] 連線測試失敗: ${err.message}`);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (name: string) => api.request('DELETE', `/remotes/${name}`),
    onSuccess: (_, name) => {
      queryClient.invalidateQueries({ queryKey: ['remotes'] });
      toast.success(`已刪除節點 [${name}]`);
    },
    onError: (err: any) => {
      toast.error(`刪除節點失敗: ${err.message}`);
    },
  });

  const remotes = remotesData?.remotes || [];

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-foreground">儲存節點管理</h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            配置 Google Drive、OneDrive、SharePoint、WebDAV、PikPak 及本機儲存節點
          </p>
        </div>

        <Button size="sm" className="gap-1.5 shadow-sm" onClick={() => setIsAddModalOpen(true)}>
          <Plus className="h-4 w-4" /> 新增節點 (Add Remote)
        </Button>
      </div>

      {isLoading ? (
        <div className="py-20 text-center text-muted-foreground">載入儲存節點清單中...</div>
      ) : remotes.length === 0 ? (
        <div className="py-20 border border-dashed border-border rounded-xl text-center space-y-3">
          <Server className="h-10 w-10 text-muted-foreground/40 mx-auto" />
          <h3 className="font-semibold text-foreground">尚未設定任何儲存節點</h3>
          <p className="text-xs text-muted-foreground max-w-sm mx-auto">請點擊上方按鈕建立您的第一個雲端或本地儲存節點。</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
          {remotes.map((remote) => (
            <RemoteCard
              key={remote.name}
              remote={remote}
              isTesting={testingRemote === remote.name}
              onTest={() => testMutation.mutate(remote.name)}
              onDelete={() => {
                if (confirm(`確定要刪除儲存節點 [${remote.name}] 嗎？`)) {
                  deleteMutation.mutate(remote.name);
                }
              }}
            />
          ))}
        </div>
      )}

      <RemoteFormModal
        open={isAddModalOpen}
        onOpenChange={setIsAddModalOpen}
      />
    </div>
  );
}

function RemoteCard({
  remote,
  isTesting,
  onTest,
  onDelete,
}: {
  remote: any;
  isTesting: boolean;
  onTest: () => void;
  onDelete: () => void;
}) {
  const { data: quota } = useQuery<QuotaResponse>({
    queryKey: ['quota', remote.name],
    queryFn: () => api.request('GET', `/remotes/${remote.name}/quota`),
    staleTime: 300000,
  });

  const percentUsed = quota?.supported && quota.total > 0 ? Math.round((quota.used / quota.total) * 100) : 0;

  return (
    <Card className="flex flex-col justify-between hover:border-primary/50 transition-all">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2.5 overflow-hidden">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 border border-primary/20 text-primary">
              <HardDrive className="h-4 w-4" />
            </div>
            <div className="truncate">
              <CardTitle className="text-base truncate flex items-center gap-1.5">
                <span>{remote.name}</span>
                {remote.is_default && (
                  <Badge variant="outline" className="text-[10px] h-4 px-1 border-primary/30 text-primary">
                    預設
                  </Badge>
                )}
              </CardTitle>
              <CardDescription className="text-xs font-mono text-muted-foreground">{remote.type}</CardDescription>
            </div>
          </div>

          {remote.health && (
            <Badge
              variant={remote.health.status === 'success' ? 'success' : 'destructive'}
              className="text-[10px] shrink-0 font-mono"
            >
              {remote.health.status === 'success' ? `${remote.health.latency_ms}ms` : '異常'}
            </Badge>
          )}
        </div>
      </CardHeader>

      <CardContent className="space-y-3 pb-3">
        {/* Quota info */}
        <div className="space-y-1.5 p-2.5 rounded-lg bg-muted/40 border border-border/60">
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">儲存空間配額</span>
            <span className="font-medium text-foreground">
              {quota?.supported
                ? `${formatBytes(quota.used)} / ${formatBytes(quota.total)} (${percentUsed}%)`
                : '不支援空間統計'}
            </span>
          </div>
          {quota?.supported && <Progress value={percentUsed} className="h-1.5" />}
        </div>
      </CardContent>

      <CardFooter className="pt-2 border-t border-border/80 flex items-center justify-between gap-2">
        <Button variant="outline" size="sm" onClick={onTest} disabled={isTesting} className="text-xs h-8 gap-1.5">
          {isTesting ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Activity className="h-3.5 w-3.5" />}
          <span>連線測試</span>
        </Button>

        <Button
          variant="ghost"
          size="iconSm"
          onClick={onDelete}
          className="text-muted-foreground hover:text-destructive h-8 w-8"
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </CardFooter>
    </Card>
  );
}
