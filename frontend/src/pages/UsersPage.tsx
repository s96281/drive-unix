import React, { useState, useEffect } from 'react';
import {
  Users,
  Plus,
  Trash2,
  Edit2,
  Shield,
  Key,
  Check,
  X,
  Save,
  Loader2,
  Search,
  Lock,
  UserCheck,
  UserX,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import { api } from '@/api';
import { PERMISSIONS, type ManageUser, type SettingsResponse } from '@/api/types';
import { toast } from 'sonner';

const PERMISSION_DEFS = [
  { key: 'SEE_HIDES', bit: PERMISSIONS.SEE_HIDES, label: '查看隱藏檔案', desc: '可看見隱藏或被 regex 過濾之檔案' },
  { key: 'ACCESS_WITHOUT_PASSWORD', bit: PERMISSIONS.ACCESS_WITHOUT_PASSWORD, label: '免密訪問', desc: '存取受密碼保護之目錄無需輸入密碼' },
  { key: 'OFFLINE_DOWNLOAD', bit: PERMISSIONS.OFFLINE_DOWNLOAD, label: '跨端傳輸', desc: '可建立跨端同步、複製與離線傳輸任務' },
  { key: 'WRITE', bit: PERMISSIONS.WRITE, label: '寫入上傳', desc: '可上傳新檔案與建立資料夾' },
  { key: 'RENAME', bit: PERMISSIONS.RENAME, label: '重新命名', desc: '可修改現有檔案與目錄名稱' },
  { key: 'MOVE', bit: PERMISSIONS.MOVE, label: '移動項目', desc: '可將檔案或資料夾移動至其他路徑' },
  { key: 'COPY', bit: PERMISSIONS.COPY, label: '複製項目', desc: '可複製檔案或資料夾至同一/其他節點' },
  { key: 'REMOVE', bit: PERMISSIONS.REMOVE, label: '刪除項目', desc: '可將檔案或目錄刪除至垃圾桶或永久抹除' },
  { key: 'WEBDAV_READ', bit: PERMISSIONS.WEBDAV_READ, label: 'WebDAV 讀取', desc: '允許透過 WebDAV 通訊協定檢視與下載' },
  { key: 'WEBDAV_MANAGE', bit: PERMISSIONS.WEBDAV_MANAGE, label: 'WebDAV 管理', desc: '允許透過 WebDAV 進行寫入與刪除操作' },
];

export function UsersPage() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [users, setUsers] = useState<ManageUser[]>([]);
  const [search, setSearch] = useState('');
  const [editingUser, setEditingUser] = useState<ManageUser | null>(null);
  const [userPassword, setUserPassword] = useState('');
  const [isModalOpen, setIsModalOpen] = useState(false);

  const loadData = async () => {
    setLoading(true);
    try {
      const resp = await api.request<SettingsResponse>('GET', '/settings');
      const loadedUsers = (resp.settings?.extra_options?.users as ManageUser[]) || [];
      setUsers(loadedUsers);
    } catch (err: any) {
      toast.error(`載入使用者清單失敗: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const saveUsers = async (updated: ManageUser[]) => {
    setSaving(true);
    try {
      await api.request('PUT', '/settings', {
        body: {
          extra_options: {
            users: updated,
          },
        },
      });
      setUsers(updated);
      toast.success('使用者與權限設定已儲存！');
    } catch (err: any) {
      toast.error(`儲存使用者失敗: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  const handleOpenAdd = () => {
    setEditingUser({
      id: `user-${Date.now().toString(36)}`,
      username: '',
      base_path: '/',
      role: 'general',
      disabled: false,
      permission: 1 | 2 | 8 | 16 | 32 | 64 | 256, // default standard permissions
    });
    setUserPassword('');
    setIsModalOpen(true);
  };

  const handleOpenEdit = (user: ManageUser) => {
    setEditingUser({ ...user });
    setUserPassword('');
    setIsModalOpen(true);
  };

  const handleDelete = (id: string) => {
    const target = users.find((u) => u.id === id);
    if (target?.username === 'admin') {
      toast.error('無法刪除系統內建 admin 最高權限帳號');
      return;
    }
    if (!confirm(`確定要刪除使用者 [${target?.username}] 嗎？`)) return;
    const next = users.filter((u) => u.id !== id);
    saveUsers(next);
  };

  const handleToggleDisabled = (user: ManageUser) => {
    const next = users.map((u) => (u.id === user.id ? { ...u, disabled: !u.disabled } : u));
    saveUsers(next);
  };

  const handleModalSave = (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingUser) return;
    if (!editingUser.username.trim()) {
      toast.error('使用者名稱不可為空');
      return;
    }

    const idx = users.findIndex((u) => u.id === editingUser.id);
    let next: ManageUser[];
    if (idx >= 0) {
      next = [...users];
      next[idx] = editingUser;
    } else {
      next = [...users, editingUser];
    }

    setIsModalOpen(false);
    saveUsers(next);
  };

  const togglePermissionBit = (bit: number) => {
    if (!editingUser) return;
    const current = editingUser.permission;
    const next = (current & bit) !== 0 ? current & ~bit : current | bit;
    setEditingUser({ ...editingUser, permission: next });
  };

  const filteredUsers = users.filter((u) =>
    (u.username || '').toLowerCase().includes(search.toLowerCase()) ||
    (u.base_path || '').toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="space-y-6 pb-12 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border pb-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <Users className="h-5 w-5 text-primary" />
            <span>使用者與權限管理 (Users & Permissions)</span>
          </h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            仿照 AList 10 項細粒度權限位元遮罩系統，配置多使用者登入、根目錄隔離與存取政策
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button size="sm" onClick={handleOpenAdd} className="text-xs gap-1.5">
            <Plus className="h-3.5 w-3.5" />
            <span>新增使用者</span>
          </Button>
        </div>
      </div>

      {/* Search and count */}
      <div className="flex items-center justify-between gap-3">
        <div className="relative w-72">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜尋帳號或根目錄路徑..."
            className="h-8 pl-8 text-xs"
          />
        </div>
        <span className="text-xs text-muted-foreground">共 {filteredUsers.length} 位使用者</span>
      </div>

      {/* Users Table */}
      {loading ? (
        <div className="py-20 text-center text-sm text-muted-foreground">載入使用者名冊中...</div>
      ) : filteredUsers.length === 0 ? (
        <div className="py-16 text-center border border-dashed rounded-xl space-y-3 bg-muted/20">
          <Users className="h-10 w-10 text-muted-foreground/40 mx-auto" />
          <h3 className="text-sm font-semibold text-foreground">尚未建立使用者</h3>
          <p className="text-xs text-muted-foreground max-w-sm mx-auto">
            您可以新增訪客或一般成員帳號，並獨立賦予唯讀或 WebDAV 權限。
          </p>
          <Button size="sm" variant="outline" onClick={handleOpenAdd} className="text-xs">
            新增使用者
          </Button>
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-card overflow-hidden shadow-xs">
          <table className="w-full text-left text-xs border-collapse">
            <thead className="bg-muted/50 border-b border-border/70 text-muted-foreground select-none">
              <tr>
                <th className="py-3 px-4 font-semibold">使用者名稱</th>
                <th className="py-3 px-4 font-semibold">角色 (Role)</th>
                <th className="py-3 px-4 font-semibold">根目錄 (Base Path)</th>
                <th className="py-3 px-4 font-semibold">AList 10 項權限位元</th>
                <th className="py-3 px-4 font-semibold">狀態 (Available)</th>
                <th className="py-3 px-4 font-semibold text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border/40">
              {filteredUsers.map((user) => (
                <tr key={user.id} className="hover:bg-muted/30 transition-colors">
                  <td className="py-3 px-4 font-semibold text-foreground flex items-center gap-2">
                    <Shield className="h-3.5 w-3.5 text-primary" />
                    <span>{user.username}</span>
                  </td>
                  <td className="py-3 px-4">
                    <Badge
                      variant="outline"
                      className={`text-[10px] ${
                        user.role === 'admin'
                          ? 'text-primary border-primary/30 bg-primary/10'
                          : user.role === 'guest'
                          ? 'text-muted-foreground'
                          : 'text-blue-500 border-blue-500/30 bg-blue-500/10'
                      }`}
                    >
                      {user.role.toUpperCase()}
                    </Badge>
                  </td>
                  <td className="py-3 px-4 font-mono text-muted-foreground">{user.base_path || '/'}</td>
                  <td className="py-3 px-4">
                    {/* AList 10 colored circles with hover tooltips */}
                    <div className="flex items-center gap-1.5 flex-wrap">
                      {PERMISSION_DEFS.map((p) => {
                        const hasPerm = (user.permission & p.bit) !== 0;
                        return (
                          <span
                            key={p.key}
                            title={`${p.label}: ${hasPerm ? '已啟用' : '已停用'}`}
                            className={`h-2.5 w-2.5 rounded-full transition-all ${
                              hasPerm ? 'bg-emerald-500 ring-2 ring-emerald-500/20' : 'bg-muted-foreground/30'
                            }`}
                          />
                        );
                      })}
                    </div>
                  </td>
                  <td className="py-3 px-4">
                    <button
                      type="button"
                      onClick={() => handleToggleDisabled(user)}
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium cursor-pointer ${
                        !user.disabled
                          ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                          : 'bg-red-500/10 text-red-600 dark:text-red-400'
                      }`}
                    >
                      {!user.disabled ? <UserCheck className="h-3 w-3" /> : <UserX className="h-3 w-3" />}
                      <span>{!user.disabled ? '正常' : '已停用'}</span>
                    </button>
                  </td>
                  <td className="py-3 px-4 text-right">
                    <div className="flex items-center justify-end gap-1.5">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleOpenEdit(user)}
                        className="h-7 w-7 p-0"
                        title="編輯權限"
                      >
                        <Edit2 className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => handleDelete(user.id)}
                        disabled={user.username === 'admin'}
                        className="h-7 w-7 p-0 text-destructive hover:bg-destructive/10 disabled:opacity-30"
                        title="刪除"
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

      {/* Add / Edit User Modal */}
      {isModalOpen && editingUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs animate-in fade-in">
          <div className="bg-background rounded-xl border border-border shadow-xl w-full max-w-2xl max-h-[90vh] flex flex-col overflow-hidden">
            <div className="flex items-center justify-between p-4 border-b border-border">
              <h3 className="font-bold text-sm text-foreground flex items-center gap-2">
                <Users className="h-4 w-4 text-primary" />
                <span>編輯使用者與 10 項權限</span>
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
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="font-semibold text-foreground">帳號名稱 (Username)</label>
                  <Input
                    value={editingUser.username}
                    onChange={(e) => setEditingUser({ ...editingUser, username: e.target.value })}
                    placeholder="例如 user1"
                    className="h-8 text-xs"
                    required
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="font-semibold text-foreground">角色 (Role)</label>
                  <select
                    value={editingUser.role}
                    onChange={(e) => setEditingUser({ ...editingUser, role: e.target.value as any })}
                    className="w-full h-8 rounded-md border border-input bg-background px-2.5 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                  >
                    <option value="admin">管理者 (Admin)</option>
                    <option value="general">一般使用者 (General)</option>
                    <option value="guest">訪客 (Guest)</option>
                  </select>
                </div>

                <div className="space-y-1.5">
                  <label className="font-semibold text-foreground">根目錄路徑 (Base Path)</label>
                  <Input
                    value={editingUser.base_path}
                    onChange={(e) => setEditingUser({ ...editingUser, base_path: e.target.value })}
                    placeholder="例如 / 或 /photos"
                    className="h-8 text-xs font-mono"
                  />
                </div>

                <div className="space-y-1.5">
                  <label className="font-semibold text-foreground">重設密碼 (Password)</label>
                  <Input
                    type="password"
                    value={userPassword}
                    onChange={(e) => setUserPassword(e.target.value)}
                    placeholder="留空表示不修改密碼"
                    className="h-8 text-xs"
                  />
                </div>
              </div>

              {/* 10 Permissions Checkbox Grid */}
              <div className="space-y-2 pt-2 border-t border-border">
                <div className="flex items-center justify-between">
                  <h4 className="font-semibold text-foreground">AList 權限位元遮罩設定 (Permissions)</h4>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => setEditingUser({ ...editingUser, permission: 1023 })}
                      className="text-[11px] text-primary hover:underline"
                    >
                      全選 (1023)
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditingUser({ ...editingUser, permission: 0 })}
                      className="text-[11px] text-muted-foreground hover:underline"
                    >
                      清空 (0)
                    </button>
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 p-3 rounded-lg border border-border/60 bg-muted/20">
                  {PERMISSION_DEFS.map((p) => {
                    const checked = (editingUser.permission & p.bit) !== 0;
                    return (
                      <label
                        key={p.key}
                        className="flex items-start gap-2 p-1.5 rounded hover:bg-muted/40 cursor-pointer select-none"
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => togglePermissionBit(p.bit)}
                          className="rounded border-input text-primary focus:ring-primary h-3.5 w-3.5 mt-0.5"
                        />
                        <div className="space-y-0.5">
                          <span className={`font-medium block ${checked ? 'text-foreground' : 'text-muted-foreground'}`}>
                            {p.label}
                          </span>
                          <span className="text-[10px] text-muted-foreground block">{p.desc}</span>
                        </div>
                      </label>
                    );
                  })}
                </div>
              </div>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-border">
                <Button type="button" variant="outline" size="sm" onClick={() => setIsModalOpen(false)}>
                  取消
                </Button>
                <Button type="submit" size="sm" disabled={saving}>
                  {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : '儲存使用者'}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
