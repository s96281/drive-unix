import React from 'react';
import { X, Sun, Moon, RotateCcw, Palette, LayoutGrid, Sliders } from 'lucide-react';
import {
  useUiStore,
  type DisplayLayout,
  type FilenameOverflowMode,
  type HeaderStickyMode,
} from '@/stores/ui-store';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';

const COLOR_PRESETS = [
  { name: 'AList 經典藍', value: '#1890ff' },
  { name: '極光靛藍', value: '#4f46e5' },
  { name: '翡翠森林', value: '#10b981' },
  { name: '羅蘭紫韻', value: '#8b5cf6' },
  { name: '落日琥珀', value: '#f59e0b' },
  { name: '珊瑚緋紅', value: '#f43f5e' },
  { name: '青碧湖水', value: '#06b6d4' },
];

export function LocalSettingsDrawer() {
  const {
    localSettingsOpen,
    setLocalSettingsOpen,
    displayLayout,
    setDisplayLayout,
    mainColor,
    setMainColor,
    gridItemSize,
    setGridItemSize,
    filenameOverflow,
    setFilenameOverflow,
    headerStickyMode,
    setHeaderStickyMode,
    checkboxOpen,
    setCheckboxOpen,
    readmeAutoRender,
    setReadmeAutoRender,
    theme,
    setTheme,
  } = useUiStore();

  if (!localSettingsOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black/45 backdrop-blur-[1px] transition-opacity"
        onClick={() => setLocalSettingsOpen(false)}
      />

      {/* Drawer Content (AList Hope UI Drawer right style) */}
      <aside className="relative z-10 w-full max-w-sm bg-[var(--alist-card-bg)] text-foreground h-full shadow-2xl border-l border-border/60 flex flex-col justify-between overflow-hidden animate-in slide-in-from-right duration-200">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border/60">
          <div className="flex items-center gap-2">
            <Sliders className="h-4 w-4 text-[var(--alist-main)]" />
            <h2 className="text-base font-bold text-[var(--alist-main)]">本機設定 (Local Settings)</h2>
          </div>
          <button
            onClick={() => setLocalSettingsOpen(false)}
            className="h-7 w-7 rounded-md flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-[var(--alist-hover)] transition-colors cursor-pointer"
            aria-label="關閉"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5 text-sm">
          {/* Default Layout */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
              <LayoutGrid className="h-3.5 w-3.5" />
              預設佈局視圖 (global_default_layout)
            </label>
            <Select value={displayLayout} onValueChange={(v) => setDisplayLayout(v as DisplayLayout)}>
              <SelectTrigger className="w-full h-9 text-xs bg-input/80 border-transparent">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="list">列表視圖 (List)</SelectItem>
                <SelectItem value="grid">網格視圖 (Grid)</SelectItem>
                <SelectItem value="image">圖片視圖 (Image Gallery)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Filename Overflow */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              列表檔名溢位顯示 (list_item_filename_overflow)
            </label>
            <Select
              value={filenameOverflow}
              onValueChange={(v) => setFilenameOverflow(v as FilenameOverflowMode)}
            >
              <SelectTrigger className="w-full h-9 text-xs bg-input/80 border-transparent">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ellipsis">單行省略號 (Ellipsis)</SelectItem>
                <SelectItem value="scrollable">滑鼠懸停跑馬燈 (Scrollable)</SelectItem>
                <SelectItem value="multi_line">多行完整顯示 (Multi-line)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Header & Navbar Position */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              頂欄與導覽列位置 (position_of_header_navbar)
            </label>
            <Select
              value={headerStickyMode}
              onValueChange={(v) => setHeaderStickyMode(v as HeaderStickyMode)}
            >
              <SelectTrigger className="w-full h-9 text-xs bg-input/80 border-transparent">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="static">隨頁面捲動 (Static)</SelectItem>
                <SelectItem value="sticky">頂欄與麵包屑固定 (Sticky)</SelectItem>
                <SelectItem value="only_navbar_sticky">僅麵包屑固定 (Only Navbar Sticky)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Grid Item Size */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <label className="text-xs font-medium text-muted-foreground">
                網格圖示尺寸 (grid_item_size)
              </label>
              <span className="text-xs font-mono text-[var(--alist-main)]">{gridItemSize}px</span>
            </div>
            <div className="flex items-center gap-3">
              <input
                type="range"
                min={60}
                max={160}
                step={10}
                value={gridItemSize}
                onChange={(e) => setGridItemSize(Number(e.target.value) || 90)}
                className="flex-1 accent-[var(--alist-main)] cursor-pointer"
              />
              <Input
                type="number"
                min={60}
                max={180}
                value={gridItemSize}
                onChange={(e) => setGridItemSize(Math.max(60, Math.min(180, Number(e.target.value) || 90)))}
                className="w-20 h-8 text-xs font-mono text-center"
              />
            </div>
          </div>

          {/* Main Theme Color */}
          <div className="space-y-2">
            <label className="text-xs font-medium text-muted-foreground flex items-center gap-1.5">
              <Palette className="h-3.5 w-3.5" />
              主題強調色 (main_color)
            </label>
            <div className="flex flex-wrap items-center gap-2">
              {COLOR_PRESETS.map((preset) => {
                const active = mainColor.toLowerCase() === preset.value.toLowerCase();
                return (
                  <button
                    key={preset.value}
                    type="button"
                    onClick={() => setMainColor(preset.value)}
                    title={preset.name}
                    className={`h-7 w-7 rounded-full transition-transform cursor-pointer flex items-center justify-center ${
                      active ? 'scale-110 ring-2 ring-offset-2 ring-[var(--alist-main)]' : 'hover:scale-105 opacity-85'
                    }`}
                    style={{ backgroundColor: preset.value }}
                  />
                );
              })}
              <input
                type="color"
                value={mainColor}
                onChange={(e) => setMainColor(e.target.value)}
                className="h-7 w-9 rounded cursor-pointer bg-transparent border-0"
                title="自訂色碼"
              />
            </div>
          </div>

          {/* Toggles */}
          <div className="space-y-3 pt-2 border-t border-border/60">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-foreground">顯示項目勾選框 (checkbox_open)</span>
              <Switch checked={checkboxOpen} onCheckedChange={setCheckboxOpen} />
            </div>

            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-foreground">自動渲染 README.md 說明卡</span>
              <Switch checked={readmeAutoRender} onCheckedChange={setReadmeAutoRender} />
            </div>
          </div>
        </div>

        {/* Footer (AList SwitchColorMode & Reset) */}
        <div className="p-4 border-t border-border/60 bg-muted/20 flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <Button
              variant={theme === 'light' ? 'subtle' : 'ghost'}
              size="sm"
              onClick={() => setTheme('light')}
              className="gap-1.5 text-xs"
            >
              <Sun className="h-3.5 w-3.5" /> 淺色
            </Button>
            <Button
              variant={theme === 'dark' ? 'subtle' : 'ghost'}
              size="sm"
              onClick={() => setTheme('dark')}
              className="gap-1.5 text-xs"
            >
              <Moon className="h-3.5 w-3.5" /> 深色
            </Button>
          </div>

          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setMainColor('#1890ff');
              setDisplayLayout('list');
              setGridItemSize(90);
              setFilenameOverflow('ellipsis');
              setHeaderStickyMode('sticky');
              setReadmeAutoRender(true);
            }}
            className="text-xs text-muted-foreground hover:text-foreground gap-1"
            title="還原預設值"
          >
            <RotateCcw className="h-3.5 w-3.5" /> 重設
          </Button>
        </div>
      </aside>
    </div>
  );
}
