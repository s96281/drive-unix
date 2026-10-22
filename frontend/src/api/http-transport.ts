import { ApiError, type ApiTransport, type EventSubscription, type HttpMethod, type RequestOptions, type UploadProgress } from './transport';

export class HttpTransport implements ApiTransport {
  constructor(private baseUrl: string = '/api') {}

  private buildUrl(path: string, query?: Record<string, string | number | boolean | null | undefined>): string {
    const cleanPath = path.startsWith('/') ? path : `/${path}`;
    const url = new URL(`${this.baseUrl}${cleanPath}`, window.location.origin);

    if (query) {
      for (const [key, val] of Object.entries(query)) {
        if (val != null) {
          url.searchParams.append(key, String(val));
        }
      }
    }
    return url.toString();
  }

  async request<T>(method: HttpMethod, path: string, options: RequestOptions = {}): Promise<T> {
    const url = this.buildUrl(path, options.query);
    const headers: Record<string, string> = {
      Accept: 'application/json',
      ...options.headers,
    };

    let body: BodyInit | undefined = undefined;
    if (options.body != null) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(options.body);
    }

    let response: Response;
    try {
      response = await fetch(url, {
        method,
        headers,
        body,
        signal: options.signal,
      });
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        throw err;
      }
      throw new ApiError(0, err instanceof Error ? err.message : '網路請求失敗，請檢查連線');
    }

    if (!response.ok) {
      let detailMsg = `HTTP 錯誤 ${response.status}: ${response.statusText}`;
      let detailObj: unknown = null;
      try {
        const json = await response.json();
        detailObj = json;
        if (typeof json.detail === 'string') {
          detailMsg = json.detail;
        } else if (Array.isArray(json.detail)) {
          detailMsg = json.detail.map((d: { msg?: string }) => d.msg || '').join(', ');
        }
      } catch {
        // Response wasn't JSON
      }
      throw new ApiError(response.status, detailMsg, detailObj);
    }

    if (response.status === 204) {
      return {} as T;
    }

    return response.json() as Promise<T>;
  }

  upload<T>(
    path: string,
    formData: FormData,
    onProgress?: (progress: UploadProgress) => void,
    signal?: AbortSignal,
  ): Promise<T> {
    const url = this.buildUrl(path);

    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', url);
      xhr.responseType = 'json';

      if (signal) {
        signal.addEventListener('abort', () => {
          xhr.abort();
          reject(new DOMException('Upload aborted', 'AbortError'));
        });
      }

      if (onProgress && xhr.upload) {
        xhr.upload.onprogress = (event) => {
          if (event.lengthComputable) {
            onProgress({
              loaded: event.loaded,
              total: event.total,
              percent: Math.round((event.loaded / event.total) * 100),
            });
          }
        };
      }

      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve(xhr.response as T);
        } else {
          const detail = xhr.response?.detail || xhr.statusText || '上傳失敗';
          reject(new ApiError(xhr.status, typeof detail === 'string' ? detail : JSON.stringify(detail), xhr.response));
        }
      };

      xhr.onerror = () => {
        reject(new ApiError(0, '網路傳輸錯誤，無法上傳檔案'));
      };

      xhr.send(formData);
    });
  }

  subscribeEvents(
    onMessage: (event: string, data: unknown, id?: string) => void,
    onError?: (error: Error) => void,
    lastEventId?: string,
  ): EventSubscription {
    const params = new URLSearchParams();
    if (lastEventId) {
      params.append('last_event_id', lastEventId);
    }

    const queryStr = params.toString() ? `?${params.toString()}` : '';
    const sseUrl = `${this.baseUrl}/events${queryStr}`;
    const es = new EventSource(sseUrl);

    const eventNames = ['hello', 'task.update', 'task.log', 'log', 'system', 'heartbeat', 'resync'];

    for (const name of eventNames) {
      es.addEventListener(name, (e: MessageEvent) => {
        try {
          const parsed = JSON.parse(e.data);
          onMessage(name, parsed, e.lastEventId);
        } catch {
          onMessage(name, e.data, e.lastEventId);
        }
      });
    }

    es.onerror = (e) => {
      if (onError) {
        onError(new Error('SSE 連線發生中斷，正在自動重試'));
      }
    };

    return {
      close: () => es.close(),
    };
  }
}
