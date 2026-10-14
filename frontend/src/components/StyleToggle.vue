<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { applyAppStyle, ensureSimpleStyles, useAppStyle, type AppStyle } from '@/theme'
import { revealTheme } from '@/motion/themeReveal'

/** 报头的页面风格开关：漫画版与简洁版。和主题开关一样，图标与提示说的是按下去换成哪一版。 */
const { t } = useI18n()
const { style } = useAppStyle()
const busy = ref(false)
const button = ref<HTMLButtonElement | null>(null)

const target = computed<AppStyle>(() => (style.value === 'simple' ? 'comic' : 'simple'))
const targetLabel = computed(() => t(target.value === 'simple' ? 'appStyle.toSimple' : 'appStyle.toComic'))

// 新的一版从按钮处铺开：去简洁版是一个圆，回漫画版炸开一枚爆炸框。头一回去简洁版要先下样式表，下完再换，
// 免得先露出一帧没有简洁样式的页面；下载期间再按不重复触发。
async function switchTo(next: AppStyle) {
  if (busy.value) return
  const rect = button.value?.getBoundingClientRect()
  const origin = rect ? { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 } : null
  busy.value = true
  try {
    if (next === 'simple') await ensureSimpleStyles()
    revealTheme(origin, () => applyAppStyle(next), next === 'simple' ? 'circle' : 'burst')
  } finally {
    busy.value = false
  }
}

function toggle() {
  void switchTo(target.value)
}
</script>

<template>
  <button
    ref="button"
    type="button"
    class="style-toggle"
    :aria-label="`${t('appStyle.toggle')}：${targetLabel}`"
    :title="targetLabel"
    :aria-busy="busy ? 'true' : undefined"
    @click="toggle"
  >
    <!-- 去简洁版：一页只有正文的纸；回漫画版：带感叹号的喊话气泡 -->
    <svg v-if="target === 'simple'" class="style-icon" viewBox="0 0 28 28" fill="none" aria-hidden="true">
      <rect class="style-icon__stroke" x="6.5" y="4.5" width="15" height="19" rx="2.5" />
      <path class="style-icon__stroke" d="M10.5 14h7M10.5 18h4.5" />
      <path class="style-icon__accent" d="M10.5 10h7" />
    </svg>
    <svg v-else class="style-icon" viewBox="0 0 28 28" fill="none" aria-hidden="true">
      <path class="style-icon__stroke" d="M4.5 8A3 3 0 0 1 7.5 5h13a3 3 0 0 1 3 3v7.5a3 3 0 0 1-3 3h-7l-5 4v-4h-1a3 3 0 0 1-3-3Z" />
      <path class="style-icon__accent" d="M14 8.6v4.4M14 15.6v.1" />
    </svg>
  </button>
</template>

<style scoped>
.style-toggle {
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

.style-toggle:hover {
  color: var(--ink);
  background: var(--acid-soft);
  transform: rotate(-3deg);
}

.style-toggle:active { transform: rotate(-3deg) scale(0.92); }
.style-toggle:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
.style-toggle[aria-busy='true'] { cursor: progress; }

.style-icon { width: 23px; height: 23px; overflow: visible; }
.style-icon__stroke,
.style-icon__accent {
  stroke: currentColor;
  stroke-width: 1.65;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.style-icon__accent { stroke: var(--acid); stroke-width: 2; }

@media (prefers-reduced-motion: reduce) {
  .style-toggle { transition: none; }
  .style-toggle:hover,
  .style-toggle:active { transform: none; }
}
</style>
