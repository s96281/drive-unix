import { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
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
import { formatBytes } from '@/lib/format';
import { FileText, Image as ImageIcon, Download, Copy, Check, ExternalLink } from 'lucide-react';
import { toast } from 'sonner';
import type { FsItem } from '@/api/types';

interface FilePreviewDialogProps {
  item: FsItem | null;
  remote: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function FilePreviewDialog({ item, remote, open, onOpenChange }: FilePreviewDialogProps) {
  const [copied, setCopied] = useState(false);

  const isImage = item
    ? /\.(png|jpe?g|gif|webp|svg|bmp)$/i.test(item.name) || item.mime_type?.startsWith('image/')
    : false;

  const isText = item
    ? /\.(txt|md|json|py|js|ts|tsx|jsx|html|css|yaml|yml|sh|env|conf|log|csv)$/i.test(item.name) ||
      item.mime_type?.startsWith('text/')
    : false;

  // Query content for text files
  const { data: textContent, isLoading: isTextLoading } = useQuery({
    queryKey: ['file-content', remote, item?.path],
    queryFn: async () => {
      if (!item || !isText) return '';
      const res = await api.request<{ content: string }>('GET', `/fs/${remote}/read`, {
        query: { path: item.path, max_bytes: 102400 },
      });
      return res.content;
    },
    enabled: open && !!item && isText,
  });

  const handleCopy = () => {
    if (textContent) {
      navigator.clipboard.writeText(textContent);
      setCopied(true);
      toast.success('已複製內容至剪貼簿');
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleDownload = () => {
    if (!item) return;
    toast.success(`開始下載 [${item.name}]...`);
    // In browser environment:
    const downloadUrl = `/api/fs/${remote}/download?path=${encodeURIComponent(item.path)}`;
    window.open(downloadUrl, '_blank');
  };

  if (!item) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[85vh] flex flex-col">
        <DialogHeader>
          <div className="flex items-center justify-between pr-6">
            <div className="flex items-center gap-2">
              <div className="p-2 rounded-lg bg-primary/10 text-primary">
                {isImage ? <ImageIcon className="h-5 w-5" /> : <FileText className="h-5 w-5" />}
              </div>
              <div>
                <DialogTitle className="truncate max-w-md">{item.name}</DialogTitle>
                <DialogDescription>
                  {remote}:{item.path} • {formatBytes(item.size)}
                </DialogDescription>
              </div>
            </div>
          </div>
        </DialogHeader>

        {/* Preview Viewport */}
        <div className="flex-1 overflow-auto min-h-[300px] max-h-[500px] border border-border rounded-lg bg-muted/20 p-4">
          {isImage ? (
            <div className="flex flex-col items-center justify-center h-full min-h-[280px]">
              {/* Image preview */}
              <div className="relative max-h-[440px] max-w-full overflow-hidden rounded-md border border-border/50 bg-black/20 flex items-center justify-center p-2">
                <img
                  src={`/api/fs/${remote}/download?path=${encodeURIComponent(item.path)}`}
                  alt={item.name}
                  className="max-h-[400px] max-w-full object-contain rounded"
                  onError={(e) => {
                    // Fallback to placeholder if backend binary stream is offline or mock
                    (e.target as HTMLElement).style.display = 'none';
                    (e.target as HTMLElement).parentElement!.innerHTML = `
                      <div class="py-12 px-6 text-center text-muted-foreground flex flex-col items-center">
                        <svg class="h-12 w-12 text-primary/60 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                        </svg>
                        <p class="font-medium text-foreground">圖片預覽 (${item.name})</p>
                        <p class="text-xs text-muted-foreground mt-1">大小: ${formatBytes(item.size)}</p>
                      </div>
                    `;
                  }}
                />
              </div>
            </div>
          ) : isText ? (
            <div className="relative">
              {isTextLoading ? (
                <div className="flex items-center justify-center py-20 text-muted-foreground text-sm">
                  讀取文字內容中...
                </div>
              ) : (
                <div>
                  <div className="flex justify-end mb-2">
                    <Button variant="ghost" size="sm" onClick={handleCopy} className="h-7 text-xs gap-1">
                      {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
                      {copied ? '已複製' : '複製文字'}
                    </Button>
                  </div>
                  <pre className="font-mono text-xs text-foreground/90 whitespace-pre-wrap break-all p-3 rounded-md bg-card/60 border border-border/60 overflow-x-auto leading-relaxed max-h-[380px]">
                    {textContent || '(空檔案)'}
                  </pre>
                </div>
              )}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full py-16 text-center space-y-3">
              <div className="h-14 w-14 rounded-full bg-accent/40 flex items-center justify-center text-muted-foreground">
                <FileText className="h-7 w-7" />
              </div>
              <div>
                <p className="font-semibold text-foreground">{item.name}</p>
                <p className="text-xs text-muted-foreground mt-0.5">
                  二進位檔案 ({item.mime_type || 'application/octet-stream'}) • {formatBytes(item.size)}
                </p>
              </div>
              <p className="text-xs text-muted-foreground max-w-sm">
                目前不支援瀏覽器內嵌即時預覽此檔案格式，建議直接下載至本機開啟。
              </p>
              <Button size="sm" onClick={handleDownload} className="gap-1.5 mt-2">
                <Download className="h-4 w-4" /> 下載檔案
              </Button>
            </div>
          )}
        </div>

        <DialogFooter className="flex items-center justify-between sm:justify-between w-full">
          <div className="text-xs text-muted-foreground">
            路徑: <code className="bg-muted px-1.5 py-0.5 rounded font-mono text-[11px]">{item.path}</code>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={handleDownload} className="gap-1.5">
              <Download className="h-3.5 w-3.5" /> 下載
            </Button>
            <Button variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
              關閉
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
