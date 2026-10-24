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
  image: { Icon: ImageIcon, color: 'text-[var(--alist-main)]' },
  video: { Icon: FileVideo, color: 'text-[var(--alist-main)]' },
  audio: { Icon: FileAudio, color: 'text-[var(--alist-main)]' },
  pdf: { Icon: FileText, color: 'text-[var(--alist-main)]' },
  markdown: { Icon: FileText, color: 'text-[var(--alist-main)]' },
  json: { Icon: FileJson, color: 'text-[var(--alist-main)]' },
  csv: { Icon: FileSpreadsheet, color: 'text-[var(--alist-main)]' },
  code: { Icon: FileCode, color: 'text-[var(--alist-main)]' },
  text: { Icon: FileText, color: 'text-[var(--alist-main)]' },
  archive: { Icon: FileArchive, color: 'text-[var(--alist-main)]' },
  office: { Icon: Presentation, color: 'text-[var(--alist-main)]' },
  binary: { Icon: FileIcon, color: 'text-[var(--alist-main)]' },
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
    return (
      <Folder
        className={cn(
          'h-5 w-5 text-[var(--alist-main)] shrink-0 fill-[var(--alist-main)]/20',
          className,
        )}
      />
    );
  }
  const kind = getFileKind(name);
  let { Icon, color } = KIND_STYLE[kind];
  const ext = getExtension(name);
  if (kind === 'office' && /^xls|^ods/.test(ext)) {
    Icon = FileSpreadsheet;
  } else if (kind === 'office' && /^doc|^odt/.test(ext)) {
    Icon = FileText;
  }
  return <Icon className={cn('h-5 w-5 shrink-0', color, className)} />;
}
