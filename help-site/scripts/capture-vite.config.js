import { defineConfig } from 'vite';
import { fileURLToPath } from 'node:url';
export default defineConfig({
  define: { __CAPTURE_SOCKET_FIXTURE__: 'true' },
  esbuild: { jsx: 'automatic' },
  resolve: { dedupe: ['react', 'react-dom'], alias: { 'socket.io-client': fileURLToPath(new URL('./capture-socket.js', import.meta.url)) } },
  server: { host: '127.0.0.1', port: 5190, strictPort: true, fs: { allow: ['..'] } },
});
