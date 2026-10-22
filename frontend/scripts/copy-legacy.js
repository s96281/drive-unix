import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const srcPath = path.resolve(__dirname, '../legacy/legacy.html');
const destDir = path.resolve(__dirname, '../../web/static');
const destPath = path.resolve(destDir, 'legacy.html');

try {
  if (fs.existsSync(srcPath)) {
    if (!fs.existsSync(destDir)) {
      fs.mkdirSync(destDir, { recursive: true });
    }
    fs.copyFileSync(srcPath, destPath);
    console.log(`[copy-legacy] Copied legacy.html to ${destPath}`);
  }
} catch (err) {
  console.warn('[copy-legacy] Failed to copy legacy.html:', err);
}
