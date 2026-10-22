import { create } from 'zustand';

interface UiState {
  theme: 'dark' | 'light';
  setTheme: (theme: 'dark' | 'light') => void;
  toggleTheme: () => void;
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (collapsed: boolean) => void;
  toggleSidebar: () => void;
  viewMode: 'single' | 'dual';
  setViewMode: (mode: 'single' | 'dual') => void;
  displayLayout: 'list' | 'grid';
  setDisplayLayout: (layout: 'list' | 'grid') => void;
}

const getInitialTheme = (): 'dark' | 'light' => {
  if (typeof window === 'undefined') return 'dark';
  const saved = localStorage.getItem('du.theme');
  if (saved === 'light' || saved === 'dark') return saved;
  return 'dark'; // Dark mode by default
};

export const useUiStore = create<UiState>((set) => ({
  theme: getInitialTheme(),
  setTheme: (theme) => {
    localStorage.setItem('du.theme', theme);
    if (typeof document !== 'undefined') {
      if (theme === 'dark') {
        document.documentElement.classList.add('dark');
      } else {
        document.documentElement.classList.remove('dark');
      }
    }
    set({ theme });
  },
  toggleTheme: () => {
    set((state) => {
      const next = state.theme === 'dark' ? 'light' : 'dark';
      localStorage.setItem('du.theme', next);
      if (typeof document !== 'undefined') {
        if (next === 'dark') {
          document.documentElement.classList.add('dark');
        } else {
          document.documentElement.classList.remove('dark');
        }
      }
      return { theme: next };
    });
  },
  sidebarCollapsed: false,
  setSidebarCollapsed: (sidebarCollapsed) => set({ sidebarCollapsed }),
  toggleSidebar: () => set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
  viewMode: 'single',
  setViewMode: (viewMode) => set({ viewMode }),
  displayLayout: 'list',
  setDisplayLayout: (displayLayout) => set({ displayLayout }),
}));

export const useUIStore = useUiStore;
