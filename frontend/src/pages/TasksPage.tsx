import React, { useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  FolderKanban,
  UploadCloud,
  RefreshCw,
  Clock,
  Play,
  RotateCcw,
  Trash2,
  CheckCircle2,
  AlertCircle,
  FileCheck,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { AlistTaskManager, type TaskNameAnalyzer } from '@/components/tasks/AlistTaskManager';
import { useTransferQueue } from '@/stores/transfer-queue';
import { api } from '@/api';
import type { TaskRecord } from '@/api/types';
import { SyncPage } from './SyncPage';
import { SchedulePage } from './SchedulePage';
import { toast } from 'sonner';

export function TasksPage() {
  const { tab } = useParams<{ tab?: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const activeTab = tab || 'copy';

  // 1. Upload Queue from useTransferQueue
  const { jobs, cancelJob, clearCompleted, enqueue } = useTransferQueue();

  const uploadTasksAsRecords: TaskRecord[] = useMemo(() => {
    return jobs.map((job) => ({
      id: job.id,
      kind: 'transfer',
      title: `上傳 ${job.file.name} 至 [${job.remote}](${job.targetDir})`,
      source: job.file.name,
      destination: `${job.remote}:${job.targetDir}`,
      source_uri: job.file.name,
      dest_uri: `${job.remote}:${job.targetDir}`,
      status:
        job.status === 'uploading'
          ? 'running'
          : job.status === 'pending'
          ? 'queued'
          : job.status === 'completed'
          ? 'completed'
          : job.status === 'failed'
          ? 'failed'
          : 'cancelled',
      created_at: Date.now() / 1000,
      bytes_done: job.progress.loaded,
      bytes_total: job.progress.total,
      files_done: job.status === 'completed' ? 1 : 0,
      files_total: 1,
      errors: job.error ? 1 : 0,
      speed_bps: 0,
      message: job.error ? `上傳失敗: ${job.error}` : job.status === 'uploading' ? `傳輸中 (${job.progress.percent}%)` : job.status,
    }));
  }, [jobs]);

  // Upload name analyzer like AList: /^upload (.+) to \[(.+)]\((.+)\)$/
  const uploadNameAnalyzer: TaskNameAnalyzer = {
    regex: /^上傳 (.+) 至 \[(.+)]\((.+)\)$/,
    title: (matches) => matches[1],
    attrs: {
      '目標目錄': (matches) => `/${matches[2]}${matches[3].startsWith('/') ? matches[3] : `/${matches[3]}`}`,
    },
  };

  // 2. Copy / Sync Tasks from backend
  const { data: syncTasks, refetch: refetchSyncTasks, isLoading: isSyncLoading } = useQuery<TaskRecord[]>({
    queryKey: ['tasks'],
    queryFn: () => api.request('GET', '/sync/tasks'),
    refetchInterval: 3000,
  });

  const cancelMutation = useMutation({
    mutationFn: (taskId: string) => api.request('POST', `/sync/tasks/${taskId}/cancel`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      toast.success('任務已取消');
    },
  });

  const retryMutation = useMutation({
    mutationFn: (taskId: string) => api.request('POST', `/sync/tasks/${taskId}/retry`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks'] });
      toast.success('已重新啟動任務');
    },
  });

  const tabsConfig = [
    { id: 'copy', label: '複製與跨端同步 (Copy & Sync)', icon: RefreshCw },
    { id: 'upload', label: '本機上傳佇列 (Upload)', icon: UploadCloud },
    { id: 'schedules', label: '定時排程與守護行程 (Schedules)', icon: Clock },
  ];

  return (
    <div className="space-y-6 pb-12 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <FolderKanban className="h-5 w-5 text-primary" />
            <span>任務管理 (Tasks)</span>
          </h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            全面仿照 AList 任務體系，集中檢視本機上傳、多雲跨端複製同步及定時排程執行進度
          </p>
        </div>
      </div>

      {/* Tab Switcher */}
      <div className="flex items-center gap-1.5 p-1 bg-muted/60 rounded-xl overflow-x-auto select-none">
        {tabsConfig.map((item) => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => navigate(`/@manage/tasks/${item.id}`)}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold whitespace-nowrap transition-all cursor-pointer ${
                isActive
                  ? 'bg-background text-foreground shadow-sm'
                  : 'text-muted-foreground hover:text-foreground hover:bg-muted/40'
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              <span>{item.label}</span>
            </button>
          );
        })}
      </div>

      {/* Content */}
      {activeTab === 'upload' && (
        <div className="rounded-xl border border-border bg-card p-5 shadow-xs space-y-4">
          <div className="flex items-center justify-between border-b border-border/60 pb-3">
            <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
              <UploadCloud className="h-4 w-4 text-primary" />
              <span>本機瀏覽器上傳佇列 (Upload Tasks)</span>
            </h2>
            <Button
              size="sm"
              variant="outline"
              onClick={clearCompleted}
              className="text-xs text-destructive hover:bg-destructive/10"
            >
              清除已完成上傳
            </Button>
          </div>

          <AlistTaskManager
            type="upload"
            tasks={uploadTasksAsRecords}
            nameAnalyzer={uploadNameAnalyzer}
            onCancel={(id) => cancelJob(id)}
            onClearDone={clearCompleted}
            onClearSucceeded={clearCompleted}
          />
        </div>
      )}

      {activeTab === 'copy' && (
        <div className="space-y-6">
          <div className="rounded-xl border border-border bg-card p-5 shadow-xs space-y-4">
            <div className="flex items-center justify-between border-b border-border/60 pb-3">
              <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
                <RefreshCw className="h-4 w-4 text-primary" />
                <span>跨端複製與鏡像傳輸執行緒 (Copy & Transfer Tasks)</span>
              </h2>
            </div>

            <AlistTaskManager
              type="copy"
              tasks={syncTasks || []}
              loading={isSyncLoading}
              onRefresh={() => refetchSyncTasks()}
              onCancel={(id) => cancelMutation.mutate(id)}
              onRetry={(id) => retryMutation.mutate(id)}
              onRetryFailed={() => {
                const failed = (syncTasks || []).filter((t) => t.status === 'failed');
                failed.forEach((t) => retryMutation.mutate(t.id));
              }}
            />
          </div>

          {/* Integrated Sync Job Builder & Diff Workspace */}
          <div className="pt-2">
            <SyncPage />
          </div>
        </div>
      )}

      {activeTab === 'schedules' && (
        <div className="pt-2">
          <SchedulePage />
        </div>
      )}
    </div>
  );
}
