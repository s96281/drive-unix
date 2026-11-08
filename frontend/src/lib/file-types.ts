/**
 * 檔案類別判定：供檔案列表圖示與預覽對話框共用。
 */

export type FileKind =
  | 'image'
  | 'video'
  | 'audio'
  | 'pdf'
  | 'markdown'
  | 'json'
  | 'csv'
  | 'code'
  | 'text'
  | 'archive'
  | 'office'
  | 'binary';

const EXT_MAP: Record<Exclude<FileKind, 'binary' | 'text'>, string[]> = {
  image: ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'ico', 'avif'],
  video: ['mp4', 'webm', 'mov', 'm4v', 'ogv', 'mkv'],
  audio: ['mp3', 'wav', 'ogg', 'oga', 'm4a', 'flac', 'aac', 'opus'],
  pdf: ['pdf'],
  markdown: ['md', 'markdown', 'mdx'],
  json: ['json', 'jsonc', 'geojson'],
  csv: ['csv', 'tsv'],
  code: [
    'py', 'js', 'mjs', 'cjs', 'ts', 'tsx', 'jsx', 'html', 'htm', 'css', 'scss', 'xml',
    'yaml', 'yml', 'toml', 'ini', 'sh', 'bash', 'zsh', 'bat', 'ps1', 'sql', 'c', 'h',
    'cpp', 'hpp', 'cs', 'java', 'go', 'rs', 'rb', 'php', 'swift', 'kt', 'lua', 'vue',
    'dockerfile', 'conf', 'cfg', 'env',
  ],
  archive: ['zip', 'rar', '7z', 'tar', 'gz', 'tgz', 'bz2', 'xz', 'zst'],
  office: ['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods', 'odp'],
};

const TEXT_EXTS = ['txt', 'log', 'text', 'rtf', 'nfo', 'srt', 'vtt', 'gitignore', 'lock'];

const EXT_LOOKUP: Map<string, FileKind> = (() => {
  const m = new Map<string, FileKind>();
  for (const [kind, exts] of Object.entries(EXT_MAP)) {
    for (const e of exts) m.set(e, kind as FileKind);
  }
  for (const e of TEXT_EXTS) m.set(e, 'text');
  return m;
})();

export function getExtension(name: string): string {
  const base = name.split('/').pop() ?? name;
  const idx = base.lastIndexOf('.');
  if (idx <= 0) return idx === 0 ? base.slice(1).toLowerCase() : base.toLowerCase();
  return base.slice(idx + 1).toLowerCase();
}

export function getFileKind(name: string, mime?: string | null): FileKind {
  const ext = getExtension(name);
  const byExt = EXT_LOOKUP.get(ext);
  if (byExt) return byExt;

  if (mime) {
    if (mime.startsWith('image/')) return 'image';
    if (mime.startsWith('video/')) return 'video';
    if (mime.startsWith('audio/')) return 'audio';
    if (mime === 'application/pdf') return 'pdf';
    if (mime === 'application/json') return 'json';
    if (mime.startsWith('text/')) return 'text';
  }
  const lower = name.toLowerCase();
  if (lower === 'makefile' || lower === 'dockerfile' || lower === 'readme' || lower === 'license') {
    return 'text';
  }
  return 'binary';
}

/** 瀏覽器原生可解碼的影音格式（mkv 等僅能提示下載）。 */
export function isBrowserPlayable(name: string, kind: FileKind): boolean {
  const ext = getExtension(name);
  if (kind === 'video') return ['mp4', 'webm', 'mov', 'm4v', 'ogv'].includes(ext);
  return kind === 'audio';
}

export const FILE_KIND_LABEL: Record<FileKind, string> = {
  image: '圖片',
  video: '影片',
  audio: '音訊',
  pdf: 'PDF 文件',
  markdown: 'Markdown',
  json: 'JSON',
  csv: '表格資料',
  code: '程式碼 / 設定檔',
  text: '純文字',
  archive: '壓縮檔',
  office: 'Office 文件',
  binary: '二進位檔案',
};

/** 需透過 /read 讀取文字內容的類別 */
export function isTextual(kind: FileKind): boolean {
  return kind === 'markdown' || kind === 'json' || kind === 'csv' || kind === 'code' || kind === 'text';
}

export function rawUrl(remote: string, path: string, redirect: boolean = true): string {
  const redirectParam = redirect ? '&redirect=true' : '&redirect=false';
  return `/api/fs/${encodeURIComponent(remote)}/raw?path=${encodeURIComponent(path)}${redirectParam}`;
}

export function downloadUrl(remote: string, path: string): string {
  return `/api/fs/${encodeURIComponent(remote)}/download?path=${encodeURIComponent(path)}`;
}

/** 取得完整的外部可存取 URL（供 Office Web Viewer 使用，若為相對路徑則補上 origin） */
export function absoluteDownloadUrl(remote: string, path: string): string {
  const rel = downloadUrl(remote, path);
  if (typeof window !== 'undefined' && window.location) {
    return new URL(rel, window.location.origin).toString();
  }
  return rel;
}

/** 取得 Microsoft Office Online Viewer 預覽連結 */
export function officeViewerUrl(fileUrl: string): string {
  return `https://view.officeapps.live.com/op/view.aspx?src=${encodeURIComponent(fileUrl)}`;
}

/** 簡易 CSV 解析（支援引號與跳脫） */
export function parseCsv(text: string, delimiter = ','): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (inQuotes) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        cell += ch;
      }
    } else if (ch === '"') {
      inQuotes = true;
    } else if (ch === delimiter) {
      row.push(cell);
      cell = '';
    } else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && text[i + 1] === '\n') i++;
      row.push(cell);
      cell = '';
      rows.push(row);
      row = [];
    } else {
      cell += ch;
    }
  }
  if (cell !== '' || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }
  return rows;
}
