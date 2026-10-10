<script setup lang="ts">
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const groupUrl = 'https://qm.qq.com/q/4569CWg9hS'
</script>

<template>
  <a
    class="qq-group-link"
    :href="groupUrl"
    target="_blank"
    rel="noopener noreferrer"
    :aria-label="t('common.joinQQGroup')"
    :title="t('common.joinQQGroup')"
  >
    <span class="qq-group-icon" aria-hidden="true"></span>
  </a>
</template>

<style scoped>
.qq-group-link {
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

.qq-group-link:hover {
  color: var(--ink);
  background: var(--acid-soft);
  transform: rotate(-3deg);
}

.qq-group-link:active { transform: rotate(-3deg) scale(0.92); }
.qq-group-link:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }

.qq-group-icon {
  width: 22px;
  height: 22px;
  background: currentColor;
  mask: url('@/assets/brands/qq.svg') center / contain no-repeat;
}

@media (prefers-reduced-motion: reduce) {
  .qq-group-link { transition: none; }
  .qq-group-link:hover,
  .qq-group-link:active { transform: none; }
}
</style>
