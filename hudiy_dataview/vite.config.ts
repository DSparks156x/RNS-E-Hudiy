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
            '/socket.io': {
                target: 'http://localhost:5003',
                ws: true,           // proxy WebSocket upgrades
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
