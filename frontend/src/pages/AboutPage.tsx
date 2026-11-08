import React from 'react';
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
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

export function AboutPage() {
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
          <Badge variant="outline" className="text-xs px-2.5 py-1 text-primary border-primary/30 bg-primary/10">
            Phase 6 UX Polish
          </Badge>
        </div>
      </div>

      {/* Info Overview Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="rounded-xl border border-border bg-card p-4 shadow-xs space-y-1.5">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-xs">系統核心版本</span>
            <Layers className="h-4 w-4 text-primary" />
          </div>
          <div className="text-xl font-bold text-foreground">v2.0.0-phase6</div>
          <p className="text-[11px] text-muted-foreground">AList UI & API 相容版</p>
        </div>

        <div className="rounded-xl border border-border bg-card p-4 shadow-xs space-y-1.5">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-xs">後端執行環境</span>
            <Cpu className="h-4 w-4 text-emerald-500" />
          </div>
          <div className="text-xl font-bold text-foreground">Python 3.12</div>
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
    </div>
  );
}
