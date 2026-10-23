import { useEffect, useRef, useState } from 'react';
import Artplayer from 'artplayer';
import artplayerZhTw from 'artplayer/i18n/zh-tw';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface ArtPlayerViewerProps {
  url: string;
  name: string;
  isAudio?: boolean;
  poster?: string;
  className?: string;
  onReady?: (art: Artplayer) => void;
}

export function ArtPlayerViewer({
  url,
  name,
  isAudio = false,
  poster,
  className,
  onReady,
}: ArtPlayerViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const artRef = useRef<Artplayer | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!containerRef.current) return;
    setErrorMsg(null);

    let art: Artplayer | null = null;
    try {
      art = new Artplayer({
        container: containerRef.current,
        url,
        poster,
        volume: 0.7,
        isLive: false,
        muted: false,
        autoplay: false,
        autoSize: false,
        autoMini: false,
        loop: false,
        flip: true,
        playbackRate: true,
        aspectRatio: true,
        screenshot: !isAudio,
        setting: true,
        hotkey: true,
        pip: !isAudio,
        fullscreen: true,
        fullscreenWeb: true,
        miniProgressBar: true,
        playsInline: true,
        lock: true,
        fastForward: true,
        autoPlayback: true,
        theme: 'var(--primary, #3b82f6)',
        lang: 'zh-tw',
        i18n: {
          'zh-tw': artplayerZhTw as any,
        },
        moreVideoAttr: {
          crossOrigin: 'anonymous',
          preload: 'metadata',
        },
      });

      art.on('error', (err: any) => {
        console.error('Artplayer playback error:', err);
        setErrorMsg('媒體載入或解碼失敗，請確認檔案格式是否被支援或儲存節點連線狀況。');
      });

      artRef.current = art;
      if (onReady) {
        art.on('ready', () => onReady(art!));
      }
    } catch (err: any) {
      console.error('Artplayer init error:', err);
      setErrorMsg(err?.message || '播放器初始化失敗');
    }

    return () => {
      if (art && !art.isDestroy) {
        art.destroy(true);
      }
      artRef.current = null;
    };
  }, [url, poster, isAudio, reloadKey, onReady]);

  if (errorMsg) {
    return (
      <div className="flex flex-col items-center justify-center text-center gap-2 py-12 text-muted-foreground text-sm">
        <AlertTriangle className="h-8 w-8 text-amber-400" />
        <p className="font-medium text-foreground">{name}</p>
        <p className="text-xs max-w-sm break-words">{errorMsg}</p>
        <Button
          size="sm"
          variant="outline"
          onClick={() => {
            setErrorMsg(null);
            setReloadKey((k) => k + 1);
          }}
          className="gap-1.5 mt-2"
        >
          <RefreshCw className="h-3.5 w-3.5" /> 重新載入
        </Button>
      </div>
    );
  }

  return (
    <div className={`relative w-full overflow-hidden rounded-md bg-black/90 ${className || ''}`}>
      <div
        ref={containerRef}
        className={`w-full ${isAudio ? 'h-[160px]' : 'h-[55vh] min-h-[320px]'}`}
      />
    </div>
  );
}
