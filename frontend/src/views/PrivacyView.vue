<script setup lang="ts">
import { computed, ref } from 'vue'
import { Clock, MessagesSquare, Trash2 } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import LegalFacts from '@/components/legal/LegalFacts.vue'
import LegalLine from '@/components/legal/LegalLine.vue'
import LegalToc from '@/components/legal/LegalToc.vue'
import { tocLabel } from '@/features/legal/legalText'

const router = useRouter()
const { t } = useI18n()
const page = ref<HTMLElement | null>(null)
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
// 桌面漫画版把最后几节（未成年人、权利，连同联系方式）放进右侧吸顶栏；窄屏两组按原顺序连排。
const ASIDE = new Set<string>(['minorTitle', 'rightsTitle'])
const groups = [
  { key: 'main', sections: sections.filter((section) => !ASIDE.has(section.title)) },
  { key: 'aside', sections: sections.filter((section) => ASIDE.has(section.title)) },
]
const toc = computed(() => [...sections.map((section) => section.title), 'contactTitle'].map((title) => ({
  id: `legal-${title}`, label: tocLabel(t(`legal.privacy.${title}`)),
})))
// 数值摘自正文（logs / security2 / right3），改正文时一起改。
const facts = computed(() => [
  { icon: Clock, label: t('legal.privacyFacts.logs.label'), value: t('legal.privacyFacts.logs.value') },
  { icon: MessagesSquare, label: t('legal.privacyFacts.sessions.label'), value: t('legal.privacyFacts.sessions.value') },
  { icon: Trash2, label: t('legal.privacyFacts.deletion.label'), value: t('legal.privacyFacts.deletion.value') },
])
</script>

<template>
  <div ref="page" class="legal-page">
    <div class="legal-card">
      <button class="back-btn" @click="router.back()">← {{ t('legal.back') }}</button>
      <div class="legal-head">
        <div class="legal-heading">
          <h1 class="legal-title comic-title">{{ t('legal.privacyTitle') }}</h1>
          <p class="legal-meta">{{ t('legal.updated') }}</p>
        </div>
        <LegalFacts :facts="facts" />
      </div>
      <div class="legal-layout">
        <LegalToc :root="page" :items="toc" />
        <div class="legal-body">
          <div v-for="group in groups" :key="group.key" :class="`legal-${group.key}`">
            <section v-for="section in group.sections" :id="`legal-${section.title}`" :key="section.title">
              <h2>{{ t(`legal.privacy.${section.title}`) }}</h2>
              <p v-for="key in ('paragraphs' in section ? section.paragraphs : [])" :key="key"><LegalLine :text="t(`legal.privacy.${key}`)" /></p>
              <ul v-if="'items' in section">
                <li v-for="key in section.items" :key="key"><LegalLine :text="t(`legal.privacy.${key}`)" /></li>
              </ul>
              <p v-if="'warning' in section" class="warning-text">{{ t(`legal.privacy.${section.warning}`) }}</p>
            </section>
            <section v-if="group.key === 'aside'" id="legal-contactTitle">
              <h2>{{ t('legal.privacy.contactTitle') }}</h2>
              <p>{{ t('legal.privacy.contactText') }}</p>
              <div class="contact-block"><a href="mailto:kaixxrua@gmail.com">kaixxrua@gmail.com</a></div>
            </section>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.legal-page{width:100%;height:100%;overflow-y:auto;display:flex;justify-content:center;padding:32px 24px 48px;box-sizing:border-box}.legal-card{width:100%;max-width:720px}.back-btn{font-size:13px;color:rgb(var(--stone-500-rgb));background:none;border:0;cursor:pointer;padding:4px 0;margin-bottom:24px}.legal-title{font-size:26px;font-weight:700;color:rgb(var(--stone-900-rgb));margin:0 0 8px;font-family:'Playfair Display',serif}.legal-meta{font-size:12px;color:rgb(var(--stone-400-rgb));margin:0 0 32px}.legal-body{display:flex;flex-direction:column;gap:28px}.legal-body h2{font-size:15px;font-weight:600;color:rgb(var(--stone-800-rgb));margin:0 0 10px;padding-bottom:6px;border-bottom:1px solid rgb(var(--stone-400-rgb) / .15)}.legal-body p,.legal-body li{font-size:14px;line-height:1.75;color:rgb(var(--stone-600-rgb))}.legal-body p{margin:0 0 8px}.legal-body ul{margin:8px 0 0;padding-left:20px}.legal-body li{margin:6px 0}.warning-text{font-size:13px!important;background:rgba(251,146,60,.05);border:1px solid rgba(251,146,60,.15);border-radius:8px;padding:10px 14px}.contact-block{display:inline-flex;margin-top:10px;padding:10px 16px;background:rgb(var(--stone-100-rgb));border-radius:10px;max-width:100%}.contact-block a{color:rgb(var(--stone-700-rgb));text-decoration:none;font-weight:500;overflow-wrap:anywhere}

/* 桌面漫画版的分栏外壳；其余布局下透明，正文仍是 .legal-body 里一列连排的小节。 */
.legal-head,.legal-heading,.legal-layout,.legal-main,.legal-aside{display:contents}

/* 移动端：收窄页边距与标题字号，正文保持 14px 可读行高 */
@media (max-width:639px){.legal-page{padding:20px 14px 40px}.legal-title{font-size:22px}.legal-meta{margin-bottom:24px}.legal-body{gap:22px}}
</style>
