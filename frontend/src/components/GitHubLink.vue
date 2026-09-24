<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

/** GitHub 仓库地址 — 从 Vite 环境变量读取，回退到项目主仓库 */
const repoUrl = import.meta.env.VITE_APP_GITHUB_URL || 'https://github.com/Kaixxrua/AIGC_NEWS'
</script>

<template>
  <a
    class="github-link"
    :href="repoUrl"
    target="_blank"
    rel="noopener noreferrer"
    :aria-label="t('common.githubRepo')"
    :title="t('common.githubRepo')"
  >
    <svg
      class="github-icon"
      viewBox="0 0 16 16"
      fill="currentColor"
      aria-hidden="true"
    >
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
    </svg>
  </a>
</template>

<style scoped>
.github-link {
  display: inline-grid;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 50%;
  color: var(--ink-muted);
  background: transparent;
  cursor: pointer;
  transition: color 150ms ease, background-color 150ms ease, transform 150ms ease;
}

.github-link:hover {
  color: var(--ink);
  background: var(--acid-soft);
  transform: rotate(-3deg);
}

.github-link:active { transform: rotate(-3deg) scale(0.92); }
.github-link:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }

.github-icon { width: 20px; height: 20px; }

@media (prefers-reduced-motion: reduce) {
  .github-link { transition: none; }
  .github-link:hover,
  .github-link:active { transform: none; }
}
</style>
