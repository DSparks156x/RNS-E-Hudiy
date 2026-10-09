import { defineConfig } from 'vite';
export default defineConfig({ base: './', esbuild: { jsx: 'automatic' }, resolve: { dedupe: ['react', 'react-dom'] }, server: { fs: { allow: ['..'] } } });
