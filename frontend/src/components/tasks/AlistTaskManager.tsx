import React, { useState, useMemo } from 'react';
import {
  RotateCw,
  Trash2,
  ChevronDown,
  ChevronRight,
  Search,
  ArrowUpDown,
  CheckCircle2,
  AlertCircle,
  Clock,
  Play,
  XCircle,
  ExternalLink,
  Loader2,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import type { TaskRecord } from '@/api/types';

export interface TaskNameAnalyzer {
  regex: RegExp;
  title: (matches: RegExpMatchArray) => string;
  attrs?: Record<string, (matches: RegExpMatchArray) => React.ReactNode>;
}

interface AlistTaskManagerProps {
  type: 'upload' | 'copy' | 'sync' | 'schedules' | 'all';
  tasks: TaskRecord[];
  loading?: boolean;
  onRefresh?: () => void;
  onCancel?: (taskId: string) => void;
  onRetry?: (taskId: string) => void;
  onDelete?: (taskId: string) => void;
  onClearDone?: () => void;
  onClearSucceeded?: () => void;
  onRetryFailed?: () => void;
  nameAnalyzer?: TaskNameAnalyzer;
}

export function AlistTaskManager({
  type,
  tasks,
  loading = false,
  onRefresh,
  onCancel,
  onRetry,
  onDelete,
  onClearDone,
  onClearSucceeded,
  onRetryFailed,
  nameAnalyzer,
}: AlistTaskManagerProps) {
  const [filterRegex, setFilterRegex] = useState('');
  const [sortBy, setSortBy] = useState<'name' | 'progress' | 'time'>('time');
  const [sortAsc, setSortAsc] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [activeTab, setActiveTab] = useState<'undone' | 'done'>('undone');

  const filteredTasks = useMemo(() => {
    let list = tasks;
    if (filterRegex.trim()) {
      try {
        const re = new RegExp(filterRegex, 'i');
        list = list.filter((t) => re.test(t.title || '') || re.test(t.message || ''));
      } catch {
        list = list.filter((t) => (t.title || '').toLowerCase().includes(filterRegex.toLowerCase()));
      }
    }

    return [...list].sort((a, b) => {
      let cmp = 0;
      if (sortBy === 'name') {
        cmp = (a.title || '').localeCompare(b.title || '');
      } else if (sortBy === 'progress') {
        const progA = a.bytes_total > 0 ? a.bytes_done / a.bytes_total : 0;
        const progB = b.bytes_total > 0 ? b.bytes_done / b.bytes_total : 0;
        cmp = progA - progB;
      } else {
        cmp = a.created_at - b.created_at;
      }
      return sortAsc ? cmp : -cmp;
    });
  }, [tasks, filterRegex, sortBy, sortAsc]);

  const undoneTasks = useMemo(
    () => filteredTasks.filter((t) => ['running', 'queued', 'pausing', 'paused'].includes(t.status)),
    [filteredTasks],
  );

  const doneTasks = useMemo(
    () => filteredTasks.filter((t) => ['completed', 'failed', 'cancelled'].includes(t.status)),
    [filteredTasks],
  );

  const currentList = activeTab === 'undone' ? undoneTasks : doneTasks;

  const toggleExpand = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const expandAll = () => {
    setExpandedIds(new Set(currentList.map((t) => t.id)));
  };

  const collapseAll = () => {
    setExpandedIds(new Set());
  };

  const formatBytes = (bytes: number) => {
    if (!bytes || bytes <= 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const idx = Math.floor(Math.log(bytes) / Math.log(1024));
    return `${(bytes / Math.pow(1024, idx)).toFixed(1)} ${units[idx]}`;
  };

  const renderStatusBadge = (status: TaskRecord['status']) => {
    switch (status) {
      case 'running':
        return (
          <Badge variant="outline" className="text-blue-500 border-blue-500/30 bg-blue-500/10 gap-1 text-xs">
            <Loader2 className="h-3 w-3 animate-spin" />
            執行中
          </Badge>
        );
      case 'completed':
        return (
          <Badge variant="outline" className="text-emerald-500 border-emerald-500/30 bg-emerald-500/10 gap-1 text-xs">
            <CheckCircle2 className="h-3 w-3" />
            已完成
          </Badge>
        );
      case 'failed':
        return (
          <Badge variant="outline" className="text-red-500 border-red-500/30 bg-red-500/10 gap-1 text-xs">
            <AlertCircle className="h-3 w-3" />
            失敗
          </Badge>
        );
      case 'cancelled':
        return (
          <Badge variant="outline" className="text-amber-500 border-amber-500/30 bg-amber-500/10 gap-1 text-xs">
            <XCircle className="h-3 w-3" />
            已取消
          </Badge>
        );
      case 'paused':
      case 'pausing':
        return (
          <Badge variant="outline" className="text-slate-400 border-slate-500/30 bg-slate-500/10 gap-1 text-xs">
            已暫停
          </Badge>
        );
      default:
        return (
          <Badge variant="outline" className="text-muted-foreground gap-1 text-xs">
            <Clock className="h-3 w-3" />
            排隊中
          </Badge>
        );
    }
  };

  return (
    <div className="w-full space-y-4">
      {/* Tab Switcher & Action Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border pb-3">
        {/* Hope UI Style Tab Buttons */}
        <div className="flex items-center gap-1.5 p-1 bg-muted/60 rounded-lg">
          <button
            type="button"
            onClick={() => setActiveTab('undone')}
            className={cn(
              'px-3.5 py-1.5 text-xs font-semibold rounded-md transition-all flex items-center gap-1.5',
              activeTab === 'undone'
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            <span>進行中 (Undone)</span>
            <span
              className={cn(
                'px-1.5 py-0.2 rounded-full text-[10px]',
                undoneTasks.length > 0 ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground',
              )}
            >
              {undoneTasks.length}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('done')}
            className={cn(
              'px-3.5 py-1.5 text-xs font-semibold rounded-md transition-all flex items-center gap-1.5',
              activeTab === 'done'
                ? 'bg-background text-foreground shadow-sm'
                : 'text-muted-foreground hover:text-foreground',
            )}
          >
            <span>已完成 (Done)</span>
            <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-muted text-muted-foreground">
              {doneTasks.length}
            </span>
          </button>
        </div>

        {/* Global Toolbar Actions */}
        <div className="flex flex-wrap items-center gap-2">
          {activeTab === 'done' && (
            <>
              {onRetryFailed && (
                <Button size="sm" variant="outline" onClick={onRetryFailed} className="h-8 text-xs gap-1">
                  <RotateCw className="h-3.5 w-3.5 text-blue-500" />
                  重試失敗任務
                </Button>
              )}
              {onClearSucceeded && (
                <Button size="sm" variant="outline" onClick={onClearSucceeded} className="h-8 text-xs gap-1">
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                  清除成功任務
                </Button>
              )}
              {onClearDone && (
                <Button size="sm" variant="outline" onClick={onClearDone} className="h-8 text-xs text-destructive gap-1 hover:bg-destructive/10">
                  <Trash2 className="h-3.5 w-3.5" />
                  清空已完成
                </Button>
              )}
            </>
          )}

          {onRefresh && (
            <Button size="sm" variant="ghost" onClick={onRefresh} disabled={loading} className="h-8 w-8 p-0">
              <RotateCw className={cn('h-3.5 w-3.5', loading && 'animate-spin')} />
            </Button>
          )}
        </div>
      </div>

      {/* Filter and Order Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
        <div className="flex items-center gap-2 flex-1 max-w-sm">
          <div className="relative w-full">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <Input
              value={filterRegex}
              onChange={(e) => setFilterRegex(e.target.value)}
              placeholder="名稱正則表達式篩選 (Regex Filter)..."
              className="h-8 pl-8 text-xs"
            />
          </div>
          {filterRegex && (
            <Button size="sm" variant="ghost" onClick={() => setFilterRegex('')} className="h-8 px-2 text-xs">
              清除
            </Button>
          )}
        </div>

        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <ArrowUpDown className="h-3.5 w-3.5" />
            <span>排序:</span>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as any)}
              className="bg-transparent border border-input rounded px-2 py-1 text-xs text-foreground cursor-pointer"
            >
              <option value="time">建立時間</option>
              <option value="name">任務名稱</option>
              <option value="progress">傳輸進度</option>
            </select>
            <button
              type="button"
              onClick={() => setSortAsc(!sortAsc)}
              className="px-1.5 py-1 rounded hover:bg-muted text-xs"
              title={sortAsc ? '遞增排序' : '遞減排序'}
            >
              {sortAsc ? '↑ 遞增' : '↓ 遞減'}
            </button>
          </div>

          <div className="h-3 w-[1px] bg-border mx-1" />

          <Button size="sm" variant="ghost" onClick={expandAll} className="h-7 px-2 text-[11px]">
            全部展開
          </Button>
          <Button size="sm" variant="ghost" onClick={collapseAll} className="h-7 px-2 text-[11px]">
            全部收合
          </Button>
        </div>
      </div>

      {/* Task List Container */}
      <div className="space-y-2.5 min-h-[220px]">
        {currentList.length === 0 ? (
          <div className="py-12 text-center text-muted-foreground border border-dashed rounded-xl bg-muted/20">
            <p className="text-sm">目前沒有{activeTab === 'undone' ? '進行中' : '已完成'}的任務</p>
          </div>
        ) : (
          currentList.map((task) => {
            const isExpanded = expandedIds.has(task.id);
            const percent = task.bytes_total > 0 ? Math.min(100, Math.round((task.bytes_done / task.bytes_total) * 100)) : 0;

            // Name analyzer check
            let parsedTitle = task.title;
            let customAttrs: React.ReactNode = null;
            if (nameAnalyzer && task.title) {
              const match = task.title.match(nameAnalyzer.regex);
              if (match) {
                parsedTitle = nameAnalyzer.title(match);
                if (nameAnalyzer.attrs) {
                  customAttrs = (
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2 mt-2 pt-2 border-t border-border/50 text-xs">
                      {Object.entries(nameAnalyzer.attrs).map(([label, fn]) => (
                        <div key={label} className="flex items-center gap-1.5">
                          <span className="text-muted-foreground">{label}:</span>
                          <span className="font-mono text-foreground break-all">{fn(match)}</span>
                        </div>
                      ))}
                    </div>
                  );
                }
              }
            }

            return (
              <div
                key={task.id}
                className={cn(
                  'rounded-lg border border-border bg-card transition-all overflow-hidden shadow-xs',
                  isExpanded ? 'ring-1 ring-primary/20' : '',
                )}
              >
                {/* Header row */}
                <div
                  className="flex items-center justify-between p-3 cursor-pointer hover:bg-muted/30 gap-3"
                  onClick={() => toggleExpand(task.id)}
                >
                  <div className="flex items-center gap-2.5 min-w-0 flex-1">
                    <button type="button" className="text-muted-foreground shrink-0">
                      {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                    </button>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-sm font-semibold truncate text-foreground">{parsedTitle}</span>
                        {renderStatusBadge(task.status)}
                      </div>
                      <div className="flex items-center gap-3 text-xs text-muted-foreground mt-0.5">
                        <span>{formatBytes(task.bytes_done)} / {formatBytes(task.bytes_total)}</span>
                        {task.speed_bps > 0 && task.status === 'running' && (
                          <span className="text-blue-500 font-mono">
                            {formatBytes(task.speed_bps)}/s
                          </span>
                        )}
                        {task.eta_seconds != null && task.eta_seconds > 0 && task.status === 'running' && (
                          <span>剩餘 ~{task.eta_seconds} 秒</span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Progress bar / percent / actions */}
                  <div className="flex items-center gap-3 shrink-0" onClick={(e) => e.stopPropagation()}>
                    <div className="w-24 hidden sm:block">
                      <div className="flex justify-between text-[11px] text-muted-foreground mb-1">
                        <span>進度</span>
                        <span>{percent}%</span>
                      </div>
                      <div className="h-1.5 w-full bg-muted rounded-full overflow-hidden">
                        <div
                          className={cn(
                            'h-full transition-all duration-300',
                            task.status === 'completed'
                              ? 'bg-emerald-500'
                              : task.status === 'failed'
                              ? 'bg-red-500'
                              : 'bg-primary',
                          )}
                          style={{ width: `${percent}%` }}
                        />
                      </div>
                    </div>

                    <div className="flex items-center gap-1">
                      {task.status === 'running' && onCancel && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => onCancel(task.id)}
                          className="h-7 px-2 text-xs text-muted-foreground hover:text-destructive"
                        >
                          取消
                        </Button>
                      )}
                      {['failed', 'cancelled'].includes(task.status) && onRetry && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => onRetry(task.id)}
                          className="h-7 px-2 text-xs text-blue-500 hover:bg-blue-500/10"
                        >
                          重試
                        </Button>
                      )}
                      {onDelete && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => onDelete(task.id)}
                          className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      )}
                    </div>
                  </div>
                </div>

                {/* Expanded details */}
                {isExpanded && (
                  <div className="p-3 bg-muted/20 border-t border-border/60 text-xs space-y-2">
                    {customAttrs}

                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 text-muted-foreground">
                      <div>
                        <span className="font-medium text-foreground">來源: </span>
                        <span className="font-mono">{task.source_uri || task.source || '-'}</span>
                      </div>
                      <div>
                        <span className="font-medium text-foreground">目的: </span>
                        <span className="font-mono">{task.dest_uri || task.destination || '-'}</span>
                      </div>
                      <div>
                        <span className="font-medium text-foreground">完成項目: </span>
                        <span>{task.files_done} / {task.files_total} 檔案</span>
                      </div>
                      <div>
                        <span className="font-medium text-foreground">建立時間: </span>
                        <span>{new Date(task.created_at * 1000).toLocaleString('zh-TW')}</span>
                      </div>
                      <div>
                        <span className="font-medium text-foreground">錯誤次數: </span>
                        <span className={task.errors > 0 ? 'text-destructive font-bold' : ''}>{task.errors}</span>
                      </div>
                      <div>
                        <span className="font-medium text-foreground">狀態說明: </span>
                        <span>{task.message || '-'}</span>
                      </div>
                    </div>

                    {task.logs && task.logs.length > 0 && (
                      <div className="mt-2">
                        <span className="font-medium text-foreground block mb-1">即時日誌明細:</span>
                        <div className="p-2 rounded bg-black/80 text-emerald-400 font-mono text-[11px] max-h-32 overflow-y-auto space-y-0.5">
                          {task.logs.map((log, idx) => (
                            <div key={idx}>{log}</div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
