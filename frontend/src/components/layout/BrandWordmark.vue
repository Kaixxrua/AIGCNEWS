<script setup lang="ts">
/**
 * BrandWordmark.vue
 * 顶栏品牌字标 —— 常驻赛博故障特效。
 *
 * 五层叠加（同字号同字距逐像素对齐）：
 *  1. 常染色差边：青/品红两层全文字残影 ±1.2px 常显并缓慢漂移（负 z-index
 *     垫底，呈现浮雕式 RGB 分色边缘）；
 *  2. 色差切片：青/品红两层 clip-path 薄切片持续跳变（常驻），周期末高烈度爆发；
 *  3. JS 字形扰动：随机字符短暂替换为块元素/符号字形后还原（常驻低烈度，
 *     hover 升烈度，每 4s 与 CSS 爆发窗口对齐一次高强度扰动）；
 *  4. 扫描线覆层 + 暗色主题霓虹辉光，提供 CRT 质感。
 *
 * 字符级 span 挂载后量宽固定，换字形不引起邻字 reflow；
 * 字距用 margin 表达（残影层用等量 letter-spacing 对齐）。
 * prefers-reduced-motion / 页面不可见时扰动暂停。
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

const props = defineProps<{ text: string }>()

/** 字形池：块元素重复加权（数字衰变感），符号少量点缀 */
const GLYPHS = '▓▒░█▄▀▓▒░█#%&*+=@<>/\\'
const TICK_MS = 110
const BURST_PERIOD_MS = 4000 // 与 CSS bw-jitter 4s 周期对齐
const BURST_WINDOW_MS = 650
const BURST_FIRST_DELAY_MS = 1400

const chars = computed(() => props.text.split(''))
const displayChars = ref<string[]>(props.text.split(''))
const hovered = ref(false)
const textEl = ref<HTMLElement | null>(null)

/** 正在扰动的字符：index → 剩余帧数 */
const active = new Map<number, number>()
let tickTimer: ReturnType<typeof setInterval> | null = null
let burstTimer: ReturnType<typeof setInterval> | null = null
let burstFirstTimer: ReturnType<typeof setTimeout> | null = null
let burstUntil = 0
let reducedMotion = false

const randomGlyph = () => GLYPHS[Math.floor(Math.random() * GLYPHS.length)]

const tick = () => {
  for (const [i, remaining] of active) {
    const next = remaining - 1
    if (next <= 0) {
      displayChars.value[i] = chars.value[i]
      active.delete(i)
    } else {
      displayChars.value[i] = randomGlyph()
      active.set(i, next)
    }
  }
  const bursting = Date.now() < burstUntil
  const probability = (bursting ? 0.22 : 0.035) * (hovered.value ? 4 : 1)
  chars.value.forEach((ch, i) => {
    if (ch === ' ' || active.has(i)) return
    if (Math.random() < probability) active.set(i, 2 + Math.floor(Math.random() * 3))
  })
}

const start = () => {
  if (tickTimer === null) tickTimer = setInterval(tick, TICK_MS)
}
const stop = () => {
  if (tickTimer !== null) {
    clearInterval(tickTimer)
    tickTimer = null
  }
}
const onVisibilityChange = () => (document.hidden ? stop() : start())

/** 量宽固定每个字符，扰动换字形时邻字零位移 */
const lockCharWidths = async () => {
  await nextTick()
  textEl.value
    ?.querySelectorAll<HTMLElement>('.brand-wordmark__char')
    .forEach((el) => {
      el.style.width = `${el.getBoundingClientRect().width}px`
    })
}

watch(
  () => props.text,
  async (next) => {
    active.clear()
    displayChars.value = next.split('')
    await lockCharWidths()
  },
)

onMounted(async () => {
  reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  await lockCharWidths()
  if (reducedMotion) return
  start()
  burstFirstTimer = setTimeout(() => {
    burstUntil = Date.now() + BURST_WINDOW_MS
    burstTimer = setInterval(() => {
      burstUntil = Date.now() + BURST_WINDOW_MS
    }, BURST_PERIOD_MS)
  }, BURST_FIRST_DELAY_MS)
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onUnmounted(() => {
  stop()
  if (burstTimer !== null) clearInterval(burstTimer)
  if (burstFirstTimer !== null) clearTimeout(burstFirstTimer)
  document.removeEventListener('visibilitychange', onVisibilityChange)
  active.clear()
})
</script>

<template>
  <RouterLink
    to="/"
    class="brand-wordmark"
    :aria-label="text"
    @mouseenter="hovered = true"
    @mouseleave="hovered = false"
  >
    <span ref="textEl" class="brand-wordmark__text" aria-hidden="true"><span class="bw-fringe bw-fringe--cyan">{{ text }}</span><span class="bw-fringe bw-fringe--magenta">{{ text }}</span><span class="bw-slice bw-slice--cyan">{{ text }}</span><span class="bw-slice bw-slice--magenta">{{ text }}</span><span
      v-for="(ch, i) in chars"
      :key="i"
      class="brand-wordmark__char"
    >{{ displayChars[i] }}</span><span class="brand-wordmark__scan"></span></span>
  </RouterLink>
</template>

<style scoped>
.brand-wordmark {
  /* 亮纸面：残影用压低明度的饱和青/品红，保证纸面上可读 */
  --glitch-cyan: #0e7f9c;
  --glitch-magenta: #d81b60;
  --glitch-glow: color-mix(in srgb, var(--glitch-cyan) 55%, transparent);
  --glitch-idle-glow: transparent;
  --glitch-scan: rgb(0 0 0 / 0.05);
  --bw-tracking: 0.22em;

  display: inline-flex;
  align-items: center;
  padding: 4px 2px;
  border-radius: 6px;
  color: var(--ink);
  text-decoration: none;
  user-select: none;
}

.brand-wordmark__text {
  position: relative;
  display: inline-block;
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
  font-size: 17px;
  font-weight: 800;
  line-height: 1;
  white-space: nowrap;
  text-shadow: 0 0 12px var(--glitch-idle-glow);
  animation: bw-jitter 4s steps(1, end) infinite;
}

.brand-wordmark__char {
  display: inline-block;
  white-space: pre;
  text-align: center;
  /* 末字符同样保留尾距：残影层 letter-spacing 也有尾部间隔，两侧等量对齐 */
  margin-right: var(--bw-tracking);
}

/* 残影层共用定位：覆盖字标盒，与本体同字距逐字形对齐 */
.bw-fringe,
.bw-slice {
  position: absolute;
  left: 0;
  top: 0;
  width: 100%;
  height: 100%;
  letter-spacing: var(--bw-tracking);
  pointer-events: none;
}

/* 常染色差边：垫底（负 z-index），全文字无裁剪，缓慢反向漂移 */
.bw-fringe {
  z-index: -1;
  opacity: 0.32;
}

.bw-fringe--cyan {
  color: var(--glitch-cyan);
  transform: translateX(-1.2px);
  animation: bw-fringe-a 6s cubic-bezier(0.65, 0, 0.35, 1) infinite alternate;
}

.bw-fringe--magenta {
  color: var(--glitch-magenta);
  transform: translateX(1.2px);
  animation: bw-fringe-b 7s cubic-bezier(0.65, 0, 0.35, 1) infinite alternate;
}

@keyframes bw-fringe-a {
  from { transform: translateX(-1.6px); }
  to { transform: translateX(-0.8px); }
}

@keyframes bw-fringe-b {
  from { transform: translateX(0.8px); }
  to { transform: translateX(1.6px); }
}

/* 色差切片：常驻薄切片小幅度跳变，周期末高烈度爆发；
   absolute 定位天然盖过 in-flow 字标本体 */
.bw-slice--cyan {
  color: var(--glitch-cyan);
  animation: bw-slice-a 2.4s steps(1, end) infinite;
}

.bw-slice--magenta {
  color: var(--glitch-magenta);
  animation: bw-slice-b 3.1s steps(1, end) infinite;
}

/* 扫描线覆层：只盖字标本体盒，提供 CRT 纹理 */
.brand-wordmark__scan {
  position: absolute;
  inset: 0;
  background: repeating-linear-gradient(
    to bottom,
    transparent 0,
    transparent 2px,
    var(--glitch-scan) 2px,
    var(--glitch-scan) 3px
  );
  mix-blend-mode: multiply;
  pointer-events: none;
}

/* ═══ 本体抖动：大部分时间静止，70%–80% 窗口爆发（与 JS 扰动爆发对齐） ═══ */
@keyframes bw-jitter {
  0%, 70%, 81%, 100% { transform: none; text-shadow: 0 0 12px var(--glitch-idle-glow); }
  72% { transform: translate(-1.5px, 0.5px) skewX(-5deg); }
  74% { transform: translate(2px, -1px) skewX(3deg); text-shadow: 0 0 16px var(--glitch-glow); }
  76% { transform: translate(-2.5px, 0) skewX(-7deg); }
  78% { transform: translate(1px, 1px) skewX(2deg); text-shadow: 0 0 22px var(--glitch-glow); }
  80% { transform: translate(-0.5px, 0); }
}

/* ═══ 青色切片（2.4s）：常驻薄切片小幅度跳变，68%–84% 高烈度爆发 ═══ */
@keyframes bw-slice-a {
  0%   { opacity: 0.5;  clip-path: inset(18% 0 72% 0); transform: translateX(-2px); }
  8%   { opacity: 0.55; clip-path: inset(64% 0 22% 0); transform: translateX(-2.5px); }
  16%  { opacity: 0.45; clip-path: inset(38% 0 50% 0); transform: translateX(-1.5px); }
  24%  { opacity: 0.3;  clip-path: inset(80% 0 8% 0); }
  32%  { opacity: 0.5;  clip-path: inset(4% 0 86% 0); transform: translateX(-2.5px); }
  40%  { opacity: 0.6;  clip-path: inset(48% 0 40% 0); transform: translateX(-3px); }
  48%  { opacity: 0.45; clip-path: inset(26% 0 62% 0); transform: translateX(-2px); }
  56%  { opacity: 0.35; clip-path: inset(72% 0 16% 0); }
  64%  { opacity: 0.55; clip-path: inset(56% 0 30% 0); transform: translateX(-2.5px); }
  68%  { opacity: 0.95; clip-path: inset(10% 0 60% 0); transform: translateX(-5px); }
  72%  { opacity: 0.95; clip-path: inset(66% 0 6% 0); transform: translateX(-3.5px); }
  76%  { opacity: 0.9;  clip-path: inset(34% 0 44% 0); transform: translateX(-6px); }
  80%  { opacity: 0.9;  clip-path: inset(84% 0 2% 0); transform: translateX(-4px); }
  84%  { opacity: 0.55; clip-path: inset(22% 0 68% 0); transform: translateX(-2px); }
  100% { opacity: 0.5;  clip-path: inset(18% 0 72% 0); transform: translateX(-2px); }
}

/* ═══ 品红切片（3.1s）：与青层错相位，76%–88% 爆发 ═══ */
@keyframes bw-slice-b {
  0%   { opacity: 0.45; clip-path: inset(70% 0 12% 0); transform: translateX(2px); }
  10%  { opacity: 0.55; clip-path: inset(12% 0 74% 0); transform: translateX(2.5px); }
  20%  { opacity: 0.35; clip-path: inset(44% 0 42% 0); }
  30%  { opacity: 0.55; clip-path: inset(82% 0 4% 0); transform: translateX(3px); }
  42%  { opacity: 0.4;  clip-path: inset(30% 0 58% 0); transform: translateX(1.5px); }
  54%  { opacity: 0.55; clip-path: inset(6% 0 80% 0); transform: translateX(2.5px); }
  64%  { opacity: 0.35; clip-path: inset(58% 0 28% 0); }
  76%  { opacity: 0.95; clip-path: inset(24% 0 54% 0); transform: translateX(5px); }
  80%  { opacity: 0.9;  clip-path: inset(74% 0 8% 0); transform: translateX(3.5px); }
  84%  { opacity: 0.95; clip-path: inset(2% 0 86% 0); transform: translateX(6px); }
  88%  { opacity: 0.55; clip-path: inset(50% 0 36% 0); transform: translateX(2.5px); }
  100% { opacity: 0.45; clip-path: inset(70% 0 12% 0); transform: translateX(2px); }
}

/* ═══ hover：切片提速、烈度拉满，色差边加宽 ═══ */
.brand-wordmark:hover .brand-wordmark__text {
  animation: bw-jitter-hover 0.9s steps(1, end) infinite;
}
.brand-wordmark:hover .bw-slice--cyan {
  animation: bw-hover-a 0.7s steps(1, end) infinite;
}
.brand-wordmark:hover .bw-slice--magenta {
  animation: bw-hover-b 0.55s steps(1, end) infinite;
}
.brand-wordmark:hover .bw-fringe {
  opacity: 0.5;
}

@keyframes bw-jitter-hover {
  0%, 100% { transform: none; }
  25% { transform: translate(-2px, 0.5px) skewX(-4deg); text-shadow: 0 0 18px var(--glitch-glow); }
  50% { transform: translate(1.5px, -1px) skewX(3deg); }
  75% { transform: translate(-1px, 0) skewX(-2deg); text-shadow: 0 0 14px var(--glitch-glow); }
}

@keyframes bw-hover-a {
  0%, 100% { opacity: 0.9; clip-path: inset(8% 0 72% 0); transform: translateX(-3.5px); }
  33% { opacity: 0.9; clip-path: inset(52% 0 20% 0); transform: translateX(-2px); }
  66% { opacity: 0.9; clip-path: inset(30% 0 44% 0); transform: translateX(-4.5px); }
}

@keyframes bw-hover-b {
  0%, 100% { opacity: 0.9; clip-path: inset(64% 0 8% 0); transform: translateX(3.5px); }
  50% { opacity: 0.9; clip-path: inset(14% 0 66% 0); transform: translateX(2px); }
}

.brand-wordmark:focus-visible {
  outline: 2px solid var(--acid);
  outline-offset: 2px;
}

/* ═══ 暗色主题：残影提亮为霓虹色，常驻微弱辉光，扫描线反白 ═══ */
:root[data-theme='dark'] .brand-wordmark {
  --glitch-cyan: #22d3ee;
  --glitch-magenta: #ff2d78;
  --glitch-idle-glow: rgba(34, 211, 238, 0.18);
  --glitch-scan: rgb(255 255 255 / 0.06);
}
:root[data-theme='dark'] .brand-wordmark__scan {
  mix-blend-mode: overlay;
}

@media (max-width: 639px) {
  .brand-wordmark {
    --bw-tracking: 0.14em;
  }
  .brand-wordmark__text {
    font-size: 14px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .brand-wordmark__text,
  .brand-wordmark:hover .brand-wordmark__text,
  .bw-fringe,
  .bw-slice,
  .brand-wordmark:hover .bw-slice--cyan,
  .brand-wordmark:hover .bw-slice--magenta {
    animation: none;
  }

  .bw-fringe,
  .bw-slice {
    opacity: 0;
  }
}
</style>
