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
      key: fs.readFileSync('./certs/localhost+3-key.pem'), 
      cert: fs.readFileSync('./certs/localhost+3.pem'),   
    },
    proxy: {
      '/api': {
        target: 'https://localhost:8000',
        changeOrigin: true,
        ws: true
      },
      '/socket.io': {
        target: 'https://localhost:8000',
        ws: true,
        changeOrigin: true
      },
      '/ws': {
        target: 'https://localhost:8000',
        ws: true,
        changeOrigin: true
      },
      '/ws-room': {
        target: 'https://localhost:8000',
        changeOrigin: true,
        ws: true,
        secure: false
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
