import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

function normalizeBasePath(value?: string) {
  const rawBasePath = value?.trim() || '/fund-nav-estimator/'
  const trimmedBasePath = rawBasePath.replace(/^\/+|\/+$/g, '')
  return trimmedBasePath ? `/${trimmedBasePath}/` : '/'
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const appBasePath = normalizeBasePath(env.VITE_APP_BASE_PATH)
  const prefixedApiPath = `${appBasePath}api`

  return {
    base: appBasePath,
    plugins: [vue()],
    server: {
      port: 5173,
      proxy: {
        [prefixedApiPath]: {
          target: 'http://192.168.50.50:18888/fund-nav-estimator',
          changeOrigin: true,
          rewrite: (path) => path.replace(new RegExp(`^${prefixedApiPath}`), '/api'),
        },
        '/api': {
          target: 'http://192.168.50.50:18888/fund-nav-estimator',
          changeOrigin: true,
        },
      },
    },
  }
})
