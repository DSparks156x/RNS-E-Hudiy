import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

export default defineConfig({
    plugins: [react({
        babel: { plugins: [['babel-plugin-react-compiler', {}]] },
    })],
    define: { 'process.env.NODE_ENV': JSON.stringify('production') },
    build: {
        lib: {
            entry: path.resolve(import.meta.dirname, 'src/portal.tsx'),
            name: 'HudiyFilePortal',
            fileName: 'portal',
            formats: ['iife'],
        },
        outDir: 'static/js',
        emptyOutDir: false,
        rollupOptions: { output: { entryFileNames: 'portal.js' } },
    },
});
