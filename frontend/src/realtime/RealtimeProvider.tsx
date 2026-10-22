import React, { createContext, useContext, useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { eventStream, type ConnectionStatus } from './event-stream';
import { useActivityStore } from './activity-store';
import type { TaskRecord } from '../api/types';

interface RealtimeContextValue {
  status: ConnectionStatus;
}

const RealtimeContext = createContext<RealtimeContextValue>({ status: 'connected' });

export function RealtimeProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<ConnectionStatus>(eventStream.getStatus());
  const queryClient = useQueryClient();
  const addActivity = useActivityStore((state) => state.addEvent);

  useEffect(() => {
    const unsubStatus = eventStream.onStatusChange((newStatus) => {
      setStatus(newStatus);
    });

    const unsubMsg = eventStream.onMessage((event, data) => {
      const ts = Date.now() / 1000;

      if (event === 'task.update') {
        const task = data as TaskRecord;
        queryClient.invalidateQueries({ queryKey: ['tasks'] });

        if (task.status === 'completed') {
          toast.success(`任務已完成：${task.title}`);
        } else if (task.status === 'failed') {
          toast.error(`任務失敗：${task.title}`, {
            description: task.message,
          });
        }
      }

      if (event === 'task.log') {
        const logData = data as { task_id: string; level: string; message: string; target?: string };
        addActivity({
          type: 'task.log',
          level: logData.level || 'INFO',
          message: logData.message || `[Task] ${logData.target || ''}`,
          data: logData,
          timestamp: ts,
        });
      }

      if (event === 'log') {
        const logData = data as { level: string; message: string; logger?: string };
        addActivity({
          type: 'log',
          level: logData.level || 'INFO',
          message: logData.message,
          data: logData,
          timestamp: ts,
        });
      }

      if (event === 'system') {
        const sysData = data as { topic: string; action: string; [k: string]: unknown };
        addActivity({
          type: 'system',
          level: 'INFO',
          message: `[系統變更] ${sysData.topic} -> ${sysData.action}`,
          data: sysData,
          timestamp: ts,
        });

        // Invalidate corresponding TanStack query cache
        if (sysData.topic === 'remotes') {
          queryClient.invalidateQueries({ queryKey: ['remotes'] });
        } else if (sysData.topic === 'schedule') {
          queryClient.invalidateQueries({ queryKey: ['schedules'] });
        } else if (sysData.topic === 'daemon') {
          queryClient.invalidateQueries({ queryKey: ['daemon'] });
        } else if (sysData.topic === 'settings') {
          queryClient.invalidateQueries({ queryKey: ['settings'] });
        } else if (sysData.topic === 'files') {
          queryClient.invalidateQueries({ queryKey: ['files'] });
        } else if (sysData.topic === 'upstash') {
          queryClient.invalidateQueries({ queryKey: ['upstash'] });
        }
      }

      if (event === 'resync') {
        queryClient.invalidateQueries();
      }
    });

    return () => {
      unsubStatus();
      unsubMsg();
    };
  }, [queryClient, addActivity]);

  return <RealtimeContext.Provider value={{ status }}>{children}</RealtimeContext.Provider>;
}

export function useRealtime() {
  return useContext(RealtimeContext);
}
