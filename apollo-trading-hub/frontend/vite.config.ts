import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  base: './',
  build: {
    target: 'esnext',
    // demo builds become ONE self-contained bundle (no extra chunks to fetch) so the page can be inlined into a single file
    ...(mode === 'demo' ? { rollupOptions: { output: { inlineDynamicImports: true } }, assetsInlineLimit: 100_000_000, cssCodeSplit: false } : {}),
  },
  server: { port: 5173, strictPort: true, host: '127.0.0.1' },
}));
