import type { ApiTransport, EventSubscription, HttpMethod, RequestOptions, UploadProgress } from '../transport';
import { mockRouter } from './router';
import { sseSimulator } from './sse-simulator';

export class MockTransport implements ApiTransport {
  async request<T>(method: HttpMethod, path: string, options?: RequestOptions): Promise<T> {
    return mockRouter.handle<T>(method, path, options);
  }

  async upload<T>(
    path: string,
    formData: FormData,
    onProgress?: (progress: UploadProgress) => void,
    signal?: AbortSignal,
  ): Promise<T> {
    const file = formData.get('file') as File | null;
    const targetDir = (formData.get('target_dir') as string) || '/';
    const total = file?.size || 1024 * 512;
    let loaded = 0;

    // Simulate progress in chunks
    const steps = 5;
    for (let i = 1; i <= steps; i++) {
      if (signal?.aborted) {
        throw new DOMException('Upload aborted', 'AbortError');
      }
      await new Promise((r) => setTimeout(r, 120));
      loaded = Math.min(total, Math.round((total / steps) * i));
      onProgress?.({
        loaded,
        total,
        percent: Math.round((loaded / total) * 100),
      });
    }

    const filename = file?.name || 'uploaded_file.bin';
    const remote = path.split('/')[2] || 'local';
    const filePath = targetDir === '/' ? `/${filename}` : `${targetDir}/${filename}`;

    const items = mockRouter.db.files[remote] || (mockRouter.db.files[remote] = []);
    items.push({
      name: filename,
      path: filePath,
      is_dir: false,
      size: total,
      modified_at: new Date().toISOString(),
    });

    return {
      status: 'uploaded',
      remote,
      path: filePath,
      size: total,
    } as T;
  }

  subscribeEvents(
    onMessage: (event: string, data: unknown, id?: string) => void,
    onError?: (error: Error) => void,
    lastEventId?: string,
  ): EventSubscription {
    return sseSimulator.subscribe(onMessage, onError, lastEventId);
  }
}

export const mockTransport = new MockTransport();
