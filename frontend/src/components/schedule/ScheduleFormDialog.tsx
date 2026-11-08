import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/api';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { formatCron } from '@/lib/cron';
import { toast } from 'sonner';
import { Clock, Calendar, Play } from 'lucide-react';
import type { TaskItemResponse } from '@/api/types';

interface ScheduleFormDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialData?: TaskItemResponse | null;
  onSuccess?: () => void;
}

const PRESET_CRONS = [
  { label: '每小時整點 (0 * * * *)', value: '0 * * * *' },
  { label: '每日凌晨 02:00 (0 2 * * *)', value: '0 2 * * *' },
  { label: '每週日午夜 00:00 (0 0 * * 0)', value: '0 0 * * 0' },
  { label: '每 15 分鐘 (*/15 * * * *)', value: '*/15 * * * *' },
  { label: '工作日早上 08:30 (30 8 * * 1-5)', value: '30 8 * * 1-5' },
];

export function ScheduleFormDialog({
  open,
  onOpenChange,
  initialData,
  onSuccess,
}: ScheduleFormDialogProps) {
  const queryClient = useQueryClient();
  const isEditing = !!initialData;

  const [name, setName] = useState(initialData?.name || '');
  const [cron, setCron] = useState(initialData?.cron || initialData?.schedule || '0 2 * * *');
  const [command, setCommand] = useState(initialData?.command || 'sync gdrive:/Backups onedrive:/Backups --mirror');
  const [enabled, setEnabled] = useState(initialData ? initialData.enabled : true);

  const naturalDesc = formatCron(cron);

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload = {
        name: name.trim(),
        cron: cron.trim(),
        command: command.trim(),
        enabled,
      };
      if (isEditing) {
        return api.request('PUT', `/schedule/${initialData.name}`, { body: payload });
      } else {
        return api.request('POST', '/schedule', { body: payload });
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['schedules'] });
      toast.success(isEditing ? `已更新排程 [${name}]` : `已新增排程 [${name}]`);
      onOpenChange(false);
      onSuccess?.();
    },
    onError: (err: any) => {
      toast.error(`儲存排程失敗: ${err.message}`);
    },
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <div className="p-2 rounded-lg bg-primary/10 text-primary">
              <Calendar className="h-5 w-5" />
            </div>
            <div>
              <DialogTitle>{isEditing ? '編輯定時排程規則' : '新增定時排程規則'}</DialogTitle>
              <DialogDescription>配置 Cron 自動觸發規則與關聯執行的同步指令</DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="space-y-4 py-2">
          {/* Schedule Name */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-foreground">排程任務名稱</label>
            <Input
              placeholder="例如: daily-backup"
              value={name}
              disabled={isEditing}
              onChange={(e) => setName(e.target.value)}
            />
          </div>

          {/* Preset Cron Selector */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-foreground">常用 Cron 規律範本</label>
            <Select onValueChange={(val) => setCron(val)}>
              <SelectTrigger className="text-xs">
                <SelectValue placeholder="挑選預設範本..." />
              </SelectTrigger>
              <SelectContent>
                {PRESET_CRONS.map((p) => (
                  <SelectItem key={p.value} value={p.value}>
                    {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Cron Expression & Natural description */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-foreground">Cron 表達式 (分 時 日 月 週)</label>
            <Input
              value={cron}
              onChange={(e) => setCron(e.target.value)}
              className="font-mono text-xs"
              placeholder="0 2 * * *"
            />
            <div className="p-2.5 rounded-lg bg-muted/40 border border-border/80 text-xs flex items-center gap-1.5 text-primary">
              <Clock className="h-3.5 w-3.5 shrink-0" />
              <span>解讀：{naturalDesc}</span>
            </div>
          </div>

          {/* Command to run */}
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-foreground">執行命令 (Command)</label>
            <Input
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              className="font-mono text-xs"
              placeholder="sync <source> <dest> [--mirror]"
            />
          </div>

          {/* Enabled switch */}
          <div className="pt-1">
            <label className="flex items-center gap-2 cursor-pointer text-xs text-foreground select-none">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
                className="rounded text-primary focus:ring-primary"
              />
              建立後立即啟用此排程 (Enabled)
            </label>
          </div>
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button
            size="sm"
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending || !name.trim() || !cron.trim()}
          >
            {saveMutation.isPending ? '儲存中...' : isEditing ? '儲存變更' : '建立排程'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
