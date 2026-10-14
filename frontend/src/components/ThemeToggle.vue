<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAppStyle, useAppTheme } from '@/theme'
import { revealTheme } from '@/motion/themeReveal'

const { t } = useI18n()
const { theme, toggleAppTheme } = useAppTheme()
const { style } = useAppStyle()

const targetThemeKey = computed(() => (theme.value === 'dark' ? 'theme.light' : 'theme.dark'))

// 新主题从按钮处炸开一枚漫画爆炸框铺满全屏（键盘触发同样以按钮为圆心）；简洁版换成圆形铺开。
function toggle(event: MouseEvent) {
  const button = event.currentTarget as HTMLElement | null
  const rect = button?.getBoundingClientRect()
  const origin = rect ? { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 } : null
  revealTheme(origin, toggleAppTheme, style.value === 'simple' ? 'circle' : 'burst')
}
</script>

<template>
  <button
    type="button"
    class="theme-toggle"
    :aria-label="`${t('theme.toggle')}：${t(targetThemeKey)}`"
    :title="t(targetThemeKey)"
    @click="toggle"
  >
    <svg
      v-if="theme === 'dark'"
      class="theme-icon"
      viewBox="0 0 28 28"
      fill="none"
      aria-hidden="true"
    >
      <circle class="theme-icon__stroke" cx="14" cy="14" r="5" />
      <path class="theme-icon__accent" d="M14 3.5v2.8M14 21.7v2.8M3.5 14h2.8M21.7 14h2.8M6.6 6.6l2 2M19.4 19.4l2 2M21.4 6.6l-2 2M8.6 19.4l-2 2" />
    </svg>
    <svg
      v-else
      class="theme-icon"
      viewBox="0 0 28 28"
      fill="none"
      aria-hidden="true"
    >
      <path class="theme-icon__stroke" d="M23.5 16.8A9.8 9.8 0 0 1 11.2 4.5a9.8 9.8 0 1 0 12.3 12.3Z" />
      <path class="theme-icon__accent" d="M20.5 4.5v3.6M18.7 6.3h3.6" />
    </svg>
  </button>
</template>

<style scoped>
.theme-toggle {
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

.theme-toggle:hover {
  color: var(--ink);
  background: var(--acid-soft);
  transform: rotate(-3deg);
}

.theme-toggle:active { transform: rotate(-3deg) scale(0.92); }
.theme-toggle:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }

.theme-icon { width: 23px; height: 23px; overflow: visible; }
.theme-icon__stroke,
.theme-icon__accent {
  stroke: currentColor;
  stroke-width: 1.65;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.theme-icon__accent { stroke: var(--acid); stroke-width: 2; }

@media (prefers-reduced-motion: reduce) {
  .theme-toggle { transition: none; }
  .theme-toggle:hover,
  .theme-toggle:active { transform: none; }
}
</style>
