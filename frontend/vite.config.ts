import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/upload':   {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        bypass(req) {
          if (req.headers.accept?.includes('text/html')) return '/index.html';
        },
      },
      '/books':    { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/pdf':      { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/validate': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/files': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        bypass(req) {
          // Browser page-refresh sends Accept: text/html — serve the SPA shell.
          // Axios API calls send Accept: application/json — proxy to backend.
          if (req.headers.accept?.includes('text/html')) return '/index.html';
        },
      },
    },
  },
});
