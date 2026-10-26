import { defineConfig } from 'vite';
import path from 'node:path';

export default defineConfig({
  root: path.resolve('renderer'),
  base: './',
  build: { outDir: path.resolve('dist/renderer'), emptyOutDir: true, sourcemap: false },
  esbuild: { jsx: 'automatic' },
});
