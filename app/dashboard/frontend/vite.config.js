import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import { resolve } from 'path';
export default defineConfig({
    plugins: [vue()],
    resolve: {
        alias: {
            '@': resolve(__dirname, 'src'),
        },
    },
    build: {
        outDir: resolve(__dirname, '..', 'static'),
        emptyOutDir: true,
        sourcemap: false,
    },
    server: {
        port: 5173,
        proxy: {
            '/ws': {
                target: 'http://127.0.0.1:8765',
                ws: true,
            },
            '/api': {
                target: 'http://127.0.0.1:8765',
            },
        },
    },
});
