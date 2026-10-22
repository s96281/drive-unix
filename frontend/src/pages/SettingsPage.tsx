import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Settings,
  Cloud,
  Sliders,
  Database,
  Lock,
  Unlock,
  Trash2,
  RefreshCw,
  UploadCloud,
  DownloadCloud,
  Activity,
  CheckCircle2,
  AlertCircle,
  HardDrive,
  ShieldCheck,
  Moon,
  Sun,
} from 'lucide-react';
import { api } from '@/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { formatRelativeTime } from '@/lib/format';
import { useUIStore } from '@/stores/ui-store';
import { toast } from 'sonner';
import type {
  UpstashConfigResponse,
  UpstashTokenItem,
  TransferSettings,
  CacheStats,
} from '@/api/types';

export function SettingsPage() {
  const queryClient = useQueryClient();
  const theme = useUIStore((s) => s.theme);
  const setTheme = useUIStore((s) => s.setTheme);

  // Upstash state
  const [upstashUrl, setUpstashUrl] = useState('');
  const [upstashToken, setUpstashToken] = useState('');
  const [syncKey, setSyncKey] = useState('drive-unix:sync:default');
  const [passphrase, setPassphrase] = useState('');
  const [isTestingUpstash, setIsTestingUpstash] = useState(false);
  const [upstashTestResult, setUpstashTestResult] = useState<{ ok: boolean; latency: number } | null>(null);

  // Prefs state
  const [workers, setWorkers] = useState(4);
  const [bandwidthLimit, setBandwidthLimit] = useState(0);
  const [logLevel, setLogLevel] = useState('INFO');

  // Queries
  const { data: upstashConfig } = useQuery<UpstashConfigResponse>({
    queryKey: ['upstash-config'],
    queryFn: () => api.request('GET', '/upstash/config'),
  });

  const { data: upstashTokensData, refetch: refetchTokens } = useQuery<UpstashTokenItem[]>({
    queryKey: ['upstash-tokens'],
    queryFn: () => api.request('GET', '/upstash/tokens'),
  });

  const { data: transferSettings } = useQuery<TransferSettings>({
    queryKey: ['transfer-settings'],
    queryFn: () => api.request('GET', '/settings/transfer'),
  });

  const { data: cacheStats, refetch: refetchCache } = useQuery<CacheStats>({
    queryKey: ['cache-stats'],
    queryFn: () => api.request('GET', '/settings/cache/stats'),
  });

  // Sync loaded configs to local form state
  useEffect(() => {
    if (upstashConfig) {
      if (upstashConfig.rest_url) setUpstashUrl(upstashConfig.rest_url);
      if (upstashConfig.sync_key) setSyncKey(upstashConfig.sync_key);
    }
  }, [upstashConfig]);

  useEffect(() => {
    if (transferSettings) {
      setWorkers(transferSettings.max_workers || 4);
      setBandwidthLimit(transferSettings.bandwidth_limit_kbps || 0);
      setLogLevel(transferSettings.log_level || 'INFO');
    }
  }, [transferSettings]);

  // Mutations
  const saveUpstashMutation = useMutation({
    mutationFn: () =>
      api.request('POST', '/upstash/config', {
        body: {
          rest_url: upstashUrl.trim(),
          rest_token: upstashToken.trim() || undefined,
          sync_key: syncKey.trim(),
          passphrase: passphrase.trim() || undefined,
        },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['upstash-config'] });
      toast.success('Upstash 雲端連線組態已儲存！');
    },
    onError: (err: any) => {
      toast.error(`儲存 Upstash 設定失敗: ${err.message}`);
    },
  });

  const pushMutation = useMutation({
    mutationFn: () =>
      api.request('POST', '/upstash/push', {
        body: {
          passphrase: passphrase.trim() || 'default-pass',
          sync_key: syncKey,
        },
      }),
    onSuccess: (res: any) => {
      toast.success(`已將節點組態與憑證加密推送至 Upstash 雲端 (${res.remotes_count || 1} 個節點)`);
      queryClient.invalidateQueries({ queryKey: ['upstash-tokens'] });
    },
    onError: (err: any) => toast.error(`推送失敗: ${err.message}`),
  });

  const pullMutation = useMutation({
    mutationFn: () =>
      api.request('POST', '/upstash/pull', {
        body: {
          passphrase: passphrase.trim() || 'default-pass',
          sync_key: syncKey,
          strategy: 'merge',
        },
      }),
    onSuccess: (res: any) => {
      toast.success(`已從 Upstash 雲端拉取並合併本機組態`);
      queryClient.invalidateQueries({ queryKey: ['remotes'] });
      queryClient.invalidateQueries({ queryKey: ['upstash-tokens'] });
    },
    onError: (err: any) => toast.error(`拉取失敗: ${err.message}`),
  });

  const testUpstash = async () => {
    setIsTestingUpstash(true);
    setUpstashTestResult(null);
    try {
      const res = await api.request<any>('POST', '/upstash/test');
      setUpstashTestResult({ ok: true, latency: res.latency_ms || 45 });
      toast.success(`Upstash 連線成功 (${res.latency_ms || 45}ms)`);
    } catch (err: any) {
      setUpstashTestResult({ ok: false, latency: 0 });
      toast.error(`Upstash 連線測試失敗: ${err.message}`);
    } finally {
      setIsTestingUpstash(false);
    }
  };

  const releaseLockMutation = useMutation({
    mutationFn: (key: string) => api.request('DELETE', `/upstash/locks/${key}`),
    onSuccess: (_, key) => {
      queryClient.invalidateQueries({ queryKey: ['upstash-tokens'] });
      toast.success(`已強制釋放節點 [${key}] 的分散式同步鎖定`);
    },
    onError: (err: any) => toast.error(`釋放鎖定失敗: ${err.message}`),
  });

  const deleteTokenMutation = useMutation({
    mutationFn: (key: string) => api.request('DELETE', `/upstash/tokens/${key}`),
    onSuccess: (_, key) => {
      queryClient.invalidateQueries({ queryKey: ['upstash-tokens'] });
      toast.success(`已清除節點 [${key}] 雲端快取憑證`);
    },
    onError: (err: any) => toast.error(`清除憑證失敗: ${err.message}`),
  });

  const savePrefsMutation = useMutation({
    mutationFn: () =>
      api.request('POST', '/settings/transfer', {
        body: {
          max_workers: workers,
          bandwidth_limit_kbps: bandwidthLimit,
          log_level: logLevel,
        },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['transfer-settings'] });
      toast.success('系統傳輸偏好設定已儲存！');
    },
    onError: (err: any) => toast.error(`儲存偏好失敗: ${err.message}`),
  });

  const clearCacheMutation = useMutation({
    mutationFn: () => api.request('POST', '/settings/cache/clear'),
    onSuccess: (res: any) => {
      queryClient.invalidateQueries({ queryKey: ['cache-stats'] });
      queryClient.invalidateQueries({ queryKey: ['fs-list'] });
      toast.success(`已清空所有本機目錄快取 (${res.cleared_entries || 0} 項目)`);
    },
    onError: (err: any) => toast.error(`清空快取失敗: ${err.message}`),
  });

  const tokens = upstashTokensData || [];

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      {/* Page Header */}
      <div>
        <h2 className="text-2xl font-bold tracking-tight text-foreground">系統偏好與快取</h2>
        <p className="text-sm text-muted-foreground mt-0.5">
          管理 Upstash E2EE 憑證同步庫、全域傳輸效能限速與本機目錄快取
        </p>
      </div>

      <Tabs defaultValue="upstash" className="space-y-6">
        <TabsList className="grid grid-cols-3 max-w-md">
          <TabsTrigger value="upstash" className="text-xs">
            Upstash 雲端庫
          </TabsTrigger>
          <TabsTrigger value="prefs" className="text-xs">
            傳輸與偏好
          </TabsTrigger>
          <TabsTrigger value="cache" className="text-xs">
            目錄快取
          </TabsTrigger>
        </TabsList>

        {/* Tab 1: Upstash */}
        <TabsContent value="upstash" className="space-y-6">
          <Card>
            <CardHeader className="pb-4">
              <div className="flex items-center gap-2">
                <div className="p-2 rounded-lg bg-primary/10 text-primary">
                  <Cloud className="h-5 w-5" />
                </div>
                <div>
                  <CardTitle className="text-base font-semibold">
                    Upstash E2EE 多端憑證與狀態同步
                  </CardTitle>
                  <CardDescription>
                    使用零知識端到端加密 (AES-256-GCM) 將網盤 Token 與節點設定安全同步至 Upstash 雲端
                  </CardDescription>
                </div>
              </div>
            </CardHeader>

            <CardContent className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-foreground">Upstash REST URL</label>
                  <Input
                    placeholder="https://...upstash.io"
                    value={upstashUrl}
                    onChange={(e) => setUpstashUrl(e.target.value)}
                    className="font-mono text-xs"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-foreground">
                    Upstash REST Token {upstashConfig?.has_token && '(已設定)'}
                  </label>
                  <Input
                    type="password"
                    placeholder="留空即保留目前金鑰"
                    value={upstashToken}
                    onChange={(e) => setUpstashToken(e.target.value)}
                    className="font-mono text-xs"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-foreground">同步金鑰識別 (Sync Key)</label>
                  <Input
                    placeholder="drive-unix:sync:default"
                    value={syncKey}
                    onChange={(e) => setSyncKey(e.target.value)}
                    className="font-mono text-xs"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-foreground">
                    E2EE 加解密主密碼 (Passphrase) {upstashConfig?.has_passphrase && '(已設定)'}
                  </label>
                  <Input
                    type="password"
                    placeholder="端到端加密金鑰"
                    value={passphrase}
                    onChange={(e) => setPassphrase(e.target.value)}
                    className="font-mono text-xs"
                  />
                </div>
              </div>

              {/* Action buttons */}
              <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-border">
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    className="text-xs gap-1.5"
                    onClick={testUpstash}
                    disabled={isTestingUpstash}
                  >
                    <Activity className="h-3.5 w-3.5" />
                    {isTestingUpstash ? '連線診斷中...' : '測試連線'}
                  </Button>

                  {upstashTestResult && (
                    <span className="text-xs text-emerald-400 flex items-center gap-1 font-medium">
                      <CheckCircle2 className="h-3.5 w-3.5" /> 就緒 ({upstashTestResult.latency}ms)
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    className="text-xs gap-1.5"
                    onClick={() => pullMutation.mutate()}
                    disabled={pullMutation.isPending}
                  >
                    <DownloadCloud className="h-3.5 w-3.5" /> 雲端拉取 (Pull)
                  </Button>

                  <Button
                    variant="outline"
                    size="sm"
                    className="text-xs gap-1.5"
                    onClick={() => pushMutation.mutate()}
                    disabled={pushMutation.isPending}
                  >
                    <UploadCloud className="h-3.5 w-3.5" /> 推送至雲端 (Push)
                  </Button>

                  <Button
                    size="sm"
                    className="text-xs gap-1.5 shadow-sm"
                    onClick={() => saveUpstashMutation.mutate()}
                    disabled={saveUpstashMutation.isPending}
                  >
                    儲存連線設定
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Tokens and Distributed Lock Status Table */}
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle className="text-sm font-semibold">
                    雲端共用憑證與分散式鎖定狀態 (Cloud Tokens & Locks)
                  </CardTitle>
                  <CardDescription>
                    檢視由多台設備共享的遠端網盤 Token 與進行中任務鎖
                  </CardDescription>
                </div>
                <Button variant="ghost" size="sm" onClick={() => refetchTokens()} className="h-7 text-xs gap-1">
                  <RefreshCw className="h-3 w-3" /> 重新整理
                </Button>
              </div>
            </CardHeader>

            <CardContent className="p-0">
              {tokens.length === 0 ? (
                <div className="py-12 text-center text-xs text-muted-foreground">
                  尚未同步任何雲端憑證紀錄
                </div>
              ) : (
                <div className="border-t border-border overflow-x-auto">
                  <table className="w-full text-left text-xs border-collapse">
                    <thead className="bg-muted/40 border-b border-border text-muted-foreground select-none">
                      <tr>
                        <th className="py-2.5 px-4 font-medium">節點識別 (Remote)</th>
                        <th className="py-2.5 px-4 font-medium">憑證到期</th>
                        <th className="py-2.5 px-4 font-medium">最後同步更新</th>
                        <th className="py-2.5 px-4 font-medium">分散式鎖定狀態</th>
                        <th className="py-2.5 px-4 font-medium text-right">操作</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/40">
                      {tokens.map((tok) => (
                        <tr key={tok.identity_key} className="hover:bg-accent/40">
                          <td className="py-2.5 px-4 font-semibold text-foreground font-mono">
                            {tok.identity_key}
                          </td>
                          <td className="py-2.5 px-4 text-muted-foreground">
                            {tok.expires_at ? formatRelativeTime(tok.expires_at) : '長期有效'}
                          </td>
                          <td className="py-2.5 px-4 text-muted-foreground">
                            {formatRelativeTime(tok.updated_at)}
                          </td>
                          <td className="py-2.5 px-4">
                            {tok.is_locked ? (
                              <Badge variant="outline" className="border-amber-500 text-amber-400 text-[10px] gap-1">
                                <Lock className="h-3 w-3" /> 已被鎖定 ({tok.locked_by || '工作端'})
                              </Badge>
                            ) : (
                              <Badge variant="secondary" className="text-[10px] gap-1 text-emerald-400">
                                <Unlock className="h-3 w-3" /> 空閒 (Free)
                              </Badge>
                            )}
                          </td>
                          <td className="py-2.5 px-4 text-right">
                            <div className="flex items-center justify-end gap-1.5">
                              {tok.is_locked && (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="h-6 text-[11px] text-amber-400"
                                  onClick={() => releaseLockMutation.mutate(tok.identity_key)}
                                >
                                  強制解鎖
                                </Button>
                              )}
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-6 w-6 text-muted-foreground hover:text-destructive"
                                onClick={() => deleteTokenMutation.mutate(tok.identity_key)}
                                title="清除憑證"
                              >
                                <Trash2 className="h-3 w-3" />
                              </Button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Tab 2: Preferences */}
        <TabsContent value="prefs" className="space-y-6">
          <Card>
            <CardHeader className="pb-4">
              <div className="flex items-center gap-2">
                <div className="p-2 rounded-lg bg-primary/10 text-primary">
                  <Sliders className="h-5 w-5" />
                </div>
                <div>
                  <CardTitle className="text-base font-semibold">傳輸偏好與效能配置</CardTitle>
                  <CardDescription>調配全域傳輸並行緒上限、頻寬限速與系統日誌輸出等級</CardDescription>
                </div>
              </div>
            </CardHeader>

            <CardContent className="space-y-5">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-foreground">
                    預設最大並行傳輸緒 (Max Workers)
                  </label>
                  <Input
                    type="number"
                    min={1}
                    max={32}
                    value={workers}
                    onChange={(e) => setWorkers(parseInt(e.target.value) || 4)}
                    className="font-mono text-xs"
                  />
                  <p className="text-[11px] text-muted-foreground">
                    建議範圍 2-8，過大可能導致公有雲 API 觸發 429 速率限制
                  </p>
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-foreground">
                    全域頻寬限速 (Rate Limit Kbps)
                  </label>
                  <Input
                    type="number"
                    min={0}
                    value={bandwidthLimit}
                    onChange={(e) => setBandwidthLimit(parseInt(e.target.value) || 0)}
                    className="font-mono text-xs"
                  />
                  <p className="text-[11px] text-muted-foreground">填入 0 表示不限制頻寬</p>
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-foreground">即時事件日誌等級</label>
                  <Select value={logLevel} onValueChange={setLogLevel}>
                    <SelectTrigger className="text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="DEBUG">DEBUG (最詳細除錯)</SelectItem>
                      <SelectItem value="INFO">INFO (一般運作資訊)</SelectItem>
                      <SelectItem value="WARNING">WARNING (僅警告與異常)</SelectItem>
                      <SelectItem value="ERROR">ERROR (僅重大錯誤)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-foreground">UI 外觀主題</label>
                  <div className="flex items-center gap-2 pt-1">
                    <Button
                      variant={theme === 'dark' ? 'default' : 'outline'}
                      size="sm"
                      className="text-xs gap-1.5"
                      onClick={() => setTheme('dark')}
                    >
                      <Moon className="h-3.5 w-3.5" /> 深色模式 (預設)
                    </Button>
                    <Button
                      variant={theme === 'light' ? 'default' : 'outline'}
                      size="sm"
                      className="text-xs gap-1.5"
                      onClick={() => setTheme('light')}
                    >
                      <Sun className="h-3.5 w-3.5" /> 淺色模式
                    </Button>
                  </div>
                </div>
              </div>

              <div className="flex justify-end pt-3 border-t border-border">
                <Button
                  size="sm"
                  className="shadow-sm"
                  onClick={() => savePrefsMutation.mutate()}
                  disabled={savePrefsMutation.isPending}
                >
                  儲存偏好設定
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        {/* Tab 3: Directory Cache */}
        <TabsContent value="cache" className="space-y-6">
          <Card>
            <CardHeader className="pb-4">
              <div className="flex items-center gap-2">
                <div className="p-2 rounded-lg bg-primary/10 text-primary">
                  <Database className="h-5 w-5" />
                </div>
                <div>
                  <CardTitle className="text-base font-semibold">本機目錄快取管理 (Directory Cache)</CardTitle>
                  <CardDescription>
                    快取遠端網盤目錄結構以大幅加速檔案導覽與比對速度
                  </CardDescription>
                </div>
              </div>
            </CardHeader>

            <CardContent className="space-y-5">
              {/* Stats metric cards */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                <div className="p-3 rounded-lg border border-border bg-card">
                  <span className="text-xs text-muted-foreground block">快取命中 (Hits)</span>
                  <span className="text-xl font-bold text-foreground mt-1 block">
                    {cacheStats?.hits || 0}
                  </span>
                </div>
                <div className="p-3 rounded-lg border border-border bg-card">
                  <span className="text-xs text-muted-foreground block">快取穿透 (Misses)</span>
                  <span className="text-xl font-bold text-foreground mt-1 block">
                    {cacheStats?.misses || 0}
                  </span>
                </div>
                <div className="p-3 rounded-lg border border-border bg-card">
                  <span className="text-xs text-muted-foreground block">命中率 (Hit Ratio)</span>
                  <span className="text-xl font-bold text-primary mt-1 block">
                    {(((cacheStats?.hit_ratio ?? cacheStats?.ratio) || 0) * 100).toFixed(1)}%
                  </span>
                </div>
                <div className="p-3 rounded-lg border border-border bg-card">
                  <span className="text-xs text-muted-foreground block">已快取目錄項目</span>
                  <span className="text-xl font-bold text-foreground mt-1 block">
                    {(cacheStats?.total_entries ?? cacheStats?.current_entries) || 0}
                  </span>
                </div>
              </div>

              <div className="flex items-center justify-between pt-4 border-t border-border">
                <p className="text-xs text-muted-foreground">
                  若雲端檔案曾於外部手動異動而未即時反映，可手動清空快取以重新抓取最新狀態。
                </p>
                <Button
                  variant="destructive"
                  size="sm"
                  className="gap-1.5"
                  onClick={() => clearCacheMutation.mutate()}
                  disabled={clearCacheMutation.isPending}
                >
                  <Trash2 className="h-3.5 w-3.5" /> 清空所有快取
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
