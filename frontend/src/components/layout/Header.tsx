import { UploadCloud, Sparkles, Database } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { ThemeToggle } from './ThemeToggle';
import { isDemoMode, setDemoMode } from '@/api';
import { useTransferQueue } from '@/stores/transfer-queue';
import { zhTW } from '@/i18n/zh-TW';
import { Badge } from '@/components/ui/badge';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

export function Header() {
  const location = useLocation();
  const { jobs, setDrawerOpen } = useTransferQueue();

  const activeUploads = jobs.filter((j) => j.status === 'uploading' || j.status === 'pending').length;

  const getPageTitle = (pathname: string) => {
    switch (pathname) {
      case '/':
        return zhTW.nav.dashboard;
      case '/remotes':
        return zhTW.nav.remotes;
      case '/files':
        return zhTW.nav.files;
      case '/sync':
        return zhTW.nav.sync;
      case '/schedule':
        return zhTW.nav.schedule;
      case '/settings':
        return zhTW.nav.settings;
      default:
        return '控制台';
    }
  };

  return (
    <header className="flex h-16 items-center justify-between border-b border-border bg-card/40 backdrop-blur-md px-6 z-20">
      {/* Title & Breadcrumbs */}
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold text-foreground tracking-tight">{getPageTitle(location.pathname)}</h1>
      </div>

      {/* Right controls */}
      <div className="flex items-center gap-3">
        {/* Demo Mode Pill */}
        <TooltipProvider delayDuration={200}>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={() => setDemoMode(!isDemoMode)}
                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium cursor-pointer transition-colors border ${
                  isDemoMode
                    ? 'bg-amber-500/10 text-amber-400 border-amber-500/30 hover:bg-amber-500/20'
                    : 'bg-secondary/80 text-muted-foreground border-border hover:bg-secondary'
                }`}
              >
                {isDemoMode ? <Sparkles className="h-3 w-3" /> : <Database className="h-3 w-3" />}
                <span>{isDemoMode ? 'Demo 模式 (已啟用)' : '正式環境模式'}</span>
              </button>
            </TooltipTrigger>
            <TooltipContent side="bottom">
              <p>{isDemoMode ? '點擊切換至真實後端 API 模式' : '點擊切換為純前端 Mock 資料模式'}</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>

        {/* Transfer Queue Trigger */}
        <TooltipProvider delayDuration={200}>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setDrawerOpen(true)}
                className="relative flex items-center gap-2 border-border"
              >
                <UploadCloud className="h-4 w-4 text-muted-foreground" />
                <span className="hidden sm:inline text-xs">傳輸佇列</span>
                {activeUploads > 0 && (
                  <Badge variant="default" className="h-4 min-w-4 px-1 text-[10px] flex items-center justify-center">
                    {activeUploads}
                  </Badge>
                )}
              </Button>
            </TooltipTrigger>
            <TooltipContent side="bottom">
              <p>檢視目前上傳與佇列進度</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>

        <ThemeToggle />
      </div>
    </header>
  );
}
