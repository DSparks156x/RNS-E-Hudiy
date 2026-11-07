import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'path';

// A/V over SD ships on its own, so its bundle lands in its own folder.
export default defineConfig({
  plugins: [react({ babel: { plugins: [['babel-plugin-react-compiler', {}]] } })],
  define: { 'process.env.NODE_ENV': JSON.stringify('production') },
  build: {
    lib: { entry: path.resolve(import.meta.dirname, 'src/avsd/avsd.tsx'), name: 'AvsdApp', fileName: 'avsd', formats: ['iife'] },
    outDir: '../avsd/app/static', emptyOutDir: false,
    rollupOptions: { output: { entryFileNames: 'avsd.js', assetFileNames: 'avsd.[ext]' } },
  },
});
