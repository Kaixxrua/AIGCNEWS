<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import RollingNumber from '@/components/dashboard/RollingNumber.vue'
import {
  isSourceStatCard,
  statCards,
  visitorCards,
  type TabKey,
} from '@/features/dashboard/dashboardViewModel'

defineProps<{
  loading: boolean
  activeTab: TabKey
  statValues: number[]
  visitorValues: number[]
  todayUiCount: number
  todayUiCountLoading: boolean
}>()

const { t } = useI18n()

const emit = defineEmits<{
  selectSource: [key: TabKey]
}>()
</script>

<template>
  <!-- 统计带：单条分段条（lg+）/ 迷你卡片网格（<lg） -->
  <div v-if="loading" class="stat-strip shrink-0" aria-hidden="true">
    <div v-for="i in 9" :key="i" class="stat-cell animate-pulse" />
  </div>

  <div v-else class="stat-strip shrink-0">
    <template v-for="(card, index) in statCards" :key="card.key">
      <button
        v-if="isSourceStatCard(card.key)"
        type="button"
        class="stat-cell stat-cell--btn stagger-enter"
        :class="{ 'stat-cell--active': activeTab === card.key }"
        :style="{ animationDelay: (index * 0.05 + 0.05) + 's' }"
        :aria-pressed="activeTab === card.key"
        :aria-label="t('dashboard.sourceRanking', { source: t(`dashboard.stats.${card.labelKey}`) })"
        @click="emit('selectSource', card.key)"
      >
        <span class="stat-cell-head">
          <span class="stat-cell-icon" :class="card.iconColor"><span class="flex h-3 w-3 items-center justify-center" v-html="card.icon" /></span>
          <span class="stat-cell-label">{{ t(`dashboard.stats.${card.labelKey}`) }}</span>
        </span>
        <RollingNumber :value="statValues[index] ?? 0" class="stat-cell-num" :class="card.numColor" />
      </button>
      <div
        v-else
        class="stat-cell stat-cell--total stagger-enter"
        :style="{ animationDelay: (index * 0.05 + 0.05) + 's' }"
      >
        <span class="stat-cell-head">
          <span class="stat-cell-icon"><span class="flex h-3 w-3 items-center justify-center" v-html="card.icon" /></span>
          <span class="stat-cell-label">{{ t(`dashboard.stats.${card.labelKey}`) }}</span>
        </span>
        <RollingNumber :value="statValues[index] ?? 0" class="stat-cell-num" />
      </div>
    </template>
    <div
      v-for="(card, index) in visitorCards"
      :key="card.key"
      class="stat-cell stagger-enter"
      :style="{ animationDelay: (index * 0.05 + 0.45) + 's' }"
    >
      <span class="stat-cell-head">
        <span class="stat-cell-icon" :class="card.iconColor"><span class="flex h-3 w-3 items-center justify-center" v-html="card.icon" /></span>
        <span class="stat-cell-label">{{ t(`dashboard.stats.${card.labelKey}`) }}</span>
      </span>
      <RollingNumber :value="visitorValues[index] ?? 0" grouping class="stat-cell-num" :class="card.numColor" />
    </div>
    <RouterLink
      :to="{ name: 'ui-library', query: { rank: 'new' } }"
      class="stat-cell stat-cell--ui stagger-enter"
      :aria-label="t('dashboard.stats.todayUiMaterials')"
      style="animation-delay: 0.6s"
    >
      <span class="stat-cell-head">
        <span class="stat-cell-icon stat-cell-ui-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <path d="M8 3v18M8 9h13" />
          </svg>
        </span>
        <span class="stat-cell-label">{{ t('dashboard.stats.todayUiMaterials') }}</span>
      </span>
      <span v-if="todayUiCountLoading" class="stat-cell-num stat-cell-num--loading" aria-hidden="true" />
      <RollingNumber v-else :value="todayUiCount" grouping class="stat-cell-num stat-cell-ui-num" />
    </RouterLink>
  </div>
</template>

<style scoped>
/* 硬边统计带：小屏为迷你卡片网格，lg 起合并为单条分段条（变量由 .dashboard-page 提供） */
.stat-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
}

@media (min-width: 640px) {
  .stat-strip { grid-template-columns: repeat(5, minmax(0, 1fr)); }
}

@media (min-width: 1024px) {
  .stat-strip {
    display: flex;
    gap: 0;
    border: 1px solid var(--ink);
    border-radius: 5px;
    background: var(--paper-light);
    box-shadow: 3px 3px 0 var(--shadow-hard);
    overflow: hidden;
  }
}

.stat-cell {
  display: flex;
  min-width: 0;
  height: 48px;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
  padding: 0 10px;
  border: 1px solid var(--ink);
  border-radius: 4px;
  background: var(--paper-light);
  box-shadow: 2px 2px 0 var(--shadow-hard);
  text-align: left;
}

@media (min-width: 1024px) {
  .stat-cell {
    height: 48px;
    flex: 1 1 0;
    border: 0;
    border-radius: 0;
    background: transparent;
    box-shadow: none;
  }
  .stat-cell + .stat-cell { border-left: 1px solid var(--ink); }
}

.stat-cell--btn { cursor: pointer; transition: background-color 0.15s ease; }
.stat-cell--btn:hover { background: var(--acid-soft); }
.stat-cell--ui { color: var(--ink); cursor: pointer; text-decoration: none; transition: background-color 0.15s ease; }
.stat-cell--ui:hover { background: var(--acid-soft); }
.stat-cell-ui-icon,
.stat-cell-ui-num { color: var(--tone-mint); }
.stat-cell-num--loading { width: 28px; height: 15px; border-radius: 3px; background: var(--paper-muted, #e7e9e4); animation: stat-pulse 1.2s ease-in-out infinite; }
@keyframes stat-pulse { 50% { opacity: .45; } }

.stat-cell--active,
.stat-cell--active:hover { background: var(--acid); box-shadow: inset 0 -3px 0 var(--ink); }

@media (max-width: 1023.98px) {
  .stat-cell--active,
  .stat-cell--active:hover { box-shadow: 2px 2px 0 var(--shadow-hard), inset 0 -3px 0 var(--ink); }
}

.stat-cell--active .stat-cell-num,
.stat-cell--active .stat-cell-label,
.stat-cell--active .stat-cell-icon { color: var(--projects-on-acid); }

.stat-cell--total { background: var(--ink); }
.stat-cell--total .stat-cell-num { color: var(--paper); }
.stat-cell--total .stat-cell-label,
.stat-cell--total .stat-cell-icon { color: var(--paper); opacity: 0.6; }

.stat-cell-head {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 5px;
  line-height: 1;
}

.stat-cell-icon { display: flex; flex-shrink: 0; align-items: center; }

.stat-cell-label {
  overflow: hidden;
  color: var(--muted);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stat-cell-num {
  font-size: 17px;
  font-weight: 800;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
  line-height: 1.1;
}

@media (max-width: 767px) {
  .stat-strip { grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
  .stat-cell--btn { display: none; }
  .stat-strip[aria-hidden='true'] .stat-cell:nth-child(n + 5) { display: none; }
  .stat-cell-label { font-size: 11px; }
  .stat-cell-head { gap: 4px; }
  .stat-cell-icon { display: none; }
}
.stat-cell--btn:focus-visible,
.stat-cell--ui:focus-visible { outline: 2px solid var(--ink); outline-offset: -4px; }
.stat-cell--active:focus-visible { outline-color: var(--projects-on-acid); }
.stat-cell:not(.stat-cell--active) .text-amber-600 { color: var(--tone-amber); }
.stat-cell:not(.stat-cell--active) .text-orange-500 { color: var(--tone-orange); }
.stat-cell .text-teal-600 { color: var(--tone-mint); }
:root[data-theme='dark'] .stat-cell:not(.stat-cell--active) :is(.text-blue-500, .text-blue-600) { color: var(--tone-blue); }
:root[data-theme='dark'] .stat-cell:not(.stat-cell--active) :is(.text-amber-500, .text-amber-600) { color: var(--tone-amber); }
:root[data-theme='dark'] .stat-cell:not(.stat-cell--active) :is(.text-rose-500, .text-rose-600) { color: var(--tone-coral); }
:root[data-theme='dark'] .stat-cell:not(.stat-cell--active) .text-orange-500 { color: var(--tone-orange); }
:root[data-theme='dark'] .stat-cell :is(.text-purple-500, .text-purple-600, .text-indigo-500, .text-indigo-600) { color: var(--tone-violet); }
:root[data-theme='dark'] .stat-cell :is(.text-teal-500, .text-teal-600) { color: var(--tone-mint); }
</style>
