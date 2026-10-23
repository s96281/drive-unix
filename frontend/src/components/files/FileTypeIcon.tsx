import {
  File as FileIcon,
  FileArchive,
  FileAudio,
  FileCode,
  FileJson,
  FileSpreadsheet,
  FileText,
  FileVideo,
  Image as ImageIcon,
  Presentation,
  Folder,
} from 'lucide-react';
import { getExtension, getFileKind, type FileKind } from '@/lib/file-types';
import { cn } from '@/lib/utils';

const KIND_STYLE: Record<FileKind, { Icon: typeof FileIcon; color: string }> = {
  image: { Icon: ImageIcon, color: 'text-emerald-400' },
  video: { Icon: FileVideo, color: 'text-fuchsia-400' },
  audio: { Icon: FileAudio, color: 'text-pink-400' },
  pdf: { Icon: FileText, color: 'text-red-400' },
  markdown: { Icon: FileText, color: 'text-sky-400' },
  json: { Icon: FileJson, color: 'text-yellow-400' },
  csv: { Icon: FileSpreadsheet, color: 'text-green-400' },
  code: { Icon: FileCode, color: 'text-violet-400' },
  text: { Icon: FileText, color: 'text-sky-400' },
  archive: { Icon: FileArchive, color: 'text-orange-400' },
  office: { Icon: Presentation, color: 'text-blue-400' },
  binary: { Icon: FileIcon, color: 'text-muted-foreground' },
};

export function kindStyle(kind: FileKind) {
  return KIND_STYLE[kind];
}

interface Props {
  name: string;
  isDir?: boolean;
  className?: string;
}

export function FileTypeIcon({ name, isDir, className }: Props) {
  if (isDir) {
    return <Folder className={cn('h-4 w-4 text-amber-400 shrink-0 fill-amber-400/20', className)} />;
  }
  const kind = getFileKind(name);
  let { Icon, color } = KIND_STYLE[kind];
  const ext = getExtension(name);
  if (kind === 'office' && /^xls|^ods/.test(ext)) {
    Icon = FileSpreadsheet;
    color = 'text-green-400';
  } else if (kind === 'office' && /^doc|^odt/.test(ext)) {
    Icon = FileText;
  }
  return <Icon className={cn('h-4 w-4 shrink-0', color, className)} />;
}
