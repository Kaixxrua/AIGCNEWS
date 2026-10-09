<script setup lang="ts">
import { computed, nextTick, provide, ref, watch } from 'vue'
import { useMediaQuery, useWindowSize } from '@vueuse/core'
import { RouterView, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { useEnrichmentAlertStore } from '@/stores/enrichmentAlertStore'
import { useTrackingUnreadStore } from '@/stores/trackingUnreadStore'
import BrandWordmark from '@/components/layout/BrandWordmark.vue'
import MastheadMeta from '@/components/layout/MastheadMeta.vue'
import MastheadUser from '@/components/layout/MastheadUser.vue'
import ComicSticker from '@/components/layout/ComicSticker.vue'
import FavoritesLink from '@/components/FavoritesLink.vue'
import TourHelpButton from '@/components/onboarding/TourHelpButton.vue'
import { tourActive } from '@/features/onboarding/signals'
import PwaInstallLink from '@/components/PwaInstallLink.vue'
import GitHubLink from '@/components/GitHubLink.vue'
import LocaleToggle from '@/components/LocaleToggle.vue'
import DensityToggle from '@/components/DensityToggle.vue'
import ThemeToggle from '@/components/ThemeToggle.vue'
import AppDock from '@/components/layout/AppDock.vue'
import LayoutFooter from '@/components/layout/LayoutFooter.vue'
import AccountSettingsDialog from '@/components/auth/AccountSettingsDialog.vue'
import QuickSearchButton from '@/components/search/QuickSearchButton.vue'
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import {
  KEEP_ALIVE_MAX,
  KEEP_ALIVE_VIEW_NAMES,
  NAV_ITEMS,
  isNavigationItemActive,
  isNavigationItemFeatureEnabled,
  isNavigationItemSitePageEnabled,
} from '@/features/navigation/navigationModel'
import { folioSection } from '@/features/navigation/folioSection'
import { FOLIO_TOOLS_AVAILABLE, FOLIO_TOOLS_TARGET_ID } from '@/features/navigation/folioTools'
import { useFeatureFlags } from '@/composables/useFeatureFlags'
import { useContactPageConfig } from '@/composables/useContactPageConfig'
import { dockSuppressed } from '@/composables/useDockSuppression'
import { useReadingMode } from '@/composables/useReadingMode'
import { routeHasDensityChoice, useAppDensity } from '@/composables/useAppDensity'
import { createRouteTransition, playEnter, routeAxis, type RouteAxis } from '@/motion/routeMotion'
import { lazyComponent } from '@/utils/lazyComponent'

const isMobile = useMediaQuery('(max-width: 767px)')
const isDesktop = useMediaQuery('(min-width: 1024px)')
const { component: OnboardingTour } = lazyComponent(() => import('@/components/onboarding/OnboardingTour.vue'))
// 站内速查只在桌面宽度可用：面板连同查询、分组逻辑单独成包，宽度头一回到桌面才加载，之后一直挂着（变窄时由 enabled 关掉），
// 手机不下载。
const { component: QuickSearch } = lazyComponent(() => import('@/components/search/QuickSearch.vue'))
const quickSearchMounted = ref(false)
watch(isDesktop, (desktop) => { if (desktop) quickSearchMounted.value = true }, { immediate: true })
const route = useRoute()
// 漫画刊头（撕纸贴纸 + 页脚卷角）覆盖首页与已按漫画概念图复刻的内容页；其余页面复刻完成后再逐个加入。
// 收银台跟着会员页走：留在旧外壳里，首页那条大字标报头比旧外壳给内容留的 56px 高，会盖住卡片顶部。
const COMIC_CONTENT_ROUTES = new Set(['disclaimer', 'dsh', 'mcp-connect', 'membership', 'membership-checkout', 'monitor', 'not-found', 'paper-read', 'privacy', 'recommended-websites', 'report', 'subscriptions', 'ui-library', 'x-board'])
// 联系页是占满一屏的场景页：窄屏的漫画外壳按文档流排版、给不出固定高度，只在桌面接入。
const DESKTOP_COMIC_ROUTES = new Set(['contact'])
// 项目库目录（projects-C）与我的网页收藏（source=website，websites-mine-C）同样按漫画概念图复刻。
const comicProjects = computed(() => route.path === '/projects')
const comicRoute = computed(() => {
  const name = String(route.name ?? '')
  return COMIC_CONTENT_ROUTES.has(name) || (isDesktop.value && DESKTOP_COMIC_ROUTES.has(name))
})
const editorialLayout = computed(() => route.path === '/' || comicProjects.value || comicRoute.value)
// 内容页（非首页）另挂一个类，页面级漫画样式与首页的一屏排版互不干扰。
const comicPage = computed(() => comicProjects.value || comicRoute.value)
// 内页的报头在桌面压成一行报眉（小号字标、版名、日期与今日更新、工具、头像），漫画贴纸与标语只留在首页。
// 联系页是占满一屏的场景页，场景与报头的咬合在私有覆盖层里调好，保持原样。
const folioPage = computed(() => comicPage.value && route.name !== 'contact')
// 未知地址的「页面不存在」页不属于任何栏目：dock 不亮、报眉不写版名。栏目按路径前缀认，不排除的话 /xyz 会亮 X 动态。
const navPath = computed(() => (route.name === 'not-found' ? '' : route.path))
const section = computed(() => folioPage.value ? folioSection(navPath.value, route.query, String(route.name ?? '')) : null)
// 报眉中间那一栏空着，各页的本版工具（FolioTools）放得下就传送进去；挂载点常驻，只在有报眉时显示。
provide(FOLIO_TOOLS_AVAILABLE, computed(() => folioPage.value && isDesktop.value))
// 版面密度：有舒适版面的内页在报眉右侧放开关；选了舒适时这几页的外壳挂一个类，舒适版面的样式据此生效（只在桌面，
// 首页和别的页不挂）。
const { comfortable } = useAppDensity()
const densityToggleShown = computed(() => folioPage.value && isDesktop.value && routeHasDensityChoice(route))
const comfortableShell = computed(() => comfortable.value && densityToggleShown.value)
// 首页的墨线在左上角贴纸处抬高、绕过飘带再落回报头底；报眉没有贴纸，墨线贴着底边走完。
const mastheadRule = computed(() => folioPage.value
  ? 'M0 47.5 L700 46.5 L1721 48'
  : 'M0 17 L420 13 Q452 12 470 28 L487 45 Q491 49 509 49 L1247 49 Q1266 49 1275 46 L1698 46 Q1712 46 1721 50')
// 首页桌面版按 1920×1080 排版；更大的屏幕（2K/4K）整体等比放大，而不是把同样的内容摊得更稀。
// 以宽高中较紧的一边为准，保证放大后仍是一屏不滚动。页内的 100dvh 须除以 --shell-zoom。
const { width: viewportWidth, height: viewportHeight } = useWindowSize()
const shellZoom = computed(() => {
  if (route.path !== '/' || !isDesktop.value) return 1
  const zoom = Math.min(viewportWidth.value / 1920, viewportHeight.value / 1080)
  return zoom > 1 ? Math.floor(zoom * 1000) / 1000 : 1
})
const shellStyle = computed(() => shellZoom.value > 1 ? { zoom: shellZoom.value, '--shell-zoom': shellZoom.value } : undefined)
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

// 页面切换动效：按 dock 顺序决定滑入方向（往右的入口从右边滑进来），dock 之外的页面从下方浮起。
// 项目库与「我的网页收藏」共用一个页面实例、只换查询参数，没有新旧页面交接，单独补一段进入动画。
const viewKey = computed(() => (route.name === 'ui-library' ? 'ui-library' : route.path))
const appContent = ref<HTMLElement | null>(null)
let pageAxis: RouteAxis = 'rise'
let dockIndex = -1
const routeTransition = createRouteTransition(() => pageAxis)
watch([viewKey, () => route.fullPath], (next, previous) => {
  const index = visibleNavItems.value.findIndex((item) => isNavigationItemActive(item, navPath.value, route.query))
  pageAxis = routeAxis(dockIndex, index)
  dockIndex = index
  if (!previous || next[0] !== previous[0] || pageAxis === 'rise') return
  void nextTick(() => {
    const view = appContent.value?.querySelector(':scope > .view-container')
    if (view) playEnter(view, pageAxis)
  })
}, { flush: 'pre', immediate: true })

// 读报态：桌面内页往下读时 dock 和页脚滑出屏幕，画板一直伸到底边，只留一条荧光拉手；换页时先回来。
const readingEnabled = computed(() => folioPage.value && isDesktop.value && !dockSuppressed.value && !tourActive.value)
const { hidden: readingHidden, reveal: revealChrome } = useReadingMode({ enabled: readingEnabled, scope: appContent })
watch(viewKey, revealChrome)
const pullChromeBack = (event: MouseEvent) => {
  revealChrome()
  // 用键盘按的拉手：焦点交给 dock 上的当前栏目，接着按 Tab 就在导航里走。
  if (event.detail === 0) {
    const dock = document.querySelector<HTMLElement>('.dock [aria-current="page"]') ?? document.querySelector<HTMLElement>('.dock a')
    dock?.focus({ preventScroll: true })
  }
}

/** 品牌名称 — 从 Vite 环境变量读取，回退默认值 */
const brandName = import.meta.env.VITE_APP_BRAND_NAME || 'AIGC NEWS'
</script>

<template>
  <!-- ═══ 全屏内容层 ═══ -->
  <div class="app-shell relative flex h-dvh w-full items-start justify-center overflow-hidden" :class="{ 'app-shell--editorial': editorialLayout, 'app-shell--comic-page': comicPage, 'app-shell--folio': folioPage, 'app-shell--reading': readingHidden, 'app-shell--comfortable': comfortableShell }" :style="shellStyle">

    <!-- ═══ 科技感背景光晕层 ═══ -->

    <!-- ═══ 居中悬浮画板（暖白纸质毛玻璃主面板） ═══ -->
    <div class="main-canvas" :class="{ 'main-canvas--editorial': editorialLayout }">
      <!-- 顶部品牌条：左侧报头信息 + 右侧用户信息，故障特效字标与工具图标居中成组 -->
      <div
        class="app-masthead absolute top-0 left-0 right-0 flex items-center justify-center px-6 py-2.5 shrink-0"
        style="z-index: 100; border-bottom: 1px solid var(--rule-strong); background: var(--paper-raised);"
      >
        <svg class="comic-masthead-rule" viewBox="0 0 1721 50" preserveAspectRatio="none" aria-hidden="true"><path :d="mastheadRule" /></svg>
        <MastheadMeta v-if="!isMobile" />
        <MastheadUser v-if="!isMobile" />
        <ComicSticker v-if="!isMobile && !folioPage" variant="corner" class="comic-masthead-corner" />
        <ComicSticker v-if="!isMobile && !folioPage" variant="shout" class="comic-masthead-creation" :text="$t('dashboard.editorial.creationMark')" />
        <div class="app-masthead__tools flex items-center gap-3">
          <BrandWordmark :key="isMobile ? 'mobile' : 'desktop'" :text="brandName" :compact="isMobile" />
          <p v-if="section && isDesktop" class="masthead-folio">{{ $t(`masthead.sections.${section.key}`) }}</p>
          <div :id="FOLIO_TOOLS_TARGET_ID" class="masthead-page-tools"></div>
          <span v-if="!isMobile && !folioPage" class="masthead-tagline"><svg class="comic-speech-outline" viewBox="0 0 300 72" preserveAspectRatio="none" aria-hidden="true"><path d="M12 5 L297 5 L282 57 L34 57 L7 70 L12 57 L3 57 Z" /></svg>{{ $t('dashboard.editorial.tagline') }}</span>
          <span class="topbar-divider" aria-hidden="true"></span>
          <div class="app-masthead__actions flex items-center gap-2">
            <QuickSearchButton v-if="isDesktop && folioPage" />
            <FavoritesLink v-if="!isMobile" />
            <PwaInstallLink v-if="!isMobile" />
            <GitHubLink v-if="!isMobile" />
            <DensityToggle v-if="densityToggleShown" />
            <ThemeToggle />
            <LocaleToggle />
            <TourHelpButton />
          </div>
        </div>
      </div>

      <!-- 内容区（顶栏占位 56px；pb-7 保证末端内容不被悬浮 dock 遮挡，
           部分浏览器不会把滚动容器的 end padding 计入可滚动区域） -->
      <main ref="appContent" class="app-content absolute inset-0 pt-[56px] pb-7 flex flex-col">
        <router-view v-slot="{ Component }">
          <Transition :css="false" v-bind="routeTransition">
            <KeepAlive :include="KEEP_ALIVE_VIEW_NAMES" :max="KEEP_ALIVE_MAX">
              <component :is="Component" :key="viewKey" class="view-container" />
            </KeepAlive>
          </Transition>
        </router-view>
      </main>

      <!-- 漫画外壳（首页与内容页）的画框下沿：与报头墨线同笔，在 dock 处抬起让出一格 -->
      <div v-if="editorialLayout" class="comic-footer-rule" aria-hidden="true">
        <svg class="comic-footer-rule__run" viewBox="0 0 100 13" preserveAspectRatio="none"><path d="M0 12 L100 11.5" /></svg>
        <svg class="comic-footer-rule__step" viewBox="0 0 26 13"><path class="comic-footer-rule__paper" d="M0 11.5 Q9 11.5 13 7 Q17 2.5 26 2.5 L26 13 L0 13 Z" /><path d="M0 11.5 Q9 11.5 13 7 Q17 2.5 26 2.5" /></svg>
        <svg class="comic-footer-rule__bay" viewBox="0 0 100 13" preserveAspectRatio="none"><path class="comic-footer-rule__paper" d="M0 2.5 L100 2.5 L100 13 L0 13 Z" /><path d="M0 2.5 L100 2.5" /></svg>
        <svg class="comic-footer-rule__step" viewBox="0 0 26 13"><path class="comic-footer-rule__paper" d="M26 11.5 Q17 11.5 13 7 Q9 2.5 0 2.5 L0 13 L26 13 Z" /><path d="M26 11.5 Q17 11.5 13 7 Q9 2.5 0 2.5" /></svg>
        <svg class="comic-footer-rule__run" viewBox="0 0 100 13" preserveAspectRatio="none"><path d="M0 11.5 L100 12" /></svg>
      </div>
    </div>

    <!-- 全屏浮层（推文详情/图片放大）打开时隐藏 dock，避免遮挡卡片 -->
    <AppDock
      v-show="!dockSuppressed"
      :items="visibleNavItems"
      :brand-name="brandName"
      :current-path="navPath"
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
    <OnboardingTour :blocked="accountSettingsOpen" />

    <!-- 站内速查（⌘K / Ctrl+K）：桌面端任何一页都能叫出来；报眉上的放大镜只在内页出现，首页不动 -->
    <QuickSearch v-if="quickSearchMounted" :enabled="isDesktop" />

    <LayoutFooter :brand-name="brandName" :editorial="editorialLayout" />

    <!-- 读报态的拉手：dock 收起后才露出来，点它（或往上滚、鼠标碰底边、按 Esc）dock 就回来 -->
    <button v-if="readingEnabled" type="button" class="reading-handle" :aria-label="$t('navigation.showDock')" :title="$t('navigation.showDock')" @click="pullChromeBack"></button>

  </div>
</template>

<style scoped>
.main-canvas.main-canvas--editorial { width: 100%; height: calc(100dvh - 90px); margin-top: 0; border: 0; border-radius: 0; background: transparent; box-shadow: none; }
.main-canvas--editorial .app-masthead { height: 70px; border-bottom: 0 !important; background: transparent !important; padding-inline: 42px; }
.main-canvas--editorial :deep(.masthead-meta) { left: 42px; font-size: 13px; line-height: 1.45; }
.main-canvas--editorial > .app-content { padding-top: 70px; padding-bottom: 0; left: 18px; right: 16px; }
.masthead-tagline { font-size: 14px; color: var(--ink-muted); border-left: 1px solid var(--rule); padding-left: 24px; margin-left: 12px; }
.masthead-page-tools { display: none; }
@media (min-width: 1100px) {
  .app-masthead__actions { flex-shrink: 0; }
  .topbar-divider { display: none; }
}
@media (max-width: 1399px) { .masthead-tagline { display: none; } }
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
  .main-canvas.main-canvas--editorial { height: 100dvh; }
  .main-canvas--editorial .app-masthead { height: 52px; padding-inline: 14px; }
  .main-canvas--editorial > .app-content { left: 0; right: 0; padding-top: 52px; padding-bottom: 76px; }
  .main-canvas { border: 0; box-shadow: none; }
  .app-masthead { height: calc(52px + env(safe-area-inset-top)); padding-top: calc(8px + env(safe-area-inset-top)); }
  .main-canvas > .app-content { padding-top: calc(52px + env(safe-area-inset-top)); padding-bottom: calc(72px + env(safe-area-inset-bottom)); }
  .app-masthead__tools { gap: 8px; }
  .topbar-divider { display: none; }
}
/* The homepage frame grows with its cards; only the outer page scrolls on small screens. */
.app-shell--editorial { height: calc(100dvh - 90px); overflow-y: auto; scrollbar-width: none; }
.app-shell--editorial::-webkit-scrollbar { display: none; }
.main-canvas.main-canvas--editorial { height: auto; min-height: calc(100dvh - 90px); overflow: visible; margin-bottom: 0; }
.main-canvas--editorial > .app-content { position: relative; inset: auto; padding: 70px 16px 0 18px; }
.main-canvas--editorial :deep(.view-container) { height: auto; flex: none; }
@media (max-width: 1023px) {
  .main-canvas--editorial > .app-content { padding: calc(52px + env(safe-area-inset-top)) 8px 0; }
  .main-canvas.main-canvas--editorial { min-height: calc(100dvh - 90px); }
}

/* Desktop home uses the actual available viewport; mobile retains readable flow. */
@media (min-width: 1024px) {
  .app-shell--editorial { height: calc(100dvh / var(--shell-zoom, 1)); overflow: hidden; }
  .main-canvas.main-canvas--editorial { height: calc(100dvh / var(--shell-zoom, 1) - 90px); min-height: 0; }
  .main-canvas--editorial > .app-content { height: 100%; min-height: 0; padding-bottom: 4px; }
  .main-canvas--editorial :deep(.view-container) { height: 100%; flex: 1 1 0; }
}


@media (min-width: 1024px) and (max-height: 700px) {
 .main-canvas--editorial .app-masthead { height: 52px; }
 .main-canvas--editorial > .app-content { padding-top: 52px; }
 .main-canvas.main-canvas--editorial { height: calc(100dvh - 80px); }
 .app-shell--editorial :deep(.dock) { bottom: 6px; }
}


/* Share a bounded center lane with the homepage footer, including signed-in items. */
@media (min-width: 1024px) {
 .app-shell { --home-dock-width: clamp(760px, 58vw, 900px); }
 .app-shell--editorial :deep(.dock) { bottom: 8px; }

}

/* Header regions participate in layout so long account names cannot cover controls. */
@media (min-width: 768px) {
 .app-masthead { display: grid; grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); gap: 16px; }
 .app-masthead :deep(.masthead-meta), .app-masthead :deep(.masthead-user) { position: static; transform: none; min-width: 0; }
 .app-masthead :deep(.masthead-meta) { grid-column: 1; grid-row: 1; overflow: hidden; }
 .app-masthead__tools { grid-column: 2; grid-row: 1; }
 .app-masthead :deep(.masthead-user) { grid-column: 3; grid-row: 1; overflow: hidden; }
 .app-masthead :deep(.masthead-user__status), .app-masthead :deep(.masthead-user__identity) { max-width: 100%; overflow: hidden; text-overflow: ellipsis; }
}
@media (min-width: 768px) and (max-width: 1199px) {
 .app-masthead { gap: 8px; }
}
</style>
