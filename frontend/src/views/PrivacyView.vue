<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

const router = useRouter()
const { t } = useI18n()
const sections = [
  { title: 'payTitle', paragraphs: ['payText'] },
  { title: 'collectTitle', paragraphs: ['collectIntro'], items: ['email', 'password', 'logs'] },
  { title: 'aiTitle', paragraphs: ['aiText'], warning: 'aiWarning' },
  { title: 'useTitle', items: ['use1', 'use2', 'use3', 'use4'] },
  { title: 'securityTitle', paragraphs: ['security1', 'security2'] },
  { title: 'cookieTitle', paragraphs: ['cookieText'] },
  { title: 'minorTitle', paragraphs: ['minorText'] },
  { title: 'rightsTitle', paragraphs: ['rightsIntro'], items: ['right1', 'right2', 'right3'] },
] as const
</script>

<template>
  <div class="legal-page">
    <div class="legal-card">
      <button class="back-btn" @click="router.back()">← {{ t('legal.back') }}</button>
      <h1 class="legal-title">{{ t('legal.privacyTitle') }}</h1>
      <p class="legal-meta">{{ t('legal.updated') }}</p>
      <div class="legal-body">
        <section v-for="section in sections" :key="section.title">
          <h2>{{ t(`legal.privacy.${section.title}`) }}</h2>
          <p v-for="key in ('paragraphs' in section ? section.paragraphs : [])" :key="key">{{ t(`legal.privacy.${key}`) }}</p>
          <ul v-if="'items' in section">
            <li v-for="key in section.items" :key="key">{{ t(`legal.privacy.${key}`) }}</li>
          </ul>
          <p v-if="'warning' in section" class="warning-text">{{ t(`legal.privacy.${section.warning}`) }}</p>
        </section>
        <section>
          <h2>{{ t('legal.privacy.contactTitle') }}</h2>
          <p>{{ t('legal.privacy.contactText') }}</p>
          <div class="contact-block"><a href="mailto:kaixxrua@gmail.com">kaixxrua@gmail.com</a></div>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.legal-page{width:100%;height:100%;overflow-y:auto;display:flex;justify-content:center;padding:32px 24px 48px;box-sizing:border-box}.legal-card{width:100%;max-width:720px}.back-btn{font-size:13px;color:rgb(var(--stone-500-rgb));background:none;border:0;cursor:pointer;padding:4px 0;margin-bottom:24px}.legal-title{font-size:26px;font-weight:700;color:rgb(var(--stone-900-rgb));margin:0 0 8px;font-family:'Playfair Display',serif}.legal-meta{font-size:12px;color:rgb(var(--stone-400-rgb));margin:0 0 32px}.legal-body{display:flex;flex-direction:column;gap:28px}.legal-body h2{font-size:15px;font-weight:600;color:rgb(var(--stone-800-rgb));margin:0 0 10px;padding-bottom:6px;border-bottom:1px solid rgb(var(--stone-400-rgb) / .15)}.legal-body p,.legal-body li{font-size:14px;line-height:1.75;color:rgb(var(--stone-600-rgb))}.legal-body p{margin:0 0 8px}.legal-body ul{margin:8px 0 0;padding-left:20px}.legal-body li{margin:6px 0}.warning-text{font-size:13px!important;background:rgba(251,146,60,.05);border:1px solid rgba(251,146,60,.15);border-radius:8px;padding:10px 14px}.contact-block{display:inline-flex;margin-top:10px;padding:10px 16px;background:rgb(var(--stone-100-rgb));border-radius:10px;max-width:100%}.contact-block a{color:rgb(var(--stone-700-rgb));text-decoration:none;font-weight:500;overflow-wrap:anywhere}

/* 移动端：收窄页边距与标题字号，正文保持 14px 可读行高 */
@media (max-width:639px){.legal-page{padding:20px 14px 40px}.legal-title{font-size:22px}.legal-meta{margin-bottom:24px}.legal-body{gap:22px}}
</style>
