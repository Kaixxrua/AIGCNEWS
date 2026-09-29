<script setup lang="ts">
import { computed, ref } from 'vue'
import { CalendarCheck, Sparkles, Timer } from 'lucide-vue-next'
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
  { title: 'aiTitle', paragraphs: ['aiWarning', 'aiReference', 'aiLiability', 'aiAcceptance'] },
  { title: 'conductTitle', paragraphs: ['conductIntro'], items: ['conduct1', 'conduct2', 'conduct3', 'conduct4', 'conduct5'], footer: 'conductWarning' },
  { title: 'ipTitle', paragraphs: ['upstream', 'generated', 'removalHow', 'removalSla', 'removalScope', 'scraping'] },
  { title: 'serviceTitle', paragraphs: ['serviceIntro'], items: ['service1', 'service2', 'service3', 'service4'] },
  { title: 'memberTitle', paragraphs: ['member1', 'member2', 'member3', 'member4'] },
  { title: 'accountTitle', paragraphs: ['account1', 'account2', 'account3'] },
] as const
const toc = computed(() => [...sections.map((section) => section.title), 'contactTitle'].map((title) => ({
  id: `legal-${title}`, label: tocLabel(t(`legal.disclaimer.${title}`)),
})))
// 数值摘自正文（removalSla / effective / aiReference），改正文时一起改。
const facts = computed(() => [
  { icon: Timer, label: t('legal.disclaimerFacts.removal.label'), value: t('legal.disclaimerFacts.removal.value') },
  { icon: CalendarCheck, label: t('legal.disclaimerFacts.effective.label'), value: t('legal.disclaimerFacts.effective.value') },
  { icon: Sparkles, label: t('legal.disclaimerFacts.ai.label'), value: t('legal.disclaimerFacts.ai.value') },
])
</script>

<template>
  <div ref="page" class="legal-page legal-page--disclaimer">
    <div class="legal-card">
      <button class="back-btn" @click="router.back()">← {{ t('legal.back') }}</button>
      <div class="legal-head">
        <div class="legal-heading">
          <h1 class="legal-title comic-title">{{ t('legal.disclaimerTitle') }}</h1>
          <p class="legal-meta">{{ t('legal.disclaimerMeta') }}</p>
        </div>
        <LegalFacts :facts="facts" />
      </div>
      <div class="legal-layout">
        <LegalToc :root="page" :items="toc" />
        <div class="legal-body">
          <div class="legal-main">
            <section v-for="section in sections" :id="`legal-${section.title}`" :key="section.title">
              <h2>{{ t(`legal.disclaimer.${section.title}`) }}</h2>
              <p v-for="key in section.paragraphs" :key="key"><LegalLine :text="t(`legal.disclaimer.${key}`)" /></p>
              <ul v-if="'items' in section">
                <li v-for="key in section.items" :key="key"><LegalLine :text="t(`legal.disclaimer.${key}`)" /></li>
              </ul>
              <p v-if="'footer' in section" class="warning-text">{{ t(`legal.disclaimer.${section.footer}`) }}</p>
            </section>
          </div>
          <!-- 桌面漫画版：联系方式与生效说明在右侧吸顶栏；窄屏接在正文后。 -->
          <div class="legal-aside">
            <section id="legal-contactTitle">
              <h2>{{ t('legal.disclaimer.contactTitle') }}</h2>
              <p>{{ t('legal.disclaimer.contactText') }}</p>
              <div class="contact-block"><a href="mailto:kaixxrua@gmail.com">kaixxrua@gmail.com</a></div>
              <p class="effective">{{ t('legal.disclaimer.effective') }}</p>
            </section>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.legal-page{width:100%;height:100%;overflow-y:auto;display:flex;justify-content:center;padding:32px 24px 48px;box-sizing:border-box}.legal-card{width:100%;max-width:760px}.back-btn{font-size:13px;color:rgb(var(--stone-500-rgb));background:none;border:0;cursor:pointer;padding:4px 0;margin-bottom:24px}.legal-title{font-size:26px;font-weight:700;color:rgb(var(--stone-900-rgb));margin:0 0 8px;font-family:'Playfair Display',serif}.legal-meta{font-size:12px;color:rgb(var(--stone-400-rgb));margin:0 0 32px}.legal-body{display:flex;flex-direction:column;gap:28px}.legal-body h2{font-size:15px;font-weight:600;color:rgb(var(--stone-800-rgb));margin:0 0 12px;padding-bottom:8px;border-bottom:1px solid rgb(var(--stone-400-rgb) / .15)}.legal-body p,.legal-body li{font-size:14px;line-height:1.75;color:rgb(var(--stone-600-rgb))}.legal-body p{margin:0 0 10px}.legal-body ul{margin:8px 0 10px;padding-left:20px}.legal-body li{margin:6px 0}.warning-text{font-size:13px!important;background:rgba(254,226,226,.4);border:1px solid rgba(252,165,165,.3);border-radius:8px;padding:10px 14px}.contact-block{display:inline-flex;margin-top:10px;padding:10px 16px;background:rgb(var(--stone-100-rgb));border-radius:10px;max-width:100%}.contact-block a{color:rgb(var(--stone-700-rgb));text-decoration:none;font-weight:500;overflow-wrap:anywhere}.effective{margin-top:12px!important;font-size:12px!important;color:rgb(var(--stone-400-rgb))!important}

/* 桌面漫画版的分栏外壳；其余布局下透明，正文仍是 .legal-body 里一列连排的小节。 */
.legal-head,.legal-heading,.legal-layout,.legal-main,.legal-aside{display:contents}

/* 移动端：收窄页边距与标题字号，正文保持 14px 可读行高 */
@media (max-width:639px){.legal-page{padding:20px 14px 40px}.legal-title{font-size:22px}.legal-meta{margin-bottom:24px}.legal-body{gap:22px}}
</style>
