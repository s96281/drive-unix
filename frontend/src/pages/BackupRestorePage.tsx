import React, { useState } from 'react';
import {
  Archive,
  Download,
  Upload,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  Terminal,
  CloudUpload,
  CloudDownload,
  Lock,
  Loader2,
  Trash2,
  FileCode,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { Badge } from '@/components/ui/badge';
import { api } from '@/api';
import type { SettingsResponse, RemoteListResponse, TaskItemResponse } from '@/api/types';
import { toast } from 'sonner';

interface LogEntry {
  type: 'info' | 'success' | 'error' | 'warn';
  message: string;
  time: string;
}

export function BackupRestorePage() {
  const [backupLoading, setBackupLoading] = useState(false);
  const [restoreLoading, setRestoreLoading] = useState(false);
  const [cloudLoading, setCloudLoading] = useState(false);
  const [overrideExisting, setOverrideExisting] = useState(true);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([
    {
      type: 'info',
      message: '備份與還原主控台已準備就緒。支援本機 JSON 封裝匯出與 Upstash 雲端 E2EE 加密同步。',
      time: new Date().toLocaleTimeString('zh-TW'),
    },
  ]);

  const addLog = (type: LogEntry['type'], message: string) => {
    setLogs((prev) => [
      ...prev,
      {
        type,
        message,
        time: new Date().toLocaleTimeString('zh-TW'),
      },
    ]);
  };

  const handleBackup = async () => {
    setBackupLoading(true);
    addLog('info', '[ + ] 開始執行系統完整組態打包...');

    try {
      // 1. Fetch settings (contains extra_options: metas, users, index)
      addLog('info', '[ ... ] 正在獲取系統全域設定與元資料...');
      const settingsResp = await api.request<SettingsResponse>('GET', '/settings');
      addLog('success', '[ + ] 完成備份系統設定 (Settings) 與元資料 (Metas/Users)。');

      // 2. Fetch remotes
      addLog('info', '[ ... ] 正在獲取儲存節點清單 (Storages)...');
      const remotesResp = await api.request<RemoteListResponse>('GET', '/remotes');
      addLog('success', `[ + ] 完成備份儲存節點 (${remotesResp.remotes?.length || 0} 個節點)。`);

      // 3. Fetch schedules
      addLog('info', '[ ... ] 正在獲取定時排程規則 (Schedules)...');
      const schedulesResp = await api.request<TaskItemResponse[]>('GET', '/schedule');
      addLog('success', `[ + ] 完成備份定時排程 (${schedulesResp?.length || 0} 條規則)。`);

      // 4. Assemble backup payload
      const backupData = {
        version: 'drive-unix-2.0',
        exported_at: new Date().toISOString(),
        settings: settingsResp.settings,
        remotes: remotesResp.remotes,
        default_remote: remotesResp.default_remote,
        schedules: schedulesResp,
      };

      // 5. Trigger download
      const blob = new Blob([JSON.stringify(backupData, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const dateStr = new Date().toISOString().slice(0, 10);
      a.href = url;
      a.download = `backup-alist-drive-unix-${dateStr}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      addLog('success', `[ + ] 備份檔案已成功下載至用戶端瀏覽器：backup-alist-drive-unix-${dateStr}.json`);
      toast.success('系統設定已成功備份並下載！');
    } catch (err: any) {
      addLog('error', `[ ! ] 備份過程發生錯誤: ${err.message}`);
      toast.error(`備份失敗: ${err.message}`);
    } finally {
      setBackupLoading(false);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      setSelectedFile(file);
      addLog('info', `[ + ] 已選取還原檔案: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`);
    }
  };

  const handleRestore = async () => {
    if (!selectedFile) {
      toast.error('請先選取備份 JSON 檔案');
      return;
    }

    if (!confirm(`確定要從檔案 [${selectedFile.name}] 還原系統組態嗎？${overrideExisting ? '（將覆寫既有儲存節點與設定）' : ''}`)) {
      return;
    }

    setRestoreLoading(true);
    addLog('info', `[ + ] 開始解析還原檔案: ${selectedFile.name}...`);

    try {
      const text = await selectedFile.text();
      const data = JSON.parse(text);

      if (!data.settings && !data.remotes) {
        throw new Error('無效的備份檔案格式，缺少必要之 settings 或 remotes 節點');
      }

      // 1. Restore settings
      if (data.settings) {
        addLog('info', '[ ... ] 正在還原全域設定、UI 與元資料 (Metas/Users)...');
        await api.request('PUT', '/settings', {
          body: {
            cache: data.settings.cache,
            ui: data.settings.ui,
            security: data.settings.security,
            transfer: data.settings.transfer,
            extra_options: data.settings.extra_options,
          },
        });
        addLog('success', '[ + ] 全域設定與元資料還原成功。');
      }

      // 2. Restore remotes
      if (Array.isArray(data.remotes)) {
        addLog('info', `[ ... ] 正在還原 ${data.remotes.length} 個儲存節點...`);
        for (const r of data.remotes) {
          try {
            await api.request('POST', '/remotes', {
              body: {
                name: r.name,
                type: r.type,
                is_default: r.is_default || r.name === data.default_remote,
                params: r.details || {},
              },
            });
            addLog('success', `[ + ] 儲存節點 [/${r.name}] (${r.type}) 已建立。`);
          } catch (rErr: any) {
            if (overrideExisting && rErr.status === 409) {
              await api.request('PUT', `/remotes/${r.name}`, {
                body: {
                  is_default: r.is_default || r.name === data.default_remote,
                  params: r.details || {},
                },
              });
              addLog('warn', `[ ~ ] 儲存節點 [/${r.name}] 已存在，已執行參數覆寫更新。`);
            } else {
              addLog('error', `[ ! ] 節點 [/${r.name}] 還原失敗: ${rErr.message}`);
            }
          }
        }
      }

      // 3. Restore schedules
      if (Array.isArray(data.schedules)) {
        addLog('info', `[ ... ] 正在還原 ${data.schedules.length} 條定時排程規則...`);
        for (const s of data.schedules) {
          try {
            await api.request('POST', '/schedule', {
              body: {
                name: s.name,
                schedule: s.schedule || s.cron,
                command: s.command,
                enabled: s.enabled,
              },
            });
            addLog('success', `[ + ] 排程規則 [${s.name}] 已建立。`);
          } catch (sErr: any) {
            addLog('warn', `[ ~ ] 排程規則 [${s.name}] 跳過: ${sErr.message}`);
          }
        }
      }

      addLog('success', '[ + ] 系統組態還原作業全數完成！');
      toast.success('系統設定已成功還原！');
    } catch (err: any) {
      addLog('error', `[ ! ] 還原作業失敗: ${err.message}`);
      toast.error(`還原失敗: ${err.message}`);
    } finally {
      setRestoreLoading(false);
    }
  };

  const handleCloudPush = async () => {
    setCloudLoading(true);
    addLog('info', '[ ... ] 正在將當前憑證與節點推送至 Upstash E2EE 雲端加密庫...');
    try {
      await api.request('POST', '/upstash/push', { body: {} });
      addLog('success', '[ + ] 雲端加密推送完成！憑證已安全同步至分散式金鑰庫。');
      toast.success('雲端加密備份推送成功！');
    } catch (err: any) {
      addLog('error', `[ ! ] 雲端推送失敗: ${err.message}`);
      toast.error(`雲端推送失敗: ${err.message}`);
    } finally {
      setCloudLoading(false);
    }
  };

  const handleCloudPull = async () => {
    setCloudLoading(true);
    addLog('info', '[ ... ] 正在從 Upstash E2EE 雲端金鑰庫拉取憑證與節點...');
    try {
      await api.request('POST', '/upstash/pull', { body: {} });
      addLog('success', '[ + ] 雲端拉取並解密成功！憑證已即時套用。');
      toast.success('雲端還原完成！');
    } catch (err: any) {
      addLog('error', `[ ! ] 雲端拉取失敗: ${err.message}`);
      toast.error(`雲端拉取失敗: ${err.message}`);
    } finally {
      setCloudLoading(false);
    }
  };

  return (
    <div className="space-y-6 pb-12 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <Archive className="h-5 w-5 text-primary" />
            <span>備份與還原 (Backup & Restore)</span>
          </h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            仿照 AList 一鍵匯出與還原設定檔、儲存節點、排程與元資料，並提供即時彩色執行終端機
          </p>
        </div>
      </div>

      {/* Main Operations Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Card 1: Backup */}
        <div className="rounded-xl border border-border bg-card p-5 shadow-xs space-y-4 flex flex-col justify-between">
          <div className="space-y-2">
            <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
              <Download className="h-4 w-4 text-emerald-500" />
              <span>一鍵備份匯出 (Backup)</span>
            </h2>
            <p className="text-xs text-muted-foreground leading-relaxed">
              將所有站點設定、儲存節點 (Remotes)、定時排程規則、路徑元資料 (Metas) 與使用者名冊完整封裝為標準 JSON 檔案，供日後快速遷移或災難復原。
            </p>
          </div>

          <div className="pt-2">
            <Button
              onClick={handleBackup}
              disabled={backupLoading}
              className="w-full text-xs gap-2"
            >
              {backupLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
              <span>產生並下載備份檔案 (.json)</span>
            </Button>
          </div>
        </div>

        {/* Card 2: Restore */}
        <div className="rounded-xl border border-border bg-card p-5 shadow-xs space-y-4 flex flex-col justify-between">
          <div className="space-y-3">
            <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
              <Upload className="h-4 w-4 text-blue-500" />
              <span>匯入檔案還原 (Restore)</span>
            </h2>

            <div className="space-y-2">
              <input
                type="file"
                accept=".json"
                onChange={handleFileChange}
                className="w-full text-xs text-muted-foreground file:mr-3 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:text-xs file:font-semibold file:bg-primary file:text-primary-foreground hover:file:opacity-90 cursor-pointer"
              />

              <div className="flex items-center justify-between pt-1">
                <label className="flex items-center gap-2 text-xs font-medium text-foreground cursor-pointer select-none">
                  <Switch checked={overrideExisting} onCheckedChange={setOverrideExisting} />
                  <span>覆寫既有節點與組態 (Override)</span>
                </label>
              </div>
            </div>
          </div>

          <div className="pt-2">
            <Button
              variant="outline"
              onClick={handleRestore}
              disabled={restoreLoading || !selectedFile}
              className="w-full text-xs gap-2"
            >
              {restoreLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
              <span>執行組態還原</span>
            </Button>
          </div>
        </div>

        {/* Card 3: Upstash Cloud E2EE Sync */}
        <div className="md:col-span-2 rounded-xl border border-border bg-card p-5 shadow-xs space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
              <Lock className="h-4 w-4 text-amber-500" />
              <span>Upstash E2EE 雲端加密金鑰庫同步</span>
            </h2>
            <Badge variant="outline" className="text-[10px]">
              AES-256-GCM
            </Badge>
          </div>
          <p className="text-xs text-muted-foreground">
            若已在「設定 &gt; 其他」中配置 Upstash Redis REST 端點與密碼短語，可將多雲存取權杖加密推播至全域雲端，實現多台 drive-unix 節點自動輪替免重新認證。
          </p>

          <div className="flex flex-wrap items-center gap-3 pt-1">
            <Button
              size="sm"
              variant="outline"
              onClick={handleCloudPush}
              disabled={cloudLoading}
              className="text-xs gap-1.5"
            >
              <CloudUpload className="h-3.5 w-3.5 text-blue-500" />
              <span>加密推送至雲端 (Cloud Push)</span>
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={handleCloudPull}
              disabled={cloudLoading}
              className="text-xs gap-1.5"
            >
              <CloudDownload className="h-3.5 w-3.5 text-emerald-500" />
              <span>從雲端拉取並還原 (Cloud Pull)</span>
            </Button>
          </div>
        </div>
      </div>

      {/* Terminal Log Console */}
      <div className="rounded-xl border border-border bg-black text-slate-200 overflow-hidden shadow-lg">
        <div className="flex items-center justify-between px-4 py-2.5 bg-zinc-900 border-b border-zinc-800 text-xs text-zinc-400 select-none">
          <div className="flex items-center gap-2">
            <Terminal className="h-3.5 w-3.5 text-emerald-400" />
            <span className="font-mono font-medium">執行即時日誌終端機 (Execution Terminal)</span>
          </div>
          <button
            type="button"
            onClick={() => setLogs([])}
            className="hover:text-zinc-200 flex items-center gap-1 text-[11px]"
          >
            <Trash2 className="h-3 w-3" />
            <span>清空記錄</span>
          </button>
        </div>

        <div className="p-4 font-mono text-[11px] space-y-1.5 max-h-72 overflow-y-auto">
          {logs.length === 0 ? (
            <div className="text-zinc-600">尚無日誌記錄。</div>
          ) : (
            logs.map((log, idx) => {
              const colorClass =
                log.type === 'success'
                  ? 'text-emerald-400'
                  : log.type === 'error'
                  ? 'text-red-400 font-bold'
                  : log.type === 'warn'
                  ? 'text-amber-400'
                  : 'text-zinc-300';
              return (
                <div key={idx} className="flex items-start gap-2 leading-relaxed">
                  <span className="text-zinc-600 shrink-0">[{log.time}]</span>
                  <span className={colorClass}>{log.message}</span>
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
