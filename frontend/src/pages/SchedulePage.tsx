import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Calendar,
  Clock,
  Play,
  Square,
  RotateCw,
  Plus,
  Trash2,
  Edit,
  Terminal,
  Activity,
  CheckCircle2,
  AlertCircle,
  Cpu,
} from 'lucide-react';
import { api } from '@/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { formatCron } from '@/lib/cron';
import { formatRelativeTime } from '@/lib/format';
import { ScheduleFormDialog } from '@/components/schedule/ScheduleFormDialog';
import { toast } from 'sonner';
import type { DaemonStatusResponse, TaskItemResponse } from '@/api/types';

export function SchedulePage() {
  const queryClient = useQueryClient();
  const [formOpen, setFormOpen] = useState(false);
  const [editingTask, setEditingTask] = useState<TaskItemResponse | null>(null);

  // Queries
  const { data: daemonData, refetch: refetchDaemon } = useQuery<DaemonStatusResponse>({
    queryKey: ['daemon-status'],
    queryFn: () => api.request('GET', '/schedule/daemon/status'),
    refetchInterval: 5000,
  });

  const { data: schedulesData, isLoading, refetch: refetchSchedules } = useQuery<TaskItemResponse[]>({
    queryKey: ['schedules'],
    queryFn: () => api.request('GET', '/schedule'),
  });

  const isRunning = daemonData?.status === 'running' || !!daemonData?.running;
  const daemonLogs = daemonData?.logs || daemonData?.log_tail || [];
  const schedules = schedulesData || [];

  // Mutations
  const daemonControlMutation = useMutation({
    mutationFn: (action: 'start' | 'stop' | 'restart') =>
      api.request('POST', `/schedule/daemon/${action}`),
    onSuccess: (_, action) => {
      queryClient.invalidateQueries({ queryKey: ['daemon-status'] });
      toast.success(`Daemon 守護行程已${action === 'start' ? '啟動' : action === 'stop' ? '停止' : '重啟'}`);
    },
    onError: (err: any) => {
      toast.error(`Daemon 操作失敗: ${err.message}`);
    },
  });

  const toggleTaskMutation = useMutation({
    mutationFn: ({ name, enabled }: { name: string; enabled: boolean }) =>
      api.request('PUT', `/schedule/${name}`, { body: { enabled } }),
    onSuccess: (_, { name, enabled }) => {
      queryClient.invalidateQueries({ queryKey: ['schedules'] });
      toast.success(`排程 [${name}] 已${enabled ? '啟用' : '停用'}`);
    },
    onError: (err: any) => {
      toast.error(`更新排程狀態失敗: ${err.message}`);
    },
  });

  const runNowMutation = useMutation({
    mutationFn: (name: string) => api.request('POST', `/schedule/${name}/run`),
    onSuccess: (_, name) => {
      queryClient.invalidateQueries({ queryKey: ['schedules'] });
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      toast.success(`已觸發排程 [${name}] 立即執行一次`);
    },
    onError: (err: any) => {
      toast.error(`觸發執行失敗: ${err.message}`);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (name: string) => api.request('DELETE', `/schedule/${name}`),
    onSuccess: (_, name) => {
      queryClient.invalidateQueries({ queryKey: ['schedules'] });
      toast.success(`已刪除排程 [${name}]`);
    },
    onError: (err: any) => {
      toast.error(`刪除排程失敗: ${err.message}`);
    },
  });

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-foreground">定時排程器</h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            管理背景 Cron 自動同步規則與系統守護行程 (Daemon) 運作狀態
          </p>
        </div>

        <Button
          size="sm"
          className="gap-1.5 shadow-sm"
          onClick={() => {
            setEditingTask(null);
            setFormOpen(true);
          }}
        >
          <Plus className="h-4 w-4" /> 新增排程規則
        </Button>
      </div>

      {/* Daemon Status Card */}
      <Card className="border border-border">
        <CardHeader className="pb-3">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div className="flex items-center gap-2">
              <div
                className={`p-2 rounded-lg ${
                  isRunning ? 'bg-emerald-500/10 text-emerald-400' : 'bg-muted text-muted-foreground'
                }`}
              >
                <Cpu className="h-5 w-5" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <CardTitle className="text-base font-semibold">守護行程 (Daemon Status)</CardTitle>
                  <Badge
                    variant="outline"
                    className={`text-xs gap-1.5 font-medium ${
                      isRunning
                        ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-400'
                        : 'border-muted-foreground/30 text-muted-foreground'
                    }`}
                  >
                    <span
                      className={`h-2 w-2 rounded-full ${
                        isRunning ? 'bg-emerald-500 animate-pulse' : 'bg-muted-foreground'
                      }`}
                    />
                    {isRunning ? '運作中 (Running)' : '已停止 (Stopped)'}
                  </Badge>
                </div>
                <CardDescription className="mt-0.5">
                  底層後端: <span className="font-mono text-foreground">{daemonData?.backend || 'systemd'}</span> • PID:{' '}
                  <span className="font-mono text-foreground">{daemonData?.pid || '-'}</span>
                </CardDescription>
              </div>
            </div>

            {/* Daemon action buttons */}
            <div className="flex items-center gap-2">
              {isRunning ? (
                <>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 text-xs gap-1"
                    onClick={() => daemonControlMutation.mutate('restart')}
                    disabled={daemonControlMutation.isPending}
                  >
                    <RotateCw className="h-3.5 w-3.5" /> 重啟
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 text-xs text-destructive hover:text-destructive gap-1"
                    onClick={() => daemonControlMutation.mutate('stop')}
                    disabled={daemonControlMutation.isPending}
                  >
                    <Square className="h-3.5 w-3.5" /> 停止 Daemon
                  </Button>
                </>
              ) : (
                <Button
                  size="sm"
                  className="h-8 text-xs gap-1"
                  onClick={() => daemonControlMutation.mutate('start')}
                  disabled={daemonControlMutation.isPending}
                >
                  <Play className="h-3.5 w-3.5" /> 啟動 Daemon
                </Button>
              )}
            </div>
          </div>
        </CardHeader>

        {daemonLogs.length > 0 && (
          <CardContent className="pt-0">
            <div className="p-3 rounded-lg bg-black/40 border border-border/80 font-mono text-[11px] text-muted-foreground space-y-0.5 max-h-32 overflow-y-auto">
              <div className="text-[10px] uppercase font-semibold text-muted-foreground/70 tracking-wider mb-1">
                守護行程日誌尾端 (Daemon Log Tail)
              </div>
              {daemonLogs.map((line: string, idx: number) => (
                <div key={idx} className="leading-relaxed">
                  {line}
                </div>
              ))}
            </div>
          </CardContent>
        )}
      </Card>

      {/* Schedules Table Card */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-base font-semibold">排程任務清單 (Scheduled Rules)</CardTitle>
              <CardDescription>設定定期執行的增量備份與雙向鏡像排程</CardDescription>
            </div>
            <Badge variant="secondary" className="font-mono text-xs">
              {schedules.length} 個規則
            </Badge>
          </div>
        </CardHeader>

        <CardContent className="p-0">
          {isLoading ? (
            <div className="py-16 text-center text-xs text-muted-foreground">載入排程清單中...</div>
          ) : schedules.length === 0 ? (
            <div className="py-16 text-center text-muted-foreground space-y-2">
              <Calendar className="h-8 w-8 text-muted-foreground/40 mx-auto" />
              <p className="text-xs">尚未設定任何定時排程規則</p>
            </div>
          ) : (
            <div className="border-t border-border overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead className="bg-muted/40 border-b border-border text-muted-foreground select-none">
                  <tr>
                    <th className="py-3 px-4 font-medium">任務名稱</th>
                    <th className="py-3 px-4 font-medium">觸發規律 (Cron)</th>
                    <th className="py-3 px-4 font-medium">執行指令</th>
                    <th className="py-3 px-4 font-medium text-center">狀態</th>
                    <th className="py-3 px-4 font-medium">下次執行</th>
                    <th className="py-3 px-4 font-medium text-right">操作</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/40">
                  {schedules.map((item) => {
                    const cronExpr = item.cron || item.schedule;
                    return (
                      <tr key={item.name} className="hover:bg-accent/40 transition-colors">
                        <td className="py-3 px-4 font-semibold text-foreground">{item.name}</td>
                        <td className="py-3 px-4">
                          <div className="space-y-0.5">
                            <span className="font-medium text-foreground block">{formatCron(cronExpr)}</span>
                            <span className="font-mono text-[11px] text-muted-foreground">({cronExpr})</span>
                          </div>
                        </td>
                        <td className="py-3 px-4 font-mono text-muted-foreground truncate max-w-xs">
                          {item.command}
                        </td>
                        <td className="py-3 px-4 text-center">
                          <input
                            type="checkbox"
                            checked={item.enabled}
                            onChange={(e) =>
                              toggleTaskMutation.mutate({ name: item.name, enabled: e.target.checked })
                            }
                            className="h-4 w-4 rounded text-primary focus:ring-primary cursor-pointer"
                          />
                        </td>
                        <td className="py-3 px-4 font-mono text-muted-foreground text-[11px]">
                          {item.next_run ? formatRelativeTime(item.next_run) : '未安排'}
                        </td>
                        <td className="py-3 px-4 text-right">
                          <div className="flex items-center justify-end gap-1.5">
                            <Button
                              variant="outline"
                              size="sm"
                              className="h-7 text-[11px] gap-1"
                              onClick={() => runNowMutation.mutate(item.name)}
                              disabled={runNowMutation.isPending}
                              title="立即執行一次"
                            >
                              <Play className="h-3 w-3" /> 執行
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7 text-muted-foreground hover:text-foreground"
                              onClick={() => {
                                setEditingTask(item);
                                setFormOpen(true);
                              }}
                              title="編輯"
                            >
                              <Edit className="h-3.5 w-3.5" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7 text-muted-foreground hover:text-destructive"
                              onClick={() => {
                                if (confirm(`確定要刪除排程 [${item.name}] 嗎？`)) {
                                  deleteMutation.mutate(item.name);
                                }
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
            </div>
          )}
        </CardContent>
      </Card>

      {/* Schedule Form Modal */}
      <ScheduleFormDialog
        open={formOpen}
        onOpenChange={setFormOpen}
        initialData={editingTask}
      />
    </div>
  );
}
