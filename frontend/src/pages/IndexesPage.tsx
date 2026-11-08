import React, { useState, useEffect } from 'react';
import {
  Search,
  Database,
  RefreshCw,
  Trash2,
  CheckCircle2,
  AlertCircle,
  Save,
  Loader2,
  HardDrive,
  Layers,
  Clock,
  Activity,
  Sliders,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { api } from '@/api';
import type { CacheStatsResponse, SettingsResponse, IndexConfig } from '@/api/types';
import { toast } from 'sonner';

export function IndexesPage() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [building, setBuilding] = useState(false);

  const [cacheStats, setCacheStats] = useState<CacheStatsResponse | null>(null);
  const [indexConfig, setIndexConfig] = useState<IndexConfig>({
    search_index: true,
    auto_update_index: true,
    ignore_paths: [],
    max_depth: 20,
  });

  const [ignorePathsText, setIgnorePathsText] = useState('');

  const loadData = async () => {
    setLoading(true);
    try {
      const resp = await api.request<SettingsResponse>('GET', '/settings');
      setCacheStats(resp.cache_stats);

      const savedIndex = resp.settings?.extra_options?.index as IndexConfig | undefined;
      if (savedIndex) {
        setIndexConfig(savedIndex);
        setIgnorePathsText((savedIndex.ignore_paths || []).join('\n'));
      }
    } catch (err: any) {
      toast.error(`載入索引與快取資料失敗: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleSaveConfig = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const paths = ignorePathsText
        .split('\n')
        .map((p) => p.trim())
        .filter(Boolean);

      const updatedConfig: IndexConfig = {
        ...indexConfig,
        ignore_paths: paths,
      };

      await api.request('PUT', '/settings', {
        body: {
          extra_options: {
            index: updatedConfig,
          },
        },
      });

      setIndexConfig(updatedConfig);
      toast.success('搜尋索引與快取組態已更新！');
    } catch (err: any) {
      toast.error(`儲存失敗: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  const handleClearCache = async (remoteName?: string) => {
    const confirmMsg = remoteName
      ? `確定要清除節點 [/${remoteName}] 的快取嗎？`
      : '確定要清空所有目錄搜尋快取與索引數據嗎？';
    if (!confirm(confirmMsg)) return;

    setClearing(true);
    try {
      const res = await api.request<any>('POST', '/settings/cache/clear', {
        query: remoteName ? { remote: remoteName } : {},
      });
      toast.success(res.message || '快取已成功清除！');
      await loadData();
    } catch (err: any) {
      toast.error(`清除快取失敗: ${err.message}`);
    } finally {
      setClearing(false);
    }
  };

  const handleBuildIndex = async () => {
    setBuilding(true);
    try {
      // Trigger a warm-up scan across remotes
      const remotesResp = await api.request<any>('GET', '/remotes');
      const remotes = remotesResp.remotes || [];
      for (const r of remotes) {
        try {
          await api.request('GET', `/fs/${r.name}/ls`, { query: { path: '/', limit: 100 } });
        } catch {
          // ignore individual node timeout
        }
      }
      toast.success('已完成目錄快取索引預熱與掃描！');
      await loadData();
    } catch (err: any) {
      toast.error(`建立索引失敗: ${err.message}`);
    } finally {
      setBuilding(false);
    }
  };

  const hitRatio = cacheStats?.ratio ?? cacheStats?.hit_ratio ?? 0;

  return (
    <div className="space-y-6 pb-12 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <Search className="h-5 w-5 text-primary" />
            <span>搜尋索引與快取管理 (Indexes & Cache)</span>
          </h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            仿照 AList 索引體系，監控目錄快取命中率、重建索引樹狀結構並管理即時快取項目
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={handleBuildIndex}
            disabled={building}
            className="text-xs gap-1.5"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${building ? 'animate-spin' : ''}`} />
            <span>重建索引 (Build Index)</span>
          </Button>
          <Button
            size="sm"
            variant="destructive"
            onClick={() => handleClearCache()}
            disabled={clearing}
            className="text-xs gap-1.5"
          >
            <Trash2 className="h-3.5 w-3.5" />
            <span>清空所有快取</span>
          </Button>
        </div>
      </div>

      {/* Metrics Cards Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="rounded-xl border border-border bg-card p-4 shadow-xs space-y-2">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-xs font-medium">快取目錄數</span>
            <Database className="h-4 w-4 text-blue-500" />
          </div>
          <div className="text-2xl font-bold text-foreground">
            {cacheStats?.current_entries ?? cacheStats?.total_entries ?? 0}
          </div>
          <p className="text-[11px] text-muted-foreground">上限 {cacheStats?.max_entries ?? 1000} 項目</p>
        </div>

        <div className="rounded-xl border border-border bg-card p-4 shadow-xs space-y-2">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-xs font-medium">快取命中率</span>
            <Activity className="h-4 w-4 text-emerald-500" />
          </div>
          <div className="text-2xl font-bold text-foreground">{hitRatio.toFixed(1)}%</div>
          <div className="w-full bg-muted rounded-full h-1.5 overflow-hidden">
            <div className="bg-emerald-500 h-full rounded-full" style={{ width: `${Math.min(100, hitRatio)}%` }} />
          </div>
        </div>

        <div className="rounded-xl border border-border bg-card p-4 shadow-xs space-y-2">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-xs font-medium">命中 / 穿透次數</span>
            <Layers className="h-4 w-4 text-amber-500" />
          </div>
          <div className="text-2xl font-bold text-foreground font-mono">
            {cacheStats?.hits ?? 0} <span className="text-xs text-muted-foreground font-normal">/ {cacheStats?.misses ?? 0}</span>
          </div>
          <p className="text-[11px] text-muted-foreground">留存時間 {cacheStats?.ttl_seconds ?? 300} 秒</p>
        </div>

        <div className="rounded-xl border border-border bg-card p-4 shadow-xs space-y-2">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="text-xs font-medium">已快取節點數</span>
            <HardDrive className="h-4 w-4 text-primary" />
          </div>
          <div className="text-2xl font-bold text-foreground">
            {cacheStats?.remotes_cached?.length ?? 0}
          </div>
          <div className="flex flex-wrap gap-1">
            {(cacheStats?.remotes_cached || []).slice(0, 3).map((r) => (
              <Badge key={r} variant="outline" className="text-[10px] px-1 py-0">
                {r}
              </Badge>
            ))}
            {(cacheStats?.remotes_cached?.length || 0) > 3 && (
              <span className="text-[10px] text-muted-foreground">+{cacheStats!.remotes_cached.length - 3}</span>
            )}
          </div>
        </div>
      </div>

      {/* Cached Remotes Details Bar */}
      {cacheStats?.remotes_cached && cacheStats.remotes_cached.length > 0 && (
        <div className="rounded-xl border border-border bg-card p-4 shadow-xs space-y-3">
          <h3 className="text-xs font-semibold text-foreground">當前記憶體快取中的儲存節點</h3>
          <div className="flex flex-wrap gap-2">
            {cacheStats.remotes_cached.map((remote) => (
              <div
                key={remote}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-border/80 bg-muted/30 text-xs"
              >
                <span className="font-mono font-medium text-foreground">/{remote}</span>
                <button
                  type="button"
                  onClick={() => handleClearCache(remote)}
                  className="text-muted-foreground hover:text-destructive p-0.5 rounded transition-colors"
                  title={`清除 /${remote} 的快取`}
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Index Configuration Form */}
      <form onSubmit={handleSaveConfig} className="rounded-xl border border-border bg-card p-5 shadow-xs space-y-5">
        <div className="flex items-center justify-between border-b border-border/60 pb-3">
          <h2 className="text-sm font-semibold text-foreground flex items-center gap-2">
            <Sliders className="h-4 w-4 text-primary" />
            <span>索引參數設定 (Index Configuration)</span>
          </h2>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
          {/* Search Index Toggle */}
          <div className="flex items-center gap-2.5">
            <input
              type="checkbox"
              id="search_index"
              checked={indexConfig.search_index}
              onChange={(e) => setIndexConfig({ ...indexConfig, search_index: e.target.checked })}
              className="rounded border-input text-primary focus:ring-primary h-4 w-4 cursor-pointer"
            />
            <label htmlFor="search_index" className="font-medium text-foreground cursor-pointer">
              啟用前台檔案搜尋索引 (Search Index)
            </label>
          </div>

          {/* Auto Update Index Toggle */}
          <div className="flex items-center gap-2.5">
            <input
              type="checkbox"
              id="auto_update_index"
              checked={indexConfig.auto_update_index}
              onChange={(e) => setIndexConfig({ ...indexConfig, auto_update_index: e.target.checked })}
              className="rounded border-input text-primary focus:ring-primary h-4 w-4 cursor-pointer"
            />
            <label htmlFor="auto_update_index" className="font-medium text-foreground cursor-pointer">
              檔案異動時自動更新索引 (Auto Update Index)
            </label>
          </div>

          {/* Max Depth */}
          <div className="space-y-1.5">
            <label className="font-semibold text-foreground">最大搜尋索引目錄深度 (Max Depth)</label>
            <Input
              type="number"
              min={1}
              max={100}
              value={indexConfig.max_depth}
              onChange={(e) => setIndexConfig({ ...indexConfig, max_depth: parseInt(e.target.value) || 20 })}
              className="h-8 text-xs"
            />
            <p className="text-[11px] text-muted-foreground">遞迴遍歷目錄之最大層級深度 (預設 20)</p>
          </div>

          {/* Ignore Paths */}
          <div className="space-y-1.5 md:col-span-2">
            <label className="font-semibold text-foreground">排除索引之路徑規則 (每行一條規則)</label>
            <textarea
              value={ignorePathsText}
              onChange={(e) => setIgnorePathsText(e.target.value)}
              placeholder="例如 /local/temp&#10;*/node_modules/*&#10;*.cache"
              rows={3}
              className="w-full rounded-md border border-input bg-background p-2.5 text-xs text-foreground font-mono focus:outline-none focus:ring-1 focus:ring-ring"
            />
            <p className="text-[11px] text-muted-foreground">符合上述模式之路徑將不會建立全文檢索或進行快取預熱</p>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 pt-2 border-t border-border">
          <Button type="submit" size="sm" disabled={saving} className="text-xs gap-1.5">
            {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
            <span>儲存索引設定</span>
          </Button>
        </div>
      </form>
    </div>
  );
}
