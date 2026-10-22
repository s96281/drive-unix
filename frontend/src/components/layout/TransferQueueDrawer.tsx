import { X, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react';
import { useTransferQueue } from '@/stores/transfer-queue';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { formatBytes } from '@/lib/format';
import { ScrollArea } from '@/components/ui/scroll-area';

export function TransferQueueDrawer() {
  const { jobs, isDrawerOpen, setDrawerOpen, cancelJob, clearCompleted } = useTransferQueue();

  const completedCount = jobs.filter((j) => j.status === 'completed').length;

  return (
    <Dialog open={isDrawerOpen} onOpenChange={setDrawerOpen}>
      <DialogContent className="max-w-md p-0 overflow-hidden">
        <DialogHeader className="p-4 pb-2 border-b border-border/80 flex flex-row items-center justify-between">
          <div>
            <DialogTitle className="text-base font-semibold">本機傳輸佇列</DialogTitle>
            <DialogDescription className="text-xs text-muted-foreground mt-0.5">
              共有 {jobs.length} 項檔案上傳作業
            </DialogDescription>
          </div>
          {completedCount > 0 && (
            <Button variant="ghost" size="sm" onClick={clearCompleted} className="text-xs h-7 px-2">
              清除已完成
            </Button>
          )}
        </DialogHeader>

        <ScrollArea className="max-h-96 p-4">
          {jobs.length === 0 ? (
            <div className="py-12 text-center text-muted-foreground text-sm">目前佇列中無進行中之上傳</div>
          ) : (
            <div className="space-y-3">
              {jobs.map((job) => (
                <div key={job.id} className="p-3 rounded-lg border border-border bg-card/60 space-y-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium truncate text-foreground">{job.file.name}</span>
                    <div className="flex items-center gap-1.5 shrink-0">
                      {job.status === 'uploading' && <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />}
                      {job.status === 'completed' && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />}
                      {job.status === 'failed' && <AlertCircle className="h-3.5 w-3.5 text-rose-500" />}
                      {job.status === 'uploading' && (
                        <Button
                          variant="ghost"
                          size="iconSm"
                          onClick={() => cancelJob(job.id)}
                          className="h-6 w-6 text-muted-foreground hover:text-foreground"
                        >
                          <X className="h-3 w-3" />
                        </Button>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center justify-between text-xs text-muted-foreground">
                    <span>
                      {job.remote}:{job.targetDir}
                    </span>
                    <span>
                      {formatBytes(job.progress.loaded)} / {formatBytes(job.progress.total)} ({job.progress.percent}%)
                    </span>
                  </div>

                  <Progress value={job.progress.percent} className="h-1.5" />

                  {job.error && <p className="text-xs text-rose-400 mt-1">{job.error}</p>}
                </div>
              ))}
            </div>
          )}
        </ScrollArea>
      </DialogContent>
    </Dialog>
  );
}
