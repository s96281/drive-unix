import cronstrue from 'cronstrue/i18n';

/**
 * Convert a standard 5-part Cron expression into human-friendly Traditional Chinese.
 */
export function describeCron(expression: string | null | undefined): string {
  if (!expression || !expression.trim()) return '未設定排程';

  const parts = expression.trim().split(/\s+/);
  if (parts.length !== 5) {
    return expression;
  }

  try {
    return cronstrue.toString(expression.trim(), {
      locale: 'zh_TW',
      use24HourTimeFormat: true,
      throwExceptionOnParseError: false,
    });
  } catch {
    return expression;
  }
}

export const formatCron = describeCron;
