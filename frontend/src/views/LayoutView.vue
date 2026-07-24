<script setup lang="ts">
import { RouterView, useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/authStore'
import GlobalSearch from '../components/GlobalSearch.vue'
import AppDock from '../components/layout/AppDock.vue'
import LayoutFooter from '../components/layout/LayoutFooter.vue'
import {
  KEEP_ALIVE_MAX,
  KEEP_ALIVE_VIEW_NAMES,
  NAV_ITEMS,
} from '../features/navigation/navigationModel'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

/** 品牌名称 — 从 Vite 环境变量读取，回退默认值 */
const brandName = import.meta.env.VITE_APP_BRAND_NAME || 'AIGC NEWS'
</script>

<template>
  <!-- ═══ 全屏内容层 ═══ -->
  <div class="relative flex h-screen w-full items-center justify-center overflow-hidden">

    <!-- ═══ 科技感背景光晕层 ═══ -->

    <!-- ═══ 居中悬浮画板（暖白纸质毛玻璃主面板） ═══ -->
    <div class="main-canvas">
      <!-- 顶部全局搜索条 -->
      <div
        class="absolute top-0 left-0 right-0 flex items-center justify-center px-6 py-2.5 shrink-0"
        style="z-index: 100; border-bottom: 1px solid var(--rule-strong); background: var(--paper-raised);"
      >
        <GlobalSearch />
      </div>

      <!-- 内容区（搜索条占位 44px） -->
      <div class="absolute inset-0 pt-[44px] flex flex-col">
        <router-view v-slot="{ Component }">
          <KeepAlive :include="KEEP_ALIVE_VIEW_NAMES" :max="KEEP_ALIVE_MAX">
            <component :is="Component" :key="route.path" class="view-container" />
          </KeepAlive>
        </router-view>
      </div>
    </div>

    <AppDock
      :items="NAV_ITEMS"
      :current-path="route.path"
      :is-admin="authStore.isAdmin"
      :is-logged-in="authStore.isLoggedIn"
      @login="router.push('/login')"
      @logout="authStore.logout()"
    />

    <LayoutFooter :brand-name="brandName" />

  </div>
</template>

<style scoped>
/* ═══ 视图容器：只控制 flex 撑满 + 溢出裁剪 ═══ */
:deep(.view-container) {
  width: 100%;
  height: 100%;
  flex: 1 1 0;
  min-height: 0;
  overflow: hidden;
}

/* ═══ 主工作画板：纸面、硬规则、轻微错版阴影 ═══ */
.main-canvas {
  width: 92%;
  max-width: 1400px;
  height: 84vh;
  border-radius: 14px;
  background: var(--paper-raised);
  border: 1px solid var(--rule-strong);
  box-shadow: 7px 7px 0 rgba(21, 21, 18, 0.12);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  position: relative;
  z-index: 1;
}

@media (max-width: 639px) {
  .main-canvas {
    width: 100%;
    height: 100dvh;
    min-height: 100dvh;
    border-radius: 18px;
  }

  .main-canvas > .absolute.top-0 {
    padding-left: max(12px, env(safe-area-inset-left));
    padding-right: max(12px, env(safe-area-inset-right));
  }

  .main-canvas > .absolute.inset-0 {
    padding-top: 48px;
    padding-bottom: 86px;
  }
}
</style>
