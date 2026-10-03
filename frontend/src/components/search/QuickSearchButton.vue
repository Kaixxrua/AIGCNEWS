<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Search } from 'lucide-vue-next'
import { useQuickSearch } from '@/composables/useQuickSearch'
import { isApplePlatform } from '@/features/search/quickSearchHotkey'

/** 报眉上的放大镜：打开站内速查，提示里写着快捷键。外观与旁边的 GitHub 图标同一配方。 */
const { t } = useI18n()
const { open, show } = useQuickSearch()
const apple = isApplePlatform()
const label = computed(() => t('quickSearch.open', { keys: apple ? '⌘K' : 'Ctrl K' }))
</script>

<template>
  <button
    type="button"
    class="quick-search-button"
    :aria-label="label"
    :title="label"
    aria-haspopup="dialog"
    :aria-expanded="open"
    :aria-keyshortcuts="apple ? 'Meta+K' : 'Control+K'"
    @click="show"
  >
    <Search :size="19" :stroke-width="2.2" aria-hidden="true" />
  </button>
</template>

<style scoped>
.quick-search-button {
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

.quick-search-button:hover,
.quick-search-button[aria-expanded='true'] {
  color: var(--ink);
  background: var(--acid-soft);
}

.quick-search-button:hover { transform: rotate(-3deg); }
.quick-search-button:active { transform: rotate(-3deg) scale(0.92); }
.quick-search-button:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }

@media (prefers-reduced-motion: reduce) {
  .quick-search-button { transition: none; }
  .quick-search-button:hover,
  .quick-search-button:active { transform: none; }
}
</style>
