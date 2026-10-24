import React, { useState } from 'react';
import { Outlet, Link, useLocation } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { TransferQueueDrawer } from './TransferQueueDrawer';
import { LocalSettingsDrawer } from './LocalSettingsDrawer';
import { useUiStore } from '@/stores/ui-store';
import { Toaster } from 'sonner';

export function AppShell() {
  const location = useLocation();
  const theme = useUiStore((s) => s.theme);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // Determine whether current route belongs to AList Front-stage (Home) or Back-stage (@manage)
  const isHomeView = location.pathname === '/' || location.pathname === '/files';

  return (
    <div className="min-h-screen w-full bg-background text-foreground flex flex-col">
      {isHomeView ? (
        /* ========== AList Home Layout (Front-stage File Explorer) ========== */
        <div className="flex flex-col min-h-screen w-full items-center">
          <Header mode="home" />

          <main className="flex-1 w-full flex flex-col items-center">
            <Outlet />
          </main>

          {/* AList Footer (`src/pages/home/Footer.tsx`) */}
          <footer className="w-full py-5 flex flex-col items-center justify-center text-xs text-muted-foreground select-none">
            <div className="flex items-center gap-2">
              <a
                href="https://github.com/AlistGo/alist-web"
                target="_blank"
                rel="noreferrer"
                className="alist-nav-link px-1.5 py-1 text-foreground/80 hover:text-[var(--alist-main)] font-medium"
              >
                由 drive-unix 多雲端引擎驅動
              </a>
              <span className="text-border">|</span>
              <Link
                to="/@manage"
                className="alist-nav-link px-1.5 py-1 text-[var(--alist-main)] font-medium"
              >
                管理 (@manage)
              </Link>
            </div>
          </footer>
        </div>
      ) : (
        /* ========== AList Manage Layout (`src/pages/manage/index.tsx`) ========== */
        <div className="flex flex-col h-screen w-screen overflow-hidden bg-background">
          <Header mode="manage" onOpenMobileMenu={() => setMobileMenuOpen(true)} />

          <div className="flex flex-1 h-[calc(100vh-64px)] w-full overflow-hidden">
            <Sidebar
              mobileOpen={mobileMenuOpen}
              onCloseMobile={() => setMobileMenuOpen(false)}
            />

            <main className="flex-1 w-full sm:w-[calc(100%-14rem)] p-4 md:p-6 overflow-y-auto">
              <Outlet />
            </main>
          </div>
        </div>
      )}

      {/* Global Drawers & Modals */}
      <LocalSettingsDrawer />
      <TransferQueueDrawer />

      {/* Toast Notifications */}
      <Toaster position="top-right" richColors closeButton theme={theme} />
    </div>
  );
}
