import { createBrowserRouter } from 'react-router-dom';
import { AppShell } from '@/components/layout/AppShell';
import { DashboardPage } from '@/pages/DashboardPage';
import { RemotesPage } from '@/pages/RemotesPage';
import { StorageAddOrEditPage } from '@/pages/StorageAddOrEditPage';
import { FilesPage } from '@/pages/FilesPage';
import { TasksPage } from '@/pages/TasksPage';
import { SettingsPage } from '@/pages/SettingsPage';
import { MetasPage } from '@/pages/MetasPage';
import { IndexesPage } from '@/pages/IndexesPage';
import { UsersPage } from '@/pages/UsersPage';
import { BackupRestorePage } from '@/pages/BackupRestorePage';
import { AboutPage } from '@/pages/AboutPage';
import { NotFoundPage } from '@/pages/NotFoundPage';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      {
        index: true,
        element: <FilesPage />,
      },
      {
        path: 'files',
        element: <FilesPage />,
      },
      // Manage Root / Profile
      {
        path: '@manage',
        element: <DashboardPage />,
      },
      {
        path: 'dashboard',
        element: <DashboardPage />,
      },
      // Storages
      {
        path: 'remotes',
        element: <RemotesPage />,
      },
      {
        path: '@manage/storages',
        element: <RemotesPage />,
      },
      {
        path: '@manage/storages/add',
        element: <StorageAddOrEditPage />,
      },
      {
        path: '@manage/storages/edit/:name',
        element: <StorageAddOrEditPage />,
      },
      // Tasks
      {
        path: 'sync',
        element: <TasksPage />,
      },
      {
        path: 'schedule',
        element: <TasksPage />,
      },
      {
        path: '@manage/tasks',
        element: <TasksPage />,
      },
      {
        path: '@manage/tasks/:tab',
        element: <TasksPage />,
      },
      {
        path: '@manage/schedules',
        element: <TasksPage />,
      },
      // Settings
      {
        path: 'settings',
        element: <SettingsPage />,
      },
      {
        path: '@manage/settings',
        element: <SettingsPage />,
      },
      {
        path: '@manage/settings/:tab',
        element: <SettingsPage />,
      },
      // Users
      {
        path: '@manage/users',
        element: <UsersPage />,
      },
      // Metas
      {
        path: '@manage/metas',
        element: <MetasPage />,
      },
      // Indexes
      {
        path: '@manage/indexes',
        element: <IndexesPage />,
      },
      // Backup & Restore
      {
        path: '@manage/backup-restore',
        element: <BackupRestorePage />,
      },
      // About
      {
        path: '@manage/about',
        element: <AboutPage />,
      },
      {
        path: '*',
        element: <NotFoundPage />,
      },
    ],
  },
]);
