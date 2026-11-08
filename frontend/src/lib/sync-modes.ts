export type SyncMode = 'copy' | 'sync-one-way' | 'sync-two-way' | 'mirror';

export type ConflictStrategy =
  | 'auto'
  | 'newer'
  | 'rename'
  | 'abort'
  | 'prefer-source'
  | 'prefer-destination';

export interface SyncModeConfig {
  mode: SyncMode;
  label: string;
  description: string;
  twoWay: boolean;
  deleteAllowed: boolean;
  defaultDelete: boolean;
  conflictOptions: { value: ConflictStrategy; label: string }[];
  defaultConflict: ConflictStrategy;
  destructiveWarning?: string;
}

export const SYNC_MODES: Record<SyncMode, SyncModeConfig> = {
  copy: {
    mode: 'copy',
    label: '僅複製 (Copy)',
    description: '僅將來源端檔案複製至目的端，不刪除目的端多餘項目，遇到衝突時覆蓋。',
    twoWay: false,
    deleteAllowed: false,
    defaultDelete: false,
    conflictOptions: [{ value: 'auto', label: '自動 (預設覆蓋)' }],
    defaultConflict: 'auto',
  },
  'sync-one-way': {
    mode: 'sync-one-way',
    label: '單向同步 (One-Way Sync)',
    description: '以來源端為主同步至目的端，可選擇是否保留目的端已有但來源端無之檔案。',
    twoWay: false,
    deleteAllowed: true,
    defaultDelete: false,
    conflictOptions: [
      { value: 'auto', label: '自動判定' },
      { value: 'newer', label: '保留較新修改' },
      { value: 'rename', label: '保留兩者並更名' },
      { value: 'prefer-source', label: '強制以來源端為主' },
    ],
    defaultConflict: 'newer',
  },
  'sync-two-way': {
    mode: 'sync-two-way',
    label: '雙向同步 (Two-Way Sync)',
    description: '雙向比對更新，兩端檔案彼此互補同步（基於安全考量雙向同步不支援刪除）。',
    twoWay: true,
    deleteAllowed: false,
    defaultDelete: false,
    conflictOptions: [
      { value: 'auto', label: '自動判定' },
      { value: 'newer', label: '保留較新修改 (推薦)' },
      { value: 'rename', label: '保留兩者並更名' },
      { value: 'prefer-source', label: '優先採用來源端' },
      { value: 'prefer-destination', label: '優先採用目的端' },
      { value: 'abort', label: '遇到衝突立即中斷' },
    ],
    defaultConflict: 'newer',
  },
  mirror: {
    mode: 'mirror',
    label: '鏡像備份 (Mirror)',
    description: '使目的端狀態完全鏡像符合來源端，目的端多餘之檔案將被完全清除。',
    twoWay: false,
    deleteAllowed: true,
    defaultDelete: true,
    conflictOptions: [{ value: 'prefer-source', label: '強制覆蓋為來源端內容' }],
    defaultConflict: 'prefer-source',
    destructiveWarning: '鏡像模式將會永久刪除目的端所有在來源端不存在的檔案與資料夾，請謹慎使用！',
  },
};

export const SYNC_MODE_LIST = Object.values(SYNC_MODES);
