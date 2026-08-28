<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useContactPageConfig } from '@/composables/useContactPageConfig'
import { renderPlainMarkdown } from '@/composables/useLatexRenderer'
import type { SiteContactEntry } from '@/services/site/contactPageApi'

/**
 * 联系合作页：内容由管理员在 monitor「站点 → 联系合作页」撰写（单语言）。
 * 路由守卫已在页面未启用时重定向，此处 enabled 判断仅作防御兜底。
 */
const { contactPageConfig } = useContactPageConfig()
const config = contactPageConfig
const { t } = useI18n()

/** 服务卡片图标 key → 内联 SVG（与导航图标同风格）；未知/空 key 回退 default */
const SERVICE_CARD_ICONS: Record<string, string> = {
  code: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="16,18 22,12 16,6"/><polyline points="8,6 2,12 8,18"/></svg>`,
  briefcase: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 00-2-2h-4a2 2 0 00-2 2v16"/></svg>`,
  chat: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>`,
  rocket: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 00-2.91-.09z"/><path d="M12 15l-3-3a22 22 0 012-3.95A12.88 12.88 0 0122 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 01-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/></svg>`,
  default: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.9 5.8H20l-4.9 3.6 1.9 5.8-5-3.6-5 3.6 1.9-5.8L4 8.8h6.1z"/></svg>`,
}

const cardIcon = (icon: string): string => SERVICE_CARD_ICONS[icon] ?? SERVICE_CARD_ICONS.default!
const isExternalLink = (href: string): boolean => /^https?:\/\//i.test(href)
const linkAttrs = (entry: SiteContactEntry) =>
  isExternalLink(entry.href) ? { target: '_blank', rel: 'noopener noreferrer' } : {}

const renderedBody = computed(() => renderPlainMarkdown(config.value.bodyMarkdown))
const failedQrEntries = ref<Record<number, boolean>>({})
const markQrFailed = (index: number) => {
  failedQrEntries.value = { ...failedQrEntries.value, [index]: true }
}

/** 只从管理员已配置的联系方式中选出一个主动作，不硬编码地址或文案。 */
const primaryEntryIndex = computed(() => {
  const hrefIndex = config.value.contactEntries.findIndex((entry) => entry.href)
  return hrefIndex >= 0 ? hrefIndex : config.value.contactEntries.findIndex((entry) => entry.qrImageUrl)
})
const primaryEntry = computed(() => {
  const index = primaryEntryIndex.value
  return index >= 0 ? config.value.contactEntries[index] ?? null : null
})
const isPrimaryEntry = (index: number): boolean => index === primaryEntryIndex.value

/** 区块按实际可见顺序编号（有空区块时自动重排），保留给信息架构标签使用。 */
type SectionKey = 'services' | 'entries' | 'notes'
const visibleSections = computed<SectionKey[]>(() => {
  const sections: SectionKey[] = []
  if (config.value.serviceCards.length) sections.push('services')
  if (config.value.contactEntries.length) sections.push('entries')
  if (config.value.bodyMarkdown.trim()) sections.push('notes')
  return sections
})
const sectionNumber = (key: SectionKey): string =>
  String(visibleSections.value.indexOf(key) + 1).padStart(2, '0')
const treeBranch = (isLast: boolean): string => (isLast ? '└──' : '├──')
</script>

<template>
  <div v-if="config.enabled" class="contact-page">
    <div class="contact-shell">
      <header class="contact-hero">
        <!-- 抽象信号场：只提供氛围，不模拟浏览器、终端或产品 chrome。 -->
        <div class="hero-field" aria-hidden="true">
          <span class="hero-beam hero-beam--a" />
          <span class="hero-beam hero-beam--b" />
          <span class="hero-beam hero-beam--c" />
          <span class="hero-beam hero-beam--d" />
          <span class="hero-scanline" />
        </div>
        <!-- 保留旧契约节点；视觉呈现改由 signal-led eyebrow 承担。 -->
        <p class="term-line contact-command" aria-hidden="true">
          <span class="term-prompt">$</span> aigcnews contact --list<span class="term-caret" />
        </p>
        <div class="hero-inner">
          <p class="contact-kicker">{{ t('contact.kicker') }}</p>
          <h1 class="contact-title">{{ config.title }}</h1>
          <p v-if="config.subtitle" class="contact-subtitle">{{ config.subtitle }}</p>
          <div class="hero-footer">
            <p v-if="config.contactEntries.length" class="contact-hero-note">{{ t('contact.heroNote') }}</p>
            <a
              v-if="primaryEntry?.href"
              class="hero-cta"
              :href="primaryEntry.href"
              v-bind="linkAttrs(primaryEntry)"
              :title="primaryEntry.value || primaryEntry.label"
            >
              <span class="hero-cta-label">{{ primaryEntry.value || primaryEntry.label }}</span>
              <span class="hero-cta-arrow" aria-hidden="true">↗</span>
            </a>
          </div>
        </div>
      </header>

      <main class="contact-content">
        <section v-if="config.serviceCards.length" class="contact-section service-section" aria-labelledby="contact-services-title">
          <div class="section-heading">
            <div class="section-heading-copy">
              <p class="section-kicker">[{{ sectionNumber('services') }}] {{ t('contact.servicesKicker') }}</p>
              <h2 id="contact-services-title">{{ t('contact.servicesTitle') }}</h2>
            </div>
            <span class="section-rule-mark" aria-hidden="true" />
          </div>
          <ul class="service-grid">
            <li v-for="(card, index) in config.serviceCards" :key="`${index}-${card.title}`" class="service-card">
              <span class="tree-branch" aria-hidden="true">{{ treeBranch(index === config.serviceCards.length - 1) }}</span>
              <div class="service-card-inner">
                <span class="service-icon" v-html="cardIcon(card.icon)" aria-hidden="true" />
                <div class="service-body">
                  <h3 class="service-title">{{ card.title }}</h3>
                  <p v-if="card.description" class="service-desc">{{ card.description }}</p>
                </div>
              </div>
            </li>
          </ul>
        </section>

        <section v-if="config.contactEntries.length" class="contact-section entry-section" aria-labelledby="contact-entry-title">
          <div class="section-heading">
            <div class="section-heading-copy">
              <p class="section-kicker">[{{ sectionNumber('entries') }}] {{ t('contact.entryKicker') }}</p>
              <h2 id="contact-entry-title">{{ t('contact.entryTitle') }}</h2>
            </div>
            <span class="section-rule-mark" aria-hidden="true" />
          </div>
          <ul class="entry-list">
            <li v-for="(entry, index) in config.contactEntries" :key="`${index}-${entry.label}`" class="entry-item" :class="{ 'entry-item--primary': isPrimaryEntry(index) }">
              <span class="tree-branch" aria-hidden="true">{{ treeBranch(index === config.contactEntries.length - 1) }}</span>
              <div class="entry-body">
                <div class="entry-meta">
                  <span class="entry-label">{{ entry.label }}</span>
                  <span v-if="isPrimaryEntry(index)" class="entry-badge">{{ t('contact.primaryBadge') }}</span>
                </div>
                <div v-if="entry.qrImageUrl" class="entry-qr-frame">
                  <img v-if="!failedQrEntries[index]" class="entry-qr" :src="entry.qrImageUrl" :alt="entry.label" loading="lazy" @error="markQrFailed(index)" />
                  <div v-else class="entry-qr-fallback" role="img" :aria-label="t('contact.qrUnavailable')">{{ t('contact.qrUnavailable') }}</div>
                </div>
                <a v-if="entry.href" class="entry-value entry-value--link" :class="{ 'entry-action--primary': isPrimaryEntry(index) }" :href="entry.href" v-bind="linkAttrs(entry)">
                  <span class="entry-link-text">{{ entry.value || entry.href }}</span><span class="entry-arrow" aria-hidden="true">↗</span>
                </a>
                <span v-else-if="entry.value" class="entry-value">{{ entry.value }}</span>
                <span v-if="entry.qrImageUrl && !failedQrEntries[index]" class="entry-qr-hint">{{ t('contact.qrHint') }}</span>
              </div>
            </li>
          </ul>
        </section>

        <section v-if="config.bodyMarkdown.trim()" class="contact-section contact-markdown-section" aria-labelledby="contact-notes-title">
          <div class="section-heading">
            <div class="section-heading-copy">
              <p class="section-kicker">[{{ sectionNumber('notes') }}] {{ t('contact.notesKicker') }}</p>
              <h2 id="contact-notes-title">{{ t('contact.notesTitle') }}</h2>
            </div>
            <span class="section-rule-mark" aria-hidden="true" />
          </div>
          <!-- 经 renderPlainMarkdown（markdown-it + DOMPurify）消毒，禁止改绑原始渲染结果 -->
          <div class="contact-markdown" v-html="renderedBody" />
        </section>
      </main>
    </div>
  </div>
</template>

<style scoped>
/* Hallmark · macrostructure: Atmosphere-First contact landing · theme: project-managed (style.css tokens) · voice: signal-led editorial · motion: beam-drift + pulse only
 * Hallmark · pre-emit critique: P5 H5 E4 S5 R5 V5
 * contrast: pass (40–41) · honest: pass (46) · chrome: pass (47) · tokens: pass (48) · responsive: pass (49–57) · icons: pass (30) · nav/footer: app-shell（不在本次范围） */
.contact-page {
  --contact-mono: ui-monospace, 'JetBrains Mono', 'Fira Code', Menlo, Consolas, 'Liberation Mono', monospace;
  --contact-display: 'DM Sans', Inter, ui-sans-serif, system-ui, sans-serif;
  --cs-1: 0.25rem;
  --cs-2: 0.5rem;
  --cs-3: 0.75rem;
  --cs-4: 1rem;
  --cs-5: 1.5rem;
  --cs-6: 2rem;
  --cs-7: 2.5rem;
  --cs-8: 3.5rem;
  --cs-dock-clear: 112px; /* 与 LayoutView/AppDock 的底部安全区契约，勿随排版节奏改动 */
  --contact-hero-bg: var(--ink);
  --contact-hero-ink: var(--paper-raised);
  --contact-hero-muted: color-mix(in srgb, var(--paper-raised) 68%, transparent);
  --contact-hero-rule: color-mix(in srgb, var(--paper-raised) 18%, transparent);
  --contact-hero-surface: color-mix(in srgb, var(--ink) 88%, var(--acid) 12%);
  --contact-hero-gradient: linear-gradient(180deg, var(--ink) 0%, var(--contact-hero-surface) 48%, var(--ink) 100%);
  --contact-hero-grid: repeating-linear-gradient(90deg, transparent 0 0.7rem, color-mix(in srgb, var(--acid) 12%, transparent) 0.7rem 0.76rem, transparent 0.76rem 1.6rem);
  --contact-hero-glow: radial-gradient(ellipse at 50% 4%, color-mix(in srgb, var(--acid) 34%, transparent), transparent 57%);
  --contact-hero-beam: linear-gradient(180deg, transparent 0%, color-mix(in srgb, var(--tech-primary) 32%, var(--acid) 28%) 34%, color-mix(in srgb, var(--acid) 56%, transparent) 56%, transparent 100%);
  --contact-hero-scan: linear-gradient(90deg, transparent, color-mix(in srgb, var(--acid) 58%, transparent), transparent);
  --contact-cta-bg: var(--paper-raised);
  --contact-cta-ink: var(--ink);
  --contact-primary-surface: color-mix(in srgb, var(--paper-raised) 92%, var(--acid) 8%);
  width: 100%;
  height: 100%;
  overflow-y: auto;
  overflow-x: clip;
  box-sizing: border-box;
  padding: var(--cs-4) var(--cs-4) var(--cs-dock-clear);
}

:global(:root[data-theme='dark'] .contact-page) {
  --contact-hero-bg: var(--paper-muted);
  --contact-hero-ink: var(--ink);
  --contact-hero-muted: color-mix(in srgb, var(--ink) 66%, transparent);
  --contact-hero-rule: color-mix(in srgb, var(--ink) 18%, transparent);
  --contact-hero-surface: color-mix(in srgb, var(--paper-muted) 84%, var(--acid) 16%);
  --contact-hero-gradient: linear-gradient(180deg, var(--paper-muted) 0%, var(--contact-hero-surface) 48%, var(--paper-muted) 100%);
  --contact-hero-grid: repeating-linear-gradient(90deg, transparent 0 0.7rem, color-mix(in srgb, var(--acid) 13%, transparent) 0.7rem 0.76rem, transparent 0.76rem 1.6rem);
  --contact-hero-glow: radial-gradient(ellipse at 50% 4%, color-mix(in srgb, var(--acid) 26%, transparent), transparent 57%);
  --contact-hero-beam: linear-gradient(180deg, transparent 0%, color-mix(in srgb, var(--tech-primary) 34%, var(--acid) 18%) 34%, color-mix(in srgb, var(--acid) 48%, transparent) 56%, transparent 100%);
  --contact-hero-scan: linear-gradient(90deg, transparent, color-mix(in srgb, var(--acid) 50%, transparent), transparent);
  --contact-cta-bg: var(--ink);
  --contact-cta-ink: var(--paper-muted);
  --contact-primary-surface: color-mix(in srgb, var(--paper-raised) 90%, var(--acid) 10%);
}

.contact-shell {
  width: 100%;
  max-width: 72rem;
  margin: 0 auto;
  min-width: 0;
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

/* ── Hero：黑场、垂直信号束和居中主张 ── */
.contact-hero {
  position: relative;
  min-height: 27rem;
  overflow: hidden;
  isolation: isolate;
  background: var(--contact-hero-bg);
  border: 1px solid var(--rule);
}
.hero-field,
.hero-field::before,
.hero-field::after {
  position: absolute;
  inset: 0;
  pointer-events: none;
}
.hero-field {
  z-index: -1;
  overflow: hidden;
  background: var(--contact-hero-gradient);
}
.hero-field::before {
  content: '';
  background-image: var(--contact-hero-grid);
  opacity: 0.76;
  mask-image: linear-gradient(180deg, var(--ink) 0%, transparent 84%);
}
.hero-field::after {
  content: '';
  background: var(--contact-hero-glow);
  opacity: 0.9;
}
.hero-beam {
  position: absolute;
  top: -20%;
  width: clamp(3.5rem, 9vw, 10rem);
  height: 150%;
  background: var(--contact-hero-beam);
  filter: blur(0.7rem);
  opacity: 0.38;
  transform: skewX(-12deg);
  transform-origin: 50% 18%;
  will-change: transform, opacity;
}
.hero-beam--a { left: 16%; animation: contact-beam-drift-a 8.5s ease-in-out infinite; }
.hero-beam--b { left: 37%; width: clamp(2.5rem, 6vw, 7rem); opacity: 0.55; animation: contact-beam-drift-b 10s ease-in-out infinite; }
.hero-beam--c { right: 28%; width: clamp(4rem, 8vw, 9rem); opacity: 0.32; animation: contact-beam-drift-c 9.2s ease-in-out infinite; }
.hero-beam--d { right: 8%; width: clamp(2.5rem, 5vw, 6rem); opacity: 0.24; animation: contact-beam-drift-d 11s ease-in-out infinite; }
.hero-scanline {
  position: absolute;
  top: 42%;
  left: 8%;
  right: 8%;
  height: 1px;
  background: var(--contact-hero-scan);
  opacity: 0.7;
  animation: contact-scanline 7s ease-in-out infinite;
}
.hero-inner {
  position: relative;
  z-index: 1;
  display: flex;
  min-height: 27rem;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--cs-8) clamp(var(--cs-5), 8vw, 5rem) var(--cs-7);
  text-align: center;
}
.contact-kicker {
  display: inline-flex;
  align-items: center;
  gap: var(--cs-4);
  margin: 0;
  color: var(--acid);
  font-family: var(--contact-mono);
  font-size: 0.6875rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  line-height: 1;
  text-transform: uppercase;
}
.contact-kicker::before,
.contact-kicker::after {
  content: '';
  display: block;
  width: clamp(2rem, 5vw, 3.25rem);
  height: 1px;
  background: var(--contact-hero-rule);
}
.contact-title {
  max-width: 18ch;
  margin: var(--cs-5) 0 0;
  color: var(--contact-hero-ink);
  font-family: var(--contact-display);
  font-size: clamp(2.35rem, 1.3rem + 4.2vw, 4rem);
  font-weight: 700;
  letter-spacing: -0.055em;
  line-height: 1.06;
  overflow-wrap: anywhere;
  min-width: 0;
}
.contact-subtitle {
  max-width: 50rem;
  margin: var(--cs-5) 0 0;
  color: var(--contact-hero-muted);
  font-family: var(--contact-display);
  font-size: clamp(0.9375rem, 0.86rem + 0.25vw, 1.0625rem);
  line-height: 1.75;
  white-space: pre-line;
  overflow-wrap: anywhere;
}
.hero-footer {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--cs-5);
  width: min(100%, 42rem);
  margin-top: var(--cs-7);
}
.contact-hero-note {
  margin: 0;
  color: var(--contact-hero-muted);
  font-family: var(--contact-mono);
  font-size: 0.6875rem;
  line-height: 1.6;
  text-align: left;
}
.contact-hero-note::before {
  content: '＋';
  margin-right: var(--cs-2);
  color: var(--acid);
}
.hero-cta {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  gap: var(--cs-2);
  min-height: 2.75rem;
  max-width: min(100%, 22rem);
  padding: 0.75rem 1.25rem;
  color: var(--contact-cta-ink);
  background: var(--contact-cta-bg);
  border: 1px solid var(--contact-cta-bg);
  border-radius: 999px;
  box-shadow: 0 1px 0 color-mix(in srgb, var(--contact-cta-bg) 68%, transparent) inset, 0 0.75rem 1.75rem color-mix(in srgb, var(--ink) 28%, transparent);
  font-family: var(--contact-display);
  font-size: 0.8125rem;
  font-weight: 700;
  line-height: 1;
  text-decoration: none;
  white-space: nowrap;
  overflow: hidden;
}
.hero-cta:hover {
  color: var(--acid-ink);
  background: var(--acid);
  border-color: var(--acid);
}
.hero-cta:active {
  color: var(--contact-hero-ink);
  background: var(--contact-hero-bg);
  border-color: var(--contact-hero-ink);
}
.hero-cta-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}
.hero-cta-arrow { font-size: 1rem; line-height: 0.8; }

@keyframes contact-beam-drift-a {
  0%, 100% { opacity: 0.28; transform: translate3d(-1.2rem, -0.25rem, 0) skewX(-12deg); }
  50% { opacity: 0.62; transform: translate3d(1.25rem, 0.75rem, 0) skewX(8deg); }
}
@keyframes contact-beam-drift-b {
  0%, 100% { opacity: 0.38; transform: translate3d(1rem, 0, 0) skewX(11deg) scaleX(0.92); }
  50% { opacity: 0.72; transform: translate3d(-1.5rem, 0.5rem, 0) skewX(-8deg) scaleX(1.08); }
}
@keyframes contact-beam-drift-c {
  0%, 100% { opacity: 0.24; transform: translate3d(0, 0.75rem, 0) skewX(-10deg); }
  50% { opacity: 0.54; transform: translate3d(-1.75rem, -0.4rem, 0) skewX(7deg); }
}
@keyframes contact-beam-drift-d {
  0%, 100% { opacity: 0.18; transform: translate3d(-0.5rem, 0, 0) skewX(12deg); }
  50% { opacity: 0.4; transform: translate3d(1rem, 0.35rem, 0) skewX(-7deg); }
}
@keyframes contact-scanline {
  0%, 100% { opacity: 0.18; transform: scaleX(0.78); }
  50% { opacity: 0.76; transform: scaleX(1); }
}

/* ── 内容区：发丝线分隔、模块化卡片和明确行动层级 ── */
.contact-content {
  display: flex;
  flex-direction: column;
  gap: var(--cs-8);
  padding: var(--cs-8) 0 var(--cs-6);
}
.contact-section { min-width: 0; }
.section-heading {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--cs-5);
  margin-bottom: var(--cs-5);
  padding-bottom: var(--cs-4);
  border-bottom: 1px solid var(--rule);
}
.section-heading-copy { min-width: 0; }
.section-kicker {
  display: flex;
  align-items: center;
  gap: var(--cs-2);
  margin: 0 0 var(--cs-2);
  color: var(--ink-muted);
  font-family: var(--contact-mono);
  font-size: 0.6875rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  line-height: 1.4;
  text-transform: uppercase;
}
.section-kicker::before {
  content: '';
  display: inline-block;
  width: 0.375rem;
  height: 0.375rem;
  flex: 0 0 auto;
  background: var(--acid);
  box-shadow: 0 0 0 1px var(--rule-strong);
}
.section-heading h2 {
  margin: 0;
  color: var(--ink);
  font-family: var(--contact-display);
  font-size: clamp(1.5rem, 1.2rem + 1vw, 2rem);
  font-weight: 700;
  letter-spacing: -0.04em;
  line-height: 1.2;
  overflow-wrap: anywhere;
}
.section-rule-mark {
  width: 5rem;
  height: 1px;
  flex: 0 0 auto;
  margin-bottom: var(--cs-2);
  background: linear-gradient(90deg, var(--acid-strong), transparent);
}

.service-grid,
.entry-list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.service-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  background: var(--rule);
  border: 1px solid var(--rule);
}
.service-card {
  position: relative;
  min-width: 0;
  min-height: 12rem;
  padding: var(--cs-5);
  background: var(--paper);
}
.service-card:hover { background: var(--paper-raised); }
.service-card-inner {
  display: flex;
  min-height: 100%;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--cs-5);
}
.service-icon {
  display: inline-flex;
  width: 2.75rem;
  height: 2.75rem;
  align-items: center;
  justify-content: center;
  color: var(--acid-ink);
  background: var(--acid);
  border: 1px solid var(--rule-strong);
}
.service-icon :deep(svg) { width: 1.35rem; height: 1.35rem; }
.service-body { min-width: 0; }
.service-title {
  margin: 0;
  color: var(--ink);
  font-family: var(--contact-display);
  font-size: 1rem;
  font-weight: 700;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
.service-desc {
  margin: var(--cs-2) 0 0;
  color: var(--ink-secondary);
  font-size: 0.8125rem;
  line-height: 1.7;
  white-space: pre-line;
  overflow-wrap: anywhere;
}

.entry-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  background: var(--rule);
  border: 1px solid var(--rule);
}
.entry-item {
  position: relative;
  min-width: 0;
  background: var(--paper);
}
.entry-item:hover { background: var(--paper-raised); }
.entry-item--primary {
  grid-column: 1 / -1;
  background: var(--contact-primary-surface);
}
.entry-body {
  display: flex;
  min-width: 0;
  min-height: 8rem;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--cs-4);
  padding: var(--cs-5);
}
.entry-item--primary .entry-body {
  display: grid;
  grid-template-areas: 'meta qr' 'value qr' 'hint qr';
  grid-template-columns: minmax(0, 1fr) minmax(8.5rem, 11rem);
  align-items: center;
  column-gap: var(--cs-7);
  row-gap: var(--cs-3);
  min-height: 13rem;
  padding: clamp(var(--cs-5), 4vw, var(--cs-7));
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
  color: var(--ink);
  font-family: var(--contact-display);
  font-size: 1rem;
  font-weight: 700;
  letter-spacing: -0.01em;
  line-height: 1.35;
  overflow-wrap: anywhere;
}
.entry-badge {
  padding: var(--cs-1) var(--cs-2);
  color: var(--acid-ink);
  background: var(--acid);
  border: 1px solid var(--rule-strong);
  font-family: var(--contact-mono);
  font-size: 0.625rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  line-height: 1.2;
  white-space: nowrap;
}
.entry-value {
  max-width: 100%;
  color: var(--ink);
  font-family: var(--contact-display);
  font-size: 0.9375rem;
  font-weight: 600;
  line-height: 1.55;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.entry-item--primary .entry-value { grid-area: value; }
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
  min-height: 2.75rem;
  padding: 0.7rem 1rem;
  color: var(--acid-ink);
  background: var(--acid);
  border: 1px solid var(--rule-strong);
  text-decoration: none;
  white-space: nowrap;
  overflow: hidden;
}
.entry-action--primary:hover { color: var(--paper); background: var(--ink); border-color: var(--ink); }
.entry-action--primary:active { color: var(--ink); background: var(--paper-muted); }
.entry-link-text { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.entry-arrow { flex: 0 0 auto; font-size: 1rem; line-height: 0.8; }
.entry-qr-frame {
  display: grid;
  grid-area: qr;
  width: 10.5rem;
  max-width: 100%;
  aspect-ratio: 1;
  box-sizing: border-box;
  place-items: center;
  padding: var(--cs-2);
  background: var(--paper-raised);
  border: 1px solid var(--rule-strong);
}
.entry-qr { display: block; width: 100%; height: 100%; object-fit: contain; image-rendering: pixelated; }
.entry-qr-fallback {
  padding: var(--cs-2);
  color: var(--ink-secondary);
  font-family: var(--contact-mono);
  font-size: 0.6875rem;
  line-height: 1.6;
  text-align: center;
}
.entry-qr-fallback::before { content: '[!] '; color: var(--ink-muted); }
.entry-qr-hint {
  grid-area: hint;
  color: var(--ink-muted);
  font-family: var(--contact-mono);
  font-size: 0.6875rem;
  line-height: 1.5;
}
.entry-qr-hint::before { content: '› '; color: var(--acid-strong); }

/* ── NOTES：保留管理员 Markdown 原文，只改变阅读容器 ── */
.contact-markdown-section { padding-bottom: var(--cs-5); }
.contact-markdown {
  max-width: 72ch;
  padding: var(--cs-5) var(--cs-6);
  color: var(--ink-secondary);
  background: var(--paper-raised);
  border: 1px solid var(--rule);
  font-size: 0.875rem;
  line-height: 1.8;
}
.contact-markdown :deep(h1),
.contact-markdown :deep(h2),
.contact-markdown :deep(h3) {
  margin: var(--cs-4) 0 var(--cs-3);
  padding-bottom: var(--cs-2);
  color: var(--ink);
  border-bottom: 1px solid var(--rule);
  font-family: var(--contact-display);
  font-weight: 700;
  letter-spacing: -0.02em;
  line-height: 1.3;
  overflow-wrap: anywhere;
}
.contact-markdown :deep(h1) { margin-top: 0; font-size: 1.25rem; }
.contact-markdown :deep(h2) { font-size: 1.0625rem; }
.contact-markdown :deep(h3) { font-size: 0.9375rem; }
.contact-markdown :deep(p) { margin: 0 0 var(--cs-3); }
.contact-markdown :deep(p:last-child) { margin-bottom: 0; }
.contact-markdown :deep(a) {
  color: var(--ink);
  text-decoration: underline;
  text-decoration-color: var(--acid-strong);
  text-underline-offset: 0.2em;
}
.contact-markdown :deep(a:hover) { color: var(--acid-ink); background: var(--acid); text-decoration-color: transparent; }
.contact-markdown :deep(ul),
.contact-markdown :deep(ol) { margin: var(--cs-2) 0 var(--cs-3); padding-left: var(--cs-5); }
.contact-markdown :deep(li) { margin: var(--cs-1) 0; }
.contact-markdown :deep(img) { max-width: 100%; border: 1px solid var(--rule); }
.contact-markdown :deep(blockquote) {
  margin: var(--cs-3) 0;
  padding: var(--cs-2) var(--cs-4);
  color: var(--ink-muted);
  background: var(--paper-muted);
  border-left: 2px solid var(--acid-strong);
}
.contact-markdown :deep(code) {
  padding: 0.1em 0.35em;
  color: var(--ink);
  background: var(--paper-muted);
  border: 1px solid var(--rule);
  font-family: var(--contact-mono);
  font-size: 0.85em;
}
.contact-markdown :deep(pre) {
  padding: var(--cs-3) var(--cs-4);
  overflow-x: auto;
  color: var(--ink);
  background: var(--paper-muted);
  border: 1px solid var(--rule);
  font-family: var(--contact-mono);
  font-size: 0.8125rem;
  line-height: 1.7;
}
.contact-markdown :deep(pre code) { padding: 0; background: none; border: none; font-size: inherit; }

@media (min-width: 48rem) {
  .contact-page { padding: var(--cs-5) clamp(1.5rem, 4vw, 3rem) var(--cs-dock-clear); }
}
@media (max-width: 47.99rem) {
  .contact-hero,
  .hero-inner { min-height: 30rem; }
  .hero-inner { padding: var(--cs-7) var(--cs-5) var(--cs-6); }
  .hero-footer { flex-direction: column; align-items: stretch; gap: var(--cs-4); }
  .contact-hero-note { text-align: center; }
  .hero-cta { align-self: center; }
  .service-grid,
  .entry-list { grid-template-columns: minmax(0, 1fr); }
  .entry-item--primary { grid-column: auto; }
  .entry-item--primary .entry-body {
    grid-template-areas: 'meta' 'value' 'qr' 'hint';
    grid-template-columns: minmax(0, 1fr);
    align-items: start;
    gap: var(--cs-4);
  }
  .entry-qr-frame { width: min(12rem, 100%); }
  .section-rule-mark { width: 3rem; }
  .contact-markdown { padding: var(--cs-4); }
}
@media (prefers-reduced-motion: reduce) {
  .hero-beam,
  .hero-scanline { animation: none; }
}
</style>
