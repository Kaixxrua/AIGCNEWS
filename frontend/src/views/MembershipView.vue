<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ArrowLeftRight, Check } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/authStore'
import { useContactPageConfig } from '@/composables/useContactPageConfig'

defineOptions({ name: 'MembershipView' })

/**
 * 会员页：档位对比 + 定价 + 人工开通 CTA（执照/商户号未落地，先接咨询）。
 * 游客可见（获客入口）；CTA 优先进联系合作页，页面未启用时回退站长邮箱。
 * 定价卡为商业化布局：动作收进卡内、付费档抬升 + 推荐徽章、年付价格锚定。
 */
const { t } = useI18n()
const authStore = useAuthStore()
const { contactPageConfig } = useContactPageConfig()

const isMember = computed(() => authStore.isMember)

/** 计费周期切换：默认月付，按钮在项目库配方（右侧、描边小按钮）里切到年付 */
const billingPeriod = ref<'monthly' | 'yearly'>('monthly')
const isYearly = computed(() => billingPeriod.value === 'yearly')
const toggleBilling = () => {
  billingPeriod.value = isYearly.value ? 'monthly' : 'yearly'
}

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
          <p class="tier-price">
            <span class="tier-price-amount">{{ t('membership.free.price') }}</span>
          </p>
          <hr class="tier-divider" />
          <ul class="tier-features">
            <li v-for="key in FREE_FEATURES" :key="key">
              <Check :size="14" :stroke-width="2.5" class="tier-check" aria-hidden="true" />
              <span>{{ t(`membership.free.features.${key}`) }}</span>
            </li>
          </ul>
          <p class="tier-plan-note">{{ t('membership.free.currentPlan') }}</p>
        </article>

        <article class="tier-card tier-card--member">
          <span class="tier-badge" :class="{ 'tier-badge--current': isMember }">
            {{ isMember ? t('membership.currentMember') : t('membership.member.badge') }}
          </span>
          <h2 class="tier-name">{{ t('membership.member.name') }}</h2>
          <p class="tier-price">
            <span class="tier-price-amount">
              {{ isYearly ? t('membership.member.priceYearlyAmount') : t('membership.member.priceMonthly') }}
            </span>
            <span class="tier-price-period">
              {{ isYearly ? t('membership.member.priceYearlyPeriod') : t('membership.member.priceMonthlyPeriod') }}
            </span>
            <button
              type="button"
              class="tier-billing-btn"
              :aria-pressed="isYearly"
              @click="toggleBilling"
            >
              <ArrowLeftRight :size="13" :stroke-width="2.5" aria-hidden="true" />
              {{ isYearly ? t('membership.member.billMonthly') : t('membership.member.billYearly') }}
              <!-- 折扣标只在月付态出现：1 − 129/(19×12) = 43.4%，向下取整 -43%（保守口径）；
                   年付态按钮是降级动作，不带折扣标 -->
              <span v-if="!isYearly" class="tier-billing-tag">{{ t('membership.member.yearlyDiscount') }}</span>
            </button>
          </p>
          <p class="tier-price-yearly">
            <template v-if="isYearly">
              {{ t('membership.member.priceMonthly') }}{{ t('membership.member.priceMonthlyPeriod') }}
            </template>
            <template v-else>{{ t('membership.member.priceYearly') }}</template>
            <span class="tier-savings">{{ t('membership.member.yearlySavings') }}</span>
          </p>
          <hr class="tier-divider" />
          <ul class="tier-features">
            <li v-for="key in MEMBER_FEATURES" :key="key">
              <Check :size="14" :stroke-width="2.5" class="tier-check" aria-hidden="true" />
              <span>{{ t(`membership.member.features.${key}`) }}</span>
            </li>
          </ul>
          <template v-if="!isMember">
            <RouterLink v-if="contactPageConfig.enabled" to="/contact" class="tier-cta">
              {{ t('membership.cta') }}
            </RouterLink>
            <a v-else :href="contactHref" class="tier-cta">{{ t('membership.cta') }}</a>
            <p class="tier-cta-hint">{{ t('membership.ctaHint') }}</p>
          </template>
          <p v-else class="tier-member-note">{{ t('membership.memberNote') }}</p>
        </article>
      </section>
    </div>
  </div>
</template>

<style scoped>
/* Hallmark · component: pricing-cards · genre: editorial · theme: project-locked
 * (paper/acid/Playfair 既有 token，零新增色值)
 * states: default · hover · focus-visible(全局 outline) · active · member-success · billing-toggle(aria-pressed)
 * pre-emit critique: P4 H5 E4 S4 R4 V4 · contrast: pass */
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

/* 顶部留白给会员徽章的外悬（top: -13px）让位 */
.tier-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 16px;
  padding-top: 13px;
}

.tier-card {
  position: relative;
  padding: 24px 22px 22px;
  display: flex;
  flex-direction: column;
}

/* 会员卡抬升：复用 glass-card-tech / report-hero 的 ink 边 + acid 硬阴影配方 */
.tier-card--member {
  border: 1px solid var(--rule-strong);
  border-radius: var(--module-radius);
  background: var(--paper-raised);
  box-shadow: 5px 5px 0 var(--acid);
}

/* 推荐徽章：acid 实色胶囊外悬卡片顶边（stream-indicator 的 acid+ink 边配方） */
.tier-badge {
  position: absolute;
  top: -13px;
  right: 18px;
  padding: 4px 12px;
  border-radius: 999px;
  background: var(--acid);
  color: var(--acid-ink);
  border: 1.5px solid var(--ink);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.04em;
  line-height: 1.4;
}

/* 已是会员：徽章反转为 ink 底（btn-primary 同色关系） */
.tier-badge--current {
  background: var(--ink);
  color: var(--btn-primary-label);
}

/* 方案名收成 eyebrow，把视觉重心让给价格 */
.tier-name {
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--ink-muted);
  margin: 0 0 14px;
}

.tier-price {
  margin: 0;
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  row-gap: 8px;
}

/* 计费周期切换：项目库 projects-home-btn 配方（1px 描边、4px 方角、小字重 800），
   钉在价格行右侧；aria-pressed=年付态反色为 ink 底（btn-primary 同色关系） */
.tier-billing-btn {
  margin-left: auto;
  align-self: center;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--rule-strong);
  border-radius: 4px;
  padding: 6px 12px;
  background: var(--paper-raised);
  color: var(--ink);
  font-size: 12px;
  font-weight: 800;
  white-space: nowrap;
  cursor: pointer;
  transition: background-color 150ms ease, color 150ms ease, transform 150ms ease;
}

.tier-billing-btn:hover {
  background: var(--acid-soft);
}

.tier-billing-btn:active {
  transform: translateY(1px);
}

.tier-billing-btn[aria-pressed='true'] {
  background: var(--ink);
  color: var(--btn-primary-label);
  border-color: var(--ink);
}

.tier-billing-btn[aria-pressed='true']:hover {
  background: var(--acid);
  color: var(--acid-ink);
}

/* 折扣百分比标：acid 实色小胶囊（tier-badge 的同族配方），嵌在描边按钮内制造对比 */
.tier-billing-tag {
  padding: 1px 6px;
  border-radius: 999px;
  background: var(--acid);
  color: var(--acid-ink);
  font-size: 10px;
  font-weight: 800;
  line-height: 1.5;
}

/* 价格用 Playfair 大字号：订阅制编辑流派的价格牌惯例 */
.tier-price-amount {
  font-family: 'Playfair Display', serif;
  font-size: 40px;
  font-weight: 700;
  letter-spacing: -0.01em;
  line-height: 1;
  color: var(--ink);
}

.tier-price-period {
  margin-left: 6px;
  font-size: 14px;
  color: var(--ink-muted);
}

.tier-price-yearly {
  margin: 8px 0 0;
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-secondary);
}

/* 年付节省标：语义绿淡染小胶囊（19×12−129=99，真实算术） */
.tier-savings {
  margin-left: 8px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 10px;
  font-weight: 700;
  color: var(--projects-success);
  background: color-mix(in srgb, var(--projects-success) 12%, transparent);
}

.tier-divider {
  border: none;
  border-top: 1px solid var(--rule);
  margin: 18px 0 16px;
}

.tier-features {
  margin: 0 0 20px;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--ink-secondary);
}

.tier-features li {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.tier-check {
  flex-shrink: 0;
  margin-top: 3px;
  color: var(--projects-success);
}

/* 免费档底部：无动作可言，安静标注默认身份（虚线发丝分隔） */
.tier-plan-note {
  margin: auto 0 0;
  padding-top: 14px;
  border-top: 1px dashed var(--rule);
  font-size: 12px;
  text-align: center;
  color: var(--ink-faint);
}

/* 卡内 CTA：复用 btn-primary 的 ink 底 acid 字 → hover 反转配方，整宽拉伸 */
.tier-cta {
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: auto;
  padding: 11px 20px;
  border-radius: var(--control-radius);
  background: var(--ink);
  color: var(--btn-primary-label);
  border: 2px solid var(--ink);
  font-size: 14px;
  font-weight: 800;
  text-decoration: none;
  transition: background-color 150ms ease, color 150ms ease, transform 150ms ease;
}

.tier-cta:hover {
  background: var(--acid);
  color: var(--acid-ink);
}

.tier-cta:active {
  transform: translateY(1px);
}

.tier-cta-hint {
  margin: 8px 0 0;
  font-size: 11px;
  line-height: 1.5;
  text-align: center;
  color: var(--ink-muted);
}

.tier-member-note {
  margin: auto 0 0;
  padding-top: 14px;
  border-top: 1px dashed var(--rule);
  font-size: 12px;
  font-weight: 600;
  text-align: center;
  color: var(--projects-success);
}

@media (max-width: 639px) {
  .membership-page {
    padding: 20px 14px 32px;
  }

  .membership-title {
    font-size: 23px;
  }

  .tier-price-amount {
    font-size: 34px;
  }
}
</style>
