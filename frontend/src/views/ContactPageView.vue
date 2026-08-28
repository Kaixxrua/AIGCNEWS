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
const isPrimaryEntry = (index: number): boolean => index === primaryEntryIndex.value

/** 区块按实际可见顺序编号（有空区块时自动重排），树形前缀只认真实末行。 */
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
        <p class="term-line contact-command" aria-hidden="true">
          <span class="term-prompt">$</span> aigcnews contact --list<span class="term-caret" />
        </p>
        <p class="contact-kicker">{{ t('contact.kicker') }}</p>
        <h1 class="contact-title">{{ config.title }}</h1>
        <p v-if="config.subtitle" class="contact-subtitle">{{ config.subtitle }}</p>
        <p v-if="config.contactEntries.length" class="contact-hero-note">{{ t('contact.heroNote') }}</p>
      </header>

      <section v-if="config.serviceCards.length" class="contact-section service-section" aria-labelledby="contact-services-title">
        <div class="section-heading">
          <p class="term-line" aria-hidden="true"><span class="term-prompt">$</span> ls ./services</p>
          <p class="section-kicker">[{{ sectionNumber('services') }}] {{ t('contact.servicesKicker') }}</p>
          <h2 id="contact-services-title">{{ t('contact.servicesTitle') }}</h2>
        </div>
        <ul class="service-grid">
          <li v-for="(card, index) in config.serviceCards" :key="`${index}-${card.title}`" class="service-card">
            <span class="tree-branch" aria-hidden="true">{{ treeBranch(index === config.serviceCards.length - 1) }}</span>
            <span class="service-icon" v-html="cardIcon(card.icon)" aria-hidden="true" />
            <div class="service-body">
              <h3 class="service-title">{{ card.title }}</h3>
              <p v-if="card.description" class="service-desc">{{ card.description }}</p>
            </div>
          </li>
        </ul>
      </section>

      <section v-if="config.contactEntries.length" class="contact-section entry-section" aria-labelledby="contact-entry-title">
        <div class="section-heading">
          <p class="term-line" aria-hidden="true"><span class="term-prompt">$</span> ls ./contact.routes</p>
          <p class="section-kicker">[{{ sectionNumber('entries') }}] {{ t('contact.entryKicker') }}</p>
          <h2 id="contact-entry-title">{{ t('contact.entryTitle') }}</h2>
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
          <p class="term-line" aria-hidden="true"><span class="term-prompt">$</span> cat ./NOTES.md</p>
          <p class="section-kicker">[{{ sectionNumber('notes') }}] {{ t('contact.notesKicker') }}</p>
          <h2 id="contact-notes-title">{{ t('contact.notesTitle') }}</h2>
        </div>
        <!-- 经 renderPlainMarkdown（markdown-it + DOMPurify）消毒，禁止改绑原始渲染结果 -->
        <div class="contact-markdown" v-html="renderedBody" />
      </section>
    </div>
  </div>
</template>

<style scoped>
/* Hallmark · macrostructure: Index-First · theme: project-managed (style.css tokens) · voice: terminal transcript · motion: caret-blink only
 * Hallmark · pre-emit critique: P4 H4 E4 S5 R5 V4
 * contrast: pass (40–41) · honest: pass (46) · chrome: pass (47) · tokens: pass (48) · responsive: pass (49) · mobile: pass (34, 49, 50–57) · icons: pass (30) · nav/footer: app-shell（不在本次范围） */
.contact-page {
  --contact-mono: ui-monospace, 'JetBrains Mono', 'Fira Code', Menlo, Consolas, 'Liberation Mono', monospace;
  --cs-3xs: 0.125rem;
  --cs-1: 0.25rem;
  --cs-2: 0.5rem;
  --cs-3: 0.75rem;
  --cs-4: 1rem;
  --cs-5: 1.5rem;
  --cs-6: 2rem;
  --cs-7: 2.5rem;
  --cs-dock-clear: 112px; /* 与 LayoutView/AppDock 的底部安全区契约，勿随排版节奏改动 */
  width: 100%;
  height: 100%;
  overflow-y: auto;
  overflow-x: clip;
  box-sizing: border-box;
  padding: var(--cs-5) var(--cs-4) var(--cs-dock-clear);
}
.contact-shell {
  width: 100%;
  max-width: 46rem;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--cs-7);
  min-width: 0;
}

/* ── 终端会话语法：提示符行 / 方块光标 / 树形前缀 ── */
.term-line {
  margin: 0;
  font-family: var(--contact-mono);
  font-size: 0.75rem;
  line-height: 1.7;
  color: var(--ink-muted);
  letter-spacing: 0.02em;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.term-prompt { color: var(--ink); font-weight: 700; }
.term-caret {
  display: inline-block;
  width: 0.58ch;
  height: 1.05em;
  margin-left: 0.4ch;
  vertical-align: text-bottom;
  background: var(--acid);
  outline: 1px solid var(--rule-strong);
  animation: contact-caret-blink 1.06s step-end infinite;
}
@keyframes contact-caret-blink {
  0%, 50% { opacity: 1; }
  50.01%, 100% { opacity: 0; }
}
.tree-branch {
  font-family: var(--contact-mono);
  font-size: 0.8125rem;
  line-height: 1.55;
  color: var(--ink-muted);
}

/* ── Hero：一条已执行的命令及其输出 ── */
.contact-hero { padding: var(--cs-2) 0 var(--cs-6); border-bottom: 1px solid var(--rule-strong); }
.contact-command { font-size: 0.8125rem; }
.contact-kicker {
  display: block;
  width: fit-content;
  margin: var(--cs-4) 0 0;
  padding: var(--cs-3xs) var(--cs-2);
  font-family: var(--contact-mono);
  font-size: 0.6875rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--acid-ink);
  background: var(--acid);
  outline: 1px solid var(--rule-strong);
}
.contact-title {
  margin: var(--cs-3) 0 0;
  max-width: 22ch;
  color: var(--ink);
  font-size: clamp(1.875rem, 1.2rem + 2.6vw, 2.75rem);
  font-weight: 750;
  letter-spacing: -0.03em;
  line-height: 1.08;
  overflow-wrap: anywhere;
  min-width: 0;
}
.contact-subtitle {
  margin: var(--cs-4) 0 0;
  max-width: 62ch;
  color: var(--ink-secondary);
  font-size: 0.9375rem;
  line-height: 1.8;
  white-space: pre-line;
  overflow-wrap: anywhere;
}
.contact-hero-note {
  margin: var(--cs-5) 0 0;
  font-family: var(--contact-mono);
  font-size: 0.75rem;
  line-height: 1.7;
  color: var(--ink-muted);
}
.contact-hero-note::before { content: '# '; color: var(--ink-muted); }

/* ── 区块头：子命令 + [NN] 编号 + 标题 + 发丝线 ── */
.contact-section { min-width: 0; }
.section-heading { margin-bottom: var(--cs-4); padding-bottom: var(--cs-3); border-bottom: 1px solid var(--rule); }
.section-heading .term-line { margin-bottom: var(--cs-3); }
.section-kicker {
  margin: 0 0 var(--cs-2);
  font-family: var(--contact-mono);
  font-size: 0.6875rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--ink-muted);
}
.section-heading h2 {
  margin: 0;
  color: var(--ink);
  font-size: 1.25rem;
  font-weight: 750;
  letter-spacing: -0.02em;
  line-height: 1.3;
  overflow-wrap: anywhere;
}

/* ── services 索引：树形行，无卡片 ── */
.service-grid { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.service-card {
  display: grid;
  grid-template-columns: auto auto minmax(0, 1fr);
  gap: var(--cs-3);
  align-items: start;
  padding: var(--cs-4) 0;
  border-top: 1px solid var(--rule);
}
.service-card:first-child { border-top: 0; padding-top: var(--cs-2); }
.service-icon { width: 1.75rem; height: 1.75rem; display: inline-flex; color: var(--ink); }
.service-icon :deep(svg) { width: 100%; height: 100%; }
.service-body { min-width: 0; display: flex; flex-direction: column; gap: var(--cs-1); }
.service-title { margin: 0; color: var(--ink); font-size: 0.9375rem; font-weight: 700; line-height: 1.4; overflow-wrap: anywhere; }
.service-desc { margin: 0; color: var(--ink-secondary); font-size: 0.8125rem; line-height: 1.7; white-space: pre-line; overflow-wrap: anywhere; }

/* ── contact.routes 索引：链接本身就是按钮 ── */
.entry-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.entry-item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: var(--cs-3);
  padding: var(--cs-4) 0 var(--cs-4) var(--cs-3);
  border-top: 1px solid var(--rule);
}
.entry-item:first-child { border-top: 0; padding-top: var(--cs-2); }
.entry-item--primary {
  background: var(--paper-raised);
  box-shadow: inset 3px 0 0 var(--acid-strong);
  padding-right: var(--cs-3);
  margin-right: calc(-1 * var(--cs-3));
}
.entry-body { min-width: 0; display: flex; flex-direction: column; align-items: flex-start; gap: var(--cs-3); }
.entry-meta { display: flex; align-items: center; gap: var(--cs-3); flex-wrap: wrap; }
.entry-label {
  font-family: var(--contact-mono);
  font-size: 0.6875rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  line-height: 1.4;
  text-transform: uppercase;
  color: var(--ink);
  overflow-wrap: anywhere;
}
.entry-badge {
  padding: var(--cs-3xs) var(--cs-2);
  font-family: var(--contact-mono);
  font-size: 0.625rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--acid-ink);
  background: var(--acid);
  outline: 1px solid var(--rule-strong);
  white-space: nowrap;
}
.entry-value {
  max-width: 100%;
  font-family: var(--contact-mono);
  font-size: 0.8125rem;
  font-weight: 650;
  line-height: 1.6;
  color: var(--ink);
  overflow-wrap: anywhere;
  word-break: break-word;
}
.entry-value--link {
  text-decoration: underline;
  text-decoration-color: var(--ink-faint);
  text-underline-offset: 2px;
}
.entry-value--link:hover {
  color: var(--acid-ink);
  background: var(--acid);
  outline: 1px solid var(--rule-strong);
  text-decoration-color: transparent;
}
.entry-value--link:active { color: var(--paper); background: var(--ink); outline-color: var(--ink); }
.entry-action--primary {
  padding: 0 4px;
  color: var(--acid-ink);
  background: var(--acid);
  outline: 1px solid var(--rule-strong);
  text-decoration: none;
  font-weight: 700;
}
.entry-action--primary:hover { color: var(--paper); background: var(--ink); outline-color: var(--ink); }
.entry-action--primary:active { color: var(--ink); background: var(--paper-muted); }
.entry-arrow { margin-left: 0.25em; }
.entry-qr-frame {
  width: 9.5rem;
  max-width: 100%;
  aspect-ratio: 1;
  box-sizing: border-box;
  padding: var(--cs-2);
  display: grid;
  place-items: center;
  background: var(--paper-raised);
  border: 1px solid var(--rule-strong);
}
.entry-qr { display: block; width: 100%; height: 100%; object-fit: contain; image-rendering: pixelated; }
.entry-qr-fallback {
  padding: var(--cs-2);
  font-family: var(--contact-mono);
  font-size: 0.6875rem;
  line-height: 1.6;
  color: var(--ink-secondary);
  text-align: center;
}
.entry-qr-fallback::before { content: '[!] '; color: var(--ink-muted); }
.entry-qr-hint { font-family: var(--contact-mono); font-size: 0.6875rem; line-height: 1.5; color: var(--ink-muted); }
.entry-qr-hint::before { content: '› '; color: var(--ink-muted); }

/* ── NOTES.md：正文按 readme/man page 渲染 ── */
.contact-markdown { max-width: 72ch; color: var(--ink-secondary); font-size: 0.875rem; line-height: 1.8; }
.contact-markdown :deep(h1), .contact-markdown :deep(h2), .contact-markdown :deep(h3) {
  margin: var(--cs-5) 0 var(--cs-3);
  padding-bottom: var(--cs-2);
  color: var(--ink);
  border-bottom: 1px solid var(--rule);
  font-weight: 650;
  overflow-wrap: anywhere;
}
.contact-markdown :deep(h1) { font-size: 1.25rem; }
.contact-markdown :deep(h2) { font-size: 1.0625rem; }
.contact-markdown :deep(h3) { font-size: 0.9375rem; }
.contact-markdown :deep(h1)::before, .contact-markdown :deep(h2)::before, .contact-markdown :deep(h3)::before {
  font-family: var(--contact-mono);
  font-weight: 400;
  color: var(--ink-muted);
}
.contact-markdown :deep(h1)::before { content: '# '; }
.contact-markdown :deep(h2)::before { content: '## '; }
.contact-markdown :deep(h3)::before { content: '### '; }
.contact-markdown :deep(p) { margin: 0 0 var(--cs-3); }
.contact-markdown :deep(a) {
  color: var(--ink);
  text-decoration: underline;
  text-decoration-color: var(--acid-strong);
  text-underline-offset: 2px;
}
.contact-markdown :deep(a:hover) { color: var(--acid-ink); background: var(--acid); text-decoration-color: transparent; }
.contact-markdown :deep(ul), .contact-markdown :deep(ol) { margin: var(--cs-2) 0 var(--cs-3); padding-left: var(--cs-5); }
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
  font-family: var(--contact-mono);
  font-size: 0.85em;
  padding: 0.1em 0.35em;
  color: var(--ink);
  background: var(--paper-muted);
  border: 1px solid var(--rule);
}
.contact-markdown :deep(pre) {
  padding: var(--cs-3) var(--cs-4);
  overflow-x: auto;
  font-family: var(--contact-mono);
  font-size: 0.8125rem;
  line-height: 1.7;
  background: var(--paper-muted);
  border: 1px solid var(--rule);
}
.contact-markdown :deep(pre code) { padding: 0; background: none; border: none; font-size: inherit; }

@media (min-width: 48rem) {
  .contact-page { padding: var(--cs-7) clamp(1.5rem, 4vw, 2.5rem) var(--cs-dock-clear); }
}
@media (prefers-reduced-motion: reduce) {
  .term-caret { animation: none; }
}
</style>
