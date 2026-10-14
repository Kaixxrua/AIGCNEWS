<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import StyleHint from '@/components/StyleHint.vue'
import { tourActive, tourStep } from '@/features/onboarding/signals'
import { applyAppStyle, ensureSimpleStyles, useAppStyle, type AppStyle } from '@/theme'
import { STYLE_HINT_DELAY_MS, markStyleHintSeen, styleHintPending } from '@/theme/styleHint'
import { revealTheme } from '@/motion/themeReveal'
import { popIn, popOut } from '@/motion/presence'

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
  closeHint()
  void switchTo(target.value)
}

// 一次性提示：漫画版下、本机没选过风格的人，页面安静下来以后在开关下方冒一个气泡，说可以换成简洁版。
// 引导正在进行、有弹窗开着、开关不在视野里时先不出，过一会儿再看，最多再等半分钟。
const hintOpen = ref(false)
const HINT_RETRIES = 20
let hintTimer: ReturnType<typeof setTimeout> | undefined
let hintTries = 0

function hintBlocked(): boolean {
  const el = button.value
  if (tourActive.value || !el?.isConnected) return true
  const rect = el.getBoundingClientRect()
  if (rect.width === 0 || rect.top < 0 || rect.bottom > window.innerHeight) return true
  return document.querySelector('dialog[open], [aria-modal="true"]') !== null
}

function scheduleHint() {
  clearTimeout(hintTimer)
  if (hintOpen.value || style.value !== 'comic' || !styleHintPending()) return
  hintTimer = setTimeout(() => {
    if (hintOpen.value || style.value !== 'comic' || !styleHintPending()) return
    if (!hintBlocked()) hintOpen.value = true
    else if (++hintTries < HINT_RETRIES) scheduleHint()
  }, STYLE_HINT_DELAY_MS)
}

function closeHint() {
  clearTimeout(hintTimer)
  if (!hintOpen.value) return
  hintOpen.value = false
  markStyleHintSeen()
}

function switchFromHint() {
  closeHint()
  void switchTo('simple')
}

onMounted(scheduleHint)
onBeforeUnmount(() => clearTimeout(hintTimer))
watch(style, (value) => { if (value !== 'comic') closeHint() })
watch(tourActive, (active) => {
  if (active) closeHint()
  else scheduleHint()
})
// 引导里讲到这个开关，就等于看过提示了。
watch(tourStep, (id) => { if (id === 'style') markStyleHintSeen() })
</script>

<template>
  <button
    ref="button"
    type="button"
    class="style-toggle"
    data-tour="style"
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
  <Teleport to="body">
    <Transition :css="false" @enter="popIn" @leave="popOut">
      <StyleHint v-if="hintOpen" :anchor="button" @switch="switchFromHint" @dismiss="closeHint" />
    </Transition>
  </Teleport>
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
