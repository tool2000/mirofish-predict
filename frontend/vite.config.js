import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

const backendPort = process.env.VITE_BACKEND_PORT || 5001
const frontendPort = process.env.VITE_FRONTEND_PORT || 3000

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    port: Number(frontendPort),
    strictPort: false,
    open: true,
    proxy: {
      '/api': {
        target: `http://localhost:${backendPort}`,
        changeOrigin: true,
        secure: false
      }
    }
  }
})
