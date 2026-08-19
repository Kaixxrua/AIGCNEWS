<script setup lang="ts">
import { computed, ref } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { useEnrichmentAlertStore } from '@/stores/enrichmentAlertStore'
import BrandWordmark from '@/components/layout/BrandWordmark.vue'
import MastheadMeta from '@/components/layout/MastheadMeta.vue'
import MastheadUser from '@/components/layout/MastheadUser.vue'
import GitHubLink from '@/components/GitHubLink.vue'
import LocaleToggle from '@/components/LocaleToggle.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
import AppDock from '@/components/layout/AppDock.vue'
import LayoutFooter from '@/components/layout/LayoutFooter.vue'
import ChangePasswordDialog from '@/components/auth/ChangePasswordDialog.vue'
import LoginDialog from '@/components/auth/LoginDialog.vue'
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

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const { isOpen: loginOpen, redirectTarget: loginRedirect, requestLogin, closeLoginPrompt } = useLoginPrompt()
// 实例化即开始对 admin 轮询富化失败状态；失败 > 0 时「监控」导航按钮显示红点
const enrichmentAlert = useEnrichmentAlertStore()
const dockAlertItems = computed(() => (enrichmentAlert.hasFailures ? ['/monitor'] : []))

// 改密对话框：dock 钥匙按钮或默认密码警示条打开
const changePasswordOpen = ref(false)
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
  <div class="relative flex h-screen w-full items-start justify-center overflow-hidden">

    <!-- ═══ 科技感背景光晕层 ═══ -->

    <!-- ═══ 居中悬浮画板（暖白纸质毛玻璃主面板） ═══ -->
    <div class="main-canvas">
      <!-- 顶部品牌条：左侧报头信息 + 右侧用户信息，故障特效字标与工具图标居中成组 -->
      <div
        class="absolute top-0 left-0 right-0 flex items-center justify-center px-6 py-2.5 shrink-0"
        style="z-index: 100; border-bottom: 1px solid var(--rule-strong); background: var(--paper-raised);"
      >
        <MastheadMeta />
        <MastheadUser />
        <div class="flex items-center gap-3">
          <BrandWordmark :text="brandName" />
          <span class="topbar-divider" aria-hidden="true"></span>
          <div class="flex items-center gap-2">
            <GitHubLink />
            <ThemeToggle />
            <LocaleToggle />
          </div>
        </div>
      </div>

      <!-- 内容区（顶栏占位 44px；pb-7 保证末端内容不被悬浮 dock 遮挡，
           部分浏览器不会把滚动容器的 end padding 计入可滚动区域） -->
      <div class="absolute inset-0 pt-[44px] pb-7 flex flex-col">
        <router-view v-slot="{ Component }">
          <KeepAlive :include="KEEP_ALIVE_VIEW_NAMES" :max="KEEP_ALIVE_MAX">
            <component :is="Component" :key="route.path" class="view-container" />
          </KeepAlive>
        </router-view>
      </div>
    </div>

    <!-- 全屏浮层（推文详情/图片放大）打开时隐藏 dock，避免遮挡卡片 -->
    <AppDock
      v-show="!dockSuppressed"
      :items="visibleNavItems"
      :current-path="route.path"
      :is-admin="authStore.isAdmin"
      :is-logged-in="authStore.isLoggedIn"
      :alert-items="dockAlertItems"
      @login="requestLogin()"
      @logout="authStore.logout()"
      @change-password="changePasswordOpen = true"
    />

    <!-- 默认密码常驻警示：点击打开改密对话框，改密成功后自动消失；
         弹窗打开期间隐藏（其 z-index 高于遮罩，否则会浮在弹窗上层） -->
    <button
      v-if="showDefaultPasswordBanner && !changePasswordOpen"
      class="default-pwd-banner"
      @click="changePasswordOpen = true"
    >
      <svg class="h-3.5 w-3.5 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M12 9v4"/>
        <path d="M12 17h.01"/>
        <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>
      </svg>
      <span>{{ $t('auth.defaultPasswordBanner') }}</span>
      <span class="default-pwd-banner__action">{{ $t('auth.defaultPasswordBannerAction') }}</span>
    </button>

    <ChangePasswordDialog v-model="changePasswordOpen" />
    <LoginDialog v-model="loginOpen" :redirect="loginRedirect" @success="closeLoginPrompt" />

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
  height: calc(100dvh - 90px);
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

@media (max-width: 639px) {
  .main-canvas {
    width: 100%;
    height: 100dvh;
    min-height: 100dvh;
    margin-top: 0;
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

/* ═══ 默认密码警示条：悬浮于 dock 上方，点击即打开改密对话框 ═══ */
.default-pwd-banner {
  position: fixed;
  bottom: 88px;
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

@media (max-width: 639px) {
  .default-pwd-banner {
    bottom: max(72px, calc(env(safe-area-inset-bottom) + 64px));
  }
}
</style>
