import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
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
