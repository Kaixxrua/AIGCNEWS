<script setup lang="ts">
import { RouterView } from 'vue-router'
import AppToast from '@/components/AppToast.vue'
import AuthPromptHost from '@/components/auth/AuthPromptHost.vue'
import FallbackEntryNotice from '@/components/FallbackEntryNotice.vue'
import RouteProgress from '@/components/RouteProgress.vue'
import { useLocaleTransition } from './composables/useLocaleTransition'

const { isLocaleTransitioning } = useLocaleTransition()
</script>

<template>
  <!-- ═══ Layer -10: 暖调米白纸张底色 ═══ -->
  <div class="app-backdrop" aria-hidden="true"></div>

  <!-- ═══ Layer -8: 极弱纸张噪点 ═══ -->
  <div class="app-noise" aria-hidden="true"></div>

  <!-- ═══ 顶层路由出口（Layout 或独立认证辅助页） ═══ -->
  <RouterView />
  <AuthPromptHost />
  <RouteProgress />
  <AppToast />
  <FallbackEntryNotice />

  <Transition name="locale-refresh">
    <div
      v-if="isLocaleTransitioning"
      class="locale-refresh"
      aria-hidden="true"
    >
      <span class="locale-refresh__sweep" />
    </div>
  </Transition>
</template>
