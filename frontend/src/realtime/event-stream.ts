import { api } from '../api';
import type { EventSubscription } from '../api/transport';

export type ConnectionStatus = 'connected' | 'reconnecting' | 'disconnected';

export class EventStreamCoordinator {
  private subscription: EventSubscription | null = null;
  private status: ConnectionStatus = 'disconnected';
  private statusListeners = new Set<(status: ConnectionStatus) => void>();
  private messageListeners = new Set<(event: string, data: unknown, id?: string) => void>();
  private retryAttempt = 0;
  private retryTimeout: number | null = null;
  private heartbeatTimeout: number | null = null;
  private lastEventId: string | undefined = undefined;
  private isDestroyed = false;

  constructor() {
    this.connect();
    this.bindWindowEvents();
  }

  public getStatus(): ConnectionStatus {
    return this.status;
  }

  public onStatusChange(callback: (status: ConnectionStatus) => void): () => void {
    this.statusListeners.add(callback);
    callback(this.status);
    return () => this.statusListeners.delete(callback);
  }

  public onMessage(callback: (event: string, data: unknown, id?: string) => void): () => void {
    this.messageListeners.add(callback);
    return () => this.messageListeners.delete(callback);
  }

  private setStatus(newStatus: ConnectionStatus) {
    if (this.status !== newStatus) {
      this.status = newStatus;
      for (const listener of this.statusListeners) {
        listener(newStatus);
      }
    }
  }

  private connect() {
    if (this.isDestroyed) return;
    this.cleanupSubscription();

    this.subscription = api.subscribeEvents(
      (event, data, id) => {
        this.resetHeartbeatWatchdog();
        this.setStatus('connected');
        this.retryAttempt = 0;

        if (id) {
          this.lastEventId = id;
        }

        for (const listener of this.messageListeners) {
          try {
            listener(event, data, id);
          } catch (err) {
            console.error('EventStream listener error:', err);
          }
        }
      },
      () => {
        this.handleDisconnect();
      },
      this.lastEventId,
    );

    this.resetHeartbeatWatchdog();
  }

  private handleDisconnect() {
    if (this.isDestroyed) return;
    this.cleanupSubscription();
    this.setStatus('reconnecting');

    // Exponential backoff with jitter: 1s, 2s, 4s, 8s, up to 30s
    this.retryAttempt++;
    const baseDelay = Math.min(30000, 1000 * Math.pow(1.8, Math.min(this.retryAttempt, 6)));
    const jitter = Math.random() * 500;
    const delay = Math.round(baseDelay + jitter);

    if (this.retryTimeout) clearTimeout(this.retryTimeout);
    this.retryTimeout = window.setTimeout(() => {
      this.connect();
    }, delay);
  }

  private resetHeartbeatWatchdog() {
    if (this.heartbeatTimeout) clearTimeout(this.heartbeatTimeout);
    // If no message or heartbeat received in 45s, reconnect
    this.heartbeatTimeout = window.setTimeout(() => {
      console.warn('SSE Heartbeat watchdog timeout (45s). Reconnecting...');
      this.handleDisconnect();
    }, 45000);
  }

  private bindWindowEvents() {
    if (typeof window === 'undefined') return;

    window.addEventListener('online', () => {
      console.log('Network online. Reconnecting SSE...');
      this.retryAttempt = 0;
      this.connect();
    });

    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible' && this.status !== 'connected') {
        this.retryAttempt = 0;
        this.connect();
      }
    });
  }

  private cleanupSubscription() {
    if (this.subscription) {
      try {
        this.subscription.close();
      } catch {}
      this.subscription = null;
    }
    if (this.heartbeatTimeout) {
      clearTimeout(this.heartbeatTimeout);
      this.heartbeatTimeout = null;
    }
  }

  public destroy() {
    this.isDestroyed = true;
    this.cleanupSubscription();
    if (this.retryTimeout) clearTimeout(this.retryTimeout);
    this.statusListeners.clear();
    this.messageListeners.clear();
  }
}

export const eventStream = new EventStreamCoordinator();
