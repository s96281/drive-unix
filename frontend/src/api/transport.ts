export class ApiError extends Error {
  constructor(
    public status: number,
    public message: string,
    public detail?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';

export interface RequestOptions {
  query?: Record<string, string | number | boolean | null | undefined>;
  body?: unknown;
  signal?: AbortSignal;
  headers?: Record<string, string>;
}

export interface UploadProgress {
  loaded: number;
  total: number;
  percent: number;
}

export interface EventSubscription {
  close: () => void;
}

export interface ApiTransport {
  request<T>(method: HttpMethod, path: string, options?: RequestOptions): Promise<T>;
  upload<T>(
    path: string,
    formData: FormData,
    onProgress?: (progress: UploadProgress) => void,
    signal?: AbortSignal,
  ): Promise<T>;
  subscribeEvents(
    onMessage: (event: string, data: unknown, id?: string) => void,
    onError?: (error: Error) => void,
    lastEventId?: string,
  ): EventSubscription;
}
