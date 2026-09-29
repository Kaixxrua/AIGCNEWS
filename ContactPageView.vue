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
const { t } = useI18n()

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
          <h1 class="contact-title">{{ config.title }}</h1>
          <p v-if="config.subtitle" class="contact-subtitle">{{ config.subtitle }}</p>
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
                  <span class="entry-label">{{ entry.label }}</span>
                  <span v-if="isPrimaryEntry(index)" class="entry-badge">{{ t('contact.primaryBadge') }}</span>
                </div>
                <div v-if="entry.qrImageUrl && showQr(index)" class="entry-qr-frame">
                  <img v-if="!failedQrEntries[index]" class="entry-qr" :src="entry.qrImageUrl" :alt="entry.label" loading="lazy" @error="markQrFailed(index)" />
                  <div v-else class="entry-qr-fallback" role="img" :aria-label="t('contact.qrUnavailable')">{{ t('contact.qrUnavailable') }}</div>
                </div>
                <a v-if="entry.href" class="entry-value entry-value--link" :class="{ 'entry-action--primary': isPrimaryEntry(index) }" :href="entry.href" v-bind="linkAttrs(entry)">
                  <span class="entry-link-text">{{ entry.value || entry.href }}</span><span class="entry-arrow" aria-hidden="true">↗</span>
                </a>
                <span v-else-if="entry.value" class="entry-value">{{ entry.value }}</span>
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
  padding: clamp(1rem, 3vw, 2rem) clamp(1rem, 3vw, 2rem) 0;
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

@media (min-width: 48rem) {
  .hero-dock { width: min(22rem, 42%); }
  .entry-qr-frame { width: clamp(84px, 13vh, 116px); }
  .entry-body { padding: var(--cs-4); }
}
@media (max-width: 47.99rem) {
  .hero-inner { padding: var(--cs-4) var(--cs-4) 0; }
  .hero-heading { max-width: 100%; }
  .hero-dock { width: 100%; justify-self: stretch; }
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
  .hero-dock { width: auto; max-width: calc(100% - 1rem); justify-self: end; }
  .entry-action--primary { min-height: 2.75rem; }
}
/* 矮屏（横持手机等）：dock 压缩间距，QR 已被 vh 钳制自动缩小 */
@media (max-height: 30rem) {
  .hero-dock { gap: var(--cs-2); }
  .entry-body { padding: var(--cs-2) var(--cs-3); }
  .contact-title { font-size: clamp(1.5rem, 1.1rem + 2.4vw, 2.25rem); }
}
@media (prefers-reduced-motion: reduce) {
  .entry-item,
  .entry-value--link,
  .entry-action--primary {
    transition: none;
  }
}
</style>
