import React, { useState, useEffect, useMemo } from 'react';
import { Search as SearchIcon, Loader2 } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { FileTypeIcon } from './FileTypeIcon';
import { formatBytes } from '@/lib/format';
import { useUiStore } from '@/stores/ui-store';
import type { FsItem, RemoteItem } from '@/api/types';

interface FileSearchModalProps {
  currentRemote: string | null;
  currentItems: FsItem[];
  remotes: RemoteItem[];
  onSelectRemote: (remoteName: string) => void;
  onSelectItem: (item: FsItem) => void;
}

function HighlightedName({ name, keyword }: { name: string; keyword: string }) {
  if (!keyword.trim()) return <>{name}</>;
  const escaped = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const parts = name.split(new RegExp(`(${escaped})`, 'gi'));
  return (
    <>
      {parts.map((part, i) =>
        part.toLowerCase() === keyword.toLowerCase() ? (
          <mark
            key={i}
            className="bg-[var(--alist-info4)] text-[var(--alist-info11)] font-bold rounded px-1"
          >
            {part}
          </mark>
        ) : (
          <React.Fragment key={i}>{part}</React.Fragment>
        ),
      )}
    </>
  );
}

export function FileSearchModal({
  currentRemote,
  currentItems,
  remotes,
  onSelectRemote,
  onSelectItem,
}: FileSearchModalProps) {
  const { searchModalOpen, setSearchModalOpen } = useUiStore();
  const [scope, setScope] = useState<'all' | 'folder' | 'file'>('all');
  const [keyword, setKeyword] = useState('');

  // Global Ctrl+K / Cmd+K shortcut listener (matches alist-web Search.tsx)
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setSearchModalOpen(!searchModalOpen);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [searchModalOpen, setSearchModalOpen]);

  const results = useMemo(() => {
    const q = keyword.trim().toLowerCase();

    // Combine mounted remotes (as folders) and current directory items
    const combined: Array<{
      id: string;
      name: string;
      parent: string;
      is_dir: boolean;
      size: number;
      remoteName?: string;
      fsItem?: FsItem;
    }> = [];

    if (scope !== 'file') {
      for (const r of remotes) {
        combined.push({
          id: `remote:${r.name}`,
          name: r.name,
          parent: `掛載節點 (${r.type})`,
          is_dir: true,
          size: 0,
          remoteName: r.name,
        });
      }
    }

    for (const item of currentItems) {
      if (scope === 'folder' && !item.is_dir) continue;
      if (scope === 'file' && item.is_dir) continue;
      const lastSlash = item.path.lastIndexOf('/');
      const parent = lastSlash <= 0 ? '/' : item.path.slice(0, lastSlash);
      combined.push({
        id: `item:${item.path}`,
        name: item.name,
        parent: `${currentRemote || 'root'}:${parent}`,
        is_dir: item.is_dir,
        size: item.size,
        fsItem: item,
      });
    }

    if (!q) return combined.slice(0, 30);
    return combined.filter(
      (entry) =>
        entry.name.toLowerCase().includes(q) || entry.parent.toLowerCase().includes(q),
    );
  }, [keyword, scope, remotes, currentItems, currentRemote]);

  return (
    <Dialog open={searchModalOpen} onOpenChange={setSearchModalOpen}>
      <DialogContent className="max-w-2xl w-[94vw] p-5 bg-[var(--alist-card-bg)] rounded-xl border border-border/60 shadow-2xl">
        <DialogHeader className="pb-2">
          <DialogTitle className="text-base font-bold text-foreground">
            搜尋檔案與掛載節點 (Search)
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-3">
          {/* Search Input Bar (AList HStack: Scope Select + Input + Search IconButton) */}
          <div className="flex items-center gap-2">
            <Select value={scope} onValueChange={(v) => setScope(v as any)}>
              <SelectTrigger className="w-28 h-9 text-xs bg-input/80 border-transparent shrink-0">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部 (All)</SelectItem>
                <SelectItem value="folder">資料夾</SelectItem>
                <SelectItem value="file">檔案</SelectItem>
              </SelectContent>
            </Select>

            <Input
              placeholder="輸入關鍵字即時篩選目錄與節點..."
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              autoFocus
              className="flex-1 h-9 text-sm"
            />

            <Button variant="subtle" size="icon" className="shrink-0 h-9 w-9">
              <SearchIcon className="h-4 w-4" />
            </Button>
          </div>

          {/* Results List */}
          <div className="max-h-[55vh] overflow-y-auto divide-y divide-border/40 rounded-lg border border-border/40">
            {results.length === 0 ? (
              <div className="py-12 text-center text-muted-foreground text-sm">
                找不到符合「{keyword}」的項目
              </div>
            ) : (
              results.map((entry) => (
                <div
                  key={entry.id}
                  onClick={() => {
                    setSearchModalOpen(false);
                    if (entry.remoteName) {
                      onSelectRemote(entry.remoteName);
                    } else if (entry.fsItem) {
                      onSelectItem(entry.fsItem);
                    }
                  }}
                  className="flex items-center gap-3 px-3 py-2.5 hover:bg-[var(--alist-hover)] cursor-pointer transition-colors"
                >
                  <FileTypeIcon name={entry.name} isDir={entry.is_dir} className="h-6 w-6" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium text-foreground break-all">
                        <HighlightedName name={entry.name} keyword={keyword} />
                      </span>
                      {!entry.is_dir && (
                        <Badge variant="info" className="text-[10px] px-1.5 py-0">
                          {formatBytes(entry.size)}
                        </Badge>
                      )}
                      {entry.remoteName && (
                        <Badge variant="default" className="text-[10px] px-1.5 py-0">
                          儲存節點
                        </Badge>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground truncate mt-0.5">{entry.parent}</p>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
