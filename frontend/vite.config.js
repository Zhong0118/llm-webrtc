import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import fs from 'fs'

export default defineConfig({
  plugins: [
    vue(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    },
  },
  server: {
    port: 3333,
    host: '0.0.0.0',
    https: {
      key: fs.readFileSync('./certs/localhost+3-key.pem'), // 确保文件名匹配
      cert: fs.readFileSync('./certs/localhost+3.pem'),     // 确保文件名匹配
    },
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true
      },
      '/socket.io': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          'webrtc': ['socket.io-client']
        }
      }
    }
  },
  optimizeDeps: {
    include: ['socket.io-client']
  }
})
