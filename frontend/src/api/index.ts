import { HttpTransport } from './http-transport';
import { mockTransport } from './mock/mock-transport';
import type { ApiTransport } from './transport';

function detectDemoMode(): boolean {
  if (typeof window === 'undefined') return false;

  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.get('demo') === '1' || urlParams.get('demo') === 'true') {
    return true;
  }

  const stored = localStorage.getItem('du.demo_mode');
  if (stored === 'true') {
    return true;
  }

  if (import.meta.env.MODE === 'mock' || import.meta.env.VITE_API_MODE === 'mock') {
    return true;
  }

  return false;
}

export const isDemoMode = detectDemoMode();
export const api: ApiTransport = isDemoMode ? mockTransport : new HttpTransport('/api');

export function setDemoMode(enable: boolean) {
  if (enable) {
    localStorage.setItem('du.demo_mode', 'true');
  } else {
    localStorage.removeItem('du.demo_mode');
  }
  window.location.reload();
}

export * from './types';
export * from './transport';
