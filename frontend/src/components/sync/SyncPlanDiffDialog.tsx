import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { formatBytes } from '@/lib/format';
import { GitCompare, PlusCircle, RefreshCw, Trash2, CheckCircle2, Play } from 'lucide-react';
import type { SyncPlanResponse } from '@/api/types';

interface SyncPlanDiffDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  plan: SyncPlanResponse | null;
  onExecute: () => void;
  isExecuting?: boolean;
}

export function SyncPlanDiffDialog({
  open,
  onOpenChange,
  plan,
  onExecute,
  isExecuting,
}: SyncPlanDiffDialogProps) {
  if (!plan) return null;

  const items = plan.items || [];
  const toAdd = items.filter((i) => i.action === 'add');
  const toUpdate = items.filter((i) => i.action === 'update');
  const toDelete = items.filter((i) => i.action === 'delete');
  const identical = items.filter((i) => i.action === 'identical');
  const toAddCount = plan.to_add ?? toAdd.length;
  const toUpdateCount = plan.to_update ?? toUpdate.length;
  const toDeleteCount = plan.to_delete ?? toDelete.length;
  const bytesToTransfer = plan.bytes_to_transfer ?? 0;
  const sourceText = plan.source || plan.source_uri;
  const destText = plan.destination || plan.dest_uri;
  const modeText = plan.mode || 'sync';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <div className="p-2 rounded-lg bg-primary/10 text-primary">
              <GitCompare className="h-5 w-5" />
            </div>
            <div>
              <DialogTitle>同步預檢計畫 (Dry-Run Plan)</DialogTitle>
              <DialogDescription>
                比對 {sourceText} ➔ {destText} (模式: {modeText})
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        {/* Diff Metric Summary Cards */}
        <div className="grid grid-cols-4 gap-2 py-2">
          <div className="p-2.5 rounded-lg border border-emerald-500/30 bg-emerald-500/10 text-center">
            <span className="text-[11px] font-medium text-emerald-400 block">新增檔案</span>
            <span className="text-xl font-bold text-emerald-400">{toAddCount}</span>
          </div>
          <div className="p-2.5 rounded-lg border border-sky-500/30 bg-sky-500/10 text-center">
            <span className="text-[11px] font-medium text-sky-400 block">更新檔案</span>
            <span className="text-xl font-bold text-sky-400">{toUpdateCount}</span>
          </div>
          <div className="p-2.5 rounded-lg border border-rose-500/30 bg-rose-500/10 text-center">
            <span className="text-[11px] font-medium text-rose-400 block">刪除多餘</span>
            <span className="text-xl font-bold text-rose-400">{toDeleteCount}</span>
          </div>
          <div className="p-2.5 rounded-lg border border-border bg-card text-center">
            <span className="text-[11px] font-medium text-muted-foreground block">傳輸位元組</span>
            <span className="text-sm font-bold text-foreground mt-1 block">
              {formatBytes(bytesToTransfer)}
            </span>
          </div>
        </div>

        {/* Diff Items List Viewport */}
        <div className="flex-1 overflow-auto border border-border rounded-lg bg-muted/20 min-h-[220px] max-h-[380px]">
          <table className="w-full text-left text-xs border-collapse">
            <thead className="bg-muted/40 sticky top-0 border-b border-border/80 text-muted-foreground z-10">
              <tr>
                <th className="py-2 px-3 font-medium w-24">預計動作</th>
                <th className="py-2 px-3 font-medium">檔案路徑</th>
                <th className="py-2 px-3 font-medium w-24 text-right">大小</th>
                <th className="py-2 px-3 font-medium w-28 text-right">原因說明</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/40">
              {items.map((item, idx) => (
                <tr key={idx} className="hover:bg-accent/40">
                  <td className="py-2 px-3">
                    {item.action === 'add' && (
                      <Badge variant="outline" className="border-emerald-500 text-emerald-400 text-[10px] gap-1">
                        <PlusCircle className="h-3 w-3" /> 新增
                      </Badge>
                    )}
                    {item.action === 'update' && (
                      <Badge variant="outline" className="border-sky-500 text-sky-400 text-[10px] gap-1">
                        <RefreshCw className="h-3 w-3" /> 更新
                      </Badge>
                    )}
                    {item.action === 'delete' && (
                      <Badge variant="outline" className="border-rose-500 text-rose-400 text-[10px] gap-1">
                        <Trash2 className="h-3 w-3" /> 刪除
                      </Badge>
                    )}
                    {item.action === 'identical' && (
                      <Badge variant="secondary" className="text-[10px] gap-1 text-muted-foreground">
                        <CheckCircle2 className="h-3 w-3" /> 一致
                      </Badge>
                    )}
                  </td>
                  <td className="py-2 px-3 font-mono text-foreground truncate max-w-xs">{item.path}</td>
                  <td className="py-2 px-3 text-right text-muted-foreground font-mono">
                    {formatBytes(item.size)}
                  </td>
                  <td className="py-2 px-3 text-right text-muted-foreground text-[11px] truncate">
                    {item.reason}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button size="sm" onClick={onExecute} disabled={isExecuting} className="gap-1.5 shadow-sm">
            <Play className="h-3.5 w-3.5" />
            {isExecuting ? '啟動中...' : '確認無誤，立即啟動同步'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
