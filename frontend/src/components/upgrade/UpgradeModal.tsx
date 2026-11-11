import React, { useState, useEffect, useRef } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Rocket,
  ShieldCheck,
  RotateCw,
  Terminal,
  CheckCircle2,
  AlertTriangle,
  Loader2,
  Copy,
  ExternalLink,
  Sparkles,
} from 'lucide-react';
import { api, isDemoMode } from '@/api';
import type { UpgradeStatusResponse } from '@/api/types';
import { toast } from 'sonner';

interface UpgradeModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  status: UpgradeStatusResponse | null;
  onRefresh: () => void;
}

export function UpgradeModal({ open, onOpenChange, status, onRefresh }: UpgradeModalProps) {
  const [phase, setPhase] = useState<'overview' | 'upgrading' | 'success' | 'error'>('overview');
  const [backupConfig, setBackupConfig] = useState(true);
  const [restartAfter, setRestartAfter] = useState(true);
  const [force, setForce] = useState(false);
  const [progress, setProgress] = useState(0);
  const [stepMessage, setStepMessage] = useState('');
  const [logs, setLogs] = useState<string[]>([]);
  const [restarting, setRestarting] = useState(false);

  const logContainerRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  // Auto-scroll terminal log
  useEffect(() => {
    if (logContainerRef.current) {
      logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight;
    }
  }, [logs]);

  // Clean up SSE stream on unmount or close
  useEffect(() => {
    if (!open) {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
      }
      setPhase('overview');
      setLogs([]);
      setProgress(0);
    }
  }, [open]);

  const startUpgrade = async () => {
    setPhase('upgrading');
    setProgress(5);
    setStepMessage('正在啟動升級任務...');
    setLogs(['[系統] 已發起升級請求，正在連線至升級串流服務...']);

    try {
      // 1. Trigger background upgrade execution
      await api.request('POST', '/upgrade/execute', {
        body: {
          target_version: status?.latest_version,
          channel: 'stable',
          backup_config: backupConfig,
          force,
          restart_after: restartAfter,
        },
      });

      // 2. Connect to SSE stream
      if (isDemoMode) {
        // Simulated progress for Demo Mode
        simulateDemoUpgrade();
      } else {
        connectUpgradeStream();
      }
    } catch (err: any) {
      setPhase('error');
      setLogs((prev) => [...prev, `[錯誤] 無法啟動升級: ${err.message}`]);
      toast.error(`升級失敗: ${err.message}`);
    }
  };

  const simulateDemoUpgrade = () => {
    const steps = [
      { pct: 15, msg: '正在建立系統組態安全備份...', log: '📦 備份完成: ~/.config/mycli/upgrades/backups/pre-upgrade.zip' },
      { pct: 40, msg: '正在拉取遠端最新代碼...', log: '🔄 執行 git fetch --tags origin (v0.2.0)' },
      { pct: 70, msg: '更新 Python 依賴套件...', log: '📦 執行 pip install -e . 完成' },
      { pct: 85, msg: '檢測並編譯前端資源...', log: '🎨 npm run build: 前端靜態資產更新完成' },
      { pct: 95, msg: '驗證新版本核心可用性...', log: '🧪 核心命令與匯入功能自檢通過' },
      { pct: 100, msg: '升級完成！', log: '🎉 drive-unix 已成功更新至版本 v0.2.0' },
    ];

    let i = 0;
    const interval = setInterval(() => {
      if (i < steps.length) {
        const item = steps[i];
        setProgress(item.pct);
        setStepMessage(item.msg);
        setLogs((prev) => [...prev, item.log]);
        i++;
      } else {
        clearInterval(interval);
        setPhase('success');
        toast.success('升級順利完成！');
      }
    }, 900);
  };

  const connectUpgradeStream = () => {
    const sse = new EventSource('/api/upgrade/stream');
    eventSourceRef.current = sse;

    sse.addEventListener('log', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        if (data.text) {
          setLogs((prev) => [...prev, data.text]);
        }
      } catch {
        setLogs((prev) => [...prev, e.data]);
      }
    });

    sse.addEventListener('step', (e: MessageEvent) => {
      try {
        const data = JSON.parse(e.data);
        if (data.percent !== undefined) setProgress(data.percent);
        if (data.message) setStepMessage(data.message);
      } catch {}
    });

    sse.addEventListener('completed', (e: MessageEvent) => {
      setProgress(100);
      setPhase('success');
      toast.success('軟體已成功升級！');
      sse.close();
      onRefresh();
    });

    sse.addEventListener('error', (e: MessageEvent) => {
      // If completed or failed, close
      if (progress < 100) {
        setPhase('error');
        setLogs((prev) => [...prev, '[錯誤] 串流中斷或升級過程遭遇錯誤。']);
      }
      sse.close();
    });
  };

  const copyLogs = () => {
    navigator.clipboard.writeText(logs.join('\n'));
    toast.success('升級日誌已複製到剪貼簿！');
  };

  const handleRestart = async () => {
    setRestarting(true);
    try {
      await api.request('POST', '/upgrade/restart');
      toast.success('已發送重新載入訊號，系統將在 3 秒後重新整理...');
      setTimeout(() => {
        window.location.reload();
      }, 3000);
    } catch (err: any) {
      toast.error(`重新載入失敗: ${err.message}`);
    } finally {
      setRestarting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl bg-card border-border shadow-2xl p-6">
        <DialogHeader className="border-b border-border pb-4">
          <div className="flex items-center justify-between">
            <DialogTitle className="text-lg font-bold flex items-center gap-2">
              <Rocket className="h-5 w-5 text-primary" />
              <span>系統升級精靈 (System Upgrade)</span>
            </DialogTitle>
            <Badge variant="outline" className="text-xs font-mono">
              當前: v{status?.current_version || '0.1.0'}
            </Badge>
          </div>
          <DialogDescription className="text-xs text-muted-foreground mt-1">
            提供無縫一鍵軟體更新，升級前將自動備份環境組態與金鑰庫
          </DialogDescription>
        </DialogHeader>

        {/* Phase 1: Overview */}
        {phase === 'overview' && (
          <div className="space-y-4 py-2">
            <div className="grid grid-cols-2 gap-3 p-3 rounded-lg bg-muted/40 border border-border/70 text-xs">
              <div>
                <span className="text-muted-foreground">目標版本:</span>
                <span className="ml-2 font-bold text-foreground">
                  v{status?.latest_version || status?.current_version}
                </span>
                {status?.has_update && (
                  <Badge className="ml-2 text-[10px] bg-emerald-500/10 text-emerald-500 border-emerald-500/20">
                    新版本可用
                  </Badge>
                )}
              </div>
              <div>
                <span className="text-muted-foreground">部署模式:</span>
                <span className="ml-2 font-mono font-semibold text-foreground uppercase">
                  {status?.install_mode || 'GIT'}
                </span>
              </div>
            </div>

            {/* Release Notes */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                <Sparkles className="h-3.5 w-3.5 text-primary" />
                <span>版本釋出紀錄 (Release Notes)</span>
              </label>
              <div className="max-h-48 overflow-y-auto rounded-md border border-border bg-background p-3 text-xs text-foreground/90 whitespace-pre-wrap leading-relaxed font-sans">
                {status?.release_notes || '目前尚無詳細釋出說明或已是最新版本。'}
              </div>
            </div>

            {/* Upgrade Options */}
            <div className="rounded-lg border border-border/80 p-3 space-y-2.5 bg-muted/20">
              <span className="text-xs font-semibold text-foreground">升級選項配置</span>

              <div className="flex items-center space-x-2">
                <Checkbox
                  id="backup"
                  checked={backupConfig}
                  onCheckedChange={(c) => setBackupConfig(!!c)}
                />
                <label htmlFor="backup" className="text-xs text-foreground font-medium cursor-pointer flex items-center gap-1">
                  <ShieldCheck className="h-3.5 w-3.5 text-emerald-500" />
                  <span>升級前自動建立系統設定快照備份 (推薦)</span>
                </label>
              </div>

              <div className="flex items-center space-x-2">
                <Checkbox
                  id="restart"
                  checked={restartAfter}
                  onCheckedChange={(c) => setRestartAfter(!!c)}
                />
                <label htmlFor="restart" className="text-xs text-foreground font-medium cursor-pointer flex items-center gap-1">
                  <RotateCw className="h-3.5 w-3.5 text-blue-500" />
                  <span>升級完成後自動發送訊號重新載入背景服務 (Zero-Downtime Reload)</span>
                </label>
              </div>

              <div className="flex items-center space-x-2">
                <Checkbox
                  id="force"
                  checked={force}
                  onCheckedChange={(c) => setForce(!!c)}
                />
                <label htmlFor="force" className="text-xs text-muted-foreground cursor-pointer">
                  強制重新拉取與編譯 (即使版本號相同)
                </label>
              </div>
            </div>

            <DialogFooter className="pt-2">
              <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
                取消
              </Button>
              <Button size="sm" onClick={startUpgrade} className="gap-1.5">
                <Rocket className="h-3.5 w-3.5" />
                <span>立即執行升級</span>
              </Button>
            </DialogFooter>
          </div>
        )}

        {/* Phase 2: Upgrading */}
        {phase === 'upgrading' && (
          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <div className="flex items-center justify-between text-xs">
                <span className="font-semibold text-foreground flex items-center gap-2">
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                  <span>{stepMessage || '正在升級中...'}</span>
                </span>
                <span className="font-mono text-muted-foreground">{progress}%</span>
              </div>
              <Progress value={progress} className="h-2" />
            </div>

            {/* Terminal Log Console */}
            <div className="rounded-lg border border-border bg-[#0f172a] text-emerald-400 font-mono text-xs overflow-hidden shadow-inner">
              <div className="bg-[#1e293b] px-3 py-1.5 flex items-center justify-between border-b border-border/40 text-[11px] text-muted-foreground">
                <div className="flex items-center gap-1.5">
                  <div className="w-2.5 h-2.5 rounded-full bg-red-500/80" />
                  <div className="w-2.5 h-2.5 rounded-full bg-amber-500/80" />
                  <div className="w-2.5 h-2.5 rounded-full bg-emerald-500/80" />
                  <span className="ml-2 text-slate-300 font-sans flex items-center gap-1">
                    <Terminal className="h-3 w-3" /> 升級即時日誌流 (Live Terminal)
                  </span>
                </div>
                <button
                  type="button"
                  onClick={copyLogs}
                  className="hover:text-white transition-colors flex items-center gap-1"
                >
                  <Copy className="h-3 w-3" /> 複製
                </button>
              </div>

              <div
                ref={logContainerRef}
                className="p-3 max-h-64 min-h-[160px] overflow-y-auto space-y-1 font-mono text-[11px] leading-relaxed"
              >
                {logs.map((log, idx) => (
                  <div key={idx} className="break-all whitespace-pre-wrap">
                    {log}
                  </div>
                ))}
              </div>
            </div>

            <p className="text-[11px] text-muted-foreground text-center">
              ⚠️ 升級進行中請勿關閉視窗或終止伺服器連線
            </p>
          </div>
        )}

        {/* Phase 3: Success */}
        {phase === 'success' && (
          <div className="space-y-4 py-4 text-center">
            <div className="w-12 h-12 rounded-full bg-emerald-500/10 text-emerald-500 mx-auto flex items-center justify-center">
              <CheckCircle2 className="h-7 w-7" />
            </div>
            <div>
              <h3 className="text-base font-bold text-foreground">升級完成！</h3>
              <p className="text-xs text-muted-foreground mt-1">
                系統已順利安裝最新組件並完成自檢測試。
              </p>
            </div>

            <div className="p-3 rounded-lg bg-muted/40 border border-border text-xs text-left font-mono max-h-36 overflow-y-auto">
              {logs.slice(-4).map((l, i) => (
                <div key={i} className="text-emerald-500">{l}</div>
              ))}
            </div>

            <DialogFooter className="sm:justify-center gap-2 pt-2">
              <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
                完成並關閉
              </Button>
              <Button size="sm" onClick={handleRestart} disabled={restarting} className="gap-1.5">
                {restarting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCw className="h-3.5 w-3.5" />}
                <span>立即重新載入服務</span>
              </Button>
            </DialogFooter>
          </div>
        )}

        {/* Phase 4: Error */}
        {phase === 'error' && (
          <div className="space-y-4 py-3 text-center">
            <div className="w-12 h-12 rounded-full bg-red-500/10 text-red-500 mx-auto flex items-center justify-center">
              <AlertTriangle className="h-7 w-7" />
            </div>
            <div>
              <h3 className="text-base font-bold text-destructive">升級失敗</h3>
              <p className="text-xs text-muted-foreground mt-1">
                在執行過程中遭遇例外狀況，系統已安全保留先前之備份還原檔。
              </p>
            </div>

            <div className="p-3 rounded-lg bg-red-950/20 border border-red-500/20 text-xs text-left font-mono text-red-400 max-h-36 overflow-y-auto">
              {logs.slice(-6).map((l, i) => (
                <div key={i}>{l}</div>
              ))}
            </div>

            <DialogFooter className="sm:justify-center gap-2 pt-2">
              <Button variant="outline" size="sm" onClick={() => onOpenChange(false)}>
                關閉
              </Button>
              <Button size="sm" onClick={startUpgrade} className="gap-1.5">
                <RotateCw className="h-3.5 w-3.5" />
                <span>重試升級</span>
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
