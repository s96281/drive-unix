import { create } from 'zustand';
import { api } from '../api';
import type { UploadProgress } from '../api/transport';

export interface LocalUploadJob {
  id: string;
  remote: string;
  targetDir: string;
  file: File;
  status: 'pending' | 'uploading' | 'completed' | 'failed' | 'cancelled';
  progress: UploadProgress;
  error?: string;
  abortController?: AbortController;
}

interface TransferQueueState {
  jobs: LocalUploadJob[];
  isDrawerOpen: boolean;
  setDrawerOpen: (open: boolean) => void;
  enqueue: (remote: string, targetDir: string, files: File[]) => void;
  cancelJob: (id: string) => void;
  clearCompleted: () => void;
  startNext: () => void;
}

export const useTransferQueue = create<TransferQueueState>((set, get) => ({
  jobs: [],
  isDrawerOpen: false,
  setDrawerOpen: (open) => set({ isDrawerOpen: open }),

  enqueue: (remote, targetDir, files) => {
    const newJobs: LocalUploadJob[] = files.map((file) => ({
      id: `up-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,
      remote,
      targetDir,
      file,
      status: 'pending',
      progress: { loaded: 0, total: file.size, percent: 0 },
    }));

    set((state) => ({
      jobs: [...newJobs, ...state.jobs],
      isDrawerOpen: true,
    }));

    get().startNext();
  },

  startNext: () => {
    const { jobs } = get();
    const uploadingCount = jobs.filter((j) => j.status === 'uploading').length;
    const maxConcurrent = 2; // Process 2 uploads concurrently

    if (uploadingCount >= maxConcurrent) return;

    const pendingJob = jobs.find((j) => j.status === 'pending');
    if (!pendingJob) return;

    const abortController = new AbortController();

    set((state) => ({
      jobs: state.jobs.map((j) => (j.id === pendingJob.id ? { ...j, status: 'uploading', abortController } : j)),
    }));

    const formData = new FormData();
    formData.append('file', pendingJob.file);
    formData.append('target_dir', pendingJob.targetDir);

    api
      .upload(
        `/fs/${pendingJob.remote}/upload`,
        formData,
        (progress) => {
          set((state) => ({
            jobs: state.jobs.map((j) => (j.id === pendingJob.id ? { ...j, progress } : j)),
          }));
        },
        abortController.signal,
      )
      .then(() => {
        set((state) => ({
          jobs: state.jobs.map((j) =>
            j.id === pendingJob.id
              ? { ...j, status: 'completed', progress: { ...j.progress, loaded: j.file.size, percent: 100 } }
              : j,
          ),
        }));
      })
      .catch((err) => {
        if (err.name === 'AbortError') {
          set((state) => ({
            jobs: state.jobs.map((j) => (j.id === pendingJob.id ? { ...j, status: 'cancelled' } : j)),
          }));
        } else {
          set((state) => ({
            jobs: state.jobs.map((j) =>
              j.id === pendingJob.id ? { ...j, status: 'failed', error: err.message || '上傳失敗' } : j,
            ),
          }));
        }
      })
      .finally(() => {
        get().startNext();
      });
  },

  cancelJob: (id) => {
    const job = get().jobs.find((j) => j.id === id);
    if (job?.abortController) {
      job.abortController.abort();
    }
    set((state) => ({
      jobs: state.jobs.map((j) => (j.id === id ? { ...j, status: 'cancelled' } : j)),
    }));
    get().startNext();
  },

  clearCompleted: () => {
    set((state) => ({
      jobs: state.jobs.filter((j) => j.status !== 'completed' && j.status !== 'cancelled'),
    }));
  },
}));

export const useTransferQueueStore = useTransferQueue;
