import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  Server,
  RefreshCw,
  Clock,
  Zap,
  ArrowRight,
  Play,
  Plus,
  FolderOpen,
  Pause,
  Terminal,
} from 'lucide-react';
import { api } from '@/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { formatSpeed, formatRelativeTime } from '@/lib/format';
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
    <div className="space-y-5 w-full">
      {/* Top Action Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold tracking-tight text-foreground">後台管理總覽 (@manage)</h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            多雲端掛載節點健康度、背景傳輸任務與即時事件串流中心
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button variant="subtle" size="sm" onClick={() => navigate('/')} className="gap-1.5">
            <FolderOpen className="h-4 w-4" /> 前台檔案瀏覽
          </Button>
          <Button variant="subtle" size="sm" onClick={() => navigate('/remotes')} className="gap-1.5">
            <Plus className="h-4 w-4" /> 管理儲存節點
          </Button>
          <Button size="sm" onClick={() => navigate('/sync')} className="gap-1.5">
            <Play className="h-4 w-4" /> 發起同步任務
          </Button>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Card className="bg-[var(--alist-card-bg)] hover:border-[var(--alist-main)] transition-colors">
          <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
            <CardTitle className="text-xs font-medium text-muted-foreground">已掛載儲存節點</CardTitle>
            <Server className="h-4 w-4 text-[var(--alist-main)]" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">
              {onlineRemotes}{' '}
              <span className="text-xs text-muted-foreground font-normal">/ {remotes.length} work</span>
            </div>
            <div className="flex items-center gap-1.5 mt-2">
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
              <p className="text-[11px] text-muted-foreground">所有掛載路徑運作正常</p>
            </div>
          </CardContent>
        </Card>

        <Card className="bg-[var(--alist-card-bg)] hover:border-[var(--alist-main)] transition-colors">
          <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
            <CardTitle className="text-xs font-medium text-muted-foreground">進行中同步任務</CardTitle>
            <RefreshCw
              className={`h-4 w-4 text-[var(--alist-main)] ${runningTasks.length > 0 ? 'animate-spin' : ''}`}
            />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">{runningTasks.length}</div>
            <p className="text-[11px] text-muted-foreground mt-2">
              {runningTasks.length > 0 ? '背景持續非同步傳輸中' : '目前無活動任務'}
            </p>
          </CardContent>
        </Card>

        <Card className="bg-[var(--alist-card-bg)] hover:border-[var(--alist-main)] transition-colors">
          <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
            <CardTitle className="text-xs font-medium text-muted-foreground">自動排程規則</CardTitle>
            <Clock className="h-4 w-4 text-violet-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-foreground">
              {activeSchedules}{' '}
              <span className="text-xs text-muted-foreground font-normal">
                / {schedulesData?.length || 0} 啟用
              </span>
            </div>
            <p className="text-[11px] text-muted-foreground mt-2">守護行程 Daemon 持續監控中</p>
          </CardContent>
        </Card>

        <Card className="bg-[var(--alist-card-bg)] hover:border-[var(--alist-main)] transition-colors">
          <CardHeader className="flex flex-row items-center justify-between pb-2 space-y-0">
            <CardTitle className="text-xs font-medium text-muted-foreground">即時傳輸頻寬</CardTitle>
            <Zap className="h-4 w-4 text-amber-500" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold font-mono text-foreground">{formatSpeed(totalSpeedBps)}</div>
            <p className="text-[11px] text-muted-foreground mt-2">EMA 移動平均速率加總</p>
          </CardContent>
        </Card>
      </div>

      {/* Main Grid: Live Activity Feed + Mounted Storages */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <Card className="lg:col-span-2 flex flex-col bg-[var(--alist-card-bg)]">
          <CardHeader className="flex flex-row items-center justify-between pb-3">
            <div>
              <CardTitle className="text-base font-semibold flex items-center gap-2">
                <Terminal className="h-4 w-4 text-[var(--alist-main)]" /> 即時活動動態 (Live Activity)
              </CardTitle>
              <CardDescription className="text-xs">即時接收 SSE 推播之任務進度與系統日誌</CardDescription>
            </div>

            <div className="flex items-center gap-1.5">
              <div className="flex rounded-lg p-0.5 bg-muted/60 text-xs">
                {(['all', 'tasks', 'logs'] as const).map((t) => (
                  <button
                    key={t}
                    type="button"
                    onClick={() => setFilter(t)}
                    className={`px-2.5 py-1 rounded-md cursor-pointer transition-colors ${
                      filter === t
                        ? 'bg-[var(--alist-info4)] text-[var(--alist-info11)] font-semibold'
                        : 'text-muted-foreground hover:text-foreground'
                    }`}
                  >
                    {t === 'all' ? '全部' : t === 'tasks' ? '任務' : '日誌'}
                  </button>
                ))}
              </div>

              <Button
                variant="subtle"
                size="iconSm"
                onClick={togglePause}
                title={isPaused ? '恢復自動捲動' : '暫停自動捲動'}
              >
                {isPaused ? <Play className="h-3.5 w-3.5" /> : <Pause className="h-3.5 w-3.5" />}
              </Button>
              <Button variant="subtle" size="sm" onClick={clear} className="text-xs h-7 px-2.5">
                清空
              </Button>
            </div>
          </CardHeader>

          <CardContent className="flex-1 p-0 px-5 pb-5">
            <ScrollArea className="h-[340px] rounded-lg border border-border/60 bg-background/50 p-3 font-mono text-xs">
              {filteredEvents.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full py-20 text-muted-foreground">
                  <Terminal className="h-8 w-8 stroke-[1.5] mb-2 opacity-40" />
                  <p>目前尚無即時活動事件</p>
                </div>
              ) : (
                <div className="space-y-1.5">
                  {filteredEvents.map((ev) => (
                    <div
                      key={ev.id}
                      className="flex items-start gap-2.5 py-1.5 px-2.5 rounded-lg hover:bg-[var(--alist-hover)] transition-colors border-l-2 border-[var(--alist-main)] text-[11px]"
                    >
                      <span className="text-muted-foreground shrink-0">{formatRelativeTime(ev.timestamp)}</span>
                      <Badge
                        variant={ev.level === 'ERROR' ? 'destructive' : 'info'}
                        className="h-4 text-[9px] px-1.5 font-mono uppercase"
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

        {/* Quick Actions & Mounted Storages List */}
        <div className="space-y-5">
          <Card className="bg-[var(--alist-card-bg)]">
            <CardHeader className="pb-3">
              <CardTitle className="text-base font-semibold">快捷工作區入口</CardTitle>
              <CardDescription className="text-xs">快速切換至前台目錄或發起跨網盤作業</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2">
              <Button
                variant="subtle"
                className="w-full justify-between h-10 text-xs"
                onClick={() => navigate('/')}
              >
                <div className="flex items-center gap-2">
                  <FolderOpen className="h-4 w-4" />
                  <span>前台檔案瀏覽器 (Home Explorer)</span>
                </div>
                <ArrowRight className="h-3.5 w-3.5" />
              </Button>

              <Button
                variant="subtle"
                className="w-full justify-between h-10 text-xs"
                onClick={() => navigate('/sync')}
              >
                <div className="flex items-center gap-2">
                  <RefreshCw className="h-4 w-4" />
                  <span>新建跨端同步作業 (Sync Builder)</span>
                </div>
                <ArrowRight className="h-3.5 w-3.5" />
              </Button>

              <Button
                variant="subtle"
                className="w-full justify-between h-10 text-xs"
                onClick={() => navigate('/remotes')}
              >
                <div className="flex items-center gap-2">
                  <Server className="h-4 w-4" />
                  <span>管理掛載儲存節點 (Storages)</span>
                </div>
                <ArrowRight className="h-3.5 w-3.5" />
              </Button>
            </CardContent>
          </Card>

          <Card className="bg-[var(--alist-card-bg)]">
            <CardHeader className="pb-3 flex flex-row items-center justify-between">
              <div>
                <CardTitle className="text-base font-semibold">掛載儲存節點</CardTitle>
                <CardDescription className="text-xs">點擊直接進入該掛載路徑瀏覽</CardDescription>
              </div>
              <Button variant="subtle" size="sm" onClick={() => navigate('/remotes')} className="text-xs h-7 px-2.5">
                全部
              </Button>
            </CardHeader>
            <CardContent className="p-0 px-5 pb-5">
              <div className="space-y-1.5">
                {remotes.slice(0, 5).map((r) => (
                  <div
                    key={r.name}
                    onClick={() => navigate(`/files?remote=${encodeURIComponent(r.name)}&path=/`)}
                    className="flex items-center justify-between p-2 rounded-lg hover:bg-[var(--alist-hover)] cursor-pointer transition-colors text-xs"
                  >
                    <div className="flex items-center gap-2 overflow-hidden">
                      <span className="h-2 w-2 rounded-full bg-emerald-500 shrink-0" />
                      <span className="font-semibold text-foreground font-mono truncate">/{r.name}</span>
                      <Badge variant="info" className="text-[10px] px-1.5 py-0 font-mono">
                        {r.type}
                      </Badge>
                    </div>
                    {r.health && (
                      <span className="text-[10px] text-emerald-500 font-mono">
                        work ({r.health.latency_ms}ms)
                      </span>
                    )}
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
