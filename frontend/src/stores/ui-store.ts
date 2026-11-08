import { create } from 'zustand';

export type DisplayLayout = 'list' | 'grid' | 'image';
export type FilenameOverflowMode = 'ellipsis' | 'scrollable' | 'multi_line';
export type HeaderStickyMode = 'static' | 'sticky' | 'only_navbar_sticky';

interface UiState {
  theme: 'dark' | 'light';
  setTheme: (theme: 'dark' | 'light') => void;
  toggleTheme: () => void;

  sidebarCollapsed: boolean;
  setSidebarCollapsed: (collapsed: boolean) => void;
  toggleSidebar: () => void;

  viewMode: 'single' | 'dual';
  setViewMode: (mode: 'single' | 'dual') => void;

  displayLayout: DisplayLayout;
  setDisplayLayout: (layout: DisplayLayout) => void;

  /* AList local_settings equivalents */
  mainColor: string;
  setMainColor: (color: string) => void;

  checkboxOpen: boolean;
  setCheckboxOpen: (open: boolean) => void;
  toggleCheckboxOpen: () => void;

  gridItemSize: number;
  setGridItemSize: (size: number) => void;

  filenameOverflow: FilenameOverflowMode;
  setFilenameOverflow: (mode: FilenameOverflowMode) => void;

  headerStickyMode: HeaderStickyMode;
  setHeaderStickyMode: (mode: HeaderStickyMode) => void;

  readmeAutoRender: boolean;
  setReadmeAutoRender: (enabled: boolean) => void;

  localSettingsOpen: boolean;
  setLocalSettingsOpen: (open: boolean) => void;

  searchModalOpen: boolean;
  setSearchModalOpen: (open: boolean) => void;
}

const getInitialTheme = (): 'dark' | 'light' => {
  if (typeof window === 'undefined') return 'dark';
  const saved = localStorage.getItem('du.theme');
  if (saved === 'light' || saved === 'dark') return saved;
  return 'dark';
};

const getStored = <T>(key: string, fallback: T): T => {
  if (typeof window === 'undefined') return fallback;
  const val = localStorage.getItem(key);
  if (val === null) return fallback;
  try {
    return JSON.parse(val) as T;
  } catch {
    return (val as unknown as T) ?? fallback;
  }
};

export function applyMainColorVariables(hexColor: string) {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  root.style.setProperty('--alist-main', hexColor);
  // Compute rgba subtle backgrounds from hex
  const clean = hexColor.replace('#', '');
  if (clean.length === 6) {
    const r = parseInt(clean.slice(0, 2), 16);
    const g = parseInt(clean.slice(2, 4), 16);
    const b = parseInt(clean.slice(4, 6), 16);
    if (!Number.isNaN(r) && !Number.isNaN(g) && !Number.isNaN(b)) {
      root.style.setProperty('--alist-main-subtle', `rgba(${r}, ${g}, ${b}, 0.15)`);
      root.style.setProperty('--alist-main-subtle-hover', `rgba(${r}, ${g}, ${b}, 0.24)`);
    }
  }
}

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

  viewMode: getStored<'single' | 'dual'>('du.viewMode', 'single'),
  setViewMode: (viewMode) => {
    localStorage.setItem('du.viewMode', JSON.stringify(viewMode));
    set({ viewMode });
  },

  displayLayout: getStored<DisplayLayout>('du.displayLayout', 'list'),
  setDisplayLayout: (displayLayout) => {
    localStorage.setItem('du.displayLayout', JSON.stringify(displayLayout));
    set({ displayLayout });
  },

  mainColor: getStored<string>('du.mainColor', '#1890ff'),
  setMainColor: (mainColor) => {
    localStorage.setItem('du.mainColor', JSON.stringify(mainColor));
    applyMainColorVariables(mainColor);
    set({ mainColor });
  },

  checkboxOpen: getStored<boolean>('du.checkboxOpen', false),
  setCheckboxOpen: (checkboxOpen) => {
    localStorage.setItem('du.checkboxOpen', JSON.stringify(checkboxOpen));
    set({ checkboxOpen });
  },
  toggleCheckboxOpen: () =>
    set((state) => {
      const next = !state.checkboxOpen;
      localStorage.setItem('du.checkboxOpen', JSON.stringify(next));
      return { checkboxOpen: next };
    }),

  gridItemSize: getStored<number>('du.gridItemSize', 90),
  setGridItemSize: (gridItemSize) => {
    localStorage.setItem('du.gridItemSize', JSON.stringify(gridItemSize));
    set({ gridItemSize });
  },

  filenameOverflow: getStored<FilenameOverflowMode>('du.filenameOverflow', 'ellipsis'),
  setFilenameOverflow: (filenameOverflow) => {
    localStorage.setItem('du.filenameOverflow', JSON.stringify(filenameOverflow));
    set({ filenameOverflow });
  },

  headerStickyMode: getStored<HeaderStickyMode>('du.headerStickyMode', 'sticky'),
  setHeaderStickyMode: (headerStickyMode) => {
    localStorage.setItem('du.headerStickyMode', JSON.stringify(headerStickyMode));
    set({ headerStickyMode });
  },

  readmeAutoRender: getStored<boolean>('du.readmeAutoRender', true),
  setReadmeAutoRender: (readmeAutoRender) => {
    localStorage.setItem('du.readmeAutoRender', JSON.stringify(readmeAutoRender));
    set({ readmeAutoRender });
  },

  localSettingsOpen: false,
  setLocalSettingsOpen: (localSettingsOpen) => set({ localSettingsOpen }),

  searchModalOpen: false,
  setSearchModalOpen: (searchModalOpen) => set({ searchModalOpen }),
}));

export const useUIStore = useUiStore;
