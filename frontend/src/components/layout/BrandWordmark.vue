<script setup lang="ts">
/**
 * BrandWordmark.vue
 * 顶栏品牌字标 —— RGB 色差 + 切片抖动 + 霓虹辉光的赛博故障特效。
 *
 * 平时是干净的墨色字标；约每 7s 进入一次短促的故障爆发窗口
 * （色差残影以 clip-path 切片跳变，字标本体抖动 + 辉光脉冲），
 * hover 时故障转为持续触发。亮纸面用可读的饱和青/品红残影，
 * 暗色主题切换为高亮霓虹色并加强辉光。
 */
defineProps<{ text: string }>()
</script>

<template>
  <RouterLink to="/" class="brand-wordmark" :aria-label="text">
    <span class="brand-wordmark__text" :data-text="text" aria-hidden="true">{{ text }}</span>
  </RouterLink>
</template>

<style scoped>
.brand-wordmark {
  /* 亮纸面：残影用压低明度的饱和青/品红，保证纸面上可读 */
  --glitch-cyan: #0e7f9c;
  --glitch-magenta: #d81b60;
  --glitch-glow: color-mix(in srgb, var(--acid) 65%, transparent);
  --glitch-idle-glow: transparent;

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
  letter-spacing: 0.22em;
  line-height: 1;
  white-space: nowrap;
  text-shadow: 0 0 12px var(--glitch-idle-glow);
  animation: bw-jitter 7s steps(1, end) infinite;
}

/* 两层色差残影：与本体同字体同字距，absolute 覆盖保证逐像素重合 */
.brand-wordmark__text::before,
.brand-wordmark__text::after {
  content: attr(data-text);
  position: absolute;
  left: 0;
  top: 0;
  width: 100%;
  height: 100%;
  opacity: 0;
  pointer-events: none;
}

.brand-wordmark__text::before {
  color: var(--glitch-cyan);
  animation: bw-slice-a 7s steps(1, end) infinite;
}

.brand-wordmark__text::after {
  color: var(--glitch-magenta);
  animation: bw-slice-b 7s steps(1, end) infinite;
}

/* ═══ 爆发窗口：~85%–95% 的 0.7s 内本体抖动 + 辉光脉冲 ═══ */
@keyframes bw-jitter {
  0%, 85%, 96%, 100% { transform: none; text-shadow: 0 0 12px var(--glitch-idle-glow); }
  87% { transform: translate(-1.5px, 0.5px) skewX(-5deg); }
  89% { transform: translate(2px, -1px) skewX(3deg); text-shadow: 0 0 16px var(--glitch-glow); }
  91% { transform: translate(-2.5px, 0) skewX(-7deg); }
  93% { transform: translate(1px, 1px) skewX(2deg); text-shadow: 0 0 22px var(--glitch-glow); }
  95% { transform: translate(-0.5px, 0); }
}

/* ═══ 青色残影：爆发窗口内切片跳变 ═══ */
@keyframes bw-slice-a {
  0%, 85%, 96%, 100% { opacity: 0; clip-path: inset(50% 0 50% 0); }
  86% { opacity: 0.85; clip-path: inset(6% 0 76% 0); transform: translateX(-4px); }
  88% { opacity: 0.85; clip-path: inset(58% 0 14% 0); transform: translateX(-2px); }
  90% { opacity: 0.9; clip-path: inset(28% 0 48% 0); transform: translateX(-5px); }
  92% { opacity: 0.85; clip-path: inset(80% 0 2% 0); transform: translateX(-2.5px); }
  94% { opacity: 0.8; clip-path: inset(42% 0 36% 0); transform: translateX(-4.5px); }
}

/* ═══ 品红残影：爆发窗口错位半拍，另有一次 ~38% 的独奏小故障 ═══ */
@keyframes bw-slice-b {
  0%, 37%, 41%, 85%, 97%, 100% { opacity: 0; clip-path: inset(50% 0 50% 0); }
  38% { opacity: 0.6; clip-path: inset(18% 0 64% 0); transform: translateX(3px); }
  40% { opacity: 0.6; clip-path: inset(70% 0 8% 0); transform: translateX(2px); }
  86% { opacity: 0.85; clip-path: inset(70% 0 10% 0); transform: translateX(4px); }
  88% { opacity: 0.85; clip-path: inset(10% 0 72% 0); transform: translateX(2.5px); }
  90% { opacity: 0.9; clip-path: inset(46% 0 30% 0); transform: translateX(5px); }
  93% { opacity: 0.8; clip-path: inset(2% 0 84% 0); transform: translateX(3px); }
  95% { opacity: 0.85; clip-path: inset(56% 0 22% 0); transform: translateX(4.5px); }
}

/* ═══ hover：故障从周期爆发转为持续触发 ═══ */
.brand-wordmark:hover .brand-wordmark__text {
  animation: bw-jitter-hover 0.9s steps(1, end) infinite;
}
.brand-wordmark:hover .brand-wordmark__text::before {
  animation: bw-hover-a 0.7s steps(1, end) infinite;
}
.brand-wordmark:hover .brand-wordmark__text::after {
  animation: bw-hover-b 0.55s steps(1, end) infinite;
}

@keyframes bw-jitter-hover {
  0%, 100% { transform: none; }
  25% { transform: translate(-2px, 0.5px) skewX(-4deg); text-shadow: 0 0 18px var(--glitch-glow); }
  50% { transform: translate(1.5px, -1px) skewX(3deg); }
  75% { transform: translate(-1px, 0) skewX(-2deg); text-shadow: 0 0 14px var(--glitch-glow); }
}

@keyframes bw-hover-a {
  0%, 100% { opacity: 0.85; clip-path: inset(8% 0 72% 0); transform: translateX(-3.5px); }
  33% { opacity: 0.85; clip-path: inset(52% 0 20% 0); transform: translateX(-2px); }
  66% { opacity: 0.85; clip-path: inset(30% 0 44% 0); transform: translateX(-4.5px); }
}

@keyframes bw-hover-b {
  0%, 100% { opacity: 0.85; clip-path: inset(64% 0 8% 0); transform: translateX(3.5px); }
  50% { opacity: 0.85; clip-path: inset(14% 0 66% 0); transform: translateX(2px); }
}

.brand-wordmark:focus-visible {
  outline: 2px solid var(--acid);
  outline-offset: 2px;
}

/* ═══ 暗色主题：残影提亮为霓虹色，常驻一层微弱辉光 ═══ */
:root[data-theme='dark'] .brand-wordmark {
  --glitch-cyan: #22d3ee;
  --glitch-magenta: #ff2d78;
  --glitch-glow: rgba(34, 211, 238, 0.55);
  --glitch-idle-glow: rgba(34, 211, 238, 0.18);
}

@media (max-width: 639px) {
  .brand-wordmark__text {
    font-size: 14px;
    letter-spacing: 0.14em;
  }
}

@media (prefers-reduced-motion: reduce) {
  .brand-wordmark__text,
  .brand-wordmark:hover .brand-wordmark__text,
  .brand-wordmark__text::before,
  .brand-wordmark__text::after,
  .brand-wordmark:hover .brand-wordmark__text::before,
  .brand-wordmark:hover .brand-wordmark__text::after {
    animation: none;
  }

  .brand-wordmark__text::before,
  .brand-wordmark__text::after {
    opacity: 0;
  }
}
</style>
