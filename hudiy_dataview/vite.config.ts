import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig(({ mode }) => ({
    plugins: [
        react({
            babel: {
                plugins: [['babel-plugin-react-compiler', {}]],
            },
        }),
        {
            name: 'file-portal-dev-route',
            configureServer(server) {
                server.middlewares.use((request, _response, next) => {
                    const [pathname, query] = (request.url || '').split('?', 2);
                    if (pathname === '/files' || pathname === '/files/') {
                        request.url = `/files.html${query ? `?${query}` : ''}`;
                    }
                    if (pathname === '/manage' || pathname === '/manage/') {
                        request.url = `/manage.html${query ? `?${query}` : ''}`;
                    }
                    next();
                });
            },
        },
    ],

    // process.env.NODE_ENV must be 'production' in the IIFE bundle (no Vite runtime to inject it).
    // In dev mode Vite injects it as 'development' automatically — overriding it breaks HMR/Fast Refresh.
    define: mode === 'production'
        ? { 'process.env.NODE_ENV': JSON.stringify('production') }
        : {},

    // Dev server: proxy socket.io requests to the running Flask backend
    server: {
        port: 5173,
        proxy: {
            '/api/manage': {
                target: 'http://localhost:5004',
                // Preserve the dev Host so the manager's same-origin check
                // can validate writes without weakening production guards.
                changeOrigin: false,
            },
            '/socket.io': {
                target: 'http://localhost:5003',
                ws: true,           // proxy WebSocket upgrades
                changeOrigin: true,
            },
            '/api': {
                target: 'http://localhost:5003',
                changeOrigin: true,
            },
        },
    },

    build: {
        lib: {
            entry: path.resolve(import.meta.dirname, 'src/main.tsx'),
            name: 'HudiyDataView',
            fileName: 'main',
            formats: ['iife'],
        },
        outDir: 'static/js',
        emptyOutDir: false,
        rollupOptions: {
            output: {
                entryFileNames: 'main.js',
            },
        },
    },
}));
