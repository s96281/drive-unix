import React, { useState, useEffect } from 'react';
import {
  Info,
  Layers,
  Cpu,
  Globe,
  HardDrive,
  Github,
  BookOpen,
  Terminal,
  ExternalLink,
  ShieldCheck,
  Rocket,
  RefreshCw,
  Sparkles,
  CheckCircle2,
  AlertCircle,
  Loader2,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { api } from '@/api';
import type { UpgradeStatusResponse } from '@/api/types';
import { UpgradeModal } from '@/components/upgrade/UpgradeModal';
import { toast } from 'sonner';

export function AboutPage() {
  const [upgradeStatus, setUpgradeStatus] = useState<UpgradeStatusResponse | null>(null);
  const [checking, setChecking] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);

  const fetchStatus = async (force: boolean = false) => {
    setChecking(true);
    try {
      const res = await api.request<UpgradeStatusResponse>(
        force ? 'POST' : 'GET',
        force ? '/upgrade/check' : '/upgrade/status',
      );
      setUpgradeStatus(res);
      if (force) {
        if (res.has_update) {
          toast.success(`發現新版本 v${res.latest_version}！`);
        } else {
          toast.info(`目前已是最新版本 (v${res.current_version})。`);
        }
      }
    } catch (err: any) {
      console.warn('Failed to fetch upgrade status:', err);
    } finally {
      setChecking(false);
    }
  };

  useEffect(() => {
    fetchStatus(false);
  }, []);

  return (
    <div className="space-y-6 pb-12 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <Info className="h-5 w-5 text-primary" />
            <span>關於系統 (About drive-unix)</span>
          </h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            現代化聚合雲端硬碟管理平台，全面仿照 AlistGo/alist-web 架構風格與後台控制工作流
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => fetchStatus(true)}
            disabled={checking}
            className="text-xs gap-1.5"
          >
            {checking ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            <span>檢查更新</span>
          </Button>

          <Button
            size="sm"
            onClick={() => setModalOpen(true)}
            className="text-xs gap-1.5 bg-primary text-primary-foreground hover:bg-primary/90"
          >
            <Rocket className="h-3.5 w-3.5" />
            <span>{upgradeStatus?.has_update ? '立即升級' : '版本與升級'}</span>
          </Button>
        </div>
      </div>

      {/* Upgrade Notification Banner if update is available */}
      {upgradeStatus?.has_update && (
        <div className="rounded-xl border border-primary/30 bg-primary/10 p-4 flex flex-wrap items-center justify-between gap-3 shadow-xs">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-primary/20 text-primary flex items-center justify-center shrink-0">
              <Sparkles className="h-5 w-5 animate-pulse" />
            </div>
            <div>
              <div className="text-sm font-semibold text-foreground flex items-center gap-2">
                <span>發現 drive-unix 新版本：v{upgradeStatus.latest_version}</span>
                <Badge className="bg-primary text-primary-foreground text-[10px]">NEW</Badge>
              </div>
              <p className="text-xs text-muted-foreground mt-0.5">
                目前安裝版本為 v{upgradeStatus.current_version}，推薦立即升級以取得最新安全改進與功能增強。
              </p>
            </div>
          </div>

          <Button size="sm" onClick={() => setModalOpen(true)} className="text-xs gap-1.5 shrink-0">
            <Rocket className="h-3.5 w-3.5" />
            <span>一鍵升級至 v{upgradeStatus.latest_version}</span>
          </Button>
        </div>
      )}

      {/* Info Overview Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="rounded-xl border border-border bg-card p-4 shadow-xs space-y-1.5">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-xs">系統核心版本</span>
            <Layers className="h-4 w-4 text-primary" />
          </div>
          <div className="text-xl font-bold text-foreground flex items-center gap-2">
            <span>v{upgradeStatus?.current_version || '0.1.0'}</span>
            {upgradeStatus?.git_commit && (
              <span className="text-xs font-mono font-normal text-muted-foreground">
                ({upgradeStatus.git_commit})
              </span>
            )}
          </div>
          <div className="flex items-center justify-between text-[11px] text-muted-foreground">
            <span>模式: {upgradeStatus?.install_mode?.toUpperCase() || 'GIT'}</span>
            {upgradeStatus?.has_update ? (
              <span className="text-primary font-medium">有新版本</span>
            ) : (
              <span className="text-emerald-500 font-medium">已是最新</span>
            )}
          </div>
        </div>

        <div className="rounded-xl border border-border bg-card p-4 shadow-xs space-y-1.5">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-xs">後端執行環境</span>
            <Cpu className="h-4 w-4 text-emerald-500" />
          </div>
          <div className="text-xl font-bold text-foreground">Python 3.12+</div>
          <p className="text-[11px] text-muted-foreground">FastAPI + Async Storage Pool</p>
        </div>

        <div className="rounded-xl border border-border bg-card p-4 shadow-xs space-y-1.5">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-xs">前端架構</span>
            <Globe className="h-4 w-4 text-blue-500" />
          </div>
          <div className="text-xl font-bold text-foreground">React 18 + Vite</div>
          <p className="text-[11px] text-muted-foreground">Hope UI Design Tokens</p>
        </div>

        <div className="rounded-xl border border-border bg-card p-4 shadow-xs space-y-1.5">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-xs">快取與憑證安全</span>
            <ShieldCheck className="h-4 w-4 text-amber-500" />
          </div>
          <div className="text-xl font-bold text-foreground">E2EE + SQLite</div>
          <p className="text-[11px] text-muted-foreground">Upstash Redis AES-256-GCM</p>
        </div>
      </div>

      {/* Documentation / Architecture Render Card */}
      <div className="rounded-xl border border-border bg-card p-6 shadow-xs space-y-4">
        <h2 className="text-sm font-semibold text-foreground border-b border-border/60 pb-3">
          核心特性與架構設計 (Key Features)
        </h2>

        <div className="prose prose-sm dark:prose-invert max-w-none text-xs leading-relaxed space-y-3">
          <p>
            <code>drive-unix</code> 是一套整合 Google Drive、Microsoft OneDrive、SharePoint、Google Photos、PikPak、WebDAV、SFTP 與本機目錄的多雲檔案管理與跨端鏡像同步系統。
          </p>

          <h3 className="font-semibold text-foreground text-sm pt-2">多雲掛載與智慧排程</h3>
          <ul className="list-disc list-inside space-y-1 text-muted-foreground">
            <li><strong>雙向跨端鏡像同步</strong>：具備 Dry-Run 預演差異比對、批次傳輸與破壞性鏡像刪除保護。</li>
            <li><strong>一鍵平滑升級與安全快照</strong>：支援 CLI 指令 (<code>drive-unix upgrade</code>) 與網頁端即時終端日誌流，升級前自動備份環境組態。</li>
            <li><strong>AList 結構化驅動</strong>：各雲端驅動支援獨立參數配置、動態條件顯示與連線延遲診斷。</li>
            <li><strong>多重要素驗證 (MFA) 支援</strong>：SharePoint 支援 Headless 瀏覽器智慧登入與 Authenticator 數字比對排查截圖。</li>
            <li><strong>路徑元資料 (Metas)</strong>：支援目錄層級密碼保護、自訂前台公告、正則過濾與 README 自動渲染。</li>
            <li><strong>10 項細粒度權限位元</strong>：仿照 AList 遮罩體系配置訪客與多使用者隔離根目錄。</li>
          </ul>

          <h3 className="font-semibold text-foreground text-sm pt-2">快速鍵操作指南</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 pt-1 font-mono text-[11px]">
            <div className="p-2 rounded bg-muted/40 border border-border/60 flex items-center justify-between">
              <span>全域搜尋快捷鍵</span>
              <kbd className="px-1.5 py-0.5 rounded bg-background border border-border shadow-2xs">Ctrl + K / /</kbd>
            </div>
            <div className="p-2 rounded bg-muted/40 border border-border/60 flex items-center justify-between">
              <span>切換前台檢視模式</span>
              <kbd className="px-1.5 py-0.5 rounded bg-background border border-border shadow-2xs">V</kbd>
            </div>
            <div className="p-2 rounded bg-muted/40 border border-border/60 flex items-center justify-between">
              <span>切換深色 / 淺色主題</span>
              <kbd className="px-1.5 py-0.5 rounded bg-background border border-border shadow-2xs">D</kbd>
            </div>
            <div className="p-2 rounded bg-muted/40 border border-border/60 flex items-center justify-between">
              <span>重新整理目錄快取</span>
              <kbd className="px-1.5 py-0.5 rounded bg-background border border-border shadow-2xs">R</kbd>
            </div>
          </div>
        </div>
      </div>

      {/* Upgrade Modal Dialog */}
      <UpgradeModal
        open={modalOpen}
        onOpenChange={setModalOpen}
        status={upgradeStatus}
        onRefresh={() => fetchStatus(true)}
      />
    </div>
  );
}
