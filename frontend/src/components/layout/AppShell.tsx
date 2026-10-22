import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { TransferQueueDrawer } from './TransferQueueDrawer';
import { Toaster } from 'sonner';

export function AppShell() {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
      {/* Permanent Sidebar */}
      <Sidebar />

      {/* Main Container */}
      <div className="flex flex-1 flex-col overflow-hidden">
        <Header />

        {/* Page Content Viewport */}
        <main className="flex-1 overflow-y-auto p-6 md:p-8">
          <Outlet />
        </main>
      </div>

      {/* Global Transfer Queue Drawer */}
      <TransferQueueDrawer />

      {/* Toast Notifications */}
      <Toaster position="top-right" richColors closeButton theme="dark" />
    </div>
  );
}
