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
</script>

<template>
  <div v-if="config.enabled" class="contact-page">
    <div class="contact-card">
      <header class="contact-hero">
        <div class="contact-hero-copy">
          <p class="contact-kicker">{{ t('contact.kicker') }}</p>
          <h1 class="contact-title">{{ config.title }}</h1>
          <p v-if="config.subtitle" class="contact-subtitle">{{ config.subtitle }}</p>
        </div>
        <div v-if="config.contactEntries.length" class="contact-hero-note">
          <span class="contact-hero-note__line" aria-hidden="true" />
          <span>{{ t('contact.heroNote') }}</span>
        </div>
      </header>

      <div class="contact-main-grid">
        <section v-if="config.serviceCards.length" class="contact-section service-section" aria-labelledby="contact-services-title">
          <div class="section-heading">
            <p class="section-kicker">{{ t('contact.servicesKicker') }}</p>
            <h2 id="contact-services-title">{{ t('contact.servicesTitle') }}</h2>
          </div>
          <div class="service-grid">
            <article v-for="(card, index) in config.serviceCards" :key="`${index}-${card.title}`" class="service-card glass-card">
              <span class="service-index">0{{ index + 1 }}</span>
              <span class="service-icon" v-html="cardIcon(card.icon)" aria-hidden="true" />
              <h3 class="service-title">{{ card.title }}</h3>
              <p v-if="card.description" class="service-desc">{{ card.description }}</p>
            </article>
          </div>
        </section>

        <section v-if="config.contactEntries.length" class="contact-section entry-section" aria-labelledby="contact-entry-title">
          <div class="section-heading">
            <p class="section-kicker">{{ t('contact.entryKicker') }}</p>
            <h2 id="contact-entry-title">{{ t('contact.entryTitle') }}</h2>
          </div>
          <div class="entry-list">
            <article v-for="(entry, index) in config.contactEntries" :key="`${index}-${entry.label}`" class="entry-item glass-card" :class="{ 'entry-item--primary': isPrimaryEntry(index) }">
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
            </article>
          </div>
        </section>
      </div>

      <section v-if="config.bodyMarkdown.trim()" class="contact-section contact-markdown-section" aria-labelledby="contact-notes-title">
        <div class="section-heading section-heading--notes">
          <p class="section-kicker">{{ t('contact.notesKicker') }}</p>
          <h2 id="contact-notes-title">{{ t('contact.notesTitle') }}</h2>
        </div>
        <!-- 经 renderPlainMarkdown（markdown-it + DOMPurify）消毒，禁止改绑原始渲染结果 -->
        <div class="contact-markdown" v-html="renderedBody" />
      </section>
    </div>
  </div>
</template>

<style scoped>
.contact-page { width: 100%; height: 100%; overflow-y: auto; box-sizing: border-box; padding: 32px 28px 112px; }
.contact-card { width: 100%; max-width: 1120px; margin: 0 auto; display: flex; flex-direction: column; gap: 38px; min-width: 0; }
.contact-hero { display: flex; align-items: flex-end; justify-content: space-between; gap: 32px; padding: 12px 2px 26px; border-bottom: 1px solid var(--rule-strong); }
.contact-hero-copy { min-width: 0; }
.contact-kicker, .section-kicker { margin: 0 0 10px; color: var(--ink-muted); font-size: 11px; font-weight: 800; letter-spacing: .12em; line-height: 1.4; text-transform: uppercase; }
.contact-title { margin: 0; color: var(--ink); font-size: clamp(30px, 4vw, 52px); font-weight: 750; letter-spacing: -.045em; line-height: 1.05; max-width: 760px; }
.contact-subtitle { margin: 16px 0 0; max-width: 660px; color: var(--ink-secondary); font-size: 15px; line-height: 1.8; white-space: pre-line; }
.contact-hero-note { display: flex; align-items: center; gap: 10px; flex: 0 0 auto; max-width: 190px; color: var(--ink-muted); font-size: 12px; line-height: 1.5; }
.contact-hero-note__line { width: 28px; height: 1px; flex: 0 0 auto; background: var(--acid-strong); }
.contact-main-grid { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(300px, .75fr); gap: 52px; align-items: start; }
.contact-section { min-width: 0; }
.section-heading { margin-bottom: 18px; }
.section-heading h2 { margin: 0; color: var(--ink); font-size: 19px; font-weight: 750; letter-spacing: -.02em; line-height: 1.25; }
.section-heading--notes { margin-bottom: 14px; }
.service-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.service-card { position: relative; min-width: 0; min-height: 166px; padding: 20px 18px 18px; display: flex; flex-direction: column; align-items: flex-start; gap: 9px; overflow: hidden; transition: transform 150ms ease, box-shadow 150ms ease, border-color 150ms ease; }
.service-card:hover { transform: translate(-2px, -2px); border-color: var(--rule-strong); box-shadow: 5px 5px 0 var(--acid); }
.service-index { position: absolute; top: 16px; right: 17px; color: var(--ink-faint); font-size: 11px; font-weight: 800; letter-spacing: .08em; }
.service-icon { width: 28px; height: 28px; margin-bottom: 10px; display: inline-flex; color: var(--acid-ink); }
.service-icon :deep(svg) { width: 28px; height: 28px; }
.service-title { margin: 0; color: var(--ink); font-size: 15px; font-weight: 700; line-height: 1.35; overflow-wrap: anywhere; }
.service-desc { margin: 0; color: var(--ink-secondary); font-size: 13px; line-height: 1.65; white-space: pre-line; overflow-wrap: anywhere; }
.entry-list { display: flex; flex-direction: column; gap: 12px; }
.entry-item { min-width: 0; padding: 18px; display: flex; flex-direction: column; align-items: flex-start; gap: 12px; transition: border-color 150ms ease, box-shadow 150ms ease; }
.entry-item--primary { border-color: var(--rule-strong); box-shadow: 5px 5px 0 var(--acid); }
.entry-meta { width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.entry-label { color: var(--ink-muted); font-size: 11px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; overflow-wrap: anywhere; }
.entry-badge { padding: 3px 7px; color: var(--acid-ink); background: var(--acid); border: 1px solid var(--acid-strong); font-size: 10px; font-weight: 800; white-space: nowrap; }
.entry-value { max-width: 100%; color: var(--ink); font-size: 15px; font-weight: 650; line-height: 1.5; overflow-wrap: anywhere; word-break: break-word; }
.entry-value--link { display: inline-flex; align-items: center; gap: 9px; padding: 9px 13px; color: var(--ink); border: 1px solid var(--rule-strong); background: var(--paper-raised); text-decoration: none; transition: background-color 150ms ease, color 150ms ease, transform 150ms ease; }
.entry-value--link:hover { color: var(--acid-ink); background: var(--acid); transform: translateY(-1px); }
.entry-action--primary { color: var(--acid-ink); background: var(--acid); border-color: var(--acid-strong); font-weight: 800; }
.entry-action--primary:hover { color: var(--btn-primary-label); background: var(--ink); border-color: var(--ink); }
.entry-arrow { font-size: 16px; line-height: 1; }
.entry-qr-frame { width: min(100%, 220px); aspect-ratio: 1; display: grid; place-items: center; align-self: center; background: var(--paper-raised); border: 1px solid var(--rule); }
.entry-qr { display: block; width: 100%; height: 100%; object-fit: contain; }
.entry-qr-fallback { padding: 20px; color: var(--ink-muted); font-size: 12px; line-height: 1.6; text-align: center; }
.entry-qr-hint { align-self: center; color: var(--ink-muted); font-size: 11px; line-height: 1.4; }
.contact-markdown-section { padding-top: 4px; border-top: 1px solid var(--rule); }
.contact-markdown { max-width: 760px; color: var(--ink-secondary); font-size: 14px; line-height: 1.8; }
.contact-markdown :deep(h1), .contact-markdown :deep(h2), .contact-markdown :deep(h3) { margin: 20px 0 10px; padding-bottom: 6px; color: var(--ink); border-bottom: 1px solid var(--rule); font-weight: 650; }
.contact-markdown :deep(h1) { font-size: 20px; } .contact-markdown :deep(h2) { font-size: 17px; } .contact-markdown :deep(h3) { font-size: 15px; }
.contact-markdown :deep(p) { margin: 0 0 12px; } .contact-markdown :deep(a) { color: var(--acid-ink); text-decoration: none; border-bottom: 1px solid var(--acid-strong); }
.contact-markdown :deep(ul), .contact-markdown :deep(ol) { margin: 8px 0 12px; padding-left: 22px; }
.contact-markdown :deep(li) { margin: 5px 0; } .contact-markdown :deep(img) { max-width: 100%; border: 1px solid var(--rule); }
.contact-markdown :deep(blockquote) { margin: 12px 0; padding: 8px 14px; color: var(--ink-muted); background: var(--paper-muted); border-left: 3px solid var(--acid); }
.contact-markdown :deep(code) { padding: 1px 5px; color: var(--ink); background: var(--paper-muted); border: 1px solid var(--rule); border-radius: 4px; }
.contact-markdown :deep(pre) { padding: 12px 14px; overflow-x: auto; background: var(--paper-muted); border: 1px solid var(--rule); }
.contact-markdown :deep(pre code) { padding: 0; background: none; border: none; }
@media (max-width: 767px) { .contact-main-grid { grid-template-columns: 1fr; gap: 34px; } }
@media (max-width: 639px) { .contact-page { padding: 20px 14px 112px; } .contact-card { gap: 30px; } .contact-hero { align-items: flex-start; flex-direction: column; gap: 18px; padding-top: 4px; } .contact-hero-note { max-width: none; } .contact-title { font-size: clamp(29px, 9vw, 40px); } .contact-subtitle { font-size: 14px; } .service-grid { grid-template-columns: 1fr; } .entry-qr-frame { width: min(100%, 200px); } }
@media (prefers-reduced-motion: reduce) { .service-card, .entry-value--link { transition: none; } .service-card:hover, .entry-value--link:hover { transform: none; } }
</style>
