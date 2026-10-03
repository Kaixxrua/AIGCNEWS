import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { uiLibraryAssets } from './build/uiLibraryAssets'
import { desktopStylesPreload } from './build/desktopStylesPreload'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
export default defineConfig({
  server: { watch: { ignored: ['**/.ui-previews/**'] }, proxy: { "/api": { target: process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000", changeOrigin: true } } },
  plugins: [
    vue(),
    uiLibraryAssets(),
    // 漫画版内页样式只在桌面宽度下载：index.html 里加一条带媒体条件的预加载，见 build/desktopStylesPreload.ts。
    desktopStylesPreload(),
    // PWA 应用外壳：generateSW 全量预缓存静态资源，离线可打开 shell。
    // - injectRegister: false：注册由 src/pwa/registerPwa.ts 手动完成，不向
    //   index.html 注入任何脚本（CSP 对内联脚本有 sha256 白名单契约）。
    // - manifest: false：manifest 走 public/ 下手写版，不由插件生成。
    // - registerType: 'autoUpdate'：新 SW 安装后立即接管并刷新，无需用户确认。
    // - /api 一律不经 SW（SSE 长连接 + JWT Authorization 头，缓存/拦截会
    //   出事故）；/camp-scene 是独立 Godot 文档与大体积资源，也不能被
    //   SPA 导航回退或预缓存接管。两者均只由同源服务器直接提供。
    VitePWA({
      injectRegister: false,
      manifest: false,
      registerType: 'autoUpdate',
      workbox: {
        navigateFallback: '/index.html',
        globIgnores: ['**/ui-library/**', '**/camp-scene/**'],
        navigateFallbackDenylist: [
          /^\/api\//,
          /^\/camp-scene(?:\/|$)/,
          /^\/ui-library\/(?:previews|sources|licenses|posters|clips|assets)\//,
        ],
        clientsClaim: true,
        skipWaiting: true,
        // 默认 globPatterns 只含 js/css/html；自托管字体与 logo 必须入预缓存，
        // 否则离线打开外壳时字体/图标回退。robots.txt / sitemap.xml 面向
        // 爬虫，不属于外壳，不预缓存。
        globPatterns: ['**/*.{js,css,html,mjs,png,svg,ico,woff,woff2,ttf}'],
      },
    }),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    // 默认排除之外再排除 Claude Code 会话 worktree 残留，
    // 避免废弃副本中的测试文件被误收集（缺 tsconfig 导致 transform 失败）。
    exclude: ['**/node_modules/**', '**/dist/**', '**/.claude/**'],
  },
})
