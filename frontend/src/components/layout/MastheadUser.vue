<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/authStore'

/* 顶栏右上角用户信息：用户名 + 用户组（free / vip），与左侧 MastheadMeta
   镜像的报纸刊头式两行小字（绝对定位，不参与居中 flex 排布）。
   仅登录后显示；档位展示与会员页命名一致：member → vip，缺省按 free。 */
const { t } = useI18n()
const authStore = useAuthStore()

const userName = computed(() => authStore.user?.email ?? '')
const tierLabel = computed(() => (authStore.user?.membership_tier === 'member' ? 'vip' : 'free'))
</script>

<template>
  <div v-if="authStore.isLoggedIn" class="masthead-user">
    <span class="masthead-user__name">{{ userName }}</span>
    <span class="masthead-user__tier">{{ t('masthead.userGroup', { tier: tierLabel }) }}</span>
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

.masthead-user__name {
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
