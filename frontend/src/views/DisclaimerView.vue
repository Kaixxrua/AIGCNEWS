<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'

const router = useRouter()
const { t } = useI18n()
const sections = [
  { title: 'aiTitle', paragraphs: ['aiWarning', 'aiReference', 'aiLiability', 'aiAcceptance'] },
  { title: 'conductTitle', paragraphs: ['conductIntro'], items: ['conduct1', 'conduct2', 'conduct3', 'conduct4', 'conduct5'], footer: 'conductWarning' },
  { title: 'ipTitle', paragraphs: ['upstream', 'generated', 'scraping'] },
  { title: 'serviceTitle', paragraphs: ['serviceIntro'], items: ['service1', 'service2', 'service3', 'service4'] },
  { title: 'accountTitle', paragraphs: ['account1', 'account2', 'account3'] },
] as const
</script>

<template>
  <div class="legal-page">
    <div class="legal-card">
      <button class="back-btn" @click="router.back()">← {{ t('legal.back') }}</button>
      <h1 class="legal-title">{{ t('legal.disclaimerTitle') }}</h1>
      <p class="legal-meta">{{ t('legal.disclaimerMeta') }}</p>
      <div class="legal-body">
        <section v-for="section in sections" :key="section.title">
          <h2>{{ t(`legal.disclaimer.${section.title}`) }}</h2>
          <p v-for="key in section.paragraphs" :key="key">{{ t(`legal.disclaimer.${key}`) }}</p>
          <ul v-if="'items' in section">
            <li v-for="key in section.items" :key="key">{{ t(`legal.disclaimer.${key}`) }}</li>
          </ul>
          <p v-if="'footer' in section" class="warning-text">{{ t(`legal.disclaimer.${section.footer}`) }}</p>
        </section>
        <section>
          <h2>{{ t('legal.disclaimer.contactTitle') }}</h2>
          <p>{{ t('legal.disclaimer.contactText') }}</p>
          <div class="contact-block"><a href="mailto:kaixxrua@gmail.com">kaixxrua@gmail.com</a></div>
          <p class="effective">{{ t('legal.disclaimer.effective') }}</p>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.legal-page{width:100%;height:100%;overflow-y:auto;display:flex;justify-content:center;padding:32px 24px 48px;box-sizing:border-box}.legal-card{width:100%;max-width:760px}.back-btn{font-size:13px;color:rgb(var(--stone-500-rgb));background:none;border:0;cursor:pointer;padding:4px 0;margin-bottom:24px}.legal-title{font-size:26px;font-weight:700;color:rgb(var(--stone-900-rgb));margin:0 0 8px;font-family:'Playfair Display',serif}.legal-meta{font-size:12px;color:rgb(var(--stone-400-rgb));margin:0 0 32px}.legal-body{display:flex;flex-direction:column;gap:28px}.legal-body h2{font-size:15px;font-weight:600;color:rgb(var(--stone-800-rgb));margin:0 0 12px;padding-bottom:8px;border-bottom:1px solid rgb(var(--stone-400-rgb) / .15)}.legal-body p,.legal-body li{font-size:14px;line-height:1.75;color:rgb(var(--stone-600-rgb))}.legal-body p{margin:0 0 10px}.legal-body ul{margin:8px 0 10px;padding-left:20px}.legal-body li{margin:6px 0}.warning-text{font-size:13px!important;background:rgba(254,226,226,.4);border:1px solid rgba(252,165,165,.3);border-radius:8px;padding:10px 14px}.contact-block{display:inline-flex;margin-top:10px;padding:10px 16px;background:rgb(var(--stone-100-rgb));border-radius:10px}.contact-block a{color:rgb(var(--stone-700-rgb));text-decoration:none;font-weight:500}.effective{margin-top:12px!important;font-size:12px!important;color:rgb(var(--stone-400-rgb))!important}
</style>
