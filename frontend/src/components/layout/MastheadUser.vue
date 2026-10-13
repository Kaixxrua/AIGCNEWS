<script setup lang="ts">
import { computed } from 'vue'
import UserAvatar from '@/components/auth/UserAvatar.vue'
import { useAuthStore } from '@/stores/authStore'

// Show identity only; account access no longer has public membership tiers.
const authStore = useAuthStore()

const userName = computed(() => {
  const username = authStore.user?.username?.trim()
  return username || authStore.user?.email || ''
})
</script>

<template>
  <div class="masthead-user">
    <UserAvatar
      :src="authStore.isLoggedIn ? authStore.user?.avatar_url : null"
      :name="authStore.isLoggedIn ? userName : ''"
      :seed="authStore.isLoggedIn ? authStore.user?.user_id : null"
    />
    <div class="masthead-user__copy">
      <template v-if="authStore.isLoggedIn">
        <span class="masthead-user__status">{{ userName }}</span>
      </template>
      <template v-else>
        <span class="masthead-user__status">未登录</span>
        <span class="masthead-user__identity">guest</span>
      </template>
    </div>
  </div>
</template>

<style scoped>
.masthead-user {
  position: absolute;
  right: 24px;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: 165px;
  font-size: 11px;
  line-height: 1.25;
  letter-spacing: 0.04em;
  color: var(--ink-muted);
  user-select: none;
  pointer-events: none;
  white-space: nowrap;
  text-align: left;
}

.masthead-user__copy { display: flex; flex-direction: column; gap: 4px; min-width: 0; }

.masthead-user__status {
  overflow: hidden;
  text-overflow: ellipsis;
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
