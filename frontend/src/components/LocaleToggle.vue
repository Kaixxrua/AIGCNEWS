<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useLocaleTransition } from '@/composables/useLocaleTransition'

const { locale, t } = useI18n()
const { isLocaleTransitioning, switchLocale } = useLocaleTransition()

const targetLocale = computed(() => locale.value === 'zh-CN' ? 'en-US' : 'zh-CN')
const targetLanguage = computed(() => (
  targetLocale.value === 'zh-CN' ? t('common.chinese') : t('common.english')
))

const toggleLocale = () => { void switchLocale(targetLocale.value) }
</script>

<template>
  <button
    type="button"
    class="locale-toggle"
    :aria-label="`${t('common.language')}：${targetLanguage}`"
    :aria-busy="isLocaleTransitioning"
    :disabled="isLocaleTransitioning"
    :title="targetLanguage"
    @click="toggleLocale"
  >
    <svg
      class="locale-icon"
      viewBox="0 0 28 28"
      fill="none"
      aria-hidden="true"
    >
      <path class="locale-icon__orbit" d="M4.5 8.25h10.75M9.875 4.5v3.75c0 5-2.125 8.125-6.375 10.25" />
      <path class="locale-icon__orbit" d="M6.25 12.25c1.8 2.45 4.2 4.25 7.25 5.5" />
      <path class="locale-icon__accent" d="m15.25 22 3.875-10 3.875 10M16.75 18.25h4.75" />
      <path class="locale-icon__tick" d="M22.25 5.25h2.25v2.25" />
    </svg>
  </button>
</template>

<style scoped>
.locale-toggle {
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

.locale-toggle:hover {
  color: var(--ink);
  background: var(--acid-soft);
  transform: rotate(-3deg);
}

.locale-toggle:active { transform: rotate(-3deg) scale(0.92); }
.locale-toggle:disabled { cursor: wait; opacity: 0.72; }
.locale-toggle:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }

.locale-icon { width: 23px; height: 23px; overflow: visible; }
.locale-icon__orbit,
.locale-icon__accent,
.locale-icon__tick {
  stroke: currentColor;
  stroke-width: 1.65;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.locale-icon__accent { stroke: var(--acid-ink, var(--ink)); }
.locale-icon__tick { stroke: var(--acid); stroke-width: 2; }

@media (prefers-reduced-motion: reduce) {
  .locale-toggle { transition: none; }
  .locale-toggle:hover,
  .locale-toggle:active { transform: none; }
}
</style>
