<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import RollingNumber from './RollingNumber.vue'
import { statCards, visitorCards, type TabKey } from '@/features/dashboard/dashboardViewModel'

const props = defineProps<{
  loading: boolean
  activeTab: TabKey
  statValues: number[]
  visitorValues: number[]
  uiCount: number | null
  uiLoading: boolean
}>()
const { t } = useI18n()
const emit = defineEmits<{ selectSource: [key: TabKey] }>()
const metrics = computed(() => [
  { key: 'total', label: 'dashboard.editorial.total', value: props.statValues[0], icon: statCards[0]!.icon },
  { key: 'github', label: 'dashboard.editorial.github', value: props.statValues[1], icon: statCards[1]!.icon },
  { key: 'new', label: 'dashboard.stats.newDocuments', value: props.visitorValues[2], icon: visitorCards[2]!.icon },
  { key: 'visitors', label: 'dashboard.stats.todayVisitors', value: props.visitorValues[0], icon: visitorCards[0]!.icon },
  { key: 'total-visitors', label: 'dashboard.stats.totalVisitors', value: props.visitorValues[1], icon: visitorCards[1]!.icon },
])
</script>

<template>
  <div class="stat-strip" :aria-busy="loading">
    <component :is="card.key === 'github' ? 'button' : 'div'" v-for="card in metrics" :key="card.key"
      class="stat-cell" :class="`stat-cell--${card.key}`"
      :type="card.key === 'github' ? 'button' : undefined"
      :aria-pressed="card.key === 'github' ? activeTab === 'github' : undefined"
      @click="card.key === 'github' && emit('selectSource', 'github')">
      <span class="stat-cell-icon" aria-hidden="true" v-html="card.icon" />
      <span class="stat-cell-body"><span class="stat-cell-label">{{ t(card.label) }}</span>
        <RollingNumber :value="card.value ?? 0" grouping class="stat-cell-num" />
      </span>
    </component>
    <RouterLink :to="{ name: 'ui-library' }" class="stat-cell stat-cell--ui" :aria-label="t('dashboard.editorial.uiTotal')" :aria-busy="uiLoading">
      <span class="stat-cell-icon stat-cell-icon--ui" aria-hidden="true"><span /><span /><span /><span /></span>
      <span class="stat-cell-body"><span class="stat-cell-label">{{ t('dashboard.editorial.uiTotal') }}</span>
        <span v-if="uiLoading" class="stat-cell-num stat-cell-num--loading" aria-hidden="true" />
        <span v-else class="stat-cell-num">{{ uiCount === null ? '—' : uiCount.toLocaleString() }}</span>
      </span>
    </RouterLink>
  </div>
</template>

<style scoped>
.stat-strip { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 8px; min-width: 0; }
.stat-cell { display: flex; align-items: center; gap: 9px; padding: 12px 10px; height: 78px; min-width: 0; border: 1px solid var(--rule); border-radius: 11px; background: var(--paper-light); text-align: left; color: var(--ink); }
.stat-cell-icon { flex: 0 0 30px; width: 30px; height: 30px; padding: 7px; border-radius: 50%; background: var(--paper); }
.stat-cell-icon :deep(svg) { width: 100%; height: 100%; }
.stat-cell--github .stat-cell-icon, .stat-cell--ui .stat-cell-icon { background: var(--acid-soft); }
.stat-cell--new .stat-cell-icon { color: var(--tone-mint); }
.stat-cell--visitors .stat-cell-icon, .stat-cell--total-visitors .stat-cell-icon { color: var(--tone-violet); }
.stat-cell-icon--ui { display: grid; grid-template-columns: 1fr 1fr; gap: 2px; }
.stat-cell-icon--ui span { border: 1px solid currentColor; border-radius: 1px; }
.stat-cell-body { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.stat-cell-label { font-size: 12px; color: var(--ink); line-height: 1.3; white-space: nowrap; }
.stat-cell-num { font-size: clamp(17px, 1.4vw, 23px); font-weight: 800; line-height: 1.2; letter-spacing: -.04em; font-variant-numeric: tabular-nums; }
.stat-cell--github:hover, .stat-cell--ui:hover { border-color: var(--muted); background: var(--acid-soft); }
.stat-cell--github:focus-visible, .stat-cell--ui:focus-visible { outline: 2px solid var(--ink); outline-offset: 3px; }
.stat-cell-num--loading { width: 35px; height: 20px; border-radius: 4px; background: var(--rule); }
@media (min-width: 1200px) and (max-width: 1499px) { .stat-cell { gap: 5px; padding: 12px 7px; } .stat-cell-icon { flex-basis: 24px; width: 24px; height: 24px; padding: 5px; } .stat-cell-label { font-size: 10px; } }
@media (max-width: 639px) { .stat-strip { grid-template-columns: repeat(3, minmax(0, 1fr)); } .stat-cell { padding: 12px 8px; } .stat-cell-icon { display: none; } }
</style>
