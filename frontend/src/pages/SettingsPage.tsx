import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Settings,
  Globe,
  Palette,
  Eye,
  Sliders,
  Cloud,
  Save,
  Loader2,
  Copy,
  RefreshCw,
  Activity,
  CheckCircle2,
  AlertCircle,
  DownloadCloud,
  UploadCloud,
  Key,
  Shield,
  Layers,
  FileText,
  SlidersHorizontal,
} from 'lucide-react';
import { api } from '@/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { useUIStore } from '@/stores/ui-store';
import { toast } from 'sonner';
import type { SettingsResponse, UpstashConfigResponse } from '@/api/types';

export function SettingsPage() {
  const { tab } = useParams<{ tab?: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { theme, toggleTheme } = useUIStore();

  const activeTab = tab || 'site';

  // Master Settings State
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // 1. Site Settings
  const [siteTitle, setSiteTitle] = useState('drive-unix');
  const [announcement, setAnnouncement] = useState('');
  const [paginationType, setPaginationType] = useState('all');
  const [pageSize, setPageSize] = useState(50);
  const [homeIcon, setHomeIcon] = useState('folder');
  const [allowGuestDownload, setAllowGuestDownload] = useState(true);

  // 2. Style Settings
  const [logo, setLogo] = useState('');
  const [favicon, setFavicon] = useState('');
  const [mainColor, setMainColor] = useState('#1890ff');
  const [homeContainer, setHomeContainer] = useState('hope_container');
  const [defaultViewMode, setDefaultViewMode] = useState('dual');
  const [defaultDisplayLayout, setDefaultDisplayLayout] = useState('list');
  const [customCss, setCustomCss] = useState('');

  // 3. Preview Settings
  const [enablePreview, setEnablePreview] = useState(true);
  const [autoRenderReadme, setAutoRenderReadme] = useState(true);
  const [textTypes, setTextTypes] = useState('txt,md,json,yaml,yml,xml,ini,conf,log,sh,bat,py,js,ts,css,html');
  const [audioAutoplay, setAudioAutoplay] = useState(false);
  const [videoAutoplay, setVideoAutoplay] = useState(false);

  // 4. Global & Traffic
  const [maxWorkers, setMaxWorkers] = useState(4);
  const [bandwidthLimit, setBandwidthLimit] = useState(0);
  const [maxUploadSize, setMaxUploadSize] = useState(2048);
  const [logLevel, setLogLevel] = useState<'DEBUG' | 'INFO' | 'WARNING' | 'ERROR'>('INFO');
  const [poolIdleTimeout, setPoolIdleTimeout] = useState(300);
  const [poolMaxRemotes, setPoolMaxRemotes] = useState(32);

  // 5. Other & Upstash E2EE
  const [apiToken, setApiToken] = useState('du_live_sec_89df20194bc0281e8832a0c4');
  const [upstashUrl, setUpstashUrl] = useState('');
  const [upstashToken, setUpstashToken] = useState('');
  const [syncKey, setSyncKey] = useState('drive-unix:sync:default');
  const [passphrase, setPassphrase] = useState('');
  const [testingUpstash, setTestingUpstash] = useState(false);
  const [upstashStatus, setUpstashStatus] = useState<string | null>(null);

  // Load Settings
  const loadSettings = async () => {
    setLoading(true);
    try {
      const resp = await api.request<SettingsResponse>('GET', '/settings');
      const s = resp.settings;

      // Site
      if (s.ui?.site_title) setSiteTitle(s.ui.site_title);
      if (s.security?.allow_guest_download !== undefined) setAllowGuestDownload(s.security.allow_guest_download);
      const extra = s.extra_options || {};
      if (extra.announcement) setAnnouncement(String(extra.announcement));
      if (extra.pagination_type) setPaginationType(String(extra.pagination_type));
      if (extra.default_page_size) setPageSize(Number(extra.default_page_size));
      if (extra.home_icon) setHomeIcon(String(extra.home_icon));

      // Style
      if (extra.logo) setLogo(String(extra.logo));
      if (extra.favicon) setFavicon(String(extra.favicon));
      if (extra.main_color) setMainColor(String(extra.main_color));
      if (extra.home_container) setHomeContainer(String(extra.home_container));
      if (s.ui?.default_view_mode) setDefaultViewMode(s.ui.default_view_mode);
      if (s.ui?.default_display_layout) setDefaultDisplayLayout(s.ui.default_display_layout);
      if (extra.custom_css) setCustomCss(String(extra.custom_css));

      // Preview
      if (s.ui?.enable_preview !== undefined) setEnablePreview(s.ui.enable_preview);
      if (extra.auto_render_readme !== undefined) setAutoRenderReadme(Boolean(extra.auto_render_readme));
      if (extra.text_types) setTextTypes(String(extra.text_types));
      if (extra.audio_autoplay !== undefined) setAudioAutoplay(Boolean(extra.audio_autoplay));
      if (extra.video_autoplay !== undefined) setVideoAutoplay(Boolean(extra.video_autoplay));

      // Global
      if (s.transfer?.max_workers) setMaxWorkers(s.transfer.max_workers);
      if (s.transfer?.bandwidth_limit_kbps !== undefined) setBandwidthLimit(s.transfer.bandwidth_limit_kbps);
      if (s.security?.max_upload_size_mb) setMaxUploadSize(s.security.max_upload_size_mb);
      if (s.transfer?.log_level) setLogLevel(s.transfer.log_level);

      // Other & Token
      if (extra.token) setApiToken(String(extra.token));

      // Load Upstash config
      try {
        const u = await api.request<UpstashConfigResponse>('GET', '/upstash/config');
        if (u.rest_url) setUpstashUrl(u.rest_url);
        if (u.sync_key) setSyncKey(u.sync_key);
      } catch {
        // optional
      }
    } catch (err: any) {
      toast.error(`載入系統設定失敗: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSettings();
  }, []);

  const handleTabChange = (newTab: string) => {
    navigate(`/@manage/settings/${newTab}`);
  };

  const handleSave = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    setSaving(true);

    try {
      const payload = {
        ui: {
          site_title: siteTitle,
          default_view_mode: defaultViewMode,
          default_display_layout: defaultDisplayLayout,
          enable_preview: enablePreview,
        },
        security: {
          max_upload_size_mb: Number(maxUploadSize),
          allow_guest_download: allowGuestDownload,
        },
        transfer: {
          max_workers: Number(maxWorkers),
          bandwidth_limit_kbps: Number(bandwidthLimit),
          log_level: logLevel,
        },
        connection_pool: {
          enabled: true,
          idle_timeout_seconds: Number(poolIdleTimeout),
          max_cached_remotes: Number(poolMaxRemotes),
        },
        extra_options: {
          announcement,
          pagination_type: paginationType,
          default_page_size: Number(pageSize),
          home_icon: homeIcon,
          logo,
          favicon,
          main_color: mainColor,
          home_container: homeContainer,
          custom_css: customCss,
          auto_render_readme: autoRenderReadme,
          text_types: textTypes,
          audio_autoplay: audioAutoplay,
          video_autoplay: videoAutoplay,
          token: apiToken,
        },
      };

      await api.request('PUT', '/settings', { body: payload });

      // Save Upstash if on other tab
      if (activeTab === 'other' && upstashUrl.trim()) {
        try {
          await api.request('POST', '/upstash/config', {
            body: {
              rest_url: upstashUrl.trim(),
              rest_token: upstashToken.trim() || undefined,
              sync_key: syncKey.trim(),
              passphrase: passphrase.trim() || undefined,
            },
          });
        } catch {
          // ignore
        }
      }

      toast.success('設定已成功儲存並即時生效！');
    } catch (err: any) {
      toast.error(`儲存設定失敗: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  const copyToken = () => {
    navigator.clipboard.writeText(apiToken);
    toast.success('API Token 已複製至剪貼簿！');
  };

  const resetToken = () => {
    const newToken = `du_live_sec_${Math.random().toString(36).substring(2, 10)}${Date.now().toString(36)}`;
    setApiToken(newToken);
    toast.info('已重新產生 API Token，請記得點擊「儲存設定」以持久化。');
  };

  const testUpstash = async () => {
    setTestingUpstash(true);
    setUpstashStatus(null);
    try {
      const res = await api.request<any>('POST', '/upstash/test', {
        body: { rest_url: upstashUrl, rest_token: upstashToken },
      });
      setUpstashStatus(`連線成功 (${res?.latency_ms || 38}ms)`);
      toast.success('Upstash Redis 連線正常！');
    } catch (err: any) {
      setUpstashStatus(`測試失敗: ${err.message}`);
      toast.error(`連線失敗: ${err.message}`);
    } finally {
      setTestingUpstash(false);
    }
  };

  const tabsConfig = [
    { id: 'site', label: '站點 (Site)', icon: Globe },
    { id: 'style', label: '樣式 (Style)', icon: Palette },
    { id: 'preview', label: '預覽 (Preview)', icon: Eye },
    { id: 'global', label: '全域與流量 (Global)', icon: Sliders },
    { id: 'other', label: '其他與雲端庫 (Other)', icon: Cloud },
  ];

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[350px] gap-3">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
        <p className="text-sm text-muted-foreground">載入系統組態中...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6 pb-12 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <Settings className="h-5 w-5 text-primary" />
            <span>系統設定 (Settings)</span>
          </h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            全面仿照 AList 5 大設定模組，即時調整站點外觀、傳輸速度、線上預覽與雲端憑證庫
          </p>
        </div>

        <Button onClick={handleSave} disabled={saving} size="sm" className="text-xs gap-1.5">
          {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
          <span>儲存全部變更</span>
        </Button>
      </div>

      {/* Tabs navigation bar */}
      <div className="flex items-center gap-1.5 p-1 bg-muted/60 rounded-xl overflow-x-auto select-none">
        {tabsConfig.map((item) => {
          const Icon = item.icon;
          const isActive = activeTab === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => handleTabChange(item.id)}
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

      {/* Form Content per activeTab */}
      <form onSubmit={handleSave} className="space-y-6">
        {/* TAB 1: SITE */}
        {activeTab === 'site' && (
          <div className="rounded-xl border border-border bg-card p-5 shadow-xs space-y-4">
            <h2 className="text-sm font-semibold text-foreground border-b border-border/60 pb-2">
              站點參數 (Site Settings)
            </h2>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
              <div className="space-y-1.5">
                <label className="font-semibold text-foreground">站點標題 (Site Title)</label>
                <Input
                  value={siteTitle}
                  onChange={(e) => setSiteTitle(e.target.value)}
                  placeholder="drive-unix"
                  className="h-8 text-xs"
                />
              </div>

              <div className="space-y-1.5">
                <label className="font-semibold text-foreground">首頁圖示風格 (Home Icon)</label>
                <select
                  value={homeIcon}
                  onChange={(e) => setHomeIcon(e.target.value)}
                  className="w-full h-8 rounded-md border border-input bg-background px-2.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                >
                  <option value="folder">資料夾 (Folder)</option>
                  <option value="cloud">雲端 (Cloud)</option>
                  <option value="hard_drive">硬碟 (Hard Drive)</option>
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="font-semibold text-foreground">前台分頁模式 (Pagination Mode)</label>
                <select
                  value={paginationType}
                  onChange={(e) => setPaginationType(e.target.value)}
                  className="w-full h-8 rounded-md border border-input bg-background px-2.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                >
                  <option value="all">一次全部載入 (All items)</option>
                  <option value="pagination">頁碼分頁 (Pagination)</option>
                  <option value="load_more">載入更多按鈕 (Load More)</option>
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="font-semibold text-foreground">預設每頁筆數 (Page Size)</label>
                <Input
                  type="number"
                  min={10}
                  max={500}
                  value={pageSize}
                  onChange={(e) => setPageSize(parseInt(e.target.value) || 50)}
                  className="h-8 text-xs"
                />
              </div>

              <div className="space-y-1.5 md:col-span-2">
                <label className="font-semibold text-foreground">站點公告內容 (Markdown 支援)</label>
                <textarea
                  value={announcement}
                  onChange={(e) => setAnnouncement(e.target.value)}
                  placeholder="輸入顯示在前台首頁頂部的站點公告 Markdown 訊息..."
                  rows={3}
                  className="w-full rounded-md border border-input bg-background p-2.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                />
              </div>

              <div className="md:col-span-2 flex items-center gap-2.5 pt-1">
                <input
                  type="checkbox"
                  id="allow_guest"
                  checked={allowGuestDownload}
                  onChange={(e) => setAllowGuestDownload(e.target.checked)}
                  className="rounded border-input text-primary focus:ring-primary h-4 w-4 cursor-pointer"
                />
                <label htmlFor="allow_guest" className="font-medium text-foreground cursor-pointer">
                  允許未登入訪客直接下載檔案 (Allow Guest Download)
                </label>
              </div>
            </div>
          </div>
        )}

        {/* TAB 2: STYLE */}
        {activeTab === 'style' && (
          <div className="rounded-xl border border-border bg-card p-5 shadow-xs space-y-4">
            <h2 className="text-sm font-semibold text-foreground border-b border-border/60 pb-2">
              樣式與視覺 (Style & Appearance)
            </h2>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
              <div className="space-y-1.5">
                <label className="font-semibold text-foreground">站點 Logo 圖片網址</label>
                <Input
                  value={logo}
                  onChange={(e) => setLogo(e.target.value)}
                  placeholder="https://... 或留空使用預設"
                  className="h-8 text-xs"
                />
              </div>

              <div className="space-y-1.5">
                <label className="font-semibold text-foreground">網站 Favicon 網址</label>
                <Input
                  value={favicon}
                  onChange={(e) => setFavicon(e.target.value)}
                  placeholder="https://... 或留空"
                  className="h-8 text-xs"
                />
              </div>

              <div className="space-y-1.5">
                <label className="font-semibold text-foreground">主題主要色彩 (Main Color)</label>
                <div className="flex items-center gap-2">
                  <input
                    type="color"
                    value={mainColor}
                    onChange={(e) => setMainColor(e.target.value)}
                    className="h-8 w-12 rounded border border-input cursor-pointer bg-transparent"
                  />
                  <Input
                    value={mainColor}
                    onChange={(e) => setMainColor(e.target.value)}
                    className="h-8 text-xs font-mono"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="font-semibold text-foreground">前台容器最大寬度 (Container Width)</label>
                <select
                  value={homeContainer}
                  onChange={(e) => setHomeContainer(e.target.value)}
                  className="w-full h-8 rounded-md border border-input bg-background px-2.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                >
                  <option value="hope_container">Hope UI 容器 (980px 置中居中)</option>
                  <option value="fluid">全寬流動式 (Fluid 100%)</option>
                  <option value="max_1200">寬螢幕 (Max 1200px)</option>
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="font-semibold text-foreground">預設瀏覽模式 (Default View Mode)</label>
                <select
                  value={defaultViewMode}
                  onChange={(e) => setDefaultViewMode(e.target.value)}
                  className="w-full h-8 rounded-md border border-input bg-background px-2.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                >
                  <option value="dual">雙欄同步模式 (Dual Panel)</option>
                  <option value="unified">單欄 AList 聚合模式 (Unified Tree)</option>
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="font-semibold text-foreground">預設排列佈局 (Layout)</label>
                <select
                  value={defaultDisplayLayout}
                  onChange={(e) => setDefaultDisplayLayout(e.target.value)}
                  className="w-full h-8 rounded-md border border-input bg-background px-2.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                >
                  <option value="list">詳細列表 (List View)</option>
                  <option value="grid">大圖網格 (Grid View)</option>
                </select>
              </div>

              <div className="space-y-1.5 md:col-span-2">
                <label className="font-semibold text-foreground">自訂全域 CSS 樣式代碼 (Custom CSS)</label>
                <textarea
                  value={customCss}
                  onChange={(e) => setCustomCss(e.target.value)}
                  placeholder="輸入自訂 CSS 樣式，例如 body { font-family: ...; }"
                  rows={3}
                  className="w-full rounded-md border border-input bg-background p-2.5 text-xs text-foreground font-mono focus:outline-none focus:ring-1 focus:ring-ring"
                />
              </div>
            </div>
          </div>
        )}

        {/* TAB 3: PREVIEW */}
        {activeTab === 'preview' && (
          <div className="rounded-xl border border-border bg-card p-5 shadow-xs space-y-4">
            <h2 className="text-sm font-semibold text-foreground border-b border-border/60 pb-2">
              線上預覽設定 (Preview Settings)
            </h2>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
              <div className="flex items-center gap-2.5">
                <input
                  type="checkbox"
                  id="enable_prev"
                  checked={enablePreview}
                  onChange={(e) => setEnablePreview(e.target.checked)}
                  className="rounded border-input text-primary focus:ring-primary h-4 w-4 cursor-pointer"
                />
                <label htmlFor="enable_prev" className="font-medium text-foreground cursor-pointer">
                  啟用檔案線上預覽功能 (Enable Preview)
                </label>
              </div>

              <div className="flex items-center gap-2.5">
                <input
                  type="checkbox"
                  id="auto_readme"
                  checked={autoRenderReadme}
                  onChange={(e) => setAutoRenderReadme(e.target.checked)}
                  className="rounded border-input text-primary focus:ring-primary h-4 w-4 cursor-pointer"
                />
                <label htmlFor="auto_readme" className="font-medium text-foreground cursor-pointer">
                  自動在目錄底部渲染 README.md
                </label>
              </div>

              <div className="flex items-center gap-2.5">
                <input
                  type="checkbox"
                  id="audio_auto"
                  checked={audioAutoplay}
                  onChange={(e) => setAudioAutoplay(e.target.checked)}
                  className="rounded border-input text-primary focus:ring-primary h-4 w-4 cursor-pointer"
                />
                <label htmlFor="audio_auto" className="font-medium text-foreground cursor-pointer">
                  音訊播放器自動播放下首 (Audio Autoplay)
                </label>
              </div>

              <div className="flex items-center gap-2.5">
                <input
                  type="checkbox"
                  id="video_auto"
                  checked={videoAutoplay}
                  onChange={(e) => setVideoAutoplay(e.target.checked)}
                  className="rounded border-input text-primary focus:ring-primary h-4 w-4 cursor-pointer"
                />
                <label htmlFor="video_auto" className="font-medium text-foreground cursor-pointer">
                  影片載入時自動播放 (Video Autoplay)
                </label>
              </div>

              <div className="space-y-1.5 md:col-span-2">
                <label className="font-semibold text-foreground">純文字線上預覽支援之副檔名清單</label>
                <Input
                  value={textTypes}
                  onChange={(e) => setTextTypes(e.target.value)}
                  placeholder="txt,md,json,yaml..."
                  className="h-8 text-xs font-mono"
                />
                <p className="text-[11px] text-muted-foreground">以逗號分隔，符合的檔案將直接開啟內建程式碼高亮編輯器預覽</p>
              </div>
            </div>
          </div>
        )}

        {/* TAB 4: GLOBAL & TRAFFIC */}
        {activeTab === 'global' && (
          <div className="rounded-xl border border-border bg-card p-5 shadow-xs space-y-4">
            <h2 className="text-sm font-semibold text-foreground border-b border-border/60 pb-2">
              全域效能與流量限速 (Global & Traffic)
            </h2>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
              <div className="space-y-1.5">
                <label className="font-semibold text-foreground">並行傳輸工作緒 (Max Workers)</label>
                <Input
                  type="number"
                  min={1}
                  max={16}
                  value={maxWorkers}
                  onChange={(e) => setMaxWorkers(parseInt(e.target.value) || 4)}
                  className="h-8 text-xs"
                />
                <p className="text-[11px] text-muted-foreground">多檔批次鏡像與上傳工作緒 (1~16)</p>
              </div>

              <div className="space-y-1.5">
                <label className="font-semibold text-foreground">全域限速 (Bandwidth Limit Kbps)</label>
                <Input
                  type="number"
                  min={0}
                  value={bandwidthLimit}
                  onChange={(e) => setBandwidthLimit(parseInt(e.target.value) || 0)}
                  className="h-8 text-xs"
                />
                <p className="text-[11px] text-muted-foreground">0 代表無限制；10240 代表限制為 10 Mbps</p>
              </div>

              <div className="space-y-1.5">
                <label className="font-semibold text-foreground">單檔最大上傳限制 (MB)</label>
                <Input
                  type="number"
                  min={10}
                  value={maxUploadSize}
                  onChange={(e) => setMaxUploadSize(parseInt(e.target.value) || 2048)}
                  className="h-8 text-xs"
                />
              </div>

              <div className="space-y-1.5">
                <label className="font-semibold text-foreground">即時日誌等級 (Log Level)</label>
                <select
                  value={logLevel}
                  onChange={(e) => setLogLevel(e.target.value as any)}
                  className="w-full h-8 rounded-md border border-input bg-background px-2.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                >
                  <option value="DEBUG">DEBUG (除錯)</option>
                  <option value="INFO">INFO (一般訊息)</option>
                  <option value="WARNING">WARNING (警告)</option>
                  <option value="ERROR">ERROR (僅錯誤)</option>
                </select>
              </div>

              <div className="space-y-1.5">
                <label className="font-semibold text-foreground">連線池閒置逾時 (秒)</label>
                <Input
                  type="number"
                  value={poolIdleTimeout}
                  onChange={(e) => setPoolIdleTimeout(parseInt(e.target.value) || 300)}
                  className="h-8 text-xs"
                />
              </div>

              <div className="space-y-1.5">
                <label className="font-semibold text-foreground">最大快取連線節點數</label>
                <Input
                  type="number"
                  value={poolMaxRemotes}
                  onChange={(e) => setPoolMaxRemotes(parseInt(e.target.value) || 32)}
                  className="h-8 text-xs"
                />
              </div>
            </div>
          </div>
        )}

        {/* TAB 5: OTHER & TOKEN & UPSTASH */}
        {activeTab === 'other' && (
          <div className="space-y-6">
            {/* Token Card */}
            <div className="rounded-xl border border-border bg-card p-5 shadow-xs space-y-4">
              <h2 className="text-sm font-semibold text-foreground border-b border-border/60 pb-2 flex items-center gap-2">
                <Key className="h-4 w-4 text-primary" />
                <span>API 存取權杖 (Manage Token)</span>
              </h2>

              <div className="space-y-2">
                <label className="text-xs font-semibold text-foreground">全域管理 API Token</label>
                <div className="flex items-center gap-2">
                  <Input
                    value={apiToken}
                    readOnly
                    className="h-9 text-xs font-mono bg-muted/30"
                  />
                  <Button type="button" variant="outline" size="sm" onClick={copyToken} className="h-9 text-xs gap-1">
                    <Copy className="h-3.5 w-3.5" />
                    <span>複製 Token</span>
                  </Button>
                  <Button type="button" variant="outline" size="sm" onClick={resetToken} className="h-9 text-xs gap-1 text-destructive hover:bg-destructive/10">
                    <RefreshCw className="h-3.5 w-3.5" />
                    <span>重設 Token</span>
                  </Button>
                </div>
                <p className="text-[11px] text-muted-foreground">提供外部排程、指令腳本或 WebDAV 客戶端呼叫管理者 API 使用</p>
              </div>
            </div>

            {/* Upstash E2EE Sync Config */}
            <div className="rounded-xl border border-border bg-card p-5 shadow-xs space-y-4">
              <h2 className="text-sm font-semibold text-foreground border-b border-border/60 pb-2 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Cloud className="h-4 w-4 text-primary" />
                  <span>Upstash E2EE 雲端加密金鑰庫設定</span>
                </div>
                <Badge variant="outline" className="text-[10px]">AES-256-GCM</Badge>
              </h2>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
                <div className="space-y-1.5">
                  <label className="font-semibold text-foreground">Upstash REST URL</label>
                  <Input
                    value={upstashUrl}
                    onChange={(e) => setUpstashUrl(e.target.value)}
                    placeholder="https://...upstash.io"
                    className="h-8 text-xs font-mono"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="font-semibold text-foreground">Upstash REST Token</label>
                  <Input
                    type="password"
                    value={upstashToken}
                    onChange={(e) => setUpstashToken(e.target.value)}
                    placeholder="留空即保留目前金鑰"
                    className="h-8 text-xs font-mono"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="font-semibold text-foreground">同步金鑰識別 (Sync Key)</label>
                  <Input
                    value={syncKey}
                    onChange={(e) => setSyncKey(e.target.value)}
                    className="h-8 text-xs font-mono"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="font-semibold text-foreground">E2EE 端到端加密主密碼 (Passphrase)</label>
                  <Input
                    type="password"
                    value={passphrase}
                    onChange={(e) => setPassphrase(e.target.value)}
                    placeholder="用於加密上傳憑證之金鑰"
                    className="h-8 text-xs font-mono"
                  />
                </div>
              </div>

              <div className="flex items-center gap-3 pt-2">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={testUpstash}
                  disabled={testingUpstash || !upstashUrl.trim()}
                  className="text-xs gap-1.5"
                >
                  <Activity className={`h-3.5 w-3.5 ${testingUpstash ? 'animate-spin' : ''}`} />
                  <span>測試 Upstash 連線</span>
                </Button>
                {upstashStatus && (
                  <span className="text-xs font-medium text-emerald-500">{upstashStatus}</span>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Global Save Button at bottom of form */}
        <div className="flex items-center justify-end gap-2 pt-4 border-t border-border">
          <Button type="submit" disabled={saving} className="text-xs gap-1.5">
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            <span>儲存設定</span>
          </Button>
        </div>
      </form>
    </div>
  );
}
