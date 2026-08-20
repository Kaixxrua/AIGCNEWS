<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/authStore'

/* 顶栏右上角用户标识：用户名 + 用户组（free / vip），与左侧 MastheadMeta
   镜像的报纸刊头式两行小字（绝对定位，不参与居中 flex 排布）。
   匿名访客固定显示「未登录 / guest」；登录后显示真实邮箱与档位，
   档位展示与会员页命名一致：member → vip，缺省按 free。 */
const { t } = useI18n()
const authStore = useAuthStore()

const userName = computed(() => authStore.user?.email ?? '')
const tierLabel = computed(() => (authStore.user?.membership_tier === 'member' ? 'vip' : 'free'))
</script>

<template>
  <div class="masthead-user">
    <template v-if="authStore.isLoggedIn">
      <span class="masthead-user__status">{{ userName }}</span>
      <span class="masthead-user__identity">{{ t('masthead.userGroup', { tier: tierLabel }) }}</span>
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

/* 窄屏隐藏：避免与居中字标/工具组挤压（与 MastheadMeta 同口径） */
@media (max-width: 767px) {
  .masthead-user {
    display: none;
  }
}
</style>
