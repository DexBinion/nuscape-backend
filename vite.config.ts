import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const useProxy = env.VITE_PROXY === '1' && !!env.VITE_API_BASE
  return {
    plugins: [react()],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src')
      }
    },
    server: {
      port: 5173,
      proxy: useProxy
        ? {
            '/api': {
              target: env.VITE_API_BASE,
              changeOrigin: true,
              secure: false,
            },
          }
        : undefined,
    },
  }
})
