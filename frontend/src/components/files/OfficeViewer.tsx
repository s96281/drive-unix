import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/api';
import {
  absoluteDownloadUrl,
  officeViewerUrl,
  downloadUrl,
} from '@/lib/file-types';
import { Button } from '@/components/ui/button';
import { AlertTriangle, Download, ExternalLink, Loader2, RefreshCw } from 'lucide-react';
import type { FsItem } from '@/api/types';

interface OfficeViewerProps {
  item: FsItem;
  remote: string;
}

interface LinkResponse {
  remote: string;
  path: string;
  url: string;
}

export function OfficeViewer({ item, remote }: OfficeViewerProps) {
  const [iframeLoaded, setIframeLoaded] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  // 優先嘗試獲取直鏈 (Provider direct download link, 例如 OneDrive / SharePoint / S3 / WebDAV 直鏈)
  const { data: directLinkData, isLoading: isLinkLoading } = useQuery<LinkResponse>({
    queryKey: ['direct-link', remote, item.path],
    queryFn: async () => {
      try {
        return await api.request<LinkResponse>('GET', `/fs/${encodeURIComponent(remote)}/link`, {
          query: { path: item.path },
        });
      } catch {
        return null as any;
      }
    },
    staleTime: 60_000,
    retry: false,
  });

  const effectiveFileUrl = directLinkData?.url || absoluteDownloadUrl(remote, item.path);
  const viewerSrc = officeViewerUrl(effectiveFileUrl);

  const isLocalHost =
    typeof window !== 'undefined' &&
    (window.location.hostname === 'localhost' ||
      window.location.hostname === '127.0.0.1' ||
      window.location.hostname === '0.0.0.0' ||
      window.location.hostname.endsWith('.local'));

  const handleDownload = () => {
    window.open(downloadUrl(remote, item.path), '_blank');
  };

  return (
    <div className="flex flex-col h-full space-y-2">
      {isLocalHost && !directLinkData?.url && (
        <div className="flex items-center gap-2 text-xs text-amber-500 bg-amber-500/10 border border-amber-500/20 px-3 py-2 rounded-md">
          <AlertTriangle className="h-4 w-4 shrink-0 text-amber-500" />
          <div className="flex-1">
            當前環境為內部本機網址（{window.location.hostname}），微軟 Office 雲端預覽伺服器可能無法公開存取本檔案。若預覽無法開啟，請點擊右側下載或於公開網域（VPS/穿透）使用。
          </div>
          <Button size="sm" variant="outline" onClick={handleDownload} className="h-7 text-xs gap-1 shrink-0">
            <Download className="h-3 w-3" /> 下載本機開啟
          </Button>
        </div>
      )}

      <div className="flex items-center justify-between text-xs text-muted-foreground px-1">
        <span>Microsoft Office Online 雲端預覽</span>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setIframeLoaded(false);
              setReloadKey((k) => k + 1);
            }}
            className="h-6 text-xs gap-1"
          >
            <RefreshCw className="h-3 w-3" /> 重新整理
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => window.open(viewerSrc, '_blank')}
            className="h-6 text-xs gap-1"
          >
            <ExternalLink className="h-3 w-3" /> 新視窗預覽
          </Button>
        </div>
      </div>

      <div className="relative rounded-md overflow-hidden border border-border/60 bg-muted/10 h-[62vh] min-h-[420px]">
        {(!iframeLoaded || isLinkLoading) && (
          <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-background/80 backdrop-blur-xs text-muted-foreground gap-2">
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
            <span className="text-xs">正在載入 Microsoft Office 預覽模組...</span>
          </div>
        )}
        <iframe
          key={reloadKey}
          title={item.name}
          src={viewerSrc}
          className="w-full h-full border-0"
          onLoad={() => setIframeLoaded(true)}
        />
      </div>
    </div>
  );
}
