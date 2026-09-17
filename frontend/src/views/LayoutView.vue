<script setup lang="ts">
import { computed, ref } from 'vue'
import { useMediaQuery } from '@vueuse/core'
import { RouterView, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { useEnrichmentAlertStore } from '@/stores/enrichmentAlertStore'
import { useTrackingUnreadStore } from '@/stores/trackingUnreadStore'
import BrandWordmark from '@/components/layout/BrandWordmark.vue'
import MastheadMeta from '@/components/layout/MastheadMeta.vue'
import MastheadUser from '@/components/layout/MastheadUser.vue'
import FavoritesLink from '@/components/FavoritesLink.vue'
import PwaInstallLink from '@/components/PwaInstallLink.vue'
import GitHubLink from '@/components/GitHubLink.vue'
import LocaleToggle from '@/components/LocaleToggle.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
import AppDock from '@/components/layout/AppDock.vue'
import LayoutFooter from '@/components/layout/LayoutFooter.vue'
import AccountSettingsDialog from '@/components/auth/AccountSettingsDialog.vue'
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import {
  KEEP_ALIVE_MAX,
  KEEP_ALIVE_VIEW_NAMES,
  NAV_ITEMS,
  isNavigationItemFeatureEnabled,
  isNavigationItemSitePageEnabled,
} from '@/features/navigation/navigationModel'
import { useFeatureFlags } from '@/composables/useFeatureFlags'
import { useContactPageConfig } from '@/composables/useContactPageConfig'
import { dockSuppressed } from '@/composables/useDockSuppression'

const isMobile = useMediaQuery('(max-width: 767px)')
const route = useRoute()
const authStore = useAuthStore()
const { requestLogin } = useLoginPrompt()
// 实例化即开始对 admin 轮询富化失败状态；失败 > 0 时「监控」导航按钮显示红点
const enrichmentAlert = useEnrichmentAlertStore()
const trackingUnread = useTrackingUnreadStore()
const dockAlertItems = computed(() => [
  ...(enrichmentAlert.hasFailures ? ['/monitor'] : []),
  ...(trackingUnread.hasUnread ? ['/subscriptions'] : []),
])

// 账户设置入口：dock 账户按钮打开账户信息面板，面板内可进入改密子流程。
const accountSettingsOpen = ref(false)
// 种子默认管理员仍用公开默认密码时全站常驻提醒，改密后随 /auth/me 刷新消失
const showDefaultPasswordBanner = computed(
  () => authStore.isLoggedIn && authStore.user?.password_change_required === true,
)

// 特性开关 fail-open：首屏全量显示，拉取完成后隐藏被关闭源的导航入口
const { featureFlags, ensureFeatureFlags } = useFeatureFlags()
void ensureFeatureFlags()
// 站点页面 fail-closed：联系合作页未启用时不出现导航入口；启用后可携带自定义文案
const { contactPageConfig, ensureContactPageConfig } = useContactPageConfig()
void ensureContactPageConfig()
const visibleNavItems = computed(() =>
  NAV_ITEMS.filter(
    (item) =>
      isNavigationItemFeatureEnabled(item, featureFlags.value) &&
      isNavigationItemSitePageEnabled(item, { contactPage: contactPageConfig.value.enabled }),
  ).map((item) =>
    item.sitePageKey === 'contactPage' && contactPageConfig.value.navLabel.trim()
      ? { ...item, labelText: contactPageConfig.value.navLabel.trim() }
      : item,
  ),
)

/** 品牌名称 — 从 Vite 环境变量读取，回退默认值 */
const brandName = import.meta.env.VITE_APP_BRAND_NAME || 'AIGC NEWS'
</script>

<template>
  <!-- ═══ 全屏内容层 ═══ -->
  <div class="app-shell relative flex h-dvh w-full items-start justify-center overflow-hidden">

    <!-- ═══ 科技感背景光晕层 ═══ -->

    <!-- ═══ 居中悬浮画板（暖白纸质毛玻璃主面板） ═══ -->
    <div class="main-canvas">
      <!-- 顶部品牌条：左侧报头信息 + 右侧用户信息，故障特效字标与工具图标居中成组 -->
      <div
        class="app-masthead absolute top-0 left-0 right-0 flex items-center justify-center px-6 py-2.5 shrink-0"
        style="z-index: 100; border-bottom: 1px solid var(--rule-strong); background: var(--paper-raised);"
      >
        <MastheadMeta v-if="!isMobile" />
        <MastheadUser v-if="!isMobile" />
        <div class="app-masthead__tools flex items-center gap-3">
          <FavoritesLink v-if="!isMobile" />
          <PwaInstallLink v-if="!isMobile" />
          <BrandWordmark :key="isMobile ? 'mobile' : 'desktop'" :text="brandName" :compact="isMobile" />
          <span class="topbar-divider" aria-hidden="true"></span>
          <div class="app-masthead__actions flex items-center gap-2">
            <PwaInstallLink v-if="isMobile" />
            <GitHubLink v-if="!isMobile" />
            <ThemeToggle />
            <LocaleToggle />
          </div>
        </div>
      </div>

      <!-- 内容区（顶栏占位 56px；pb-7 保证末端内容不被悬浮 dock 遮挡，
           部分浏览器不会把滚动容器的 end padding 计入可滚动区域） -->
      <div class="app-content absolute inset-0 pt-[56px] pb-7 flex flex-col">
        <router-view v-slot="{ Component }">
          <KeepAlive :include="KEEP_ALIVE_VIEW_NAMES" :max="KEEP_ALIVE_MAX">
            <component :is="Component" :key="route.name === 'ui-library' ? 'ui-library' : route.path" class="view-container" />
          </KeepAlive>
        </router-view>
      </div>
    </div>

    <!-- 全屏浮层（推文详情/图片放大）打开时隐藏 dock，避免遮挡卡片 -->
    <AppDock
      v-show="!dockSuppressed"
      :items="visibleNavItems"
      :brand-name="brandName"
      :current-path="route.path"
      :current-query="route.query"
      :is-admin="authStore.isAdmin"
      :is-logged-in="authStore.isLoggedIn"
      :alert-items="dockAlertItems"
      @login="requestLogin(route.fullPath)"
      @logout="authStore.logout()"
      @account-settings="accountSettingsOpen = true"
    />

    <!-- 默认密码常驻警示：点击打开改密对话框，改密成功后自动消失；
         弹窗打开期间隐藏（其 z-index 高于遮罩，否则会浮在弹窗上层） -->
    <button
      v-if="showDefaultPasswordBanner && !accountSettingsOpen"
      class="default-pwd-banner"
      @click="accountSettingsOpen = true"
    >
      <svg class="h-3.5 w-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 9v4"/>
        <path d="M12 17h.01"/>
        <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>
      </svg>
      <span>{{ $t('auth.defaultPasswordBanner') }}</span>
      <span class="default-pwd-banner__action">{{ $t('auth.defaultPasswordBannerAction') }}</span>
    </button>

    <AccountSettingsDialog v-model="accountSettingsOpen" />

    <LayoutFooter :brand-name="brandName" />

  </div>
</template>

<style scoped>
/* 各页面管理自己的滚动容器；布局层只限定可用尺寸。 */
:deep(.view-container) {
  width: 100%;
  min-width: 0;
  max-width: 100%;
  height: 100%;
  flex: 1 1 0;
  min-height: 0;
}

/* ═══ 顶栏：品牌字标与工具图标之间的细分隔线 ═══ */
.topbar-divider {
  width: 1px;
  height: 18px;
  background: var(--rule);
}

/* ═══ 主工作画板：纸面、硬规则、轻微错版阴影 ═══ */
.main-canvas {
  width: calc(100% - 40px);
  max-width: none;
  height: calc(100dvh - 116px);
  margin-top: 20px;
  border-radius: 14px;
  background: var(--paper-raised);
  border: 1px solid var(--rule-strong);
  box-shadow: 7px 7px 0 var(--shadow-ink-soft);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  position: relative;
  z-index: 1;
}

@media (max-width: 1023px) {
  .app-masthead__tools,
  .app-masthead__actions {
    gap: 4px;
  }

  .main-canvas {
    width: 100%;
    height: 100dvh;
    min-height: 100dvh;
    margin-top: 0;
    /* 四边贴边的全屏画板不再保留 18px 圆角：角落露底色且浪费内容空间 */
    border-radius: 0;
  }

  .main-canvas > .absolute.top-0 {
    padding-left: max(12px, env(safe-area-inset-left));
    padding-right: max(12px, env(safe-area-inset-right));
  }

  .main-canvas > .absolute.inset-0 {
    padding-top: 56px;
    padding-bottom: calc(84px + env(safe-area-inset-bottom));
  }
}

/* ═══ 默认密码警示条：悬浮于 dock 上方，点击即打开改密对话框 ═══ */
.default-pwd-banner {
  position: fixed;
  bottom: 112px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 100;
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: calc(100vw - 32px);
  padding: 8px 14px;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  color: var(--warning-ink, #7c4a03);
  background: var(--warning-surface, #fdf0d5);
  border: 1px solid var(--warning-rule, #e8c47a);
  box-shadow: 3px 3px 0 var(--dock-shadow);
  cursor: pointer;
}

.default-pwd-banner__action {
  text-decoration: underline;
  text-underline-offset: 2px;
  white-space: nowrap;
}

@media (max-width: 1023px) {
  .default-pwd-banner {
    bottom: max(84px, calc(env(safe-area-inset-bottom) + 76px));
  }
}
@media (max-width: 767px) {
  .main-canvas { border: 0; box-shadow: none; }
  .app-masthead { height: calc(52px + env(safe-area-inset-top)); padding-top: calc(8px + env(safe-area-inset-top)); }
  .main-canvas > .app-content { padding-top: calc(52px + env(safe-area-inset-top)); padding-bottom: calc(72px + env(safe-area-inset-bottom)); }
  .app-masthead__tools { gap: 8px; }
  .topbar-divider { display: none; }
}
</style>
