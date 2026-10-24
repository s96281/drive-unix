import React, { useState, useEffect } from 'react';
import {
  FileText,
  Plus,
  Trash2,
  Edit2,
  Lock,
  EyeOff,
  Check,
  X,
  Save,
  Loader2,
  Search,
  BookOpen,
  Shield,
  HelpCircle,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { api } from '@/api';
import type { MetaRule, SettingsResponse } from '@/api/types';
import { toast } from 'sonner';

export function MetasPage() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [metas, setMetas] = useState<MetaRule[]>([]);
  const [search, setSearch] = useState('');
  const [editingRule, setEditingRule] = useState<MetaRule | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);

  const loadSettings = async () => {
    setLoading(true);
    try {
      const resp = await api.request<SettingsResponse>('GET', '/settings');
      const loadedMetas = (resp.settings?.extra_options?.metas as MetaRule[]) || [];
      setMetas(loadedMetas);
    } catch (err: any) {
      toast.error(`載入元資料設定失敗: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSettings();
  }, []);

  const saveMetas = async (updated: MetaRule[]) => {
    setSaving(true);
    try {
      await api.request('PUT', '/settings', {
        body: {
          extra_options: {
            metas: updated,
          },
        },
      });
      setMetas(updated);
      toast.success('元資料規則已儲存並即時生效！');
    } catch (err: any) {
      toast.error(`儲存元資料失敗: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  const handleOpenAdd = () => {
    setEditingRule({
      id: `meta-${Date.now().toString(36)}`,
      path: '/',
      password: '',
      p_sub: true,
      write: true,
      w_sub: true,
      hide: '',
      h_sub: true,
      readme: '',
      r_sub: true,
      header: '',
      header_sub: true,
    });
    setIsModalOpen(true);
  };

  const handleOpenEdit = (rule: MetaRule) => {
    setEditingRule({ ...rule });
    setIsModalOpen(true);
  };

  const handleDelete = (id: string) => {
    if (!confirm('確定要刪除此條路徑元資料規則嗎？')) return;
    const next = metas.filter((m) => m.id !== id);
    saveMetas(next);
  };

  const handleModalSave = (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingRule) return;
    if (!editingRule.path.trim()) {
      toast.error('路徑不可為空');
      return;
    }

    const normalizedPath = editingRule.path.startsWith('/') ? editingRule.path : `/${editingRule.path}`;
    const ruleToSave = { ...editingRule, path: normalizedPath };

    const idx = metas.findIndex((m) => m.id === ruleToSave.id);
    let next: MetaRule[];
    if (idx >= 0) {
      next = [...metas];
      next[idx] = ruleToSave;
    } else {
      next = [...metas, ruleToSave];
    }

    setIsModalOpen(false);
    saveMetas(next);
  };

  const filteredMetas = metas.filter((m) =>
    (m.path || '').toLowerCase().includes(search.toLowerCase()) ||
    (m.header || '').toLowerCase().includes(search.toLowerCase()) ||
    (m.readme || '').toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="space-y-6 pb-12 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <BookOpen className="h-5 w-5 text-primary" />
            <span>元資料管理 (Metas)</span>
          </h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            仿照 AList 元資料體系，為特定目錄設定存取密碼、寫入權限、隱藏檔案規則及自訂頂部/底部 Markdown 說明
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button size="sm" onClick={handleOpenAdd} className="text-xs gap-1.5">
            <Plus className="h-3.5 w-3.5" />
            <span>新增規則</span>
          </Button>
        </div>
      </div>

      {/* Search and stats bar */}
      <div className="flex items-center justify-between gap-3">
        <div className="relative w-72">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜尋路徑或說明內容..."
            className="h-8 pl-8 text-xs"
          />
        </div>
        <span className="text-xs text-muted-foreground">共 {filteredMetas.length} 條路徑規則</span>
      </div>

      {/* Rules Table */}
      {loading ? (
        <div className="py-20 text-center text-sm text-muted-foreground">載入元資料設定中...</div>
      ) : filteredMetas.length === 0 ? (
        <div className="py-16 text-center border border-dashed rounded-xl space-y-3 bg-muted/20">
          <BookOpen className="h-10 w-10 text-muted-foreground/40 mx-auto" />
          <h3 className="text-sm font-semibold text-foreground">尚未建立路徑元資料規則</h3>
          <p className="text-xs text-muted-foreground max-w-sm mx-auto">
            您可以為例如 <code>/photos</code> 或 <code>/gdrive/機密</code> 加入訪問密碼、過濾隱藏檔案或自訂前台公告。
          </p>
          <Button size="sm" variant="outline" onClick={handleOpenAdd} className="text-xs">
            建立第一條規則
          </Button>
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card overflow-hidden shadow-xs">
          <table className="w-full text-left text-xs border-collapse">
            <thead className="bg-muted/50 border-b border-border/70 text-muted-foreground select-none">
              <tr>
                <th className="py-3 px-4 font-semibold">目標路徑 (Path)</th>
                <th className="py-3 px-4 font-semibold">存取密碼</th>
                <th className="py-3 px-4 font-semibold">寫入權限</th>
                <th className="py-3 px-4 font-semibold">隱藏正則 (Hide)</th>
                <th className="py-3 px-4 font-semibold">自訂說明 (Header / Readme)</th>
                <th className="py-3 px-4 font-semibold text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/40">
              {filteredMetas.map((meta) => (
                <tr key={meta.id} className="hover:bg-muted/30 transition-colors">
                  <td className="py-3 px-4 font-mono font-medium text-foreground">
                    <span>{meta.path}</span>
                  </td>
                  <td className="py-3 px-4">
                    {meta.password ? (
                      <Badge variant="outline" className="text-amber-500 border-amber-500/30 bg-amber-500/10 gap-1 text-[11px]">
                        <Lock className="h-3 w-3" />
                        已加密 {meta.p_sub && '(含子目錄)'}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground">公開</span>
                    )}
                  </td>
                  <td className="py-3 px-4">
                    {meta.write ? (
                      <Badge variant="outline" className="text-emerald-500 border-emerald-500/30 bg-emerald-500/10 text-[11px]">
                        可寫入 {meta.w_sub && '(含子目錄)'}
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="text-red-500 border-red-500/30 bg-red-500/10 text-[11px]">
                        唯讀
                      </Badge>
                    )}
                  </td>
                  <td className="py-3 px-4 font-mono">
                    {meta.hide ? (
                      <span className="bg-muted px-1.5 py-0.5 rounded text-foreground text-[11px]">
                        {meta.hide}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">-</span>
                    )}
                  </td>
                  <td className="py-3 px-4 text-muted-foreground truncate max-w-xs">
                    {meta.header ? 'Header' : ''}
                    {meta.header && meta.readme ? ' / ' : ''}
                    {meta.readme ? 'README' : ''}
                    {!meta.header && !meta.readme ? '-' : ''}
                  </td>
                  <td className="py-3 px-4 text-right">
                    <div className="flex items-center justify-end gap-1.5">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleOpenEdit(meta)}
                        className="h-7 w-7 p-0"
                        title="編輯規則"
                      >
                        <Edit2 className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleDelete(meta.id)}
                        className="h-7 w-7 p-0 text-destructive hover:bg-destructive/10"
                        title="刪除規則"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Add / Edit Rule Modal */}
      {isModalOpen && editingRule && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs animate-in fade-in">
          <div className="bg-background rounded-xl border border-border shadow-xl w-full max-w-2xl max-h-[90vh] flex flex-col overflow-hidden">
            <div className="flex items-center justify-between p-4 border-b border-border">
              <h3 className="font-bold text-sm text-foreground flex items-center gap-2">
                <BookOpen className="h-4 w-4 text-primary" />
                <span>編輯路徑元資料 (Meta Rule)</span>
              </h3>
              <button
                type="button"
                onClick={() => setIsModalOpen(false)}
                className="text-muted-foreground hover:text-foreground p-1 rounded-md"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <form onSubmit={handleModalSave} className="p-4 space-y-4 overflow-y-auto flex-1 text-xs">
              {/* Path */}
              <div className="space-y-1.5">
                <label className="font-semibold text-foreground flex items-center gap-1">
                  <span>目標路徑 (Path)</span>
                  <span className="text-destructive">*</span>
                </label>
                <Input
                  value={editingRule.path}
                  onChange={(e) => setEditingRule({ ...editingRule, path: e.target.value })}
                  placeholder="例如 / 或 /photos 或 /gdrive/工作文件"
                  className="h-8 text-xs font-mono"
                  required
                />
                <p className="text-[11px] text-muted-foreground">以斜線開頭之掛載路徑</p>
              </div>

              {/* Password & Sub Apply */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                <div className="space-y-1.5">
                  <label className="font-semibold text-foreground flex items-center gap-1">
                    <Lock className="h-3 w-3 text-amber-500" />
                    <span>訪問保護密碼 (Password)</span>
                  </label>
                  <Input
                    type="password"
                    value={editingRule.password || ''}
                    onChange={(e) => setEditingRule({ ...editingRule, password: e.target.value })}
                    placeholder="留空表示免密訪問"
                    className="h-8 text-xs"
                  />
                </div>
                <div className="flex items-center gap-2 pt-5">
                  <input
                    type="checkbox"
                    id="p_sub"
                    checked={editingRule.p_sub ?? true}
                    onChange={(e) => setEditingRule({ ...editingRule, p_sub: e.target.checked })}
                    className="rounded border-input text-primary focus:ring-primary h-4 w-4 cursor-pointer"
                  />
                  <label htmlFor="p_sub" className="cursor-pointer text-muted-foreground">
                    套用密碼保護至所有子目錄 (p_sub)
                  </label>
                </div>
              </div>

              {/* Write & Hide Regex */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                <div className="space-y-1.5">
                  <label className="font-semibold text-foreground flex items-center gap-1">
                    <EyeOff className="h-3 w-3 text-slate-400" />
                    <span>隱藏檔案正則表達式 (Hide Regex)</span>
                  </label>
                  <Input
                    value={editingRule.hide || ''}
                    onChange={(e) => setEditingRule({ ...editingRule, hide: e.target.value })}
                    placeholder="例如 ^\..* 或 .*\.tmp$"
                    className="h-8 text-xs font-mono"
                  />
                </div>
                <div className="flex items-center gap-2 pt-5">
                  <input
                    type="checkbox"
                    id="h_sub"
                    checked={editingRule.h_sub ?? true}
                    onChange={(e) => setEditingRule({ ...editingRule, h_sub: e.target.checked })}
                    className="rounded border-input text-primary focus:ring-primary h-4 w-4 cursor-pointer"
                  />
                  <label htmlFor="h_sub" className="cursor-pointer text-muted-foreground">
                    套用隱藏正則至所有子目錄 (h_sub)
                  </label>
                </div>
              </div>

              {/* Header Markdown */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label className="font-semibold text-foreground flex items-center gap-1">
                    <FileText className="h-3 w-3 text-blue-500" />
                    <span>自訂頂部說明 (Header Markdown)</span>
                  </label>
                  <label className="flex items-center gap-1.5 text-muted-foreground cursor-pointer">
                    <input
                      type="checkbox"
                      checked={editingRule.header_sub ?? true}
                      onChange={(e) => setEditingRule({ ...editingRule, header_sub: e.target.checked })}
                      className="rounded border-input text-primary focus:ring-primary h-3.5 w-3.5"
                    />
                    <span>套用至子目錄</span>
                  </label>
                </div>
                <textarea
                  value={editingRule.header || ''}
                  onChange={(e) => setEditingRule({ ...editingRule, header: e.target.value })}
                  placeholder="渲染於前台檔案列表上方之 Markdown 內容..."
                  rows={3}
                  className="w-full rounded-md border border-input bg-background p-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                />
              </div>

              {/* Readme Markdown */}
              <div className="space-y-1.5">
                <div className="flex items-center justify-between">
                  <label className="font-semibold text-foreground flex items-center gap-1">
                    <BookOpen className="h-3 w-3 text-emerald-500" />
                    <span>自訂底部說明 (README Markdown)</span>
                  </label>
                  <label className="flex items-center gap-1.5 text-muted-foreground cursor-pointer">
                    <input
                      type="checkbox"
                      checked={editingRule.r_sub ?? true}
                      onChange={(e) => setEditingRule({ ...editingRule, r_sub: e.target.checked })}
                      className="rounded border-input text-primary focus:ring-primary h-3.5 w-3.5"
                    />
                    <span>套用至子目錄</span>
                  </label>
                </div>
                <textarea
                  value={editingRule.readme || ''}
                  onChange={(e) => setEditingRule({ ...editingRule, readme: e.target.value })}
                  placeholder="渲染於前台檔案列表下方之 Markdown 說明卡片..."
                  rows={3}
                  className="w-full rounded-md border border-input bg-background p-2 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-border">
                <Button type="button" variant="outline" size="sm" onClick={() => setIsModalOpen(false)}>
                  取消
                </Button>
                <Button type="submit" size="sm" disabled={saving}>
                  {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : '儲存規則'}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
