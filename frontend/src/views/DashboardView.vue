<script setup lang="ts">
import { useDashboardData } from '../composables/useDashboardData'
import { useDashboardStats } from '../composables/useDashboardStats'
import GlassCalendar from '../components/GlassCalendar.vue'
import { CalendarDays, Zap, CheckCircle2 } from 'lucide-vue-next'
import {
  DAILY_ONLY_TABS,
  PERIODS,
  TABS,
  aiScoreDisplay,
  getModuleTags,
  getSourceConfig,
  isSourceStatCard,
  scoreDisplay,
  statCards,
  visitorCards,
  type Stats,
} from '../features/dashboard/dashboardViewModel'

defineOptions({ name: 'DashboardView' })

let currentStats: () => Stats = () => ({})
const {
  updateStatSources,
  updateVisitorSources,
  disableCountUp,
  getAnimatedValue,
  getVisitorDisplayValue,
} = useDashboardStats(() => currentStats())

const {
  activeTab,
  activePeriod,
  isPeriodDisabled,
  tabList,
  stats,
  loading,
  tabLoading,
  errorMsg,
  currentDate,
  availableDates,
  isViewingHistory,
  isFinalized,
  isEmbargoed,
  selectSourceTab,
  onDateChange,
  hasData,
} = useDashboardData({
  updateStatSources,
  updateVisitorSources,
  disableCountUp,
})
currentStats = () => stats.value

</script>

<template>
  <div class="dashboard-page flex h-full flex-col gap-2 overflow-y-auto px-6 py-3 pb-16">

    <!-- 页头 — 简洁标题 -->
    <div class="stagger-enter flex items-center justify-between shrink-0">
      <h1 class="text-xl font-semibold text-stone-800 tracking-tight font-serif">Dashboard</h1>
      <div v-if="!loading && isViewingHistory" class="flex items-center gap-1.5 text-xs text-stone-400">
        <CalendarDays class="h-3.5 w-3.5" />
        <span class="text-stone-700 font-medium">{{ currentDate }}</span>
      </div>
    </div>

    <!-- 错误提示 -->
    <div
      v-if="errorMsg"
      class="shrink-0 glass-card flex items-center gap-2 px-5 py-3 text-sm text-rose-600"
    >
      <svg class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
      </svg>
      {{ errorMsg }}
    </div>

    <!-- 顶部区域：统计卡片 + 日历 -->
    <div v-if="loading" class="flex flex-col gap-2 shrink-0 md:flex-row md:items-start">
      <div class="flex-1 flex flex-col gap-2">
        <div class="grid gap-2 grid-cols-2 sm:grid-cols-3">
          <div v-for="i in 6" :key="i" class="glass-card h-[44px] animate-pulse" />
        </div>
        <div class="grid gap-2 grid-cols-2">
          <div v-for="i in 2" :key="'v'+i" class="glass-card h-[44px] animate-pulse" />
        </div>
      </div>
      <div class="w-[170px] shrink-0 glass-card h-[150px] animate-pulse" />
    </div>

    <div v-else class="flex flex-col gap-2 shrink-0 md:flex-row md:items-start">
      <div class="flex-1 flex flex-col gap-2">
        <!-- 6 个数据源卡片 -->
        <div class="grid gap-2 grid-cols-2 sm:grid-cols-3">
          <template v-for="(card, index) in statCards" :key="card.key">
            <button
              v-if="isSourceStatCard(card.key)"
              type="button"
              class="dashboard-source-card stagger-enter h-[44px] px-2.5 flex items-center justify-between transition-colors"
              :class="[activeTab === card.key ? 'dashboard-source-card--active' : '', 'glass-card card-hover']"
              :style="{ animationDelay: (index * 0.08 + 0.1) + 's' }"
              :aria-pressed="activeTab === card.key"
              :aria-label="`查看${card.label}排行榜`"
              @click="selectSourceTab(card.key)"
            >
              <span class="flex items-center gap-2">
                <span
                  class="w-6 h-6 rounded-full flex items-center justify-center shrink-0"
                  :class="[card.iconBg, card.iconColor]"
                >
                  <span class="w-3 h-3 flex items-center justify-center" v-html="card.icon" />
                </span>
                <span class="text-xs font-medium" :class="card.labelColor || 'text-stone-500'">{{ card.label }}</span>
              </span>
              <span class="text-lg font-bold tabular-nums" :class="card.numColor">
                {{ getAnimatedValue(index) }}
              </span>
            </button>
            <div
              v-else
              class="stagger-enter h-[44px] px-2.5 flex items-center justify-between transition-colors rounded-xl shadow-sm"
              :class="card.cardBg"
              :style="{ animationDelay: (index * 0.08 + 0.1) + 's' }"
            >
              <span class="flex items-center gap-2">
                <span class="w-6 h-6 rounded-full flex items-center justify-center shrink-0" :class="[card.iconBg, card.iconColor]">
                  <span class="w-3 h-3 flex items-center justify-center" v-html="card.icon" />
                </span>
                <span class="text-xs font-medium" :class="card.labelColor">{{ card.label }}</span>
              </span>
              <span class="text-lg font-bold tabular-nums" :class="card.numColor">{{ getAnimatedValue(index) }}</span>
            </div>
          </template>
        </div>

        <!-- 2 个运营统计卡片 -->
        <div class="grid gap-2 grid-cols-2">
          <div
            v-for="(card, index) in visitorCards"
            :key="card.key"
            class="stagger-enter glass-card h-[44px] px-2.5 flex items-center justify-between transition-colors"
            :style="{ animationDelay: (index * 0.08 + 0.6) + 's' }"
          >
            <div class="flex items-center gap-2">
              <div
                class="w-6 h-6 rounded-full flex items-center justify-center shrink-0"
                :class="[card.iconBg, card.iconColor]"
              >
                <span class="w-3 h-3 flex items-center justify-center" v-html="card.icon" />
              </div>
              <span class="text-xs font-medium text-stone-400">{{ card.label }}</span>
            </div>
            <span class="text-lg font-bold tabular-nums" :class="card.numColor">
              {{ getVisitorDisplayValue(card.key, index) }}
            </span>
          </div>
        </div>
      </div>

      <!-- 日历 -->
      <div class="w-full shrink-0 md:w-[170px]">
        <GlassCalendar
          v-model="currentDate"
          :available-dates="availableDates"
          @update:model-value="onDateChange"
        />
      </div>
    </div>

    <!-- 静默期专用空状态 (Embargo Empty State) -->
    <div
      v-if="!loading && isEmbargoed"
      class="stagger-enter flex flex-col items-center justify-center flex-1 min-h-0 py-20 text-center"
      style="animation-delay: 0.4s"
    >
      <div class="relative mb-6">
        <!-- 外层光晕 -->
        <div class="absolute inset-0 w-24 h-24 rounded-full bg-gradient-to-br from-amber-100 to-orange-50 blur-xl opacity-60" />
        <!-- 图标容器 -->
        <div class="relative w-24 h-24 rounded-2xl bg-gradient-to-br from-amber-50 to-orange-50 border border-amber-200/60 flex items-center justify-center shadow-sm">
          <svg class="w-12 h-12 text-amber-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
            <line x1="16" y1="2" x2="16" y2="6"/>
            <line x1="8" y1="2" x2="8" y2="6"/>
            <line x1="3" y1="10" x2="21" y2="10"/>
            <circle cx="12" cy="16" r="1.5" fill="currentColor" stroke="none"/>
            <line x1="12" y1="12.5" x2="12" y2="14"/>
          </svg>
        </div>
      </div>
      <h3 class="text-xl font-semibold text-stone-700 font-serif tracking-tight">昨日榜单数据整理中</h3>
      <p class="mt-2 text-sm text-stone-400 leading-relaxed max-w-xs">
        最终排位将于今日 <span class="font-semibold text-amber-600">15:00</span>
        <span class="text-stone-300">(UTC+8)</span> 准时发布，敬请期待
      </p>
      <div class="mt-5 flex items-center gap-1.5 text-xs text-stone-300">
        <span class="inline-block w-1.5 h-1.5 rounded-full bg-amber-300 animate-pulse" />
        数据归档进行中…
      </div>
    </div>

    <!-- 全局空状态（非静默期） -->
    <div
      v-else-if="!loading && !hasData && !tabLoading && !isEmbargoed"
      class="stagger-enter flex flex-col items-center justify-center flex-1 min-h-0 py-24 text-center"
      style="animation-delay: 0.5s"
    >
      <div class="w-16 h-16 mb-4 rounded-full flex items-center justify-center bg-stone-100">
        <svg class="w-8 h-8 text-stone-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/>
          <line x1="16" y1="2" x2="16" y2="6"/>
          <line x1="8" y1="2" x2="8" y2="6"/>
          <line x1="3" y1="10" x2="21" y2="10"/>
          <line x1="9" y1="16" x2="15" y2="16"/>
        </svg>
      </div>
      <h3 class="text-lg font-medium text-stone-500 font-serif">该日期暂无数据</h3>
      <p class="mt-1 text-sm text-stone-400">请尝试在日历中选择其他日期</p>
    </div>

    <!-- 榜单面板（静默期时隐藏） -->
    <div v-if="!loading && hasData && !isEmbargoed" class="stagger-enter glass-card flex-1 min-h-0 flex flex-col overflow-hidden" style="animation-delay: 0.6s">

      <!-- 面板头部：Tab + 周期 -->
      <div class="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5"
        style="border-bottom: 1px solid rgba(168,162,158,0.15)"
      >
        <div class="flex flex-wrap gap-1" role="tablist" aria-label="排行榜来源">
          <button
            v-for="tab in TABS"
            :key="tab.key"
            class="flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium transition-all duration-200"
            :class="activeTab === tab.key ? 'tab-active' : 'tab-inactive'"
            role="tab"
            :aria-selected="activeTab === tab.key"
            @click="selectSourceTab(tab.key)"
          >
            <component :is="tab.icon" class="h-3.5 w-3.5" />
            {{ tab.label }}
          </button>
        </div>

        <div class="flex items-center gap-1">
          <button
            v-for="period in PERIODS"
            :key="period.key"
            class="rounded-full px-3 py-1 text-xs font-medium transition-all duration-200"
            :class="[
              isPeriodDisabled(period.key)
                ? 'cursor-not-allowed opacity-30 text-stone-400'
                : activePeriod === period.key
                  ? 'tab-active font-semibold'
                  : 'tab-inactive'
            ]"
            :disabled="isPeriodDisabled(period.key)"
            @click="!isPeriodDisabled(period.key) && (activePeriod = period.key)"
          >
            {{ period.label }}
          </button>
          <span v-if="DAILY_ONLY_TABS.has(activeTab)" class="ml-1 text-2xs text-stone-400">
            仅日榜
          </span>
        </div>
      </div>

      <!-- 定榜状态横幅 (Editorial Status Banner) -->
      <div
        v-if="!isFinalized && !isEmbargoed && !tabLoading"
        class="flex items-center gap-2 px-4 py-1.5 text-xs bg-amber-50/50"
        style="border-bottom: 1px solid rgba(217,119,6,0.1)"
      >
        <Zap class="h-3.5 w-3.5 animate-pulse text-amber-500" />
        <span class="text-stone-600">实时动态初榜 · 正在采集中</span>
      </div>
      <div
        v-else-if="isFinalized && !tabLoading"
        class="flex items-center gap-2 px-4 py-1.5 text-xs bg-emerald-50/30"
        style="border-bottom: 1px solid rgba(16,185,129,0.08)"
      >
        <CheckCircle2 class="h-3.5 w-3.5 text-emerald-500" />
        <span class="text-stone-400">数据已定榜 · 历史排位已永久归档</span>
      </div>

      <!-- 列表内容 -->
      <div class="flex-1 overflow-y-auto">
        <div v-if="tabLoading" class="flex items-center justify-center py-8">
          <span class="inline-block h-5 w-5 rounded-full border-2 border-stone-200 border-t-stone-500 animate-spin" />
        </div>

        <div v-else-if="!tabList.length" class="flex flex-col items-center justify-center py-12 text-stone-400">
          <div class="w-12 h-12 mb-3 rounded-full bg-stone-100 flex items-center justify-center">
            <svg class="h-6 w-6 text-stone-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"/>
              <polyline points="12 6 12 12 16 14"/>
            </svg>
          </div>
          <p v-if="!isViewingHistory" class="text-sm font-medium text-stone-500">实时数据采集中，请稍候</p>
          <p v-if="!isViewingHistory" class="mt-1 text-2xs text-stone-400">当前周期数据将在爬虫完成后自动上榜</p>
          <p v-else class="text-sm font-medium text-stone-500">该日期此周期暂无榜单数据</p>
          <p v-if="isViewingHistory" class="mt-1 text-2xs text-stone-400">可能是当天未采集该周期，或数据尚未归档</p>
        </div>

        <!-- 列表（暖色交替背景） -->
        <ol v-else>
          <li
            v-for="(doc, idx) in tabList"
            :key="idx"
            class="group transition-colors duration-150"
            :class="idx % 2 === 0 ? '' : 'bg-stone-50/50'"
            style="border: none"
          >
            <a
              :href="doc.url || undefined"
              :target="doc.url ? '_blank' : undefined"
              :rel="doc.url ? 'noopener noreferrer' : undefined"
              class="flex items-start gap-2.5 px-4 py-2.5"
              :class="doc.url ? 'hover:bg-stone-50 cursor-pointer' : 'pointer-events-none'"
            >
              <!-- 序号 -->
              <span
                class="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-2xs font-bold"
                :class="idx < 3 ? 'bg-stone-700 text-white' : 'bg-stone-100 text-stone-400'"
              >
                {{ idx + 1 }}
              </span>

              <!-- 内容 -->
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-start gap-2">
                  <p
                    class="min-w-0 flex-1 text-sm font-medium text-stone-700 leading-tight group-hover:text-stone-900 line-clamp-2 sm:line-clamp-1"
                    :class="doc.url ? 'group-hover:underline underline-offset-2' : ''"
                  >
                    {{ doc.title || '(无标题)' }}
                  </p>

                  <div class="flex shrink-0 items-center gap-1.5 ml-2">
                    <span
                      v-if="doc.ai_score !== undefined && doc.ai_score !== null"
                      class="badge bg-white text-stone-600 border border-stone-200"
                      :title="doc.ai_reason || 'AI 评分'"
                    >
                      {{ aiScoreDisplay(doc.ai_score) }}
                    </span>
                    <span class="badge border" :class="getSourceConfig(doc.source).badge">
                      <span class="status-dot shrink-0" :class="getSourceConfig(doc.source).dot" />
                      {{ getSourceConfig(doc.source).label }}
                    </span>
                  </div>
                </div>

                <div class="mt-0.5 flex flex-wrap items-center gap-1.5">
                  <span class="flex items-center gap-0.5 text-2xs text-stone-500 font-medium">
                    <component :is="scoreDisplay(doc).icon" class="h-3 w-3 shrink-0" />
                    {{ scoreDisplay(doc).text }}
                  </span>

                  <span v-if="doc.language" class="badge bg-white text-stone-500 border border-stone-200">
                    {{ doc.language }}
                  </span>

                  <!-- 日期已隐藏：榜单项不再显示日期 -->

                  <span
                    v-for="tag in getModuleTags(doc)"
                    :key="tag"
                    class="badge bg-white text-stone-500 border border-stone-200"
                  >
                    {{ tag }}
                  </span>
                </div>
              </div>

              <!-- 外链图标（所有来源统一） -->
              <svg
                v-if="doc.url"
                class="mt-1 h-3.5 w-3.5 shrink-0 text-stone-300 opacity-0 group-hover:opacity-100 transition-opacity"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
              >
                <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/>
                <polyline points="15 3 21 3 21 9"/>
                <line x1="10" y1="14" x2="21" y2="3"/>
              </svg>
            </a>
          </li>
        </ol>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dashboard-page {
  --paper: #f3f0e6;
  --paper-light: #fffdf5;
  --ink: #11110f;
  --muted: #68655d;
  --acid: #c7f432;
  --acid-soft: #f1f8d2;
  color: var(--ink);
  background-color: var(--paper);
  background-image: linear-gradient(rgba(17, 17, 15, .035) 1px, transparent 1px);
  background-size: 100% 32px;
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}

.dashboard-page :deep(.font-serif) { font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
.dashboard-page :deep(h1),
.dashboard-page :deep(h2),
.dashboard-page :deep(h3) { color: var(--ink); font-weight: 850; letter-spacing: -.04em; }
.dashboard-page :deep(.glass-card) {
  border: 1px solid var(--ink);
  border-radius: 5px;
  background: var(--paper-light);
  box-shadow: 3px 3px 0 var(--ink);
  backdrop-filter: none;
}
.dashboard-page :deep(.card-hover:hover) { border-color: var(--ink); background: var(--acid-soft); box-shadow: 3px 3px 0 var(--ink); transform: none; }
.dashboard-page :deep(.text-stone-300),
.dashboard-page :deep(.text-stone-400) { color: var(--muted); }
.dashboard-page :deep(.rounded-full),
.dashboard-page :deep(.rounded-xl),
.dashboard-page :deep(.rounded-2xl) { border-radius: 4px; }

.dashboard-page :deep(.bg-slate-800) { border: 1px solid var(--ink); color: var(--ink); background: var(--acid); box-shadow: 3px 3px 0 var(--ink); }
.dashboard-page :deep(.bg-slate-800:hover) { color: var(--ink); background: var(--acid); }
.dashboard-page :deep(.bg-slate-800 .text-white),
.dashboard-page :deep(.bg-slate-800 .text-slate-300) { color: inherit; }
.dashboard-page :deep(.dashboard-source-card--active) {
  border-color: var(--ink);
  background: var(--acid);
  box-shadow: inset 0 -3px 0 var(--ink), 3px 3px 0 var(--ink);
}
.dashboard-page :deep(.dashboard-source-card--active .text-blue-600),
.dashboard-page :deep(.dashboard-source-card--active .text-gray-800),
.dashboard-page :deep(.dashboard-source-card--active .text-amber-600),
.dashboard-page :deep(.dashboard-source-card--active .text-rose-600),
.dashboard-page :deep(.dashboard-source-card--active .text-orange-500) { color: var(--ink) !important; }

.dashboard-page :deep(.tab-active) { border: 1px solid var(--ink); border-radius: 4px; color: var(--ink); background: var(--acid); box-shadow: none; }
.dashboard-page :deep(.tab-inactive) { border: 1px solid transparent; border-radius: 4px; color: var(--ink); }
.dashboard-page :deep(.tab-inactive:hover) { border-color: var(--ink); color: var(--ink); background: var(--acid-soft); }

.dashboard-page ol > li { border-top: 1px solid var(--ink) !important; background: transparent; }
.dashboard-page ol > li:first-child { border-top: 0 !important; }
.dashboard-page ol > li a:hover { color: var(--ink); background: var(--acid-soft); }
.dashboard-page ol > li a:hover :deep(.text-stone-700),
.dashboard-page ol > li a:hover :deep(.text-stone-500),
.dashboard-page ol > li a:hover :deep(.text-stone-300) { color: inherit; }
.dashboard-page :deep(.badge) { border-color: var(--ink); border-radius: 3px; background: var(--paper-light); }

.dashboard-page :deep(.bg-gradient-to-br) { background-image: none; background-color: var(--acid); }
.dashboard-page :deep(.blur-xl) { filter: none; }

@media (prefers-reduced-motion: reduce) {
  .dashboard-page *, .dashboard-page *::before, .dashboard-page *::after { transition-duration: .01ms !important; animation-duration: .01ms !important; }
}
</style>
