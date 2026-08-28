<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/authStore'

/* 顶栏右上角用户标识：用户名 + 用户组（free / vip），与左侧 MastheadMeta
   镜像的报纸刊头式两行小字（绝对定位，不参与居中 flex 排布）。
   匿名访客固定显示「未登录 / guest」；登录后优先显示用户名，无用户名
   （旧数据/ OAuth 两者皆空）回退邮箱，再兜底空串。
   档位展示与会员页命名一致：member → vip，缺省按 free。
   member 档到期时间以两个空格同行缀于档位之后（后端每请求实时裁决，
   过期自动回落 free，因此不会出现"已过期"的展示态）；
   NULL 到期时间 = 长期有效。 */
const { t, locale } = useI18n()
const authStore = useAuthStore()

const userName = computed(() => {
  const username = authStore.user?.username?.trim()
  return username || authStore.user?.email || ''
})
const tierLabel = computed(() => (authStore.user?.membership_tier === 'member' ? 'vip' : 'free'))

const expiryText = computed(() => {
  if (authStore.user?.membership_tier !== 'member') return ''
  const raw = authStore.user.membership_expires_at
  if (!raw) return t('masthead.memberLifetime')
  const timestamp = Date.parse(raw)
  if (Number.isNaN(timestamp)) return ''
  const date = new Intl.DateTimeFormat(locale.value, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(timestamp)
  return t('masthead.memberUntil', { date })
})

const groupLabel = computed(() => t('masthead.userGroup', { tier: tierLabel.value }))
</script>

<template>
  <div class="masthead-user">
    <template v-if="authStore.isLoggedIn">
      <span class="masthead-user__status">{{ userName }}</span>
      <span class="masthead-user__identity">
        <span>{{ groupLabel }}</span>
        <span v-if="expiryText" class="masthead-user__expiry">{{ `  ${expiryText}` }}</span>
      </span>
    </template>
    <template v-else>
      <span class="masthead-user__status">未登录</span>
      <span class="masthead-user__identity">guest</span>
    </template>
  </div>
</template>

<style scoped>
.masthead-user {
  position: absolute;
  right: 24px;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 1px;
  font-size: 10px;
  line-height: 1.25;
  letter-spacing: 0.04em;
  color: var(--ink-muted);
  user-select: none;
  pointer-events: none;
  white-space: nowrap;
  text-align: right;
}

.masthead-user__status {
  font-weight: 800;
  color: var(--ink);
}

/* 到期日期与档位保持同行，并用明确间距拉开；等宽数字避免逐年跳动 */
.masthead-user__identity {
  display: inline-flex;
  align-items: baseline;
  gap: 8px;
}

.masthead-user__expiry {
  font-variant-numeric: tabular-nums;
}

/* 窄屏隐藏：避免与居中字标/工具组挤压（与 MastheadMeta 同口径） */
@media (max-width: 767px) {
  .masthead-user {
    display: none;
  }
}
</style>
