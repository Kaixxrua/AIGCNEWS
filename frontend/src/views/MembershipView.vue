<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMediaQuery } from '@vueuse/core'
import { ArrowLeftRight, Check, X } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/authStore'
import { useContactPageConfig } from '@/composables/useContactPageConfig'
import { paymentApi } from '@/services/payments/paymentApi'
import RollText from '@/motion/RollText.vue'
import { vMorph } from '@/motion/morph'
import { popIn, popOut } from '@/motion/presence'
import { vSwap } from '@/motion/swap'
import {
  FALLBACK_MEMBER_MONTHLY_CENTS,
  FALLBACK_MEMBER_MONTHLY_USD_CENTS,
  FALLBACK_MEMBER_YEARLY_CENTS,
  FALLBACK_MEMBER_YEARLY_USD_CENTS,
  computeYearlyDiscountPercent,
  computeYearlySavingsCents,
  formatAmountCents,
  planCurrencyForLocale,
  resolvePlan,
} from '@/features/payments/paymentModel'
import type { PaymentPlan } from '@/features/payments/paymentModel'
import { COMPARE_ROWS, sameAcrossTiers } from '@/features/membership/membershipCompare'
import TierCompareList from '@/components/membership/TierCompareList.vue'
import { useAppDensity } from '@/composables/useAppDensity'

defineOptions({ name: 'MembershipView' })

/**
 * 会员页：三档对比（guest / free / vip）+ 定价 + 开通 CTA。
 * 游客可见（获客入口）。CTA 分三支：支付开关开启（plans 接口可达）→
 * 在线收银台；否则退回联系合作页，页面未启用时回退站长邮箱。
 * 定价卡为商业化布局：动作收进卡内、付费档抬升 + 推荐徽章、年付价格锚定。
 * 会员卡金额/折扣由 plans 接口价自算（管理员可在监控页运行时调价）；
 * 探测失败按 paymentModel 兜底常量渲染（与 plans.py 默认价钉住）。
 * 特性列表勾/叉双态：✓ 为已含权益，✗ 为该档不可用（升级诱因）；
 * 公共简报与 RSS 免费；个人追踪为 free 1 条、vip 10 条规则。
 * 桌面（≥1024px）三张卡排成一张对比表：左列是行名，三档的权益逐行对齐（行与格见 features/membership/membershipCompare），
 * 开通按钮挪到价格下面；手机与平板仍是三张卡、各列各的权益，报眉的版面密度选了舒适时桌面也是三张卡。
 */
const { t, locale } = useI18n()
const authStore = useAuthStore()
const { contactPageConfig } = useContactPageConfig()

const isMember = computed(() => authStore.isMember)

const desktop = useMediaQuery('(min-width: 1024px)')
const { comfortable } = useAppDensity()
const compare = computed(() => desktop.value && !comfortable.value)
// 对比表的行数交给样式排网格：行名列和三档的格子都按这个数分行。
const compareStyle = computed(() => (compare.value ? { '--compare-rows': String(COMPARE_ROWS.length) } : undefined))

/** 计费周期切换：默认月付，按钮在项目库配方（右侧、描边小按钮）里切到年付 */
const billingPeriod = ref<'monthly' | 'yearly'>('monthly')
const isYearly = computed(() => billingPeriod.value === 'yearly')
const toggleBilling = () => {
  billingPeriod.value = isYearly.value ? 'monthly' : 'yearly'
}
/** 切换方向：去年付时价格等内容自下而上滚入，回月付时自上而下。 */
const billingDirection = computed<1 | -1>(() => (isYearly.value ? 1 : -1))
const periodText = computed(() =>
  isYearly.value ? t('membership.member.priceYearlyPeriod') : t('membership.member.priceMonthlyPeriod'),
)
const billingLabel = computed(() =>
  isYearly.value ? t('membership.member.billMonthly') : t('membership.member.billYearly'),
)
// 折扣标等按钮撑开一截再盖上去，不从还没展开的按钮边上探出来。
const popInTag = (el: Element, done: () => void) => popIn(el, done, { delay: 120 })

// 在线收银台可用性 = plans 接口可达（payments_enabled 关闭时整组 404）。
// 探测失败静默保持 false，CTA 维持联系开通兜底；金额渲染退回兜底常量。
const checkoutAvailable = ref(false)
const memberPlans = ref<PaymentPlan[] | null>(null)
const checkoutTo = computed(() => ({
  path: '/membership/checkout',
  query: { plan: billingPeriod.value },
}))

onMounted(async () => {
  try {
    const response = await paymentApi.listPlans()
    memberPlans.value = response.plans
    checkoutAvailable.value = true
  } catch {
    memberPlans.value = null
    checkoutAvailable.value = false
  }
})

// 金额一律整数分；缺 plans 数据（探测失败/套餐缺席）一律回落兜底常量——
// 单一代码路径，兜底渲染与调价前逐字节一致。币种随界面语言：中文 CNY、
// 其他语言 USD（与收银台渠道门控同一判定，英文界面只卖美元套餐）。
const plansCurrency = computed(() => planCurrencyForLocale(locale.value))
const monthlyCents = computed(
  () =>
    (memberPlans.value ? resolvePlan(memberPlans.value, 'monthly', plansCurrency.value) : null)
      ?.amount_cents ??
    (plansCurrency.value === 'USD' ? FALLBACK_MEMBER_MONTHLY_USD_CENTS : FALLBACK_MEMBER_MONTHLY_CENTS),
)
const yearlyCents = computed(
  () =>
    (memberPlans.value ? resolvePlan(memberPlans.value, 'yearly', plansCurrency.value) : null)
      ?.amount_cents ??
    (plansCurrency.value === 'USD' ? FALLBACK_MEMBER_YEARLY_USD_CENTS : FALLBACK_MEMBER_YEARLY_CENTS),
)

const memberAmountText = computed(() =>
  formatAmountCents(isYearly.value ? yearlyCents.value : monthlyCents.value, plansCurrency.value),
)
// 锚点行两种态的字距保持既有排版：月付态看年付锚「¥159 / 年」（斜杠两侧空格），
// 年付态看月付锚「¥19/ 月」（无空格，period 键内自带前导空格）。
const anchorText = computed(() =>
  isYearly.value
    ? `${formatAmountCents(monthlyCents.value, plansCurrency.value)}${t('membership.member.priceMonthlyPeriod')}`
    : `${formatAmountCents(yearlyCents.value, plansCurrency.value)} ${t('membership.member.priceYearlyPeriod')}`,
)
const savingsCents = computed(() =>
  computeYearlySavingsCents(monthlyCents.value, yearlyCents.value),
)
const savingsText = computed(() =>
  t('membership.member.yearlySavings', {
    amount: formatAmountCents(savingsCents.value, plansCurrency.value),
  }),
)
const discountPercent = computed(() =>
  computeYearlyDiscountPercent(monthlyCents.value, yearlyCents.value),
)
const discountText = computed(() =>
  t('membership.member.yearlyDiscount', { percent: discountPercent.value }),
)

const contactHref = computed(() =>
  contactPageConfig.value.enabled
    ? ''
    : `mailto:kaixxrua@gmail.com?subject=${encodeURIComponent(t('membership.ctaMailSubject'))}`,
)

/** 特性条目：included=false 渲染 ✗（该档不可用），勾/叉对比即三档区分度 */
type TierFeature = { key: string; included: boolean }

const GUEST_FEATURES: readonly TierFeature[] = [
  { key: 'browse', included: true },
  { key: 'mcpAnonymous', included: true },
  { key: 'rss', included: false },
  { key: 'briefing', included: false },
  { key: 'website', included: false },
]
const FREE_FEATURES: readonly TierFeature[] = [
  { key: 'tracking', included: true },
  { key: 'mcpFree', included: true },
  { key: 'websiteFree', included: true },
  { key: 'briefingFree', included: true },
  { key: 'rssFree', included: true },
]
const MEMBER_FEATURES: readonly TierFeature[] = [
  { key: 'tracking', included: true },
  { key: 'personalDigest', included: true },
  { key: 'mcpMember', included: true },
  { key: 'websiteMember', included: true },
]
</script>

<template>
  <div class="membership-page">
    <div class="membership-card" :class="{ 'membership-card--compare': compare }" :style="compareStyle">
      <header class="stagger-enter membership-hero">
        <h1 class="membership-title comic-title">{{ t('membership.title') }}</h1>
        <p class="membership-subtitle">{{ t('membership.subtitle') }}</p>
      </header>

      <!-- 报眉换成舒适、对比表散回三张卡时三档依次浮现；换成对比表时各列自带弹入（cardPopIn），这里不再叠一层 -->
      <section v-swap="{ key: compare ? null : 'cards', stagger: true }" class="stagger-enter tier-grid" style="animation-delay: 0.05s">
        <!-- 桌面对比表左侧的行名：读屏从每格开头的隐藏行名读，这一列只给眼睛看。 -->
        <div v-if="compare" class="tier-rows" aria-hidden="true">
          <span v-for="row in COMPARE_ROWS" :key="row.key" class="tier-row-label" :class="{ 'tier-row-label--same': sameAcrossTiers(row) }">{{ t(`membership.compare.rows.${row.key}`) }}</span>
        </div>
        <article class="glass-card tier-card">
          <h2 class="tier-name">{{ t('membership.guest.name') }}</h2>
          <p class="tier-price">
            <span class="tier-price-amount">{{ t('membership.guest.price') }}</span>
          </p>
          <hr class="tier-divider" />
          <TierCompareList v-if="compare" tier="guest" />
          <ul v-else class="tier-features">
            <li
              v-for="feature in GUEST_FEATURES"
              :key="feature.key"
              :class="{ 'tier-feature--excluded': !feature.included }"
            >
              <Check
                v-if="feature.included"
                :size="14"
                :stroke-width="2.5"
                class="tier-check"
                aria-hidden="true"
              />
              <X v-else :size="14" :stroke-width="2.5" class="tier-x" aria-hidden="true" />
              <span>{{ t(`membership.guest.features.${feature.key}`) }}</span>
            </li>
          </ul>
          <p class="tier-plan-note">{{ t('membership.guest.note') }}</p>
        </article>

        <article class="glass-card tier-card">
          <h2 class="tier-name">{{ t('membership.free.name') }}</h2>
          <p class="tier-price">
            <span class="tier-price-amount">{{ t('membership.free.price') }}</span>
          </p>
          <hr class="tier-divider" />
          <TierCompareList v-if="compare" tier="free" />
          <ul v-else class="tier-features">
            <li
              v-for="feature in FREE_FEATURES"
              :key="feature.key"
              :class="{ 'tier-feature--excluded': !feature.included }"
            >
              <Check
                v-if="feature.included"
                :size="14"
                :stroke-width="2.5"
                class="tier-check"
                aria-hidden="true"
              />
              <X v-else :size="14" :stroke-width="2.5" class="tier-x" aria-hidden="true" />
              <span>{{ t(`membership.free.features.${feature.key}`) }}</span>
            </li>
          </ul>
          <p class="tier-plan-note">{{ t('membership.free.currentPlan') }}</p>
        </article>

        <article class="tier-card tier-card--member">
          <span class="tier-badge" :class="{ 'tier-badge--current': isMember }">
            {{ isMember ? t('membership.currentMember') : t('membership.member.badge') }}
          </span>
          <h2 class="tier-name">{{ t('membership.member.name') }}</h2>
          <!-- 切换计费周期：价格整块滚动换值（去年付向上、回月付向下），锚点行稍后跟上；按钮图标翻转、折扣标弹入弹出。
               价格与按钮的宽度一起过渡（同一行里此消彼长，不会中途把按钮挤到下一行）；较窄时按钮在两行之间滑动，
               价格行高度随之过渡。 -->
          <p v-morph="billingPeriod" class="tier-price">
            <RollText :value="`${memberAmountText} ${periodText}`" :direction="billingDirection">
              <span class="tier-price-amount">{{ memberAmountText }}</span>
              <span class="tier-price-period">{{ periodText }}</span>
            </RollText>
            <button
              v-morph="billingPeriod"
              type="button"
              class="tier-billing-btn"
              :aria-pressed="isYearly"
              @click="toggleBilling"
            >
              <ArrowLeftRight :size="13" :stroke-width="2.5" aria-hidden="true" />
              <RollText :value="billingLabel" :direction="billingDirection" :morph="false" />
              <!-- 折扣标只在月付态且真实存在折扣时出现：前端按 plans 价自算
                   1 − yearly/(monthly×12)，向下取整（保守口径），≤0 即隐藏；
                   年付态按钮是降级动作，不带折扣标 -->
              <Transition @enter="popInTag" @leave="popOut">
                <span v-if="!isYearly && discountPercent > 0" class="tier-billing-tag">{{ discountText }}</span>
              </Transition>
            </button>
          </p>
          <p class="tier-price-yearly">
            <RollText :value="anchorText" :direction="billingDirection" :delay="60" /> <span v-if="savingsCents > 0" class="tier-savings">{{ savingsText }}</span>
          </p>
          <hr class="tier-divider" />
          <TierCompareList v-if="compare" tier="member" />
          <ul v-else class="tier-features">
            <li
              v-for="feature in MEMBER_FEATURES"
              :key="feature.key"
              :class="{ 'tier-feature--excluded': !feature.included }"
            >
              <Check
                v-if="feature.included"
                :size="14"
                :stroke-width="2.5"
                class="tier-check"
                aria-hidden="true"
              />
              <X v-else :size="14" :stroke-width="2.5" class="tier-x" aria-hidden="true" />
              <span>{{ t(`membership.member.features.${feature.key}`) }}</span>
            </li>
          </ul>
          <template v-if="!isMember">
            <RouterLink v-if="checkoutAvailable" :to="checkoutTo" class="tier-cta">
              <span class="tier-cta-label">{{ t('membership.ctaOnline') }}</span>
            </RouterLink>
            <RouterLink v-else-if="contactPageConfig.enabled" to="/contact" class="tier-cta">
              <span class="tier-cta-label">{{ t('membership.cta') }}</span>
            </RouterLink>
            <a v-else :href="contactHref" class="tier-cta"><span class="tier-cta-label">{{ t('membership.cta') }}</span></a>
            <p class="tier-cta-hint">
              {{ checkoutAvailable ? t('membership.ctaOnlineHint') : t('membership.ctaHint') }}
            </p>
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
 * states: default · hover · focus-visible(全局 outline) · active · member-success · billing-toggle(aria-pressed) · feature-excluded(✗)
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

/* 三档卡（guest/free/vip）：比两档时期的 860px 加宽，给第三张卡让位 */
.membership-card {
  width: 100%;
  max-width: 1020px;
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
   钉在价格行右侧；aria-pressed=年付态反色为 ink 底（btn-primary 同色关系）。
   定位元素：离场的折扣标钉在按钮内原处缩小淡出 */
.tier-billing-btn {
  position: relative;
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

/* 每次切换双向箭头翻转半圈、带回弹，切回时再转回来；按钮宽度过渡途中内容暂时放不下时图标不被挤扁 */
.tier-billing-btn svg {
  flex-shrink: 0;
  transition: rotate 560ms var(--motion-pop);
}

.tier-billing-btn[aria-pressed='true'] svg {
  rotate: 180deg;
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

/* 年付节省标：语义绿淡染小胶囊（金额由前端按 plans 价自算，非正即不渲染） */
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

/* ✗ 排除项：图标与文案同步降透明度，一眼读出「该档不含」（对比 ✓ 即区分度） */
.tier-x {
  flex-shrink: 0;
  margin-top: 3px;
  color: var(--ink-faint);
}

.tier-feature--excluded {
  color: var(--ink-faint);
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
