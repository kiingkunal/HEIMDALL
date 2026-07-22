import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Proxy /api to the HEIMDALL FastAPI backend on :8100.
// (8000 is reserved by the user's separate secure-wealth twin — do not use.)
const proxy = { '/api': { target: 'http://127.0.0.1:8100', changeOrigin: true } };

export default defineConfig({
  plugins: [react()],
  server: { port: 5174, proxy },
  preview: { port: 5174, proxy },
});
