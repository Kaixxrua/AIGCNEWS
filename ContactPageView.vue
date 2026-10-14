<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import GodotContactScene from '@/components/contact/GodotContactScene.vue'
import { useContactPageConfig } from '@/composables/useContactPageConfig'
import type { SiteContactEntry } from '@/services/site/contactPageApi'

/**
 * 联系合作页：内容由管理员在 monitor「站点 → 联系合作页」撰写（单语言）。
 * 路由守卫已在页面未启用时重定向，此处 enabled 判断仅作防御兜底。
 * 展示层收敛为「场景占满整张卡片 + 联系方式条目」：服务卡与 Markdown 正文不再渲染
 * （后台字段与 API 契约不动，仅展示层取舍）。
 */
const { contactPageConfig } = useContactPageConfig()
const config = contactPageConfig
const { t, locale } = useI18n()

/**
 * 后台文案只有中文。英文界面下，认得的原文换成英文；管理员改了文案就对不上，
 * 照原样显示，不会挂着过期的译文。
 */
const ENGLISH_CONFIG_TEXT = new Map<string, string>([
  ['联系与合作', 'Contact & Collaboration'],
  ['开发者交流群：聊 AI 编程与 Vibe Coding，也聊这个网站和各自的项目。', 'A developer group for AI coding and vibe coding, plus this site and everyone’s own projects.'],
  ['网站及 Vibe Coding 交流群', 'Site & Vibe Coding group'],
  // 桌面漫画版主按钮最宽 208px，长句会被截成省略号。
  ['点击加入 QQ 群', 'Join us on QQ'],
])
const shown = (text: string): string =>
  (locale.value.startsWith('en') ? ENGLISH_CONFIG_TEXT.get(text.trim()) ?? text : text)

const isExternalLink = (href: string): boolean => /^https?:\/\//i.test(href)
const linkAttrs = (entry: SiteContactEntry) =>
  isExternalLink(entry.href) ? { target: '_blank', rel: 'noopener noreferrer' } : {}

const failedQrEntries = ref<Record<number, boolean>>({})
const markQrFailed = (index: number) => {
  failedQrEntries.value = { ...failedQrEntries.value, [index]: true }
}

/** 只从管理员已配置的联系方式中选出一个主动作，不硬编码地址或文案。 */
const primaryEntryIndex = () => {
  const hrefIndex = config.value.contactEntries.findIndex((entry) => entry.href)
  return hrefIndex >= 0 ? hrefIndex : config.value.contactEntries.findIndex((entry) => entry.qrImageUrl)
}
const isPrimaryEntry = (index: number): boolean => index === primaryEntryIndex()
/** >2 条目时仅 primary 显示 QR（健壮性兜底；生产配置固定交流群 + 邮箱两条） */
const showQr = (index: number): boolean =>
  config.value.contactEntries.length <= 2 || isPrimaryEntry(index)
const treeBranch = (isLast: boolean): string => (isLast ? '└──' : '├──')

/** 场景的画质面板打开时，把场景层抬到标题与条目之上，面板不被遮挡。 */
const sceneOverlay = ref(false)
</script>

<template>
  <div v-if="config.enabled" class="contact-page">
    <!-- Godot HD-2D 原野占满整张卡片：标题在左上，联系方式条目收进底部像素框面板。 -->
    <header class="contact-hero" :class="{ 'contact-hero--scene-front': sceneOverlay }">
      <div class="hero-field">
        <GodotContactScene @overlay="sceneOverlay = $event" />
        <div class="hero-overlay" />
        <!-- 旧契约节点：仅为兼容既有选择器保留，不再渲染任何可见内容。 -->
        <span class="hero-beam hero-beam--a" hidden aria-hidden="true" />
        <span class="hero-beam hero-beam--b" hidden aria-hidden="true" />
        <span class="hero-beam hero-beam--c" hidden aria-hidden="true" />
        <span class="hero-beam hero-beam--d" hidden aria-hidden="true" />
        <span class="hero-scanline" hidden aria-hidden="true" />
      </div>
      <!-- 保留旧契约节点；视觉呈现改由 signal-led eyebrow 承担。 -->
      <p class="term-line contact-command" aria-hidden="true">
        <span class="term-prompt">$</span> aigcnews contact --list<span class="term-caret" />
      </p>
      <div class="hero-inner">
        <div class="hero-heading">
          <p class="contact-kicker">{{ t('contact.kicker') }}</p>
          <h1 class="contact-title comic-title">{{ shown(config.title) }}</h1>
          <p v-if="config.subtitle" class="contact-subtitle">{{ shown(config.subtitle) }}</p>
        </div>
        <div v-if="config.contactEntries.length" class="hero-dock">
          <p class="contact-hero-note">{{ t('contact.heroNote') }}</p>
          <ul class="entry-list" :class="{ 'entry-list--many': config.contactEntries.length > 2 }">
            <li
              v-for="(entry, index) in config.contactEntries"
              :key="`${index}-${entry.label}`"
              class="entry-item"
              :class="{ 'entry-item--primary': isPrimaryEntry(index), 'entry-item--qr': entry.qrImageUrl && showQr(index) }"
            >
              <span class="tree-branch" aria-hidden="true">{{ treeBranch(index === config.contactEntries.length - 1) }}</span>
              <div class="entry-body">
                <div class="entry-meta">
                  <span class="entry-label">{{ shown(entry.label) }}</span>
                  <span v-if="isPrimaryEntry(index)" class="entry-badge">{{ t('contact.primaryBadge') }}</span>
                </div>
                <div v-if="entry.qrImageUrl && showQr(index)" class="entry-qr-frame">
                  <img v-if="!failedQrEntries[index]" class="entry-qr" :src="entry.qrImageUrl" :alt="shown(entry.label)" loading="lazy" @error="markQrFailed(index)" />
                  <div v-else class="entry-qr-fallback" role="img" :aria-label="t('contact.qrUnavailable')">{{ t('contact.qrUnavailable') }}</div>
                </div>
                <a v-if="entry.href" class="entry-value entry-value--link" :class="{ 'entry-action--primary': isPrimaryEntry(index) }" :href="entry.href" v-bind="linkAttrs(entry)">
                  <span class="entry-link-text">{{ shown(entry.value) || entry.href }}</span><span class="entry-arrow" aria-hidden="true">↗</span>
                </a>
                <span v-else-if="entry.value" class="entry-value">{{ shown(entry.value) }}</span>
                <span v-if="entry.qrImageUrl && showQr(index) && !failedQrEntries[index]" class="entry-qr-hint">{{ t('contact.qrHint') }}</span>
              </div>
            </li>
          </ul>
        </div>
      </div>
    </header>
  </div>
</template>

<style scoped>
/* Hallmark · macrostructure: Atmosphere-First contact landing · theme: project-managed (style.css tokens) · voice: signal-led editorial · motion: 默认静态原野截图，访客选画质开启后才内嵌 Godot 实时原野（截图 .45s 淡出）；reduced-motion → 无淡变
 * Hallmark · pre-emit critique: P5 H5 E4 S5 R5 V5
 * contrast: pass · honest: pass · chrome: pass · tokens: pass（纸色经 --contact-scene-bg 与场景边缘融合严格同色）· responsive: pass · icons: pass · nav/footer: app-shell（不在本次范围） */
.contact-page {
  --contact-mono: ui-monospace, 'JetBrains Mono', 'Fira Code', Menlo, Consolas, 'Liberation Mono', monospace;
  --contact-display: 'DM Sans', Inter, ui-sans-serif, system-ui, sans-serif;
  --cs-1: 0.25rem;
  --cs-2: 0.5rem;
  --cs-3: 0.75rem;
  --cs-4: 1rem;
  --cs-5: 1.5rem;
  --cs-6: 2rem;
  --cs-dock-clear: 112px; /* 与 LayoutView/AppDock 的底部安全区契约，勿随排版节奏改动 */
  --contact-gutter: clamp(1rem, 3vw, 2rem);
  /* 场景最外层与卡片外的严格同色契约：边缘融合/清屏/页面背景都读这一个 token */
  --contact-scene-bg: var(--paper-raised);
  --contact-hero-ink: var(--ink);
  --contact-hero-muted: color-mix(in srgb, var(--ink) 72%, transparent);
  --contact-hero-rule: color-mix(in srgb, var(--ink) 22%, transparent);
  --contact-primary-surface: color-mix(in srgb, var(--paper-raised) 86%, var(--acid) 14%);
  /* 酸绿文字在昼场亮天上需压暗保对比；暗主题用纯 acid */
  --contact-acid-ink: color-mix(in srgb, var(--acid) 52%, var(--ink));
  position: relative;
  width: 100%;
  height: 100%;
  box-sizing: border-box;
  overflow: hidden; /* 不再是滚动容器：右侧滚动条消除 */
  background: var(--contact-scene-bg);
}

:global(:root[data-theme='dark'] .contact-page) {
  --contact-acid-ink: var(--acid);
}

/* 保留旧测试/契约节点，但不让实现细节主导新的视觉语言。 */
.term-line,
.contact-command {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}
.term-caret { display: none; }
.term-prompt { color: inherit; }
.tree-branch {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

/* ── Hero：场景占满整张卡片，UI 以 pointer-events 分层浮在场景上 ── */
.contact-hero {
  position: absolute;
  inset: 0;
  overflow: hidden;
  isolation: isolate;
  background: transparent;
}
.hero-field {
  position: absolute;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  pointer-events: auto;
}
.contact-hero--scene-front .hero-field { z-index: 2; }
/* 桌面端站点顶栏压住卡片上缘约 47–71px；场景按钮、状态与画质面板从标题行起排（标题本身已让开顶栏）。 */
@media (min-width: 64rem) {
  .hero-field { --scene-safe-top: calc(clamp(1rem, 3vw, 2rem) + 2.5rem); }
}
/* 可读性遮罩：只压上缘标题区与下缘条目区，中间场景完整露出 */
.hero-overlay {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background:
    linear-gradient(180deg, color-mix(in srgb, var(--contact-scene-bg) 42%, transparent) 0%, transparent 26%),
    linear-gradient(0deg, color-mix(in srgb, var(--contact-scene-bg) 34%, transparent) 0%, transparent 30%);
}
.hero-inner {
  position: relative;
  z-index: 1;
  display: grid;
  height: 100%;
  box-sizing: border-box;
  grid-template-rows: auto 1fr auto;
  padding: var(--contact-gutter) var(--contact-gutter) 0;
  pointer-events: none; /* 镂空区域把指针让给场景交互 */
}

.hero-heading {
  max-width: 34rem;
  min-width: 0;
  align-self: start;
  justify-self: start;
  text-align: left;
}
.contact-kicker {
  display: inline-flex;
  align-items: center;
  gap: var(--cs-4);
  margin: 0;
  color: var(--contact-acid-ink);
  font-family: var(--contact-mono);
  font-size: 0.6875rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  line-height: 1;
  text-transform: uppercase;
}
.contact-kicker::after {
  content: '';
  display: block;
  width: clamp(2rem, 5vw, 3.25rem);
  height: 1px;
  background: var(--contact-hero-rule);
}
.contact-title {
  max-width: 18ch;
  margin: var(--cs-4) 0 0;
  color: var(--contact-hero-ink);
  font-family: var(--contact-display);
  font-size: clamp(2rem, 1.2rem + 3.6vw, 3.25rem);
  font-weight: 700;
  letter-spacing: -0.055em;
  line-height: 1.06;
  overflow-wrap: anywhere;
  min-width: 0;
  /* 像素场景上的压边：借纸色做硬偏移描影，昼场夜场都读得清 */
  text-shadow: 2px 2px 0 color-mix(in srgb, var(--contact-scene-bg) 72%, transparent);
}
.contact-subtitle {
  max-width: 34rem;
  margin: var(--cs-3) 0 0;
  color: var(--contact-hero-muted);
  font-family: var(--contact-display);
  font-size: clamp(0.875rem, 0.82rem + 0.25vw, 1rem);
  line-height: 1.7;
  white-space: pre-line;
  overflow-wrap: anywhere;
  text-shadow: 1px 1px 0 color-mix(in srgb, var(--contact-scene-bg) 66%, transparent);
}

/* ── 底部条目 dock：八方旅人式对话框面板，右下对齐 ── */
.hero-dock {
  display: flex;
  min-width: 0;
  max-height: 100%;
  flex-direction: column;
  align-items: stretch;
  gap: var(--cs-2);
  grid-row: 3; /* 只有 heading+dock 两个子项：钉进第三行（底部 auto 行），1fr 中行只吃余量 */
  justify-self: end;
  padding-bottom: var(--cs-dock-clear);
  pointer-events: none;
  overflow-y: auto;
  scrollbar-width: none; /* 任何情况下不露出滚动条 */
}
.hero-dock::-webkit-scrollbar { display: none; }
.contact-hero-note {
  align-self: flex-end;
  margin: 0 var(--cs-3) 0 0;
  color: #efe4bd;
  font-family: var(--contact-mono);
  font-size: 0.6875rem;
  line-height: 1.6;
  text-align: right;
  text-shadow: 0 1px 3px rgb(0 0 0/.9);
}
.contact-hero-note,
.entry-list { pointer-events: auto; }
.contact-hero-note::before {
  content: '＋';
  margin-right: var(--cs-2);
  color: var(--contact-acid-ink);
}
.entry-list {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--cs-3);
  margin: 0;
  padding: 0;
  list-style: none;
}
.entry-list--many { grid-template-columns: repeat(auto-fit, minmax(min(100%, 9.5rem), 1fr)); }

.entry-item {
  position: relative;
  min-width: 0;
  /* 像素框面板：纸色 88% 底 + 硬描边 + 3px 硬偏移投影 */
  overflow: hidden;
  color: #f6efd8;
  background:
    linear-gradient(135deg, rgb(64 70 45/.94), rgb(25 36 27/.94)),
    rgb(25 36 27/.94);
  border: 1px solid rgb(232 207 137/.74);
  box-shadow: 0 12px 28px rgb(5 12 8/.32), inset 0 0 0 3px rgb(10 18 13/.36);
  backdrop-filter: blur(9px) saturate(.85);
}
.entry-item--primary {
  background:
    linear-gradient(135deg, rgb(70 76 48/.95), rgb(27 39 29/.95)),
    rgb(27 39 29/.95);
}
/* primary 酸性角标：右上角折角 */
.entry-item--primary::after {
  content: '';
  position: absolute;
  top: -2px;
  right: -2px;
  width: 0;
  height: 0;
  border-style: solid;
  border-width: 0 1.35rem 1.35rem 0;
  border-color: transparent #d8c06f transparent transparent;
  pointer-events: none;
}
.entry-body {
  display: flex;
  min-width: 0;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--cs-2);
  padding: var(--cs-3) var(--cs-4);
}
.entry-item--qr .entry-body {
  display: grid;
  grid-template-areas: 'meta qr' 'value qr' 'hint qr';
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  column-gap: var(--cs-4);
  row-gap: var(--cs-2);
}
.entry-meta {
  display: flex;
  grid-area: meta;
  min-width: 0;
  align-items: center;
  gap: var(--cs-3);
  flex-wrap: wrap;
}
.entry-label {
  min-width: 0;
  color: #fff8df;
  font-family: var(--contact-display);
  font-size: 0.9375rem;
  font-weight: 700;
  letter-spacing: -0.01em;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
.entry-badge {
  padding: var(--cs-1) var(--cs-2);
  color: #172019;
  background: #dcc676;
  border: 1px solid #f3dda0;
  font-family: var(--contact-mono);
  font-size: 0.625rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  line-height: 1.2;
  white-space: nowrap;
}
.entry-value {
  max-width: 100%;
  color: #f7eed1;
  font-family: var(--contact-display);
  font-size: 0.875rem;
  font-weight: 600;
  line-height: 1.55;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.entry-item--qr .entry-value { grid-area: value; }
.entry-value--link {
  text-decoration: underline;
  text-decoration-color: var(--acid-strong);
  text-underline-offset: 0.2em;
}
.entry-value--link:hover {
  color: var(--acid-ink);
  background: var(--acid);
  text-decoration-color: transparent;
}
.entry-value--link:active { color: var(--paper); background: var(--ink); }
.entry-action--primary {
  display: inline-flex;
  width: fit-content;
  max-width: 100%;
  align-items: center;
  gap: var(--cs-2);
  min-height: 2.25rem;
  padding: 0.45rem 0.75rem;
  color: #172019;
  background: #dbc570;
  border: 1px solid #f0dda0;
  text-decoration: none;
  white-space: nowrap;
  overflow: hidden;
}
.entry-action--primary:hover { color:#fff8df;background:#52603d;border-color:#f0dda0; }
.entry-action--primary:active { color: var(--ink); background: var(--paper-muted); }
.entry-link-text { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.entry-arrow { flex: 0 0 auto; font-size: 1rem; line-height: 0.8; }
.entry-qr-frame {
  display: grid;
  grid-area: qr;
  width: clamp(64px, 12vh, 96px);
  max-width: 100%;
  aspect-ratio: 1;
  box-sizing: border-box;
  place-items: center;
  padding: var(--cs-1);
  background:#f3edcf;
  border:1px solid #d5bf79;
  box-shadow:inset 0 0 0 3px rgb(95 76 38/.16);
}
.entry-qr { display: block; width: 100%; height: 100%; object-fit: contain; image-rendering: pixelated; }
.entry-qr-fallback {
  padding: var(--cs-1);
  color: var(--ink-secondary);
  font-family: var(--contact-mono);
  font-size: 0.6875rem;
  line-height: 1.6;
  text-align: center;
}
.entry-qr-fallback::before { content: '[!] '; color: var(--ink-muted); }
.entry-qr-hint {
  grid-area: hint;
  color:#d2c8a5;
  font-family: var(--contact-mono);
  font-size: 0.6875rem;
  line-height: 1.5;
}
.entry-qr-hint::before { content: '› '; color: var(--acid-strong); }

/* 手机与平板：标题和副标题放在场景上方的纸面上，不压在截图上（深色主题下浅色大标题会和亮天空糊成一片，
 * 副标题压在村庄上也读不清）。场景占下面剩下的高度，联系方式照旧浮在场景底部。 */
@media (max-width: 63.99rem) {
  .contact-hero {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto minmax(0, 1fr);
  }
  .hero-field {
    position: relative;
    inset: auto;
    grid-row: 2;
    grid-column: 1;
  }
  /* 标题不在场景上了，上缘那道遮罩也就不要了；下缘的留给联系方式 */
  .hero-overlay { background: linear-gradient(0deg, color-mix(in srgb, var(--contact-scene-bg) 34%, transparent) 0%, transparent 30%); }
  .hero-inner { display: contents; }
  .hero-heading {
    grid-row: 1;
    grid-column: 1;
    max-width: none;
    padding: var(--contact-gutter) var(--contact-gutter) var(--cs-4);
  }
  .hero-dock {
    position: relative;
    z-index: 1;
    grid-row: 2;
    grid-column: 1;
    align-self: end;
    margin-inline: var(--contact-gutter);
  }
}
@media (min-width: 48rem) {
  .hero-dock { width: min(22rem, 42%); }
  .entry-qr-frame { width: clamp(84px, 13vh, 116px); }
  .entry-body { padding: var(--cs-4); }
}
@media (max-width: 47.99rem) {
  .contact-page { --contact-gutter: var(--cs-4); }
  .hero-dock { width: auto; justify-self: stretch; }
  .contact-hero-note { text-align: left; }
  .entry-qr-frame,
  .entry-qr-hint { display: none; }
  .entry-item--qr .entry-body {
    display: flex;
    padding: var(--cs-2) var(--cs-3);
  }
}
@media (max-width: 30rem) {
  .contact-hero-note,
  .entry-label,
  .entry-badge { display: none; }
  .hero-dock { width: auto; max-width: calc(100% - 2 * var(--contact-gutter) - 1rem); justify-self: end; }
  .entry-action--primary { min-height: 2.75rem; }
}
/* 矮屏（横持手机等）：dock 压缩间距，QR 已被 vh 钳制自动缩小 */
@media (max-height: 30rem) {
  .hero-dock { gap: var(--cs-2); }
  .entry-body { padding: var(--cs-2) var(--cs-3); }
  .contact-title { font-size: clamp(1.5rem, 1.1rem + 2.4vw, 2.25rem); }
}
/* ── 桌面漫画版（contact-C）：站点漫画外壳下，标题与副标题回到纸面，原野收进上缘斜切的墨线画框，
 * 联系方式成为压在画框右下角的纸质漫画卡。墨线、投影、网点、笔刷都是按概念图逐像素量出后程序化生成的
 * 3x 九宫格素材（camp-scene/comic/ct-*.webp，暗色主题用 -night 版），不用 CSS 近似。
 * 阅读优先：正文直立、≥13px；斜体只给标题、标签与按钮。手机与旧布局不受影响（选择器都挂在
 * .app-shell--comic-page 下，且只在 ≥64rem 生效）。 */
@media (min-width: 64rem) {
  #app .app-shell--comic-page .contact-page {
    --ct-frame: url('/camp-scene/comic/ct-frame.webp?v=1');
    --ct-frame-dots: url('/camp-scene/comic/ct-frame-dots.webp?v=1');
    --ct-brush: url('/camp-scene/comic/ct-brush.webp?v=1');
    --ct-card: url('/camp-scene/comic/ct-card.webp?v=1');
    --ct-note: url('/camp-scene/comic/ct-note.webp?v=1');
    --ct-badge: url('/camp-scene/comic/ct-badge.webp?v=1');
    --ct-cta: url('/camp-scene/comic/ct-cta.webp?v=1');
    --ct-qr: url('/camp-scene/comic/ct-qr.webp?v=1');
    --ct-act: url('/camp-scene/comic/ct-act.webp?v=1');
    --ct-tag: url('/camp-scene/comic/ct-tag.webp?v=1');
    --ct-panel: url('/camp-scene/comic/ct-panel.webp?v=1');
    --ct-opt: url('/camp-scene/comic/ct-opt.webp?v=1');
    --ct-opt-on: url('/camp-scene/comic/ct-opt-on.webp?v=1');
    --ct-navy: #14223c;
    --ct-copy: #162b4b;
    --ct-on-lime: #0b1422;
    padding: 0 13px 28px 8px;
    background: transparent;
  }
  :root[data-theme='dark'] #app .app-shell--comic-page .contact-page {
    --ct-frame: url('/camp-scene/comic/ct-frame-night.webp?v=1');
    --ct-frame-dots: url('/camp-scene/comic/ct-frame-dots-night.webp?v=1');
    --ct-brush: url('/camp-scene/comic/ct-brush-night.webp?v=1');
    --ct-card: url('/camp-scene/comic/ct-card-night.webp?v=1');
    --ct-note: url('/camp-scene/comic/ct-note-night.webp?v=1');
    --ct-badge: url('/camp-scene/comic/ct-badge-night.webp?v=1');
    --ct-cta: url('/camp-scene/comic/ct-cta-night.webp?v=1');
    --ct-qr: url('/camp-scene/comic/ct-qr-night.webp?v=1');
    --ct-act: url('/camp-scene/comic/ct-act-night.webp?v=1');
    --ct-tag: url('/camp-scene/comic/ct-tag-night.webp?v=1');
    --ct-panel: url('/camp-scene/comic/ct-panel-night.webp?v=1');
    --ct-opt: url('/camp-scene/comic/ct-opt-night.webp?v=1');
    --ct-opt-on: url('/camp-scene/comic/ct-opt-on-night.webp?v=1');
    --ct-navy: var(--ink);
    --ct-copy: var(--ink);
  }

  /* 标题行与画框共用一个网格：hero-inner 让出盒子；标题行只占 85px，副标题落进画框斜切让出的左上空白 */
  #app .app-shell--comic-page .contact-hero {
    position: relative;
    inset: auto;
    display: grid;
    height: 100%;
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: 85px minmax(0, 1fr);
    row-gap: 0;
    overflow: visible;
  }
  #app .app-shell--comic-page .hero-inner { display: contents; }
  #app .app-shell--comic-page .hero-heading {
    position: relative;
    z-index: 5;
    grid-row: 1;
    grid-column: 1;
    align-self: start;
    max-width: none;
    padding: 9px 0 0 25px;
    pointer-events: auto;
  }
  #app .app-shell--comic-page .contact-kicker { display: none; }
  #app .app-shell--comic-page .contact-title.comic-title {
    max-width: none;
    margin: 0 36px 0 0;
    color: var(--ct-navy);
    font-size: 62px;
    letter-spacing: -5px;
    line-height: 1.12;
    -webkit-text-stroke: .5px currentColor;
    text-shadow: 1.5px 0 var(--paper), -1.5px 0 var(--paper), 0 1.5px var(--paper), 0 -1.5px var(--paper), 1.2px 1.2px var(--paper), -1.2px -1.2px var(--paper), 1.2px -1.2px var(--paper), -1.2px 1.2px var(--paper);
  }
  /* 酸绿笔刷：干笔收尾的斜向笔触，左端两笔深色飞白 */
  #app .app-shell--comic-page .contact-title.comic-title::before {
    inset: auto;
    top: .13em;
    left: -.5em;
    width: 5.484em;
    height: 1em;
    border-radius: 0;
    background: var(--ct-brush) 0 0 / 100% 100% no-repeat;
    transform: none;
  }
  #app .app-shell--comic-page .contact-title.comic-title::after {
    right: -25px;
    top: -6px;
    width: 22px;
    height: 24px;
    clip-path: none;
    mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 26 24'%3E%3Cpath d='M1.5 1.8 5.2.6 7 13.4 4.4 14.2zM22.6 2.4 25.4 5 10.6 23.4 8 21.2z'/%3E%3C/svg%3E") center / contain no-repeat;
  }
  #app .app-shell--comic-page .contact-subtitle {
    max-width: none;
    margin: .5px 0 0 4px;
    color: var(--ct-copy);
    font-family: inherit;
    font-size: 16.4px;
    font-style: italic;
    font-weight: 800;
    line-height: 1.5;
    text-shadow: none;
  }

  /* 画框：场景按概念图的斜切轮廓裁切；墨线与实心投影由 contact-hero::after 盖在上面（画框会溢出场景盒子） */
  #app .app-shell--comic-page .hero-field {
    --scene-safe-top: 14px;
    position: relative;
    inset: auto;
    z-index: 0;
    grid-row: 2;
    grid-column: 1;
    clip-path: polygon(1.6px 53.6px, calc(100% - 1.6px) 1.6px, calc(100% - 1.6px) calc(100% - 1.6px), 1.6px calc(100% - 16.6px));
  }
  #app .app-shell--comic-page .contact-hero--scene-front .hero-field { z-index: 3; }
  #app .app-shell--comic-page .contact-hero::after {
    content: '';
    position: absolute;
    z-index: 4;
    grid-row: 2;
    grid-column: 1;
    inset: -2px -8px -11px -2px;
    pointer-events: none;
    border-style: solid;
    border-color: transparent;
    border-width: 180px 143px 143px 167px;
    border-image: var(--ct-frame) 540 429 429 501 / 180px 143px 143px 167px stretch;
  }
  #app .app-shell--comic-page .hero-overlay { display: none; }
  /* 静态截图上的网点只压画框三个角，实时场景与画质面板时撤掉 */
  #app .app-shell--comic-page .hero-field:has(.godot-contact-scene--poster)::after {
    content: '';
    position: absolute;
    z-index: 2;
    inset: -2px -8px -11px -2px;
    pointer-events: none;
    border-style: solid;
    border-color: transparent;
    border-width: 180px 143px 143px 167px;
    border-image: var(--ct-frame-dots) 540 429 429 501 / 180px 143px 143px 167px stretch;
  }

  /* 场景自带按钮：纸面墨线小签 + 白底墨线按钮（概念图没有这两个控件，沿用联系卡的笔墨） */
  #app .app-shell--comic-page .hero-field :deep(.scene-actions) { right: 20px; gap: 12px; }
  #app .app-shell--comic-page .hero-field :deep(.scene-actions button) {
    position: relative;
    isolation: isolate;
    color: var(--ct-navy);
    background: transparent;
    border: 0;
    border-radius: 0;
    box-shadow: none;
    backdrop-filter: none;
  }
  #app .app-shell--comic-page .hero-field :deep(.scene-actions button::after) {
    content: '';
    position: absolute;
    z-index: -1;
    inset: -2px -6px -7px -2px;
    border-style: solid;
    border-color: transparent;
    border-width: 12px 18px 17px 12px;
    border-image: var(--ct-act) 36 54 51 36 fill / 12px 18px 17px 12px stretch;
  }
  #app .app-shell--comic-page .hero-field :deep(.scene-actions button:hover) { color: var(--ct-navy); background: transparent; transform: translate(-1px, -1px); }
  #app .app-shell--comic-page .hero-field :deep(.scene-actions button:focus-visible) { outline: 3px solid var(--rule-strong); outline-offset: 5px; }
  #app .app-shell--comic-page .hero-field :deep(.scene-actions .scene-launch) {
    height: 42px;
    padding: 0 17px 0 14px;
    font-family: inherit;
    font-size: 15px;
    font-style: italic;
    font-weight: 900;
    line-height: 1;
    letter-spacing: 0;
  }
  #app .app-shell--comic-page .hero-field :deep(.scene-poster-badge) {
    position: relative;
    isolation: isolate;
    padding: 7px 11px 7px 10px;
    color: var(--ct-navy);
    background: transparent;
    border: 0;
    font-family: inherit;
    font-size: 13px;
    font-style: italic;
    font-weight: 900;
    line-height: 1;
    letter-spacing: .02em;
  }
  #app .app-shell--comic-page .hero-field :deep(.scene-poster-badge::after) {
    content: '';
    position: absolute;
    z-index: -1;
    inset: -2px -5px -6px -2px;
    border-style: solid;
    border-color: transparent;
    border-width: 11px 15px 15px 12px;
    border-image: var(--ct-tag) 33 45 45 36 fill / 11px 15px 15px 12px stretch;
  }

  /* 画质面板：与联系卡同一套纸面漫画卡 */
  #app .app-shell--comic-page .hero-field :deep(.scene-chooser-panel) {
    position: relative;
    isolation: isolate;
    width: min(28rem, 100%);
    padding: 22px 24px 22px 22px;
    color: var(--ink);
    background: transparent;
    border: 0;
    box-shadow: none;
  }
  #app .app-shell--comic-page .hero-field :deep(.scene-chooser-panel::after) {
    content: '';
    position: absolute;
    z-index: -1;
    inset: -2px -10px -11px -2px;
    border-style: solid;
    border-color: transparent;
    border-width: 42px 74px 55px 32px;
    border-image: var(--ct-panel) 126 222 165 96 fill / 42px 74px 55px 32px stretch;
  }
  #app .app-shell--comic-page .hero-field :deep(.scene-chooser-title) { color: var(--ct-navy); font-family: inherit; font-size: 21px; font-style: italic; font-weight: 900; line-height: 1.3; letter-spacing: 0; }
  #app .app-shell--comic-page .hero-field :deep(.scene-chooser-note) { color: var(--ink-secondary); font-size: 14px; }
  #app .app-shell--comic-page .hero-field :deep(.scene-chooser-hint) { color: var(--ink-secondary); font-size: 13px; }
  #app .app-shell--comic-page .hero-field :deep(.scene-chooser-options) { gap: 12px; }
  #app .app-shell--comic-page .hero-field :deep(.scene-option) {
    position: relative;
    isolation: isolate;
    background: transparent;
    border: 0;
  }
  #app .app-shell--comic-page .hero-field :deep(.scene-option::after) {
    content: '';
    position: absolute;
    z-index: -1;
    inset: -2px -2px -3px -2px;
    border-style: solid;
    border-color: transparent;
    border-width: 12px 12px 13px 12px;
    border-image: var(--ct-opt) 36 36 39 36 fill / 12px 12px 13px 12px stretch;
  }
  #app .app-shell--comic-page .hero-field :deep(.scene-option:hover) { background: transparent; transform: translate(-1px, -1px); }
  #app .app-shell--comic-page .hero-field :deep(.scene-option:has(input:checked)) { background: transparent; }
  #app .app-shell--comic-page .hero-field :deep(.scene-option:has(input:checked)::after) {
    inset: -2px -5px -6px -2px;
    border-width: 12px 15px 16px 12px;
    border-image: var(--ct-opt-on) 36 45 48 36 fill / 12px 15px 16px 12px stretch;
  }
  #app .app-shell--comic-page .hero-field :deep(.scene-option input) { accent-color: var(--rule-strong); }
  #app .app-shell--comic-page .hero-field :deep(.scene-option-body strong) { color: var(--ink); font-size: 15.5px; }
  #app .app-shell--comic-page .hero-field :deep(.scene-option-body em) {
    color: var(--ct-on-lime);
    background: var(--acid);
    border: 1.5px solid var(--rule-strong);
    font-family: inherit;
    font-size: 11.5px;
    font-style: italic;
    font-weight: 900;
    line-height: 1.3;
    letter-spacing: 0;
  }
  #app .app-shell--comic-page .hero-field :deep(.scene-option-body small) { color: var(--ink-secondary); font-size: 13px; }
  #app .app-shell--comic-page .hero-field :deep(.scene-option-size) { color: var(--ink-secondary); font-family: inherit; font-size: 12.5px; font-style: normal; font-weight: 700; line-height: 1.4; font-variant-numeric: tabular-nums; }
  #app .app-shell--comic-page .hero-field :deep(.scene-chooser-actions) { gap: 16px; }
  #app .app-shell--comic-page .hero-field :deep(.scene-chooser-actions button) {
    position: relative;
    isolation: isolate;
    min-height: 42px;
    padding: 0 20px;
    background: transparent;
    border: 0;
    border-radius: 0;
    box-shadow: none;
    font-family: inherit;
    font-size: 15px;
    font-style: italic;
    font-weight: 900;
  }
  #app .app-shell--comic-page .hero-field :deep(.scene-chooser-actions button::after) {
    content: '';
    position: absolute;
    z-index: -1;
    inset: -2px -6px -7px -2px;
    border-style: solid;
    border-color: transparent;
    border-width: 12px 18px 17px 12px;
    border-image: var(--ct-act) 36 54 51 36 fill / 12px 18px 17px 12px stretch;
  }
  #app .app-shell--comic-page .hero-field :deep(.scene-chooser-cancel) { color: var(--ct-navy); }
  #app .app-shell--comic-page .hero-field :deep(.scene-chooser-actions .scene-chooser-enter) { color: var(--ct-on-lime); }
  #app .app-shell--comic-page .hero-field :deep(.scene-chooser-actions .scene-chooser-enter::after) {
    inset: -2px -7px -7px -2px;
    border-width: 14px 21px 19px 16px;
    border-image: var(--ct-cta) 42 63 57 48 fill / 14px 21px 19px 16px stretch;
  }
  #app .app-shell--comic-page .hero-field :deep(.scene-chooser-actions button:hover) { background: transparent; transform: translate(-1px, -1px); }
  #app .app-shell--comic-page .hero-field :deep(.scene-chooser-cancel:hover) { color: var(--ct-navy); }
  #app .app-shell--comic-page .hero-field :deep(.scene-chooser-actions .scene-chooser-enter:hover) { color: var(--ct-on-lime); box-shadow: none; }
  #app .app-shell--comic-page .hero-field :deep(.scene-chooser button:focus-visible) { outline: 3px solid var(--rule-strong); outline-offset: 5px; }

  /* 联系卡：压在画框右下角的斜平行四边形纸卡，便签条骑在它左上角 */
  #app .app-shell--comic-page .hero-dock {
    position: relative;
    z-index: 2;
    grid-row: 2;
    grid-column: 1;
    width: 435px;
    max-width: calc(100% - 60px);
    max-height: none;
    align-self: end;
    justify-self: end;
    gap: 0;
    margin: 0 25px 24px 0;
    padding: 0;
    overflow: visible;
  }
  #app .app-shell--comic-page .contact-hero-note {
    position: relative;
    z-index: 3;
    isolation: isolate;
    align-self: flex-start;
    min-width: 312px;
    min-height: 50px;
    box-sizing: border-box;
    margin: 0 0 -19px 29px;
    padding: 16px 22px 14px 20px;
    color: var(--ct-navy);
    background: transparent;
    border: 0;
    box-shadow: none;
    font-family: inherit;
    font-size: 16.5px;
    font-style: normal;
    font-weight: 800;
    line-height: 20px;
    -webkit-text-stroke: .2px currentColor;
    text-align: left;
    text-shadow: none;
    transform: none;
  }
  #app .app-shell--comic-page .contact-hero-note::before { margin-right: 6px; color: var(--ct-navy); font-weight: 900; }
  #app .app-shell--comic-page .contact-hero-note::after {
    content: '';
    position: absolute;
    z-index: -1;
    inset: -3px -8px -9px -3px;
    pointer-events: none;
    border-style: solid;
    border-color: transparent;
    border-width: 17px 24px 23px 25px;
    border-image: var(--ct-note) 51 72 69 75 fill / 17px 24px 23px 25px stretch;
  }
  #app .app-shell--comic-page .entry-list { gap: 22px; }
  #app .app-shell--comic-page .entry-item,
  #app .app-shell--comic-page .entry-item--primary {
    isolation: isolate;
    overflow: visible;
    color: var(--ink);
    background: transparent;
    border: 0;
    border-radius: 0;
    box-shadow: none;
    backdrop-filter: none;
  }
  #app .app-shell--comic-page .entry-item::after,
  #app .app-shell--comic-page .entry-item--primary::after {
    content: '';
    position: absolute;
    z-index: -1;
    inset: -2px -11px -11px -2px;
    width: auto;
    height: auto;
    pointer-events: none;
    border-style: solid;
    border-color: transparent;
    border-radius: 0;
    border-width: 36px 75px 51px 30px;
    border-image: var(--ct-card) 108 225 153 90 fill / 36px 75px 51px 30px stretch;
  }
  #app .app-shell--comic-page .entry-body {
    position: relative;
    z-index: 1;
    gap: 10px;
    padding: 28px 29px 20px 36px;
  }
  #app .app-shell--comic-page .entry-item--qr .entry-body {
    grid-template-areas: 'label label' 'badge qr' 'value qr' 'hint qr';
    grid-template-columns: minmax(0, 1fr) 131px;
    grid-template-rows: auto auto auto minmax(0, 1fr);
    align-items: start;
    column-gap: 12px;
    row-gap: 0;
    padding: 28px 29px 20px 29px;
  }
  #app .app-shell--comic-page .entry-item--qr .entry-meta { display: contents; }
  #app .app-shell--comic-page .entry-label {
    grid-area: label;
    margin: 0 0 0 10px;
    color: var(--ct-navy);
    font-family: inherit;
    font-size: 21px;
    font-style: italic;
    font-weight: 900;
    letter-spacing: 0;
    line-height: 26px;
    -webkit-text-stroke: .35px currentColor;
  }
  #app .app-shell--comic-page .entry-badge {
    position: relative;
    isolation: isolate;
    grid-area: badge;
    justify-self: start;
    display: inline-grid;
    min-width: 94px;
    height: 28px;
    box-sizing: border-box;
    margin: 18px 0 0 4px;
    padding: 0 12px 0 14px;
    place-items: center;
    color: var(--ct-on-lime);
    background: transparent;
    border: 0;
    border-radius: 0;
    box-shadow: none;
    font-family: inherit;
    font-size: 15px;
    font-style: italic;
    font-weight: 900;
    line-height: 1;
    letter-spacing: 0;
    transform: none;
  }
  #app .app-shell--comic-page .entry-badge::after {
    content: '';
    position: absolute;
    z-index: -1;
    inset: -2px -5px -6px -2px;
    border-style: solid;
    border-color: transparent;
    border-width: 12px 17px 16px 14px;
    border-image: var(--ct-badge) 36 51 48 42 fill / 12px 17px 16px 14px stretch;
  }
  #app .app-shell--comic-page .entry-value {
    color: var(--ink);
    font-family: inherit;
    font-size: 15px;
    font-weight: 700;
  }
  #app .app-shell--comic-page .entry-value--link {
    text-decoration-color: var(--acid);
    text-decoration-thickness: 3px;
  }
  #app .app-shell--comic-page .entry-action--primary {
    position: relative;
    isolation: isolate;
    grid-area: value;
    justify-self: start;
    min-width: 208px;
    min-height: 47px;
    box-sizing: border-box;
    gap: 12px;
    margin: 8px 0 0;
    padding: 0 22px 0 24px;
    color: var(--ct-on-lime);
    background: transparent;
    border: 0;
    border-radius: 0;
    box-shadow: none;
    font-size: 19px;
    font-style: italic;
    font-weight: 900;
    text-decoration: none;
    transition: transform .12s ease;
  }
  #app .app-shell--comic-page .entry-action--primary::after {
    content: '';
    position: absolute;
    z-index: -1;
    inset: -2px -7px -7px -2px;
    border-style: solid;
    border-color: transparent;
    border-width: 14px 21px 19px 16px;
    border-image: var(--ct-cta) 42 63 57 48 fill / 14px 21px 19px 16px stretch;
  }
  #app .app-shell--comic-page .entry-action--primary:hover {
    color: var(--ct-on-lime);
    background: transparent;
    box-shadow: none;
    transform: translate(-1px, -1px);
  }
  #app .app-shell--comic-page .entry-action--primary:active {
    color: var(--ct-on-lime);
    background: transparent;
    box-shadow: none;
    transform: translate(2px, 2px);
  }
  #app .app-shell--comic-page .entry-value--link:focus-visible { outline: 3px solid var(--rule-strong); outline-offset: 5px; }
  #app .app-shell--comic-page .entry-arrow { font-size: 19px; font-style: normal; }
  /* 二维码：白底保扫码对比（暗色主题也是白底），墨线框自带轻微歪斜 */
  #app .app-shell--comic-page .entry-qr-frame {
    position: relative;
    isolation: isolate;
    grid-area: qr;
    width: 131px;
    height: 134px;
    box-sizing: border-box;
    margin: -4px 0 0;
    padding: 15px 11px 13px 14px;
    background: transparent;
    border: 0;
    border-radius: 0;
    box-shadow: none;
    transform: none;
  }
  #app .app-shell--comic-page .entry-qr-frame::after {
    content: '';
    position: absolute;
    z-index: -1;
    inset: -2px -8px -8px -2px;
    border-style: solid;
    border-color: transparent;
    border-width: 14px 22px 20px 14px;
    border-image: var(--ct-qr) 42 66 60 42 fill / 14px 22px 20px 14px stretch;
  }
  #app .app-shell--comic-page .entry-qr { width: 100%; height: 100%; }
  #app .app-shell--comic-page .entry-qr-fallback { color: #3f4654; font-family: inherit; font-size: 12.5px; }
  #app .app-shell--comic-page .entry-qr-hint {
    grid-area: hint;
    margin: 15px 0 0 3px;
    color: var(--ct-navy);
    font-family: inherit;
    font-size: 15px;
    font-style: italic;
    font-weight: 900;
    line-height: 22px;
    -webkit-text-stroke: .35px currentColor;
  }
  #app .app-shell--comic-page .entry-qr-hint::before { display: inline-block; width: 18px; color: var(--ct-navy); font-style: normal; font-weight: 900; }
}
/* 画框较矮时（如 1024×768）联系卡收紧 */
@media (min-width: 64rem) and (max-height: 50rem) {
  #app .app-shell--comic-page .contact-title.comic-title { font-size: 54px; letter-spacing: -7px; }
  #app .app-shell--comic-page .contact-hero { grid-template-rows: 76px minmax(0, 1fr); }
  #app .app-shell--comic-page .contact-hero-note { margin-bottom: -19px; }
  #app .app-shell--comic-page .entry-item--qr .entry-body { padding-top: 22px; padding-bottom: 14px; }
  #app .app-shell--comic-page .entry-badge { margin-top: 12px; }
  #app .app-shell--comic-page .entry-qr-hint { margin-top: 10px; }
}

/* ── 简洁版（html[data-style='simple']，样式表在公开仓的 simple-theme.css）：和站点其余页面一样用细线、规整圆角、
 * 正体半粗，强调色只留一种蓝。画框不斜切、不压网点，联系卡、场景按钮、画质面板都换成纸面卡片，漫画版的生成素材
 * 一张都不用。联系页只在桌面接入漫画外壳，窄屏在旧外壳里，所以这些规则挂在两边都有的 .app-shell 下；选择器比上面
 * 漫画版的同名规则多一级 html:root[data-style='simple']，任何宽度都压得住。只有最后的桌面版式跟着漫画外壳走。 */
html:root[data-style='simple'] #app .app-shell .contact-page { --contact-acid-ink: var(--simple-accent); }
html:root[data-style='simple'] #app .app-shell .hero-overlay { display: none; }
html:root[data-style='simple'] #app .app-shell .contact-kicker { letter-spacing: 0.08em; }
html:root[data-style='simple'] #app .app-shell .contact-title.comic-title {
  font-size: var(--simple-title-size);
  font-weight: 650;
  letter-spacing: -0.01em;
  line-height: 1.3;
  -webkit-text-stroke: 0;
  text-shadow: none;
}
html:root[data-style='simple'] #app .app-shell .contact-subtitle {
  color: var(--ink-secondary);
  font-family: inherit;
  font-size: 15px;
  font-style: normal;
  font-weight: 400;
  line-height: 1.6;
  text-shadow: none;
}

/* 场景上的「静态预览」和「选择画质」 */
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-actions) { gap: 8px; }
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-actions button) {
  color: var(--ink);
  background: var(--paper);
  border: 1px solid var(--rule-strong);
  border-radius: var(--control-radius);
  box-shadow: var(--simple-pop-shadow);
  backdrop-filter: none;
}
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-actions button::after) { content: none; }
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-actions button:hover) {
  color: var(--ink);
  background: var(--simple-hover);
  border-color: var(--rule-strong);
  transform: none;
}
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-actions .scene-launch) {
  height: 40px;
  padding: 0 14px 0 12px;
  font-family: inherit;
  font-size: 14px;
  font-style: normal;
  font-weight: 600;
  letter-spacing: 0;
}
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-poster-badge) {
  padding: 4px 8px;
  color: var(--ink-secondary);
  background: var(--paper);
  border: 1px solid var(--rule-strong);
  border-radius: 4px;
  font-family: inherit;
  font-size: 12px;
  font-style: normal;
  font-weight: 600;
  letter-spacing: 0;
}
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-poster-badge::after) { content: none; }

/* 加载状态与画质面板 */
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-status--visible) {
  color: var(--ink);
  background: var(--paper);
  border-color: var(--rule-strong);
  border-radius: var(--control-radius);
  box-shadow: var(--simple-pop-shadow);
  font-family: inherit;
  font-weight: 500;
}
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-status--busy::after) { background: var(--simple-accent); }
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-status-retry) {
  color: var(--simple-accent-ink);
  background: var(--simple-accent);
  border-color: var(--simple-accent);
  border-radius: var(--control-radius);
}
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-chooser) { background: rgb(15 18 22 / 0.4); }
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-chooser-panel) {
  padding: 20px;
  color: var(--ink);
  background: var(--paper);
  border: 1px solid var(--rule-strong);
  border-radius: var(--module-radius);
  box-shadow: var(--simple-pop-shadow);
}
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-chooser-panel::after) { content: none; }
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-chooser-title) {
  color: var(--ink);
  font-family: inherit;
  font-size: 18px;
  font-style: normal;
  font-weight: 600;
  letter-spacing: 0;
}
html:root[data-style='simple'] #app .app-shell .hero-field :deep(:is(.scene-chooser-note, .scene-chooser-hint)) { color: var(--ink-secondary); }
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-option) {
  background: var(--paper);
  border: 1px solid var(--rule-strong);
  border-radius: var(--control-radius);
}
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-option::after) { content: none; }
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-option:hover) {
  background: var(--simple-hover);
  border-color: var(--rule-strong);
  transform: none;
}
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-option:has(input:checked)) {
  background: var(--simple-select);
  border-color: var(--simple-select-edge);
}
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-option input) { accent-color: var(--simple-accent); }
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-option-body strong) { color: var(--ink); font-size: 15px; }
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-option-body em) {
  color: var(--simple-select-ink);
  background: var(--simple-select);
  border: 1px solid var(--simple-select-edge);
  border-radius: 4px;
  font-family: inherit;
  font-size: 11.5px;
  font-style: normal;
  font-weight: 600;
}
html:root[data-style='simple'] #app .app-shell .hero-field :deep(:is(.scene-option-body small, .scene-option-size)) {
  color: var(--ink-muted);
  font-family: inherit;
  font-style: normal;
}
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-chooser-actions button) {
  min-height: 38px;
  padding: 0 16px;
  border-radius: var(--control-radius);
  font-family: inherit;
  font-size: 14px;
  font-style: normal;
  font-weight: 600;
}
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-chooser-actions button::after) { content: none; }
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-chooser-actions button:hover) { transform: none; }
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-chooser-cancel),
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-chooser-cancel:hover) {
  color: var(--ink);
  background: var(--paper);
  border: 1px solid var(--rule-strong);
}
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-chooser-cancel:hover) { background: var(--simple-hover); }
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-chooser-actions .scene-chooser-enter),
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-chooser-actions .scene-chooser-enter:hover) {
  color: var(--simple-accent-ink);
  background: var(--simple-accent);
  border: 1px solid var(--simple-accent);
}
html:root[data-style='simple'] #app .app-shell .hero-field :deep(.scene-chooser-actions .scene-chooser-enter:hover) {
  background: var(--simple-accent-hover);
  border-color: var(--simple-accent-hover);
}
html:root[data-style='simple'] #app .app-shell .hero-field :deep(:is(.scene-actions button, .scene-chooser button, .scene-status-retry):focus-visible) {
  outline: 2px solid var(--simple-accent);
  outline-offset: 2px;
}

/* 联系方式：纸面卡片，主按钮是蓝底，二维码保持白底好扫 */
html:root[data-style='simple'] #app .app-shell .contact-hero-note {
  color: var(--ink-secondary);
  background: var(--paper);
  border: 1px solid var(--rule-strong);
  border-radius: var(--control-radius);
  padding: 6px 10px;
  font-family: inherit;
  font-size: 13px;
  font-style: normal;
  font-weight: 500;
  -webkit-text-stroke: 0;
  text-shadow: none;
}
html:root[data-style='simple'] #app .app-shell .contact-hero-note::before,
html:root[data-style='simple'] #app .app-shell .contact-hero-note::after { content: none; }
html:root[data-style='simple'] #app .app-shell .entry-item {
  overflow: hidden;
  color: var(--ink);
  background: var(--paper);
  border: 1px solid var(--rule-strong);
  border-radius: var(--module-radius);
  box-shadow: var(--simple-pop-shadow);
  backdrop-filter: none;
}
html:root[data-style='simple'] #app .app-shell .entry-item::after { content: none; }
html:root[data-style='simple'] #app .app-shell .entry-label {
  color: var(--ink);
  font-family: inherit;
  font-size: 15px;
  font-style: normal;
  font-weight: 600;
  line-height: 1.4;
  -webkit-text-stroke: 0;
}
html:root[data-style='simple'] #app .app-shell .entry-badge {
  min-width: 0;
  height: auto;
  padding: 2px 8px;
  color: var(--simple-select-ink);
  background: var(--simple-select);
  border: 1px solid var(--simple-select-edge);
  border-radius: 4px;
  font-family: inherit;
  font-size: 12px;
  font-style: normal;
  font-weight: 600;
  letter-spacing: 0;
  transform: none;
}
html:root[data-style='simple'] #app .app-shell .entry-badge::after { content: none; }
html:root[data-style='simple'] #app .app-shell .entry-value { color: var(--ink); font-family: inherit; font-size: 14px; font-weight: 500; }
html:root[data-style='simple'] #app .app-shell .entry-value--link {
  text-decoration-color: var(--simple-select-edge);
  text-decoration-thickness: 1px;
}
html:root[data-style='simple'] #app .app-shell .entry-value--link:hover {
  color: var(--simple-accent);
  background: transparent;
  text-decoration-color: currentColor;
}
html:root[data-style='simple'] #app .app-shell .entry-action--primary,
html:root[data-style='simple'] #app .app-shell .entry-action--primary:is(:hover, :active) {
  min-width: 0;
  min-height: 40px;
  gap: 8px;
  padding: 0 16px;
  color: var(--simple-accent-ink);
  background: var(--simple-accent);
  border: 1px solid var(--simple-accent);
  border-radius: var(--control-radius);
  box-shadow: none;
  font-size: 15px;
  font-style: normal;
  font-weight: 600;
  text-decoration: none;
  transform: none;
}
html:root[data-style='simple'] #app .app-shell .entry-action--primary:is(:hover, :active) {
  background: var(--simple-accent-hover);
  border-color: var(--simple-accent-hover);
}
html:root[data-style='simple'] #app .app-shell .entry-action--primary::after { content: none; }
html:root[data-style='simple'] #app .app-shell .entry-value--link:focus-visible { outline: 2px solid var(--simple-accent); outline-offset: 2px; }
html:root[data-style='simple'] #app .app-shell .entry-arrow { font-size: 15px; }
html:root[data-style='simple'] #app .app-shell .entry-qr-frame {
  padding: 6px;
  background: #fff;
  border: 1px solid var(--rule-strong);
  border-radius: var(--control-radius);
  box-shadow: none;
  transform: none;
}
html:root[data-style='simple'] #app .app-shell .entry-qr-frame::after { content: none; }
html:root[data-style='simple'] #app .app-shell .entry-qr-fallback { color: #4b535d; font-family: inherit; }
html:root[data-style='simple'] #app .app-shell .entry-qr-hint {
  color: var(--ink-muted);
  font-family: inherit;
  font-size: 13px;
  font-style: normal;
  font-weight: 500;
  -webkit-text-stroke: 0;
}
html:root[data-style='simple'] #app .app-shell .entry-qr-hint::before { color: var(--ink-faint); font-weight: 500; }

/* 桌面：标题行在纸面上，画框是一个规整的圆角矩形，联系卡收在画框右下角 */
@media (min-width: 64rem) {
  html:root[data-style='simple'] #app .app-shell--comic-page .contact-page { padding: 0 0 16px; }
  html:root[data-style='simple'] #app .app-shell--comic-page .contact-hero {
    grid-template-rows: auto minmax(0, 1fr);
    row-gap: 16px;
  }
  html:root[data-style='simple'] #app .app-shell--comic-page .hero-heading { padding: 4px 0 0 2px; }
  html:root[data-style='simple'] #app .app-shell--comic-page .contact-title.comic-title { margin: 0; }
  html:root[data-style='simple'] #app .app-shell--comic-page .contact-subtitle { margin: 4px 0 0; }
  html:root[data-style='simple'] #app .app-shell--comic-page .hero-field {
    --scene-safe-top: 12px;
    clip-path: none;
    border: 1px solid var(--rule-strong);
    border-radius: var(--module-radius);
  }
  html:root[data-style='simple'] #app .app-shell--comic-page .contact-hero::after,
  html:root[data-style='simple'] #app .app-shell--comic-page .hero-field:has(.godot-contact-scene--poster)::after { content: none; }
  html:root[data-style='simple'] #app .app-shell--comic-page .hero-field :deep(.scene-actions) { right: 12px; }
  html:root[data-style='simple'] #app .app-shell--comic-page .hero-dock {
    width: 400px;
    max-width: calc(100% - 32px);
    margin: 0 16px 16px 0;
  }
  html:root[data-style='simple'] #app .app-shell--comic-page .contact-hero-note {
    align-self: flex-end;
    min-width: 0;
    min-height: 0;
    margin: 0 0 8px;
  }
  html:root[data-style='simple'] #app .app-shell--comic-page .entry-list { gap: 12px; }
  html:root[data-style='simple'] #app .app-shell--comic-page .entry-body { gap: 8px; padding: 16px; }
  html:root[data-style='simple'] #app .app-shell--comic-page .entry-item--qr .entry-body {
    grid-template-areas: 'label qr' 'badge qr' 'value qr' 'hint qr';
    grid-template-columns: minmax(0, 1fr) 112px;
    grid-template-rows: auto auto auto minmax(0, 1fr);
    column-gap: 16px;
    row-gap: 8px;
    padding: 16px;
  }
  html:root[data-style='simple'] #app .app-shell--comic-page .entry-label { margin: 0; font-size: 16px; line-height: 1.4; }
  html:root[data-style='simple'] #app .app-shell--comic-page .entry-badge { margin: 0; }
  html:root[data-style='simple'] #app .app-shell--comic-page .entry-action--primary { margin: 4px 0 0; }
  html:root[data-style='simple'] #app .app-shell--comic-page .entry-qr-frame { width: 112px; height: 112px; margin: 0; }
  html:root[data-style='simple'] #app .app-shell--comic-page .entry-qr-hint { margin: 0; line-height: 1.5; }
}
@media (prefers-reduced-motion: reduce) {
  .entry-item,
  .entry-value--link,
  .entry-action--primary {
    transition: none;
  }
  #app .app-shell--comic-page .entry-action--primary:is(:hover, :active),
  #app .app-shell--comic-page .hero-field :deep(:is(.scene-actions button, .scene-option, .scene-chooser-actions button):hover) { transform: none; }
}
</style>
