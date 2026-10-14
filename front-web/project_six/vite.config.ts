/**
 * 文件说明：Vite 构建配置。
 * 包含 Vue 插件、路径别名与开发服务器代理（/api 与 /uploads 转发至后端 8000 端口）。
 */
import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    vue(),
    vueDevTools(),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    /** 监听全部回环地址：同时支持 127.0.0.1 / localhost / 局域网移动端真机访问 */
    host: true,
    proxy: {
      /** 后端业务接口代理 */
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
      /** 后端图片等静态资源代理 */
      '/uploads': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
