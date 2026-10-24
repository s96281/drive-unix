import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Play,
  Pause,
  RotateCcw,
  XCircle,
  RefreshCw,
  GitCompare,
  Sliders,
  CheckCircle2,
  AlertCircle,
  Clock,
  Zap,
  ArrowRight,
  FolderSync,
  FileCheck,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { api } from '@/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { formatBytes, formatSpeed, formatEta, formatRelativeTime } from '@/lib/format';
import { SYNC_MODE_LIST } from '@/lib/sync-modes';
import { SyncPlanDiffDialog } from '@/components/sync/SyncPlanDiffDialog';
import { toast } from 'sonner';
import type { RemoteListResponse, TaskRecord, SyncPlanResponse } from '@/api/types';

export function SyncPage() {
  const queryClient = useQueryClient();

  // Builder state
  const [sourceRemote, setSourceRemote] = useState('gdrive');
  const [sourcePath, setSourcePath] = useState('/Backups');
  const [destRemote, setDestRemote] = useState('onedrive');
  const [destPath, setDestPath] = useState('/CloudBackup');
  const [mode, setMode] = useState<'copy' | 'sync' | 'mirror'>('sync');
  const [conflictResolution, setConflictResolution] = useState<'newer' | 'overwrite' | 'skip'>('newer');
  const [deleteExtra, setDeleteExtra] = useState(false);
  const [checksum, setChecksum] = useState(true);
  const [workers, setWorkers] = useState(4);

  // Dry run dialog state
  const [diffPlan, setDiffPlan] = useState<SyncPlanResponse | null>(null);
  const [isDiffOpen, setIsDiffOpen] = useState(false);
  const [expandedLogs, setExpandedLogs] = useState<Set<string>>(new Set());

  // Fetch remotes
  const { data: remotesData } = useQuery<RemoteListResponse>({
    queryKey: ['remotes'],
    queryFn: () => api.request('GET', '/remotes'),
  });

  const remotes = remotesData?.remotes || [];

  // Fetch tasks
  const { data: tasksData, refetch: refetchTasks } = useQuery<TaskRecord[]>({
    queryKey: ['tasks'],
    queryFn: () => api.request('GET', '/sync/tasks'),
    refetchInterval: 3000,
  });

  const tasks = tasksData || [];
  const activeTasks = tasks.filter((t) => t.status === 'running' || t.status === 'paused' || t.status === 'queued');
  const historyTasks = tasks.filter((t) => t.status === 'completed' || t.status === 'failed' || t.status === 'cancelled');

  // Mutations
  const planMutation = useMutation({
    mutationFn: () =>
      api.request<SyncPlanResponse>('POST', '/sync/plan', {
        body: {
          source: `${sourceRemote}:${sourcePath}`,
          destination: `${destRemote}:${destPath}`,
          mode,
          conflict_resolution: conflictResolution,
          delete_extra: mode === 'mirror' ? true : deleteExtra,
          checksum,
        },
      }),
    onSuccess: (data) => {
      setDiffPlan(data);
      setIsDiffOpen(true);
    },
    onError: (err: any) => {
      toast.error(`預檢失敗: ${err.message}`);
    },
  });

  const startMutation = useMutation({
    mutationFn: () =>
      api.request('POST', '/sync/start', {
        body: {
          source: `${sourceRemote}:${sourcePath}`,
          destination: `${destRemote}:${destPath}`,
          mode,
          conflict_resolution: conflictResolution,
          delete_extra: mode === 'mirror' ? true : deleteExtra,
          checksum,
          workers,
        },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      setIsDiffOpen(false);
      toast.success('同步任務已啟動！');
    },
    onError: (err: any) => {
      toast.error(`啟動同步失敗: ${err.message}`);
    },
  });

  const pauseMutation = useMutation({
    mutationFn: (id: string) => api.request('POST', `/tasks/${id}/pause`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      toast.success('已暫停任務傳輸');
    },
    onError: (err: any) => toast.error(err.message),
  });

  const resumeMutation = useMutation({
    mutationFn: (id: string) => api.request('POST', `/tasks/${id}/resume`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      toast.success('已恢復任務傳輸');
    },
    onError: (err: any) => toast.error(err.message),
  });

  const cancelMutation = useMutation({
    mutationFn: (id: string) => api.request('POST', `/tasks/${id}/cancel`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      toast.success('已取消任務');
    },
    onError: (err: any) => toast.error(err.message),
  });

  const retryMutation = useMutation({
    mutationFn: (id: string) => api.request('POST', `/tasks/${id}/retry`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      toast.success('任務已重新加入佇列');
    },
    onError: (err: any) => toast.error(err.message),
  });

  const toggleExpandLogs = (id: string) => {
    const next = new Set(expandedLogs);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setExpandedLogs(next);
  };

  return (
    <div className="space-y-5 w-full">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-foreground">跨端同步與傳輸任務 (Tasks)</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            規劃跨網盤增量備份、雙向同步、即時傳輸控制與歷史任務紀錄
          </p>
        </div>
      </div>

      {/* Sync Job Builder Card */}
      <Card className="bg-[var(--alist-card-bg)]">
        <CardHeader className="pb-4">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-[var(--alist-main-subtle)] text-[var(--alist-main)]">
              <FolderSync className="h-5 w-5" />
            </div>
            <div>
              <CardTitle className="text-base font-semibold">新建同步任務 (Sync Job Builder)</CardTitle>
              <CardDescription className="text-xs">設定來源端與目的端儲存路徑，並挑選最適備份模式與比對策略</CardDescription>
            </div>
          </div>
        </CardHeader>

        <CardContent className="space-y-5">
          {/* Source & Destination Pickers */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 p-4 rounded-xl border border-border/80 bg-accent/10">
            {/* Source */}
            <div className="space-y-2">
              <span className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-emerald-500" />
                來源路徑 (Source)
              </span>
              <div className="flex items-center gap-2">
                <Select value={sourceRemote} onValueChange={setSourceRemote}>
                  <SelectTrigger className="w-[140px] h-9 text-xs">
                    <SelectValue placeholder="來源節點" />
                  </SelectTrigger>
                  <SelectContent>
                    {remotes.map((r) => (
                      <SelectItem key={r.name} value={r.name}>
                        {r.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Input
                  value={sourcePath}
                  onChange={(e) => setSourcePath(e.target.value)}
                  placeholder="/目錄路徑"
                  className="font-mono text-xs"
                />
              </div>
            </div>

            {/* Destination */}
            <div className="space-y-2">
              <span className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-sky-500" />
                目的路徑 (Destination)
              </span>
              <div className="flex items-center gap-2">
                <Select value={destRemote} onValueChange={setDestRemote}>
                  <SelectTrigger className="w-[140px] h-9 text-xs">
                    <SelectValue placeholder="目的節點" />
                  </SelectTrigger>
                  <SelectContent>
                    {remotes.map((r) => (
                      <SelectItem key={r.name} value={r.name}>
                        {r.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Input
                  value={destPath}
                  onChange={(e) => setDestPath(e.target.value)}
                  placeholder="/目錄路徑"
                  className="font-mono text-xs"
                />
              </div>
            </div>
          </div>

          {/* Sync Mode Selector Cards */}
          <div className="space-y-2">
            <label className="text-xs font-semibold text-foreground">同步模式 (Sync Mode)</label>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {SYNC_MODE_LIST.map((m) => {
                const isSelected = mode === m.mode;
                return (
                  <button
                    key={m.mode}
                    type="button"
                    onClick={() => {
                      setMode(m.mode as any);
                      if (m.mode === 'mirror') setDeleteExtra(true);
                      if (m.mode === 'copy') setDeleteExtra(false);
                    }}
                    className={`p-3.5 rounded-lg border text-left transition-all cursor-pointer ${
                      isSelected
                        ? 'border-primary bg-primary/10 shadow-xs'
                        : 'border-border bg-card hover:border-border/80'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-semibold text-xs text-foreground">{m.label}</span>
                      {isSelected && <Badge className="text-[10px] h-4">選中</Badge>}
                    </div>
                    <p className="text-[11px] text-muted-foreground leading-relaxed">{m.description}</p>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Detailed Options Row */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-1">
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-foreground">檔案衝突處理 (Conflict)</label>
              <Select value={conflictResolution} onValueChange={(v: any) => setConflictResolution(v)}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="newer">較新優先 (Newer Wins)</SelectItem>
                  <SelectItem value="overwrite">直接覆蓋 (Always Overwrite)</SelectItem>
                  <SelectItem value="skip">跳過已存在 (Skip Existing)</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-foreground">並行傳輸緒 (Workers)</label>
              <Input
                type="number"
                min={1}
                max={16}
                value={workers}
                onChange={(e) => setWorkers(parseInt(e.target.value) || 4)}
                className="h-8 text-xs font-mono"
              />
            </div>

            <div className="space-y-2 pt-5">
              <label className="flex items-center gap-2 cursor-pointer text-xs text-foreground select-none">
                <input
                  type="checkbox"
                  checked={mode === 'mirror' ? true : deleteExtra}
                  disabled={mode === 'mirror'}
                  onChange={(e) => setDeleteExtra(e.target.checked)}
                  className="rounded text-primary focus:ring-primary"
                />
                刪除目的端多餘檔案 (Delete Extra)
              </label>

              <label className="flex items-center gap-2 cursor-pointer text-xs text-foreground select-none">
                <input
                  type="checkbox"
                  checked={checksum}
                  onChange={(e) => setChecksum(e.target.checked)}
                  className="rounded text-primary focus:ring-primary"
                />
                雜湊校驗比對 (Checksum Verify)
              </label>
            </div>
          </div>

          {/* Action Footer */}
          <div className="flex items-center justify-end gap-3 pt-2 border-t border-border">
            <Button
              variant="outline"
              size="sm"
              onClick={() => planMutation.mutate()}
              disabled={planMutation.isPending}
              className="gap-1.5"
            >
              <GitCompare className="h-4 w-4" />
              {planMutation.isPending ? '分析規劃中...' : '預檢計畫 (Dry-Run)'}
            </Button>
            <Button
              size="sm"
              onClick={() => startMutation.mutate()}
              disabled={startMutation.isPending}
              className="gap-1.5 shadow-sm"
            >
              <Play className="h-4 w-4" />
              {startMutation.isPending ? '啟動中...' : '立即啟動同步'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Active Tasks Section */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h3 className="text-base font-semibold text-foreground">進行中任務 (Active Tasks)</h3>
            <Badge variant="secondary" className="font-mono text-xs">
              {activeTasks.length}
            </Badge>
          </div>
          <Button variant="ghost" size="sm" onClick={() => refetchTasks()} className="h-7 text-xs gap-1">
            <RefreshCw className="h-3 w-3" /> 重新整理
          </Button>
        </div>

        {activeTasks.length === 0 ? (
          <Card className="p-8 text-center border-dashed">
            <Clock className="h-8 w-8 text-muted-foreground/40 mx-auto mb-2" />
            <p className="text-xs text-muted-foreground">目前沒有進行中的傳輸任務</p>
          </Card>
        ) : (
          <div className="space-y-3">
            {activeTasks.map((task) => {
              const taskId = task.task_id || task.id;
              const bytesTransferred = task.bytes_transferred ?? task.bytes_done ?? 0;
              const filesTransferred = task.files_transferred ?? task.files_done ?? 0;
              const sourceText = task.source || task.source_uri || '未知來源';
              const destText = task.destination || task.dest_uri || '未知目的';
              const progressPct =
                task.bytes_total > 0
                  ? Math.min(100, Math.round((bytesTransferred / task.bytes_total) * 100))
                  : 0;
              const isPaused = task.status === 'paused';
              const isLogsExpanded = expandedLogs.has(taskId);

              return (
                <Card key={taskId} className="overflow-hidden border border-border">
                  <div className="p-4 space-y-3">
                    {/* Top Row: Path & Status */}
                    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                      <div className="space-y-0.5">
                        <div className="flex items-center gap-2">
                          <Badge
                            variant={isPaused ? 'outline' : 'default'}
                            className={`text-xs ${
                              isPaused
                                ? 'border-amber-500 text-amber-400'
                                : 'bg-primary text-primary-foreground'
                            }`}
                          >
                            {isPaused ? '已暫停 (Paused)' : '執行中 (Running)'}
                          </Badge>
                          <span className="font-mono text-xs text-muted-foreground">{taskId}</span>
                        </div>
                        <div className="text-sm font-semibold text-foreground flex items-center gap-2 mt-1">
                          <span>{sourceText}</span>
                          <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
                          <span>{destText}</span>
                        </div>
                      </div>

                      {/* Action buttons */}
                      <div className="flex items-center gap-1.5 shrink-0">
                        {isPaused ? (
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-8 text-xs gap-1"
                            onClick={() => resumeMutation.mutate(taskId)}
                          >
                            <Play className="h-3.5 w-3.5 text-emerald-400" /> 繼續
                          </Button>
                        ) : (
                          <Button
                            variant="outline"
                            size="sm"
                            className="h-8 text-xs gap-1"
                            onClick={() => pauseMutation.mutate(taskId)}
                          >
                            <Pause className="h-3.5 w-3.5 text-amber-400" /> 暫停
                          </Button>
                        )}

                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-8 text-xs text-destructive hover:text-destructive gap-1"
                          onClick={() => cancelMutation.mutate(taskId)}
                        >
                          <XCircle className="h-3.5 w-3.5" /> 取消
                        </Button>
                      </div>
                    </div>

                    {/* Progress Bar */}
                    <div className="space-y-1.5">
                      <div className="flex items-center justify-between text-xs text-muted-foreground font-mono">
                        <span>
                          {formatBytes(bytesTransferred)} / {formatBytes(task.bytes_total)} ({progressPct}%)
                        </span>
                        <div className="flex items-center gap-3">
                          <span>速度: {formatSpeed(task.speed_bps)}</span>
                          <span>剩餘時間: {formatEta(task.eta_seconds)}</span>
                        </div>
                      </div>
                      <Progress value={progressPct} className="h-2" />
                    </div>

                    {/* Footer Info */}
                    <div className="flex items-center justify-between text-[11px] text-muted-foreground pt-1">
                      <span>
                        已傳輸檔案: {filesTransferred} / {task.files_total}
                      </span>
                      <button
                        onClick={() => toggleExpandLogs(taskId)}
                        className="flex items-center gap-1 hover:text-foreground cursor-pointer font-medium"
                      >
                        {isLogsExpanded ? '收合日誌' : '檢視執行日誌'}
                        {isLogsExpanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                      </button>
                    </div>

                    {/* Expandable Task Logs */}
                    {isLogsExpanded && (
                      <div className="p-3 rounded-lg bg-black/30 border border-border/80 font-mono text-[11px] text-muted-foreground space-y-1 max-h-40 overflow-y-auto">
                        {task.logs && task.logs.length > 0 ? (
                          task.logs.map((line: string, idx: number) => (
                            <div key={idx} className="leading-relaxed">
                              {line}
                            </div>
                          ))
                        ) : (
                          <div className="text-muted-foreground/60">(暫無日誌紀錄)</div>
                        )}
                      </div>
                    )}
                  </div>
                </Card>
              );
            })}
          </div>
        )}
      </div>

      {/* Task History Section */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <h3 className="text-base font-semibold text-foreground">傳輸紀錄 (Task History)</h3>
          <Badge variant="secondary" className="font-mono text-xs">
            {historyTasks.length}
          </Badge>
        </div>

        {historyTasks.length === 0 ? (
          <Card className="p-6 text-center border-dashed">
            <p className="text-xs text-muted-foreground">尚無歷史傳輸紀錄</p>
          </Card>
        ) : (
          <div className="border border-border rounded-lg overflow-hidden bg-card">
            <table className="w-full text-left text-xs border-collapse">
              <thead className="bg-muted/40 border-b border-border text-muted-foreground">
                <tr>
                  <th className="py-2.5 px-3 font-medium">任務 ID</th>
                  <th className="py-2.5 px-3 font-medium">狀態</th>
                  <th className="py-2.5 px-3 font-medium">路徑 (Source ➔ Destination)</th>
                  <th className="py-2.5 px-3 font-medium text-right">傳輸大小</th>
                  <th className="py-2.5 px-3 font-medium text-right">完成時間</th>
                  <th className="py-2.5 px-3 font-medium text-right">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {historyTasks.map((t) => {
                  const taskId = t.task_id || t.id;
                  const bytesTransferred = t.bytes_transferred ?? t.bytes_done ?? 0;
                  const sourceText = t.source || t.source_uri || '未知來源';
                  const destText = t.destination || t.dest_uri || '未知目的';
                  const endedTime = t.ended_at || t.finished_at;

                  return (
                    <tr key={taskId} className="hover:bg-accent/40">
                      <td className="py-2 px-3 font-mono text-muted-foreground">{taskId}</td>
                      <td className="py-2 px-3">
                        {t.status === 'completed' && (
                          <Badge variant="outline" className="border-emerald-500 text-emerald-400 text-[10px]">
                            完成
                          </Badge>
                        )}
                        {t.status === 'failed' && (
                          <Badge variant="destructive" className="text-[10px]">
                            失敗
                          </Badge>
                        )}
                        {t.status === 'cancelled' && (
                          <Badge variant="secondary" className="text-[10px] text-muted-foreground">
                            已取消
                          </Badge>
                        )}
                      </td>
                      <td className="py-2 px-3 font-mono text-foreground truncate max-w-sm">
                        {sourceText} ➔ {destText}
                      </td>
                      <td className="py-2 px-3 text-right font-mono text-muted-foreground">
                        {formatBytes(bytesTransferred)}
                      </td>
                      <td className="py-2 px-3 text-right text-muted-foreground">
                        {endedTime ? formatRelativeTime(endedTime) : '-'}
                      </td>
                      <td className="py-2 px-3 text-right">
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-6 text-[11px] gap-1"
                          onClick={() => retryMutation.mutate(taskId)}
                        >
                          <RotateCcw className="h-3 w-3" /> 重跑
                        </Button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Dry Run Plan Diff Modal */}
      <SyncPlanDiffDialog
        open={isDiffOpen}
        onOpenChange={setIsDiffOpen}
        plan={diffPlan}
        onExecute={() => startMutation.mutate()}
        isExecuting={startMutation.isPending}
      />
    </div>
  );
}
