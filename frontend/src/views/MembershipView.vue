<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/authStore'
import { useContactPageConfig } from '@/composables/useContactPageConfig'

defineOptions({ name: 'MembershipView' })

/**
 * 会员页：档位对比 + 定价 + 人工开通 CTA（执照/商户号未落地，先接咨询）。
 * 游客可见（获客入口）；CTA 优先进联系合作页，页面未启用时回退站长邮箱。
 */
const { t } = useI18n()
const authStore = useAuthStore()
const { contactPageConfig } = useContactPageConfig()

const isMember = computed(() => authStore.isMember)

const contactHref = computed(() =>
  contactPageConfig.value.enabled
    ? ''
    : `mailto:kaixxrua@gmail.com?subject=${encodeURIComponent(t('membership.ctaMailSubject'))}`,
)

const FREE_FEATURES = ['mcpAnonymous', 'mcpFree', 'briefingFree'] as const
const MEMBER_FEATURES = ['mcpMember', 'briefingMember', 'support'] as const
</script>

<template>
  <div class="membership-page">
    <div class="membership-card">
      <header class="stagger-enter membership-hero">
        <h1 class="membership-title">{{ t('membership.title') }}</h1>
        <p class="membership-subtitle">{{ t('membership.subtitle') }}</p>
      </header>

      <section class="stagger-enter tier-grid" style="animation-delay: 0.05s">
        <article class="glass-card tier-card">
          <h2 class="tier-name">{{ t('membership.free.name') }}</h2>
          <p class="tier-price">{{ t('membership.free.price') }}</p>
          <ul class="tier-features">
            <li v-for="key in FREE_FEATURES" :key="key">{{ t(`membership.free.features.${key}`) }}</li>
          </ul>
        </article>

        <article class="glass-card tier-card tier-card--member">
          <span v-if="isMember" class="tier-current-badge">{{ t('membership.currentMember') }}</span>
          <h2 class="tier-name">{{ t('membership.member.name') }}</h2>
          <p class="tier-price">
            <span class="tier-price-main">{{ t('membership.member.priceMonthly') }}</span>
            <span class="tier-price-alt">{{ t('membership.member.priceYearly') }}</span>
          </p>
          <ul class="tier-features">
            <li v-for="key in MEMBER_FEATURES" :key="key">{{ t(`membership.member.features.${key}`) }}</li>
          </ul>
        </article>
      </section>

      <section class="stagger-enter membership-cta" style="animation-delay: 0.1s">
        <p class="membership-cta-hint">{{ t('membership.ctaHint') }}</p>
        <template v-if="!isMember">
          <RouterLink v-if="contactPageConfig.enabled" to="/contact" class="cta-button">
            {{ t('membership.cta') }}
          </RouterLink>
          <a v-else :href="contactHref" class="cta-button">{{ t('membership.cta') }}</a>
        </template>
        <p v-else class="membership-member-note">{{ t('membership.memberNote') }}</p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.membership-page {
  width: 100%;
  height: 100%;
  overflow-y: auto;
  display: flex;
  justify-content: center;
  padding: 32px 24px 48px;
  box-sizing: border-box;
}

.membership-card {
  width: 100%;
  max-width: 860px;
  display: flex;
  flex-direction: column;
  gap: 28px;
}

.membership-hero {
  text-align: center;
}

.membership-title {
  font-size: 28px;
  font-weight: 700;
  color: var(--ink);
  margin: 0 0 10px;
  font-family: 'Playfair Display', serif;
}

.membership-subtitle {
  font-size: 14px;
  line-height: 1.7;
  color: var(--ink-muted);
  margin: 0 auto;
  max-width: 560px;
}

.tier-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 14px;
}

.tier-card {
  position: relative;
  padding: 22px 20px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

/* 会员卡对齐 Dock 激活态配色：acid 描边 + 软底色，突出但不刺眼 */
.tier-card--member {
  border: 1px solid var(--acid-strong);
  background: color-mix(in srgb, var(--acid) 14%, var(--paper-raised));
}

.tier-current-badge {
  position: absolute;
  top: 12px;
  right: 12px;
  padding: 2px 10px;
  border-radius: 999px;
  background: var(--acid);
  color: var(--acid-ink);
  border: 1px solid var(--acid-strong);
  font-size: 11px;
  font-weight: 700;
}

.tier-name {
  font-size: 16px;
  font-weight: 700;
  color: var(--ink);
  margin: 0;
}

.tier-price {
  margin: 0;
  display: flex;
  align-items: baseline;
  gap: 8px;
  color: var(--ink-muted);
  font-size: 13px;
}

.tier-price-main {
  font-size: 24px;
  font-weight: 700;
  color: var(--ink);
}

.tier-features {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--ink-secondary);
}

.membership-cta {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.membership-cta-hint {
  margin: 0;
  font-size: 13px;
  color: var(--ink-muted);
  text-align: center;
}

/* CTA 复用联系页胶囊按钮配方：acid 实色底 + acid-ink 文字 */
.cta-button {
  display: inline-flex;
  align-items: center;
  padding: 10px 28px;
  border-radius: 999px;
  background: var(--acid);
  color: var(--acid-ink);
  border: 1px solid var(--acid-strong);
  text-decoration: none;
  font-size: 14px;
  font-weight: 700;
  transition: background-color 150ms ease;
}

.cta-button:hover {
  background: var(--acid-bright);
  color: var(--acid-ink);
}

.membership-member-note {
  margin: 0;
  font-size: 13px;
  color: var(--ink-muted);
}

@media (max-width: 639px) {
  .membership-page {
    padding: 20px 14px 32px;
  }

  .membership-title {
    font-size: 23px;
  }
}
</style>
