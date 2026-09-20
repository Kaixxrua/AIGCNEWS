<script setup lang="ts">
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { useDocumentVisibility, useElementVisibility, usePreferredReducedMotion } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import { useDashboardData } from '@/composables/useDashboardData'
import { useDashboardStats } from '@/composables/useDashboardStats'
import { subscribeLiveStats } from '@/composables/useLiveStatsStream'
import GlassCalendar from '@/components/GlassCalendar.vue'
import SpinnerLoader from '@/components/SpinnerLoader.vue'
import DashboardEmptyState from '@/components/dashboard/DashboardEmptyState.vue'
import DashboardOverviewPanel from '@/components/dashboard/DashboardOverviewPanel.vue'
import DashboardRankingPanel from '@/components/dashboard/DashboardRankingPanel.vue'
import RollingNumber from '@/components/dashboard/RollingNumber.vue'
import { ArrowRight, MailPlus, Plug, Terminal, Check, ChevronRight } from 'lucide-vue-next'
import type { Stats } from '@/features/dashboard/dashboardViewModel'
import { loadCatalog, type UiTemplate } from '@/features/ui-library/catalog'

defineOptions({ name: 'DesktopDashboardView' })
const { t, locale } = useI18n()
const digestFeatures = computed(() => locale.value.startsWith('zh') ? ['更快', '更深', '更广', '连接 AI 创新'] : ['Faster', 'Deeper', 'Broader', 'Connect AI innovation'])
const uiCount = ref<number | null>(null)
const uiLoading = ref(true)
const uiPreview = ref<UiTemplate | null>(null)
const previewFailed = ref(false)
const clipFailed = ref(false)
const previewElement = ref<HTMLElement>()
const previewVisible = useElementVisibility(previewElement)
const active = ref(true)
onActivated(() => { active.value = true })
onDeactivated(() => { active.value = false })
const visibility = useDocumentVisibility()
const motion = usePreferredReducedMotion()
const previewName = computed(() => uiPreview.value?.name[locale.value.startsWith('zh') ? 'zh' : 'en'] ?? '')
const uiCatalogController = new AbortController()
let currentStats: () => Stats = () => ({})
const {
  statValues,
  visitorValues,
  mcpTotalCalls,
  mcpDshCalls,
  updateStatSources,
  updateVisitorSources,
} = useDashboardStats(() => currentStats())

const {
  activeTab,
  tabList,
  stats,
  loading,
  tabLoading,
  errorMsg,
  currentDate,
  todayStr,
  availableDates,
  isViewingHistory,
  isFinalized,
  isEmbargoed,
  sourceStatus,
  selectSourceTab,
  onDateChange,
  hasData,
  applyLiveStats,
} = useDashboardData({
  updateStatSources,
  updateVisitorSources,
})
currentStats = () => stats.value

// 与顶栏共用 SSE；断流后的轮询由共享订阅统一管理。
subscribeLiveStats(applyLiveStats)

onMounted(async () => {
  try {
    const items = await loadCatalog(uiCatalogController.signal)
    uiCount.value = items.length
    const clips = items.filter(item => item.clip_url && item.poster_url)
    const candidates = clips.length ? clips : items.filter(item => item.poster_url)
    uiPreview.value = candidates[Math.floor(Math.random() * candidates.length)] ?? null
  } catch {
    // 目录不可用时显示未知，不把加载失败误报为零。
  } finally {
    uiLoading.value = false
  }
})

onBeforeUnmount(() => uiCatalogController.abort())

</script>

<template>
  <div class="dashboard-page">
    <header class="dashboard-heading">
      <div class="dashboard-heading__copy">
        <h1>{{ t('dashboard.editorial.title') }}</h1>
        <p>{{ t('dashboard.editorial.subtitle') }}</p>
      </div>
      <DashboardOverviewPanel v-if="!loading" :loading="loading" :active-tab="activeTab"
        :stat-values="statValues" :visitor-values="visitorValues" :ui-count="uiCount" :ui-loading="uiLoading"
        @select-source="selectSourceTab" />
    </header>
    <div v-if="errorMsg" class="dashboard-error" role="alert">{{ errorMsg }}</div>
    <div class="dashboard-main">
      <SpinnerLoader v-if="loading" class="min-h-[360px]" />
      <DashboardEmptyState v-else-if="isEmbargoed" variant="embargoed" />
      <DashboardEmptyState v-else-if="!hasData && !tabLoading" variant="no-data" />
      <DashboardRankingPanel v-else :active-tab="activeTab" :tab-list="tabList" :tab-loading="tabLoading"
        :is-viewing-history="isViewingHistory" :is-finalized="isFinalized" :source-status="sourceStatus"
        @select-source="selectSourceTab" />

      <aside v-if="!loading" class="dashboard-sidebar min-h-0">
        <p class="sidebar-motto"><span>{{ t('dashboard.editorial.motto') }}</span><ChevronRight :size="22" aria-hidden="true" /></p>
        <GlassCalendar :model-value="currentDate" :today-date="todayStr" :available-dates="availableDates" @update:model-value="onDateChange" />
        <section class="digest-card">
          <div class="digest-heading"><MailPlus :size="27" /><h2>{{ t('dashboard.editorial.digestTitle') }}</h2></div>
          <p>{{ t('dashboard.editorial.digestDescription') }}</p>
          <ul class="digest-features"><li v-for="feature in digestFeatures" :key="feature"><Check :size="16" aria-hidden="true" />{{ feature }}</li></ul>
          <RouterLink :to="{ path: '/report', query: { subscribe: '1' } }" class="digest-cta">
            {{ t('dashboard.digest.cta') }}<ArrowRight :size="15" />
          </RouterLink>
          <img class="digest-robot" :src="'/assets/comic/digest-robot.webp'" alt="" aria-hidden="true" />
        </section>
        <div class="integration-grid">
          <RouterLink to="/mcp" class="integration-card integration-card--mcp" :aria-label="t('dashboard.mcpCalls.title')">
            <Plug :size="19" /><span>{{ t('dashboard.mcpCalls.title') }}<RollingNumber :value="mcpTotalCalls" grouping /></span>
          </RouterLink>
          <RouterLink to="/dsh" class="integration-card integration-card--dsh items-center" :aria-label="t('dashboard.dshCalls.title')">
            <Terminal :size="19" /><span>{{ t('dashboard.dshCalls.title') }}<RollingNumber :value="mcpDshCalls" grouping /></span>
          </RouterLink>
        </div>
        <RouterLink :to="uiPreview ? { name: 'ui-library', params: { id: uiPreview.id } } : { name: 'ui-library' }" class="ui-inspiration">
          <div class="ui-inspiration__heading"><span>{{ t('dashboard.editorial.inspiration') }}</span><ArrowRight :size="16" /></div>
          <div ref="previewElement" class="ui-inspiration__preview">
            <video v-if="uiPreview?.clip_url && !clipFailed && active && previewVisible && motion !== 'reduce' && visibility === 'visible'" :src="uiPreview.clip_url" :poster="uiPreview.poster_url" :aria-label="previewName" autoplay muted loop playsinline @error="clipFailed = true" />
            <img v-else-if="uiPreview && !previewFailed" :src="uiPreview.poster_url" :alt="previewName" loading="lazy" @error="previewFailed = true" />
            <span v-else class="ui-inspiration__fallback">UI / {{ t('dashboard.editorial.explore') }}</span>
          </div>
          <div class="ui-inspiration__caption"><span>{{ previewName || t('dashboard.editorial.explore') }}</span><span>UI LIBRARY ↗</span></div>
        </RouterLink>
      </aside>
    </div>
  </div>
</template>

<style scoped>

.dashboard-page { --sidebar-width:24%; display:grid;grid-template-columns:minmax(0,1fr) var(--sidebar-width);grid-template-rows:94px minmax(0,1fr);gap:14px 24px;position:relative;isolation:isolate;height:100%;min-height:0;padding:16px 12px 6px;color:var(--ink); }
.dashboard-page::before,.dashboard-page::after { content:'';position:absolute;z-index:-1;top:0;bottom:0;border:1.5px solid var(--rule-strong);border-radius:14px;background:color-mix(in srgb,var(--paper) 96%,transparent);pointer-events:none; }
.dashboard-page::before { left:0;right:calc(var(--sidebar-width) + 13px); }
.dashboard-page::after { right:0;width:calc(var(--sidebar-width) + 12px); }
.dashboard-heading { grid-column:1;grid-row:1;display:flex;align-items:center;min-width:0;gap:16px; }
.dashboard-heading__copy { flex:0 0 258px;min-width:0;padding-left:5px; }
.dashboard-heading h1 { text-shadow:1px 1px 0 var(--paper-raised);position:relative;isolation:isolate;display:inline-block;margin:0 0 5px;font-size:43px;font-style:italic;font-weight:950;line-height:1.2;letter-spacing:-.045em;white-space:nowrap; }
.dashboard-heading h1::before { content:'';position:absolute;z-index:-1;inset:70% -4px 1px;background:var(--acid);transform:rotate(-5deg) skewX(-18deg); }
.dashboard-heading h1::after { content:'';position:absolute;right:-14px;top:-9px;width:24px;height:28px;background:var(--acid);clip-path:polygon(0 0,15% 0,12% 65%,0 65%,60% 10%,80% 20%,22% 85%,15% 78%,95% 66%,100% 82%,25% 100%,23% 88%); }
.dashboard-heading p { font-size:20px;font-weight:700;font-style:italic;line-height:1.4;white-space:nowrap; }
.dashboard-heading :deep(.stat-strip) { flex:1;height:100%; }
.dashboard-main { display:contents; }
.dashboard-main > :not(aside) { grid-column:1;grid-row:2;min-width:0; }
.dashboard-sidebar { grid-column:2;grid-row:1/3;display:grid;grid-template-rows:70px 220px minmax(180px,226px) 60px 81px;align-content:start;gap:9px;min-width:0;min-height:0; }
.sidebar-motto { display:flex;justify-content:space-between;align-items:center;position:relative;white-space:pre-line;font-size:20px;font-weight:850;line-height:1.3;padding:10px 15px;border:1.5px solid var(--rule-strong);border-radius:7px;background:var(--paper-raised);box-shadow:inset 5px 0 0 var(--acid); }
.sidebar-motto svg { flex-shrink:0; }
.dashboard-sidebar :deep(.dash-calendar) { padding:8px 12px;border:1.5px solid var(--rule-strong);border-radius:8px;background:var(--paper-raised); }
.dashboard-sidebar :deep(.dash-calendar h3) { color:var(--ink);font-family:inherit;font-size:24px;font-weight:850;font-style:italic; }
.dashboard-sidebar :deep(.dash-calendar > div:first-child) { margin-bottom:4px; }
.dashboard-sidebar :deep(.dash-calendar > .grid:last-child) { flex:1;min-height:0;grid-auto-rows:minmax(0,1fr); }
.dashboard-sidebar :deep(.dash-calendar .calendar-day) { height:100%;min-height:20px;font-size:15px;color:var(--ink); }
.dashboard-sidebar :deep(.dash-calendar .calendar-day.text-stone-300) { color:var(--muted); }
.dashboard-sidebar :deep(.dash-calendar .calendar-day--disabled) { opacity:.65; }
.dashboard-sidebar :deep(.dash-calendar .grid > span) { font-size:14px !important;line-height:25px !important;color:var(--ink-secondary); }
.dashboard-sidebar :deep(.calendar-day--active) { width:39px;justify-self:center;font-size:20px !important;font-weight:850;border:1.5px solid var(--rule-strong);border-radius:4px;box-shadow:none !important; }
.dashboard-sidebar :deep(.cal-nav) { color:var(--ink);width:35px; }
.dashboard-sidebar :deep(.cal-nav svg) { width:19px;height:19px; }
.dashboard-sidebar :deep(.snapshot-dot) { display:none; }
.dashboard-error { position:absolute;top:0;left:12px;right:12px;z-index:3;padding:8px;color:var(--ink);background:var(--paper-raised);border:1px solid var(--tone-coral);border-radius:5px; }
.digest-card { position:relative;isolation:isolate;overflow:visible;padding:10px 13px;border:1.5px solid var(--rule-strong);border-radius:8px;background:var(--paper-raised); }
.digest-card::before { content:'';position:absolute;inset:0;z-index:-1;border-radius:inherit;background-image:radial-gradient(#37b9df .8px,transparent .8px);background-size:4px 4px;mask-image:linear-gradient(135deg,transparent 48%,#000 85%);opacity:.5; }
.digest-heading { position:relative;z-index:1;display:flex;align-items:center;gap:11px; }
.digest-heading > svg { width:34px;height:31px;padding:2px;color:var(--ink);background:var(--acid);border-radius:5px;flex-shrink:0; }
.digest-heading h2 { font-size:26px;line-height:1.3;font-weight:850;letter-spacing:.02em; }
.digest-card p { position:relative;z-index:1;color:var(--ink-secondary);font-size:13px;line-height:1.4;margin-top:5px;white-space:nowrap; }
.digest-features { position:relative;z-index:1;display:flex;flex-direction:column;gap:3px;margin-top:10px;font-size:15px;font-weight:650; }
.digest-features li { display:flex;align-items:center;gap:12px; }
.digest-features svg { background:var(--acid);color:var(--acid-ink);border-radius:50%;padding:2px;width:19px;height:19px;stroke-width:3; }
.digest-cta { position:absolute;left:12px;bottom:9px;z-index:4;display:flex;align-items:center;justify-content:center;gap:13px;width:52%;height:39px;border:2px solid var(--rule-strong);border-radius:12px;background:var(--acid);color:var(--acid-ink);font-size:18px;font-weight:850; }
.digest-cta svg { width:23px;height:23px; }
.digest-robot { position:absolute;z-index:3;right:-21px;bottom:-1px;width:55%;height:92%;object-fit:contain;object-position:right bottom;pointer-events:none; }
.integration-grid { display:grid;grid-template-columns:1fr 1fr;gap:8px; }
.integration-card { height:100%;min-height:0;overflow:hidden;display:flex;align-items:center;gap:9px;min-width:0;padding:5px 8px;border:1px solid var(--rule-strong);border-radius:7px;background:var(--paper-raised); }
.integration-card > svg { width:45px;height:45px;padding:8px;flex-shrink:0;border-radius:10px;background:color-mix(in srgb,#65c9f5 22%,var(--paper-raised));color:var(--ink); }
.integration-card--dsh > svg { background:color-mix(in srgb,#a190f6 25%,var(--paper-raised));color:#7441d4; }
.integration-card > span { min-width:0;font-size:12px;line-height:1.25;color:var(--ink-secondary); }
.integration-card :deep(number-flow-vue),.integration-card :deep(span > span) { display:block;color:var(--ink);font-size:25px;line-height:1.2;font-weight:850; }
.ui-inspiration { display:grid;grid-template-columns:78px minmax(0,1fr);grid-template-rows:25px 1fr;column-gap:10px;padding:6px 8px;border:1px solid var(--rule-strong);border-radius:7px;background:var(--paper-raised); }
.ui-inspiration__heading { grid-column:2;display:flex;align-items:center;justify-content:space-between;font-size:20px;font-weight:850; }
.ui-inspiration__heading svg { width:23px;height:23px; }
.ui-inspiration__preview { grid-column:1;grid-row:1/3;overflow:hidden;border-radius:6px;background:var(--paper-muted); }
.ui-inspiration__preview video,.ui-inspiration__preview img { width:100%;height:100%;object-fit:cover; }
.ui-inspiration__fallback { display:grid;height:100%;place-items:center;font-size:11px;color:var(--muted); }
.ui-inspiration__caption { display:flex;flex-direction:column;justify-content:center;gap:2px;min-width:0;color:var(--ink-secondary);font-size:13px;line-height:1.25; }
.ui-inspiration__caption > span:first-child { overflow:hidden;text-overflow:ellipsis;white-space:nowrap; }
.ui-inspiration__caption > span:last-child { color:var(--ink);font-size:12px; }
.dashboard-sidebar a:focus-visible { outline:2px solid var(--acid);outline-offset:3px; }
:root[data-theme='dark'] .dashboard-heading h1 { color:var(--acid); }
:root[data-theme='dark'] .dashboard-heading h1::before { opacity:0; }
:root[data-theme='dark'] .dashboard-page::before { border-color:transparent;background:transparent; }
:root[data-theme='dark'] .dashboard-page::after { border-color:transparent;background:color-mix(in srgb,var(--paper-raised) 55%,var(--paper)); }
:root[data-theme='dark'] .digest-card::before { opacity:.06; }
:root[data-theme='dark'] .digest-heading > svg { color:var(--acid);background:transparent; }
:root[data-theme='dark'] .digest-robot { filter:saturate(.85) brightness(.91); }

/* Printed ink edges and local comic accents retain clean reading surfaces. */
.sidebar-motto { border-width:2px 2px 2.5px 3px;transform:rotate(-.45deg);border-radius:4px 7px 4px 3px;box-shadow:inset 5px 0 0 var(--acid),1px 2px 0 var(--rule-strong); }
.dashboard-sidebar :deep(.dash-calendar) { border-width:2px 2.5px 2px 2px;border-radius:5px 9px 4px 6px;box-shadow:inset -2px -2px 0 color-mix(in srgb,var(--rule-strong) 12%,transparent); }
.dashboard-sidebar :deep(.calendar-day--active)::before { content:'';position:absolute;inset:-13px;z-index:0;pointer-events:none;background:repeating-conic-gradient(from 5deg,var(--acid) 0 3deg,transparent 3deg 32deg);mask:radial-gradient(ellipse,transparent 56%,#000 59%); }
.digest-card { border-width:2px 2.5px 3px 2px;border-radius:5px 9px 4px 7px;box-shadow:inset 2px -2px 0 color-mix(in srgb,var(--rule-strong) 15%,transparent); }
.digest-card::after { content:'';position:absolute;z-index:-1;right:-10px;bottom:0;width:59%;height:87%;background:var(--acid);opacity:.8;clip-path:polygon(50% 24%,60% 0,63% 25%,79% 2%,76% 32%,99% 17%,86% 43%,100% 47%,90% 57%,100% 76%,79% 71%,86% 97%,59% 82%,43% 100%,37% 80%,12% 91%,21% 66%,0 59%,22% 48%,4% 25%,32% 37%,27% 10%); }
.digest-heading h2,.sidebar-motto { letter-spacing:-.035em;font-weight:900; }
:root[data-theme='dark'] .digest-card::after { opacity:.2; }
:root[data-theme='dark'] .sidebar-motto { box-shadow:inset 4px 0 0 color-mix(in srgb,var(--acid) 60%,transparent); }

:root[data-theme='dark'] .sidebar-motto,:root[data-theme='dark'] .digest-card,:root[data-theme='dark'] .dashboard-sidebar :deep(.dash-calendar) { border-width:1px; }
@media (max-width:1499px) { .dashboard-page { gap:12px 20px; }.dashboard-heading { gap:12px; }.dashboard-heading__copy { flex-basis:205px; }.dashboard-heading h1 { font-size:34px; }.dashboard-heading p { font-size:16px; }.digest-heading h2 { font-size:22px; }.digest-card p { font-size:11px;white-space:normal; }.integration-card { gap:6px;padding-inline:6px; }.integration-card > svg { width:35px;height:38px;padding:6px; }.integration-card > span { font-size:10px; }.integration-card :deep(number-flow-vue),.integration-card :deep(span > span) { font-size:22px; }.sidebar-motto { font-size:18px; } }
@media (min-width:1200px) and (max-height:820px) { .dashboard-page { grid-template-rows:80px minmax(0,1fr);padding-top:10px; }.dashboard-sidebar { grid-template-rows:60px 190px 170px 52px 62px;gap:7px; }.dashboard-heading :deep(.stat-cell) { min-height:80px; }.dashboard-sidebar :deep(.dash-calendar .calendar-day) { height:100%;min-height:19px; }.digest-features { font-size:13px;gap:1px;margin-top:5px; }.digest-heading h2 { font-size:22px; }.digest-cta { height:30px;font-size:15px;bottom:7px; }.digest-card { min-height:0; }.digest-features { font-size:12px;line-height:1.3;gap:1px; }.digest-features svg { width:15px;height:15px; }.digest-card p { font-size:10px;line-height:1.25; }.integration-card :deep(number-flow-vue),.integration-card :deep(span > span) { font-size:21px; }.ui-inspiration { grid-template-rows:20px 1fr;padding-block:4px; }.ui-inspiration__heading { font-size:17px; }.ui-inspiration__caption { font-size:11px; }.ui-inspiration { grid-template-columns:60px minmax(0,1fr); } }
@media (max-width:1199px) { .dashboard-page { height:auto;grid-template-columns:minmax(0,1fr) 29%;grid-template-rows:auto auto;padding-top:15px;gap:14px; }.dashboard-heading { flex-wrap:wrap;gap:12px; }.dashboard-heading__copy { flex-basis:100%; }.dashboard-heading :deep(.stat-strip) { flex-basis:100%; }.dashboard-sidebar { grid-template-rows:70px 230px 240px 65px 82px; }.dashboard-sidebar :deep(.dash-calendar .calendar-day) { height:28px; }.digest-heading h2 { font-size:20px; }.digest-heading { gap:6px; }.digest-heading > svg { width:26px; }.digest-features { font-size:13px; }.digest-cta { font-size:15px; }.integration-card > svg { width:28px;height:33px;padding:4px; }.integration-card :deep(number-flow-vue),.integration-card :deep(span > span) { font-size:19px; }.ui-inspiration { grid-template-columns:55px minmax(0,1fr); }.ui-inspiration__heading { font-size:17px; } }
@media (max-width:899px) { .dashboard-page { display:flex;flex-direction:column;padding:14px 10px; }.dashboard-page::before { right:0; }.dashboard-page::after { display:none; }.dashboard-sidebar { display:grid;grid-template-columns:1fr 1fr;grid-template-rows:auto;gap:12px; }.sidebar-motto { display:none; }.dashboard-sidebar :deep(.dash-calendar) { min-height:270px; }.dashboard-sidebar :deep(.dash-calendar .calendar-day) { height:35px; }.digest-card { min-height:270px; }.integration-grid,.ui-inspiration { min-height:78px; }.dashboard-heading__copy { padding-bottom:5px; }.dashboard-heading h1 { font-size:39px; }.dashboard-heading p { font-size:18px; } }
@media (max-width:539px) { .dashboard-sidebar { display:flex;flex-direction:column; }.dashboard-sidebar :deep(.dash-calendar) { min-height:290px; }.dashboard-sidebar :deep(.dash-calendar .calendar-day) { height:38px; }.digest-card { min-height:270px; }.digest-heading h2 { font-size:25px; }.digest-card p { font-size:12px; }.digest-features { font-size:16px;gap:5px; }.digest-cta { font-size:18px;height:40px; }.dashboard-heading h1 { font-size:35px; }.dashboard-heading p { font-size:16px; } }

</style>
