import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { Server, RefreshCw, Clock, Zap, ArrowRight, Play, Plus, Upload, Pause, Terminal } from 'lucide-react';
import { api } from '@/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { formatBytes, formatSpeed, formatRelativeTime } from '@/lib/format';
import { useActivityStore } from '@/realtime/activity-store';
import { ScrollArea } from '@/components/ui/scroll-area';
import type { RemoteListResponse, TaskRecord, TaskItemResponse } from '@/api/types';

export function DashboardPage() {
  const navigate = useNavigate();
  const { events, isPaused, togglePause, clear, filter, setFilter } = useActivityStore();

  const { data: remotesData } = useQuery<RemoteListResponse>({
    queryKey: ['remotes'],
    queryFn: () => api.request('GET', '/remotes'),
  });

  const { data: tasksData } = useQuery<TaskRecord[]>({
    queryKey: ['tasks'],
    queryFn: () => api.request('GET', '/sync/tasks'),
  });

  const { data: schedulesData } = useQuery<TaskItemResponse[]>({
    queryKey: ['schedules'],
    queryFn: () => api.request('GET', '/schedule'),
  });

  const remotes = remotesData?.remotes || [];
  const onlineRemotes = remotes.filter((r) => r.health?.status === 'success').length;

  const runningTasks = (tasksData || []).filter((t) => t.status === 'running');
  const activeSchedules = (schedulesData || []).filter((s) => s.enabled).length;

  const totalSpeedBps = runningTasks.reduce((acc, t) => acc + (t.speed_bps || 0), 0);

  const filteredEvents = events.filter((e) => {
    if (filter === 'tasks') return e.type === 'task.update' || e.type === 'task.log';
    if (filter === 'logs') return e.type === 'log';
    return true;
  });

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-foreground">總覽儀表板</h2>
          <p className="text-sm text-muted-foreground mt-0.5">多雲端儲存節點狀態、即時活動動態與快速操作中心</p>
        </div>

        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => navigate('/remotes')} className="gap-1.5">
            <Plus className="h-4 w-4" /> 新增節點
          </Button>
          <Button size="sm" onClick={() => navigate('/sync')} className="gap-1.5 shadow-sm">
            <Play className="h-4 w-4" /> 發起同步
          </Button>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Remotes Stat */}
        <Card className="hover:border-primary/40 transition-colors">
          <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
            <CardTitle className="text-xs font-medium text-muted-foreground">已連線儲存節點</CardTitle>
            <Server className="h-4 w-4 text-primary" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">
              {onlineRemotes} <span className="text-xs text-muted-foreground font-normal">/ {remotes.length} 在線</span>
            </div>
            <div className="flex items-center gap-1.5 mt-2">
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
              <p className="text-[11px] text-muted-foreground">所有儲存節點服務皆就緒</p>
            </div>
          </CardContent>
        </Card>

        {/* Active Syncs Stat */}
        <Card className="hover:border-primary/40 transition-colors">
          <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
            <CardTitle className="text-xs font-medium text-muted-foreground">進行中同步任務</CardTitle>
            <RefreshCw className={`h-4 w-4 text-sky-400 ${runningTasks.length > 0 ? 'animate-spin' : ''}`} />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">{runningTasks.length}</div>
            <p className="text-[11px] text-muted-foreground mt-2">
              {runningTasks.length > 0 ? '背景持續非同步傳輸中' : '目前無活動任務'}
            </p>
          </CardContent>
        </Card>

        {/* Scheduled Tasks Stat */}
        <Card className="hover:border-primary/40 transition-colors">
          <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
            <CardTitle className="text-xs font-medium text-muted-foreground">自動排程任務</CardTitle>
            <Clock className="h-4 w-4 text-violet-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">
              {activeSchedules}{' '}
              <span className="text-xs text-muted-foreground font-normal">/ {schedulesData?.length || 0} 啟用</span>
            </div>
            <p className="text-[11px] text-muted-foreground mt-2">守護行程 Daemon 持續監控中</p>
          </CardContent>
        </Card>

        {/* Realtime Bandwidth Stat */}
        <Card className="hover:border-primary/40 transition-colors">
          <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
            <CardTitle className="text-xs font-medium text-muted-foreground">即時傳輸頻寬</CardTitle>
            <Zap className="h-4 w-4 text-amber-400" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono text-foreground">{formatSpeed(totalSpeedBps)}</div>
            <p className="text-[11px] text-muted-foreground mt-2">EMA 移動平均速率加總</p>
          </CardContent>
        </Card>
      </div>

      {/* Main Grid: Live Activity Feed + Quick Actions */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Activity Feed (2 Cols) */}
        <Card className="lg:col-span-2 flex flex-col">
          <CardHeader className="flex flex-row items-center justify-between pb-3">
            <div>
              <CardTitle className="text-base font-semibold flex items-center gap-2">
                <Terminal className="h-4 w-4 text-primary" /> 即時活動動態 (Live Activity)
              </CardTitle>
              <CardDescription className="text-xs">即時接收 SSE 推播之任務進度與系統日誌</CardDescription>
            </div>

            <div className="flex items-center gap-2">
              {/* Filter pills */}
              <div className="flex rounded-lg border border-border p-0.5 bg-muted/40 text-xs">
                {(['all', 'tasks', 'logs'] as const).map((t) => (
                  <button
                    key={t}
                    onClick={() => setFilter(t)}
                    className={`px-2 py-0.5 rounded-md cursor-pointer transition-colors ${
                      filter === t ? 'bg-background text-foreground shadow-xs font-medium' : 'text-muted-foreground'
                    }`}
                  >
                    {t === 'all' ? '全部' : t === 'tasks' ? '任務' : '日誌'}
                  </button>
                ))}
              </div>

              <Button
                variant="ghost"
                size="iconSm"
                onClick={togglePause}
                title={isPaused ? '恢復自動捲動' : '暫停自動捲動'}
                className="text-muted-foreground hover:text-foreground"
              >
                {isPaused ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}
              </Button>
              <Button variant="ghost" size="sm" onClick={clear} className="text-xs h-7 px-2 text-muted-foreground">
                清空
              </Button>
            </div>
          </CardHeader>

          <CardContent className="flex-1 p-0 px-5 pb-5">
            <ScrollArea className="h-[360px] rounded-lg border border-border bg-card/40 p-3 font-mono text-xs">
              {filteredEvents.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full py-20 text-muted-foreground">
                  <Terminal className="h-8 w-8 stroke-[1.5] mb-2 opacity-40" />
                  <p>目前尚無即時活動事件</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {filteredEvents.map((ev) => (
                    <div
                      key={ev.id}
                      className="flex items-start gap-2.5 py-1 px-2 rounded-md hover:bg-muted/30 transition-colors border-l-2 border-primary/40 text-[11px]"
                    >
                      <span className="text-muted-foreground shrink-0">{formatRelativeTime(ev.timestamp)}</span>
                      <Badge
                        variant={ev.level === 'ERROR' ? 'destructive' : 'secondary'}
                        className="h-4 text-[9px] px-1 font-mono uppercase"
                      >
                        {ev.type}
                      </Badge>
                      <span className="text-foreground/90 break-all">{ev.message}</span>
                    </div>
                  ))}
                </div>
              )}
            </ScrollArea>
          </CardContent>
        </Card>

        {/* Quick Actions & Remotes Summary */}
        <div className="space-y-6">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-semibold">快捷常用操作</CardTitle>
              <CardDescription className="text-xs">一鍵啟動跨節點檔案任務</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2.5">
              <Button
                variant="outline"
                className="w-full justify-between h-11 text-xs border-border hover:border-primary/50"
                onClick={() => navigate('/sync')}
              >
                <div className="flex items-center gap-2.5">
                  <RefreshCw className="h-4 w-4 text-primary" />
                  <span>新建同步作業 (Sync Plan)</span>
                </div>
                <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
              </Button>

              <Button
                variant="outline"
                className="w-full justify-between h-11 text-xs border-border hover:border-primary/50"
                onClick={() => navigate('/files')}
              >
                <div className="flex items-center gap-2.5">
                  <Upload className="h-4 w-4 text-emerald-400" />
                  <span>瀏覽與上傳檔案 (Explorer)</span>
                </div>
                <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
              </Button>

              <Button
                variant="outline"
                className="w-full justify-between h-11 text-xs border-border hover:border-primary/50"
                onClick={() => navigate('/remotes')}
              >
                <div className="flex items-center gap-2.5">
                  <Server className="h-4 w-4 text-violet-400" />
                  <span>管理遠端雲端節點 (Remotes)</span>
                </div>
                <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
              </Button>
            </CardContent>
          </Card>

          {/* Connected Remotes Mini List */}
          <Card>
            <CardHeader className="pb-3 flex flex-row items-center justify-between">
              <div>
                <CardTitle className="text-base font-semibold">節點概況</CardTitle>
                <CardDescription className="text-xs">近期連線儲存端點</CardDescription>
              </div>
              <Button variant="ghost" size="sm" onClick={() => navigate('/remotes')} className="text-xs h-7 px-2">
                全部
              </Button>
            </CardHeader>
            <CardContent className="p-0 px-5 pb-5">
              <div className="space-y-2">
                {remotes.slice(0, 4).map((r) => (
                  <div
                    key={r.name}
                    className="flex items-center justify-between p-2 rounded-lg border border-border/60 hover:bg-muted/30 transition-colors text-xs"
                  >
                    <div className="flex items-center gap-2 overflow-hidden">
                      <span className="h-2 w-2 rounded-full bg-emerald-500 shrink-0" />
                      <span className="font-medium text-foreground truncate">{r.name}</span>
                      <span className="text-[10px] text-muted-foreground">({r.type})</span>
                    </div>
                    {r.health && <span className="text-[10px] text-muted-foreground font-mono">{r.health.latency_ms}ms</span>}
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
