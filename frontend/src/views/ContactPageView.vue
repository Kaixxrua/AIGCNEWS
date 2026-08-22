<script setup lang="ts">
import { computed } from 'vue'
import { useContactPageConfig } from '@/composables/useContactPageConfig'
import { renderPlainMarkdown } from '@/composables/useLatexRenderer'
import type { SiteContactEntry } from '@/services/site/contactPageApi'

/**
 * 联系合作页：内容由管理员在 monitor「站点 → 联系合作页」撰写（单语言）。
 * 路由守卫已在页面未启用时重定向，此处 enabled 判断仅作防御兜底。
 */
const { contactPageConfig } = useContactPageConfig()
const config = contactPageConfig

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
</script>

<template>
  <div v-if="config.enabled" class="contact-page">
    <div class="contact-card">
      <header class="contact-hero">
        <h1 class="contact-title">{{ config.title }}</h1>
        <p v-if="config.subtitle" class="contact-subtitle">{{ config.subtitle }}</p>
      </header>

      <section v-if="config.serviceCards.length" class="contact-section">
        <div class="service-grid">
          <article v-for="card in config.serviceCards" :key="card.title" class="service-card glass-card">
            <span class="service-icon" v-html="cardIcon(card.icon)" />
            <h2 class="service-title">{{ card.title }}</h2>
            <p v-if="card.description" class="service-desc">{{ card.description }}</p>
          </article>
        </div>
      </section>

      <section v-if="config.contactEntries.length" class="contact-section">
        <div class="entry-list">
          <div v-for="entry in config.contactEntries" :key="entry.label" class="entry-item glass-card">
            <span class="entry-label">{{ entry.label }}</span>
            <img
              v-if="entry.qrImageUrl"
              class="entry-qr"
              :src="entry.qrImageUrl"
              :alt="entry.label"
              loading="lazy"
            />
            <a
              v-if="entry.href"
              class="entry-value entry-value--link"
              :href="entry.href"
              v-bind="linkAttrs(entry)"
            >{{ entry.value || entry.href }}</a>
            <span v-else-if="entry.value" class="entry-value">{{ entry.value }}</span>
          </div>
        </div>
      </section>

      <section v-if="config.bodyMarkdown.trim()" class="contact-section contact-markdown-section">
        <!-- 经 renderPlainMarkdown（markdown-it + DOMPurify）消毒，禁止改绑原始渲染结果 -->
        <div class="contact-markdown" v-html="renderedBody" />
      </section>
    </div>
  </div>
</template>

<style scoped>
.contact-page {
  width: 100%;
  height: 100%;
  overflow-y: auto;
  display: flex;
  justify-content: center;
  padding: 32px 24px 48px;
  box-sizing: border-box;
}

.contact-card {
  width: 100%;
  max-width: 860px;
  display: flex;
  flex-direction: column;
  gap: 28px;
}

.contact-hero {
  text-align: center;
}

.contact-title {
  font-size: 28px;
  font-weight: 700;
  color: var(--ink);
  margin: 0 0 10px;
  font-family: 'Playfair Display', serif;
}

.contact-subtitle {
  font-size: 14px;
  line-height: 1.7;
  color: var(--ink-muted);
  margin: 0 auto;
  max-width: 560px;
  white-space: pre-line;
}

.service-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 14px;
}

.service-card {
  padding: 18px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.service-icon {
  width: 26px;
  height: 26px;
  color: var(--acid-ink);
  display: inline-flex;
}

.service-icon :deep(svg) {
  width: 26px;
  height: 26px;
}

.service-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--ink);
  margin: 0;
}

.service-desc {
  font-size: 13px;
  line-height: 1.7;
  color: var(--ink-secondary);
  margin: 0;
  white-space: pre-line;
}

.entry-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 340px));
  justify-content: center;
  gap: 14px;
}

/* 联系卡片以二维码为视觉主体：标签在上、QR 大图居中、CTA 按钮收尾 */
.entry-item {
  padding: 20px 18px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 12px;
}

.entry-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-muted);
  letter-spacing: 0.02em;
}

.entry-value {
  font-size: 15px;
  font-weight: 600;
  color: var(--ink);
  word-break: break-all;
}

/* 外链联系方式渲染为 CTA 胶囊按钮（拉起 QQ/打开合作链接的动作入口），
   配色对齐 Dock 激活态：acid 实色底 + acid-ink 文字 */
.entry-value--link {
  display: inline-flex;
  align-items: center;
  padding: 9px 22px;
  border-radius: 999px;
  background: var(--acid);
  color: var(--acid-ink);
  border: 1px solid var(--acid-strong);
  text-decoration: none;
  transition: background-color 150ms ease;
}

.entry-value--link:hover {
  background: var(--acid-bright);
  color: var(--acid-ink);
}

/* 二维码是加群动作的另一入口，必须大到随手可扫 */
.entry-qr {
  width: 220px;
  height: 220px;
  object-fit: contain;
  border-radius: 10px;
  border: 1px solid var(--rule);
  background: var(--paper-raised);
}

.contact-markdown {
  font-size: 14px;
  line-height: 1.8;
  color: var(--ink-secondary);
}

.contact-markdown :deep(h1),
.contact-markdown :deep(h2),
.contact-markdown :deep(h3) {
  color: var(--ink);
  font-weight: 600;
  margin: 20px 0 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--rule);
}

.contact-markdown :deep(h1) { font-size: 20px; }
.contact-markdown :deep(h2) { font-size: 17px; }
.contact-markdown :deep(h3) { font-size: 15px; }

.contact-markdown :deep(p) {
  margin: 0 0 12px;
}

.contact-markdown :deep(a) {
  color: var(--acid-ink);
  text-decoration: none;
  border-bottom: 1px solid var(--acid-strong);
}

.contact-markdown :deep(a:hover) {
  color: var(--ink);
}

.contact-markdown :deep(ul),
.contact-markdown :deep(ol) {
  margin: 8px 0 12px;
  padding-left: 22px;
}

.contact-markdown :deep(li) {
  margin: 5px 0;
}

.contact-markdown :deep(img) {
  max-width: 100%;
  border-radius: 8px;
  border: 1px solid var(--rule);
}

.contact-markdown :deep(blockquote) {
  margin: 12px 0;
  padding: 8px 14px;
  border-left: 3px solid var(--acid);
  background: var(--paper-muted);
  color: var(--ink-muted);
}

.contact-markdown :deep(code) {
  font-size: 13px;
  background: var(--paper-muted);
  border: 1px solid var(--rule);
  border-radius: 4px;
  padding: 1px 5px;
}

.contact-markdown :deep(pre) {
  background: var(--paper-muted);
  border: 1px solid var(--rule);
  border-radius: 8px;
  padding: 12px 14px;
  overflow-x: auto;
}

.contact-markdown :deep(pre code) {
  background: none;
  border: none;
  padding: 0;
}

@media (max-width: 639px) {
  .contact-page {
    padding: 20px 14px 32px;
  }

  .contact-title {
    font-size: 23px;
  }

  /* 服务卡与联系方式卡强制单列：auto-fill/auto-fit 的 minmax 下限
     在 375px 减去页边距后只剩一列，但显式单列能避免临界宽度抖动 */
  .service-grid,
  .entry-list {
    grid-template-columns: 1fr;
  }

  .entry-qr {
    width: 200px;
    height: 200px;
  }
}
</style>
