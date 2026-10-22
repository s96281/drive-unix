import { useRealtime } from '@/realtime/RealtimeProvider';
import { zhTW } from '@/i18n/zh-TW';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

export function ConnectionIndicator() {
  const { status } = useRealtime();

  const config = {
    connected: {
      color: 'bg-emerald-500',
      text: zhTW.app.connected,
      pulse: 'animate-pulse',
    },
    reconnecting: {
      color: 'bg-amber-500',
      text: zhTW.app.reconnecting,
      pulse: 'animate-ping',
    },
    disconnected: {
      color: 'bg-rose-500',
      text: zhTW.app.disconnected,
      pulse: '',
    },
  }[status];

  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-full bg-secondary/60 hover:bg-secondary text-xs cursor-default transition-colors">
            <span className="relative flex h-2 w-2">
              {status === 'connected' && (
                <span className={`absolute inline-flex h-full w-full rounded-full opacity-75 ${config.color} ${config.pulse}`} />
              )}
              <span className={`relative inline-flex rounded-full h-2 w-2 ${config.color}`} />
            </span>
            <span className="text-muted-foreground font-mono">{config.text}</span>
          </div>
        </TooltipTrigger>
        <TooltipContent side="bottom">
          <p>SSE 即時事件串流 (/api/events)</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
