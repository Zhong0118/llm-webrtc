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
    port: 5173,
    host: '0.0.0.0',
    https: {
      key: fs.readFileSync('./certs/localhost+3-key.pem'), 
      cert: fs.readFileSync('./certs/localhost+3.pem'),   
    },
    proxy: {
      // 规则 1: 代理所有 /api/ 开头的 HTTP 请求 (例如 /api/rtsp/status)
      // (这个规则保持不变，它是正确的)
      '/api': {
        target: 'https://localhost:33335', // 后端 HTTPS 地址
        changeOrigin: true,
        secure: false // 信任自签名证书
      },
      
      // 【修改点 2】: 代理所有 Socket.IO 连接
      // Socket.IO 需要同时代理 HTTP (用于握手) 和 WebSocket (用于通信)
      // 我们需要捕获所有命名空间
      '/p2p': {
        target: 'https://localhost:33335',
        changeOrigin: true,
        secure: false
      },
      '/streamer': {
        target: 'https://localhost:33335',
        changeOrigin: true,
        secure: false
      },
      '/server_push': {
        target: 'https://localhost:33335',
        changeOrigin: true,
        secure: false
      },
      // 规则 3: 代理 Socket.IO 的底层引擎 (engine.io)
      // (这个规则保持不变，它是正确的)
      '/socket.io': {
        target: 'https://localhost:33335', // 后端 HTTPS 地址
        ws: true,                          // 启用 WebSocket 代理
        changeOrigin: true,
        secure: false // 信任自签名证书
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
