import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/api';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { toast } from 'sonner';
import { FolderPlus, Edit3, ArrowRightLeft, Copy, Trash2 } from 'lucide-react';
import type { FsItem, RemoteItem } from '@/api/types';

export type FileOpType = 'mkdir' | 'rename' | 'transfer' | 'delete_batch';

interface FileOpsDialogProps {
  type: FileOpType | null;
  remote: string;
  currentPath: string;
  items: FsItem[];
  availableRemotes: RemoteItem[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess?: () => void;
}

export function FileOpsDialog({
  type,
  remote,
  currentPath,
  items,
  availableRemotes,
  open,
  onOpenChange,
  onSuccess,
}: FileOpsDialogProps) {
  const queryClient = useQueryClient();
  const [folderName, setFolderName] = useState('');
  const [newName, setNewName] = useState(items[0]?.name || '');
  const [destRemote, setDestRemote] = useState(availableRemotes[0]?.name || remote);
  const [destPath, setDestPath] = useState(currentPath);
  const [isMove, setIsMove] = useState(false);

  // Sync newName when single item changes
  useState(() => {
    if (items[0]) {
      setNewName(items[0].name);
    }
  });

  const mutation = useMutation({
    mutationFn: async () => {
      if (type === 'mkdir') {
        const fullPath = currentPath === '/' ? `/${folderName}` : `${currentPath}/${folderName}`;
        return api.request('POST', `/fs/${remote}/mkdir`, {
          body: { path: fullPath },
        });
      }

      if (type === 'rename' && items[0]) {
        const parent = items[0].path.substring(0, items[0].path.lastIndexOf('/')) || '/';
        const newPath = parent === '/' ? `/${newName}` : `${parent}/${newName}`;
        return api.request('POST', `/fs/${remote}/rename`, {
          body: { old_path: items[0].path, new_path: newPath },
        });
      }

      if (type === 'transfer') {
        return api.request('POST', '/fs/transfer', {
          body: {
            src_remote: remote,
            sources: items.map((i) => i.path),
            dest_remote: destRemote,
            dest_path: destPath,
            is_move: isMove,
          },
        });
      }

      if (type === 'delete_batch') {
        // Delete all selected items sequentially
        for (const item of items) {
          await api.request('POST', `/fs/${remote}/delete`, {
            body: { path: item.path, recursive: item.is_dir },
          });
        }
        return { count: items.length };
      }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['fs-list'] });
      if (type === 'mkdir') toast.success(`目錄 [${folderName}] 建立成功`);
      if (type === 'rename') toast.success(`已重新命名為 [${newName}]`);
      if (type === 'transfer') {
        toast.success(
          `已啟動${isMove ? '移動' : '複製'}傳輸任務 (${items.length} 個項目至 ${destRemote}:${destPath})`,
        );
        queryClient.invalidateQueries({ queryKey: ['tasks'] });
      }
      if (type === 'delete_batch') toast.success(`已刪除 ${items.length} 個項目`);

      onOpenChange(false);
      onSuccess?.();
    },
    onError: (err: any) => {
      toast.error(`操作失敗: ${err.message}`);
    },
  });

  if (!type) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <div className="flex items-center gap-2">
            <div className="p-2 rounded-lg bg-primary/10 text-primary">
              {type === 'mkdir' && <FolderPlus className="h-5 w-5" />}
              {type === 'rename' && <Edit3 className="h-5 w-5" />}
              {type === 'transfer' && <ArrowRightLeft className="h-5 w-5" />}
              {type === 'delete_batch' && <Trash2 className="h-5 w-5 text-destructive" />}
            </div>
            <div>
              <DialogTitle>
                {type === 'mkdir' && '新增子資料夾'}
                {type === 'rename' && '重新命名項目'}
                {type === 'transfer' && '複製 / 移動至遠端或路徑'}
                {type === 'delete_batch' && '確認批次刪除'}
              </DialogTitle>
              <DialogDescription>
                {type === 'mkdir' && `在目前路徑 [${currentPath}] 建立新資料夾`}
                {type === 'rename' && `變更 [${items[0]?.name}] 的名稱`}
                {type === 'transfer' && `將 ${items.length} 個選取項目傳輸至目標節點`}
                {type === 'delete_batch' && `此操作將刪除 ${items.length} 個選取的檔案或目錄`}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="py-3 space-y-4">
          {type === 'mkdir' && (
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-foreground">資料夾名稱</label>
              <Input
                placeholder="例如: Documents 或 2026-Backup"
                value={folderName}
                onChange={(e) => setFolderName(e.target.value)}
                autoFocus
              />
            </div>
          )}

          {type === 'rename' && (
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-foreground">新名稱</label>
              <Input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                placeholder="輸入新名稱"
                autoFocus
              />
            </div>
          )}

          {type === 'transfer' && (
            <div className="space-y-3">
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-foreground">目標儲存節點 (Destination Remote)</label>
                <Select value={destRemote} onValueChange={setDestRemote}>
                  <SelectTrigger>
                    <SelectValue placeholder="選擇目標節點" />
                  </SelectTrigger>
                  <SelectContent>
                    {availableRemotes.map((r) => (
                      <SelectItem key={r.name} value={r.name}>
                        {r.name} ({r.type})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-foreground">目標目錄路徑</label>
                <Input
                  value={destPath}
                  onChange={(e) => setDestPath(e.target.value)}
                  placeholder="例如: / 或 /Backups/Target"
                />
              </div>

              <div className="pt-1">
                <label className="flex items-center gap-2 cursor-pointer text-xs text-foreground select-none">
                  <input
                    type="checkbox"
                    checked={isMove}
                    onChange={(e) => setIsMove(e.target.checked)}
                    className="rounded text-primary focus:ring-primary"
                  />
                  傳輸完成後刪除來源檔案 (Move 剪下移動)
                </label>
              </div>
            </div>
          )}

          {type === 'delete_batch' && (
            <div className="p-3 rounded-lg bg-destructive/10 border border-destructive/20 text-xs text-destructive space-y-2">
              <p className="font-semibold">警告：此操作不可復原！</p>
              <ul className="list-disc list-inside space-y-0.5 text-muted-foreground">
                {items.slice(0, 5).map((it) => (
                  <li key={it.path} className="truncate">
                    {it.name} {it.is_dir && '(目錄)'}
                  </li>
                ))}
                {items.length > 5 && <li>以及其他 {items.length - 5} 個項目...</li>}
              </ul>
            </div>
          )}
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button
            size="sm"
            variant={type === 'delete_batch' ? 'destructive' : 'default'}
            onClick={() => mutation.mutate()}
            disabled={
              mutation.isPending ||
              (type === 'mkdir' && !folderName.trim()) ||
              (type === 'rename' && !newName.trim())
            }
          >
            {mutation.isPending ? '處理中...' : '確認執行'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
