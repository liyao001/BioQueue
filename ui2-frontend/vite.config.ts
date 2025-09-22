import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import basicSsl from '@vitejs/plugin-basic-ssl'

// dev proxy to django at http://localhost:8000
export default defineConfig({
  // plugins: [react(), basicSsl()],
  plugins: [react(), ],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:6666',
        changeOrigin: true,
        secure: false,
        rewrite: (path) => path.replace(/^\/api/, '/api/ui'),
        cookieDomainRewrite: 'localhost',
        cookiePathRewrite: '/',
      },
    },

  },
})


