import { useEffect, useMemo, useState } from 'react';
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
import { Badge } from '@/components/ui/badge';
import { formatBytes } from '@/lib/format';
import {
  FILE_KIND_LABEL,
  downloadUrl,
  getExtension,
  getFileKind,
  isBrowserPlayable,
  isTextual,
  parseCsv,
  rawUrl,
  type FileKind,
} from '@/lib/file-types';
import { FileTypeIcon } from '@/components/files/FileTypeIcon';
import { ArtPlayerViewer } from '@/components/files/ArtPlayerViewer';
import { OfficeViewer } from '@/components/files/OfficeViewer';
import {
  AlertTriangle,
  Check,
  Copy,
  Download,
  ExternalLink,
  Loader2,
  RefreshCw,
  WrapText,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import { toast } from 'sonner';
import type { FsItem } from '@/api/types';

interface FilePreviewDialogProps {
  item: FsItem | null;
  remote: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface ReadResult {
  content: string;
  size?: number;
  truncated?: boolean;
  is_binary?: boolean;
  encoding?: string;
}

const MAX_PREVIEW_BYTES = 262144;

/* ---------- 共用小元件 ---------- */

function Centered({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center text-center gap-2 py-16 min-h-[260px] text-muted-foreground text-sm">
      {children}
    </div>
  );
}

function LoadingState({ label }: { label: string }) {
  return (
    <Centered>
      <Loader2 className="h-6 w-6 animate-spin text-primary/70" />
      <span>{label}</span>
    </Centered>
  );
}

function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <Centered>
      <AlertTriangle className="h-8 w-8 text-amber-400" />
      <p className="font-medium text-foreground">無法預覽此檔案</p>
      <p className="text-xs max-w-sm break-words">{message}</p>
      {onRetry && (
        <Button size="sm" variant="outline" onClick={onRetry} className="gap-1.5 mt-1">
          <RefreshCw className="h-3.5 w-3.5" /> 重試
        </Button>
      )}
    </Centered>
  );
}

function UnsupportedState({
  item,
  kind,
  note,
  onDownload,
}: {
  item: FsItem;
  kind: FileKind;
  note?: string;
  onDownload: () => void;
}) {
  return (
    <Centered>
      <div className="h-16 w-16 rounded-2xl bg-accent/40 flex items-center justify-center">
        <FileTypeIcon name={item.name} className="h-8 w-8" />
      </div>
      <p className="font-semibold text-foreground break-all max-w-md">{item.name}</p>
      <p className="text-xs">
        {FILE_KIND_LABEL[kind]} • {formatBytes(item.size)}
      </p>
      <p className="text-xs max-w-sm">{note ?? '目前不支援瀏覽器內嵌預覽此檔案格式，請下載後以本機程式開啟。'}</p>
      <Button size="sm" onClick={onDownload} className="gap-1.5 mt-2">
        <Download className="h-4 w-4" /> 下載檔案
      </Button>
    </Centered>
  );
}

/* ---------- 圖片 ---------- */

function ImageViewer({ src, name }: { src: string; name: string }) {
  const [state, setState] = useState<'loading' | 'ok' | 'error'>('loading');
  const [zoom, setZoom] = useState(1);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    setState('loading');
    setZoom(1);
  }, [src]);

  if (state === 'error') {
    return <ErrorState message="圖片載入失敗（檔案可能損毀、格式不受瀏覽器支援，或儲存節點暫時無法連線）。" onRetry={() => { setState('loading'); setNonce((n) => n + 1); }} />;
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-end gap-1 mb-2">
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setZoom((z) => Math.max(0.25, z - 0.25))} title="縮小">
          <ZoomOut className="h-3.5 w-3.5" />
        </Button>
        <button type="button" className="text-xs text-muted-foreground w-12 text-center hover:text-foreground" onClick={() => setZoom(1)} title="重設">
          {Math.round(zoom * 100)}%
        </button>
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setZoom((z) => Math.min(4, z + 0.25))} title="放大">
          <ZoomIn className="h-3.5 w-3.5" />
        </Button>
      </div>
      <div
        className="relative flex-1 overflow-auto rounded-md border border-border/50 min-h-[300px] max-h-[55vh]"
        style={{
          backgroundImage:
            'conic-gradient(#8881 25%, transparent 0 50%, #8881 0 75%, transparent 0)',
          backgroundSize: '16px 16px',
        }}
      >
        {state === 'loading' && (
          <div className="absolute inset-0 flex items-center justify-center text-muted-foreground">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
        )}
        <div className="min-h-full min-w-full flex items-center justify-center p-2">
          <img
            key={nonce}
            src={`${src}${src.includes('?') ? '&' : '?'}_=${nonce}`}
            alt={name}
            onLoad={() => setState('ok')}
            onError={() => setState('error')}
            style={zoom === 1 ? undefined : { width: `${zoom * 100}%`, maxWidth: 'none' }}
            className={zoom === 1 ? 'max-h-[52vh] max-w-full object-contain' : 'h-auto'}
          />
        </div>
      </div>
    </div>
  );
}

/* ---------- Markdown（輕量，不使用 innerHTML） ---------- */

function renderInline(text: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\[[^\]]+\]\((?:https?:\/\/|\/|#)[^)\s]*\))/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    if (tok.startsWith('`')) {
      out.push(<code key={i++} className="px-1 py-0.5 rounded bg-muted font-mono text-[0.85em]">{tok.slice(1, -1)}</code>);
    } else if (tok.startsWith('**')) {
      out.push(<strong key={i++}>{tok.slice(2, -2)}</strong>);
    } else {
      const mm = /\[([^\]]+)\]\(([^)]+)\)/.exec(tok)!;
      out.push(<a key={i++} href={mm[2]} target="_blank" rel="noreferrer noopener" className="text-primary underline underline-offset-2">{mm[1]}</a>);
    }
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function MarkdownView({ source }: { source: string }) {
  const blocks = useMemo(() => {
    const lines = source.replace(/\r\n?/g, '\n').split('\n');
    const nodes: React.ReactNode[] = [];
    let i = 0;
    let key = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (/^```/.test(line)) {
        const buf: string[] = [];
        i++;
        while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
        i++;
        nodes.push(<pre key={key++} className="font-mono text-xs p-3 rounded-md bg-muted/60 border border-border/60 overflow-x-auto">{buf.join('\n')}</pre>);
        continue;
      }
      const h = /^(#{1,6})\s+(.*)$/.exec(line);
      if (h) {
        const level = h[1].length;
        const cls = ['text-2xl', 'text-xl', 'text-lg', 'text-base', 'text-sm', 'text-sm'][level - 1];
        nodes.push(<div key={key++} className={`${cls} font-semibold mt-4 mb-1 text-foreground`}>{renderInline(h[2])}</div>);
        i++;
        continue;
      }
      if (/^\s*([-*+]|\d+\.)\s+/.test(line)) {
        const ordered = /^\s*\d+\./.test(line);
        const items: React.ReactNode[] = [];
        while (i < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[i])) {
          items.push(<li key={items.length}>{renderInline(lines[i].replace(/^\s*([-*+]|\d+\.)\s+/, ''))}</li>);
          i++;
        }
        const L = ordered ? 'ol' : 'ul';
        nodes.push(<L key={key++} className={`${ordered ? 'list-decimal' : 'list-disc'} pl-6 my-2 space-y-0.5`}>{items}</L>);
        continue;
      }
      if (/^>\s?/.test(line)) {
        const buf: string[] = [];
        while (i < lines.length && /^>\s?/.test(lines[i])) buf.push(lines[i++].replace(/^>\s?/, ''));
        nodes.push(<blockquote key={key++} className="border-l-2 border-primary/50 pl-3 my-2 text-muted-foreground">{renderInline(buf.join(' '))}</blockquote>);
        continue;
      }
      if (/^\s*(---|\*\*\*)\s*$/.test(line)) {
        nodes.push(<hr key={key++} className="my-3 border-border" />);
        i++;
        continue;
      }
      if (line.trim() === '') {
        i++;
        continue;
      }
      const buf: string[] = [];
      while (i < lines.length && lines[i].trim() !== '' && !/^(```|#{1,6}\s|>\s?|\s*([-*+]|\d+\.)\s+)/.test(lines[i])) buf.push(lines[i++]);
      nodes.push(<p key={key++} className="my-2 leading-relaxed">{renderInline(buf.join(' '))}</p>);
    }
    return nodes;
  }, [source]);

  return <div className="text-sm text-foreground/90 p-3">{blocks}</div>;
}

/* ---------- 文字 / 程式碼 ---------- */

function CodeView({ text, wrap }: { text: string; wrap: boolean }) {
  const lines = useMemo(() => text.split('\n'), [text]);
  const width = String(lines.length).length;
  return (
    <div className="flex font-mono text-xs leading-relaxed rounded-md bg-card/60 border border-border/60 overflow-auto max-h-[55vh]">
      <div
        aria-hidden
        className="select-none text-right text-muted-foreground/60 px-2 py-3 border-r border-border/50 bg-muted/30 sticky left-0"
        style={{ minWidth: `${width + 2}ch` }}
      >
        {lines.map((_, i) => (
          <div key={i}>{i + 1}</div>
        ))}
      </div>
      <pre className={`p-3 flex-1 text-foreground/90 ${wrap ? 'whitespace-pre-wrap break-all' : 'whitespace-pre'}`}>{text || '(空檔案)'}</pre>
    </div>
  );
}

function CsvView({ text, delimiter }: { text: string; delimiter: string }) {
  const rows = useMemo(() => parseCsv(text, delimiter).slice(0, 500), [text, delimiter]);
  if (rows.length === 0) return <Centered>(空檔案)</Centered>;
  const [head, ...body] = rows;
  return (
    <div className="overflow-auto max-h-[55vh] rounded-md border border-border/60">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-muted/80 backdrop-blur">
          <tr>
            {head.map((c, i) => (
              <th key={i} className="text-left font-semibold px-3 py-1.5 border-b border-border whitespace-nowrap">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border/40">
          {body.map((r, ri) => (
            <tr key={ri} className="hover:bg-accent/30">
              {r.map((c, ci) => (
                <td key={ci} className="px-3 py-1 whitespace-nowrap max-w-[280px] truncate" title={c}>{c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function prettyJson(text: string): { text: string; valid: boolean } {
  try {
    return { text: JSON.stringify(JSON.parse(text), null, 2), valid: true };
  } catch {
    return { text, valid: false };
  }
}

function TextualViewer({
  item,
  remote,
  kind,
  onDownload,
}: {
  item: FsItem;
  remote: string;
  kind: FileKind;
  onDownload: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const [wrap, setWrap] = useState(kind !== 'code');
  const [rendered, setRendered] = useState(true);

  const { data, isLoading, error, refetch, isFetching } = useQuery<ReadResult>({
    queryKey: ['file-content', remote, item.path],
    queryFn: () =>
      api.request<ReadResult>('GET', `/fs/${encodeURIComponent(remote)}/read`, {
        query: { path: item.path, max_bytes: MAX_PREVIEW_BYTES },
      }),
    retry: false,
    staleTime: 30_000,
  });

  if (isLoading) return <LoadingState label="讀取文字內容中..." />;
  if (error) {
    return <ErrorState message={error instanceof Error ? error.message : '讀取失敗'} onRetry={() => void refetch()} />;
  }
  if (!data) return null;
  if (data.is_binary) {
    return <UnsupportedState item={item} kind="binary" note="此檔案內容為二進位資料，無法以文字顯示。" onDownload={onDownload} />;
  }

  const json = kind === 'json' ? prettyJson(data.content) : null;
  const displayText = json ? json.text : data.content;

  const copy = () => {
    void navigator.clipboard?.writeText(data.content).then(
      () => {
        setCopied(true);
        toast.success('已複製內容至剪貼簿');
        setTimeout(() => setCopied(false), 2000);
      },
      () => toast.error('複製失敗，瀏覽器未授權剪貼簿存取'),
    );
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          {data.encoding && <Badge variant="outline" className="text-[10px] font-mono">{data.encoding}</Badge>}
          {json && !json.valid && <Badge variant="outline" className="text-[10px] text-amber-400">JSON 格式無效，顯示原文</Badge>}
          <span>{data.content.split('\n').length} 行</span>
        </div>
        <div className="flex items-center gap-1">
          {kind === 'markdown' && (
            <Button variant={rendered ? 'secondary' : 'ghost'} size="sm" className="h-7 text-xs" onClick={() => setRendered((v) => !v)}>
              {rendered ? '檢視原始碼' : '檢視渲染'}
            </Button>
          )}
          {kind !== 'csv' && !(kind === 'markdown' && rendered) && (
            <Button variant={wrap ? 'secondary' : 'ghost'} size="sm" className="h-7 text-xs gap-1" onClick={() => setWrap((v) => !v)}>
              <WrapText className="h-3 w-3" /> 自動換行
            </Button>
          )}
          <Button variant="ghost" size="sm" onClick={copy} className="h-7 text-xs gap-1">
            {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
            {copied ? '已複製' : '複製'}
          </Button>
          {isFetching && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}
        </div>
      </div>

      {kind === 'markdown' && rendered ? (
        <div className="overflow-auto max-h-[55vh] rounded-md border border-border/60 bg-card/60">
          <MarkdownView source={data.content} />
        </div>
      ) : kind === 'csv' ? (
        <CsvView text={data.content} delimiter={getExtension(item.name) === 'tsv' ? '\t' : ','} />
      ) : (
        <CodeView text={displayText} wrap={wrap} />
      )}

      {data.truncated && (
        <div className="flex items-center gap-2 text-xs text-amber-400 bg-amber-400/10 border border-amber-400/30 rounded-md px-3 py-1.5">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          檔案過大，僅顯示前 {formatBytes(MAX_PREVIEW_BYTES)}（完整大小 {formatBytes(data.size ?? item.size)}）。
          <button type="button" className="underline ml-auto" onClick={onDownload}>下載完整檔案</button>
        </div>
      )}
    </div>
  );
}

/* ---------- 主對話框 ---------- */

export function FilePreviewDialog({ item, remote, open, onOpenChange }: FilePreviewDialogProps) {
  const [mediaError, setMediaError] = useState(false);
  const [pdfLoading, setPdfLoading] = useState(true);

  // 嘗試取得雲端節點的直鏈/下載網址 (Direct download link)
  const { data: directLinkData } = useQuery<{ url: string }>({
    queryKey: ['media-direct-link', remote, item?.path],
    queryFn: async () => {
      if (!item) return null as any;
      try {
        return await api.request<{ url: string }>('GET', `/fs/${encodeURIComponent(remote)}/link`, {
          query: { path: item.path },
        });
      } catch {
        return null as any;
      }
    },
    enabled: open && !!item,
    staleTime: 60_000,
    retry: false,
  });

  useEffect(() => {
    setMediaError(false);
    setPdfLoading(true);
  }, [item?.path, remote]);

  if (!item) return null;

  const kind = getFileKind(item.name, item.mime_type);
  // 優先使用雲端直接下載網址，若無則回退至原生的串流/重定向網址
  const src = directLinkData?.url || rawUrl(remote, item.path);
  const handleDownload = () => {
    toast.success(`開始下載 [${item.name}]...`);
    window.open(directLinkData?.url || downloadUrl(remote, item.path), '_blank');
  };

  const renderBody = () => {
    if (kind === 'image') return <ImageViewer src={src} name={item.name} />;

    if (kind === 'video' || kind === 'audio') {
      if (!isBrowserPlayable(item.name, kind)) {
        return (
          <UnsupportedState
            item={item}
            kind={kind}
            note={`瀏覽器無法原生播放 .${getExtension(item.name)} 格式，請下載後以播放器開啟。`}
            onDownload={handleDownload}
          />
        );
      }
      return (
        <ArtPlayerViewer
          key={`${remote}:${item.path}`}
          url={src}
          name={item.name}
          isAudio={kind === 'audio'}
          poster={item.thumbnail_url || ''}
        />
      );
    }

    if (kind === 'office') {
      return <OfficeViewer key={`${remote}:${item.path}`} item={item} remote={remote} />;
    }

    if (kind === 'pdf') {
      return (
        <div className="relative rounded-md overflow-hidden border border-border/60 bg-background">
          {pdfLoading && (
            <div className="absolute inset-0 flex items-center justify-center text-muted-foreground">
              <Loader2 className="h-6 w-6 animate-spin" />
            </div>
          )}
          <iframe title={item.name} src={src} onLoad={() => setPdfLoading(false)} className="w-full h-[60vh]" />
        </div>
      );
    }

    if (isTextual(kind)) {
      return <TextualViewer key={`${remote}:${item.path}`} item={item} remote={remote} kind={kind} onDownload={handleDownload} />;
    }

    const note =
      kind === 'archive'
        ? '壓縮檔無法在瀏覽器內預覽，請下載後解壓縮。'
        : undefined;
    return <UnsupportedState item={item} kind={kind} note={note} onDownload={handleDownload} />;
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl w-[95vw] max-h-[92vh] flex flex-col overflow-hidden">
        <DialogHeader>
          <div className="flex items-center gap-3 pr-6 min-w-0">
            <div className="p-2 rounded-lg bg-primary/10 shrink-0">
              <FileTypeIcon name={item.name} className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <DialogTitle className="truncate flex items-center gap-2">
                <span className="truncate">{item.name}</span>
                <Badge variant="outline" className="text-[10px] shrink-0">{FILE_KIND_LABEL[kind]}</Badge>
              </DialogTitle>
              <DialogDescription className="truncate">
                {remote}:{item.path} • {formatBytes(item.size)}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="flex-1 overflow-auto min-h-[200px]">{renderBody()}</div>

        <DialogFooter className="flex items-center justify-between sm:justify-between w-full gap-2">
          <div className="text-xs text-muted-foreground min-w-0 truncate">
            路徑: <code className="bg-muted px-1.5 py-0.5 rounded font-mono text-[11px]">{item.path}</code>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {(kind === 'image' || kind === 'pdf' || kind === 'video' || kind === 'audio') && (
              <Button variant="ghost" size="sm" onClick={() => window.open(src, '_blank')} className="gap-1.5">
                <ExternalLink className="h-3.5 w-3.5" /> 新分頁開啟
              </Button>
            )}
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
