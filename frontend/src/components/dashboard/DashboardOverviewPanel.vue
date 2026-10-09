<script setup lang="ts">
import { computed, ref, useId } from 'vue'
import { useI18n } from 'vue-i18n'
import RollingNumber from './RollingNumber.vue'
import { LibraryBig, Github, FilePlus, CircleUserRound, UsersRound, Blocks } from 'lucide-vue-next'
import type { TabKey } from '@/features/dashboard/dashboardViewModel'

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
const expanded = ref(false)
const overviewId = useId()
const metrics = computed(() => [
  { key: 'total', label: 'dashboard.editorial.total', value: props.statValues[0], icon: LibraryBig },
  { key: 'github', label: 'dashboard.editorial.github', value: props.statValues[1], icon: Github },
  { key: 'new', label: 'dashboard.stats.newDocuments', value: props.visitorValues[2], icon: FilePlus },
  { key: 'visitors', label: 'dashboard.stats.todayVisitors', value: props.visitorValues[0], icon: CircleUserRound },
  { key: 'total-visitors', label: 'dashboard.stats.totalVisitors', value: props.visitorValues[1], icon: UsersRound },
])
</script>

<template>
  <div :id="overviewId" class="stat-strip" :data-expanded="expanded" :aria-busy="loading">
    <component :is="card.key === 'github' ? 'button' : 'div'" v-for="card in metrics" :key="card.key"
      class="stat-cell" :class="`stat-cell--${card.key}`"
      :type="card.key === 'github' ? 'button' : undefined"
      :aria-pressed="card.key === 'github' ? activeTab === 'github' : undefined"
      @click="card.key === 'github' && emit('selectSource', 'github')">
      <svg class="stat-ink-frame" viewBox="0 0 160 94" preserveAspectRatio="none" aria-hidden="true"><path d="M6 1.5 154 2 Q159 2 158.5 8 L158 87 Q158.5 92 153 92 L7 91.5 Q1.5 92 2 86 L1.5 8 Q1 2 6 1.5Z" /></svg>
      <span class="stat-cell-icon" aria-hidden="true"><component :is="card.icon" :stroke-width="2.5" /></span>
      <span class="stat-cell-body"><span class="stat-cell-label">{{ t(card.label) }}</span>
        <span v-if="loading" class="stat-cell-num stat-cell-num--loading" aria-hidden="true" />
        <RollingNumber v-else :value="card.value ?? 0" grouping class="stat-cell-num" />
      </span>
    </component>
    <RouterLink :to="{ name: 'ui-library' }" class="stat-cell stat-cell--ui" :aria-label="t('dashboard.editorial.uiTotal')" :aria-busy="loading || uiLoading">
      <svg class="stat-ink-frame" viewBox="0 0 160 94" preserveAspectRatio="none" aria-hidden="true"><path d="M6 1.5 154 2 Q159 2 158.5 8 L158 87 Q158.5 92 153 92 L7 91.5 Q1.5 92 2 86 L1.5 8 Q1 2 6 1.5Z" /></svg>
      <span class="stat-cell-icon" aria-hidden="true"><Blocks :stroke-width="2.5" /></span>
      <span class="stat-cell-body"><span class="stat-cell-label">{{ t('dashboard.editorial.uiTotal') }}</span>
        <span v-if="loading || uiLoading" class="stat-cell-num stat-cell-num--loading" aria-hidden="true" />
        <span v-else-if="uiCount === null" class="stat-cell-num">—</span>
        <RollingNumber v-else :value="uiCount" grouping class="stat-cell-num" />
      </span>
    </RouterLink>
    <button type="button" class="stat-expand" :aria-expanded="expanded" :aria-controls="overviewId" @click="expanded = !expanded">
      {{ t(expanded ? 'dashboard.collapseOverview' : 'dashboard.dataOverview') }}
      <span aria-hidden="true">{{ expanded ? '−' : '+' }}</span>
    </button>
  </div>
</template>

<style scoped>

.stat-strip { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:10px; min-width:0; }
.stat-expand { display:none; }
.stat-cell { --metric:var(--comic-cyan-line); --metric-ink:var(--metric-total-ink); container-type:inline-size; position:relative;isolation:isolate;display:flex; align-items:center; gap:8px; min-width:0; min-height:94px; padding:12px 13px; border:2px solid transparent; border-radius:5px 8px 4px 6px; background:linear-gradient(130deg,var(--paper-raised),color-mix(in srgb,var(--metric) 5%,var(--paper-raised))); color:var(--ink); text-align:left; }
.stat-ink-frame { position:absolute;inset:-2px;width:calc(100% + 4px);height:calc(100% + 4px);fill:none;stroke:var(--rule-strong);stroke-width:1.5;pointer-events:none; }
.stat-ink-frame path { vector-effect:non-scaling-stroke; }
.stat-cell:nth-child(even) .stat-ink-frame { transform:scaleX(-1); }
.stat-cell-icon { display:grid; place-items:center; flex:0 0 42px; width:42px; height:48px; padding:8px; border-radius:45%; background:color-mix(in srgb,var(--metric) 30%,var(--paper-raised)); color:var(--ink); }
.stat-cell-icon :deep(svg) { width:100%; height:100%; }
.stat-cell-body { display:flex; flex-direction:column; gap:4px; min-width:0; }
.stat-cell-label { font-size:12px; line-height:1.35; white-space:nowrap; }
.stat-cell-num { color:var(--metric-ink); font-size:clamp(18px,1.3vw,23px); font-weight:850; line-height:1.15; letter-spacing:-.04em; font-variant-numeric:tabular-nums; }
.stat-cell--github { --metric:var(--metric-github); --metric-ink:var(--metric-github-ink); }
.stat-cell--new { --metric:var(--metric-new); --metric-ink:var(--metric-new-ink); }
.stat-cell--total-visitors { --metric:var(--metric-new); --metric-ink:var(--metric-total-visitors-ink); }
.stat-cell--visitors { --metric:var(--metric-visitors); --metric-ink:var(--metric-visitors-ink); }
.stat-cell--ui { --metric:var(--metric-ui); --metric-ink:var(--metric-ui-ink); }
.stat-cell--ui .stat-cell-icon { color:var(--metric-ui-ink); }
.stat-cell--visitors .stat-cell-icon { color:var(--metric-visitors-ink); }
.stat-cell--total-visitors .stat-cell-icon { color:var(--metric-total-visitors-ink); }
.stat-cell--github:hover,.stat-cell--ui:hover { background:color-mix(in srgb,var(--metric) 16%,var(--paper-raised)); }
.stat-cell--github:focus-visible,.stat-cell--ui:focus-visible { outline:2px solid var(--ink); outline-offset:3px; }
.stat-cell-num--loading { width:35px; height:23px; border-radius:4px; background:var(--rule); }
:root[data-theme='dark'] .stat-ink-frame { stroke:var(--rule);stroke-width:1; }
:root[data-theme='dark'] .stat-cell-icon { background:color-mix(in srgb,var(--metric) 22%,var(--paper-raised)); color:var(--metric); }
@media (max-width:1450px) { .stat-cell { padding:9px 6px; gap:6px; }.stat-cell-icon { width:36px; height:42px; flex-basis:36px; padding:6px; }.stat-cell-label { font-size:10px; } }
@media (max-width:1199px) { .stat-strip { grid-template-columns:repeat(3,minmax(0,1fr)); }.stat-cell { min-height:76px; }.stat-cell-icon { width:42px;flex-basis:42px; } }
@media (max-width:639px) { .stat-strip { grid-template-columns:repeat(3,minmax(0,1fr)); }.stat-cell { min-height:74px; }.stat-cell-icon { width:32px;flex-basis:32px; }.stat-cell-num { font-size:20px; } }
/* Narrow cells give the label and count the full width; the icon becomes a corner badge. */
@container (max-width:150px) { .stat-cell-icon { position:absolute;right:7px;bottom:8px;width:24px;height:24px;padding:4px;border-radius:50%; } }
@container (max-width:103px) { .stat-cell-icon { display:none; } }

@media (max-width:1023px) {
  .stat-strip { gap:6px;grid-auto-rows:auto; }
  .stat-strip:not([data-expanded="true"]) :is(.stat-cell--total,.stat-cell--visitors,.stat-cell--total-visitors) { display:none; }
  .stat-cell { display:grid;grid-template-columns:minmax(0,1fr) 22px;grid-template-rows:minmax(0,1fr) auto;gap:3px;height:64px;min-height:64px;padding:8px; }
  .stat-cell--github { order:0; }
  .stat-cell--new { order:1; }
  .stat-cell--ui { order:2; }
  .stat-cell--total { order:3; }
  .stat-cell--visitors { order:4; }
  .stat-cell--total-visitors { order:5; }
  .stat-cell-body { display:contents; }
  .stat-cell-label { grid-column:1 / -1;grid-row:1;align-self:center;font-size:11px;white-space:normal;word-break:keep-all; }
  .stat-cell-num { grid-column:1 / -1;grid-row:2;font-size:21px; }
  .stat-cell-icon { display:none; }
  .stat-expand { order:6;grid-column:1 / -1;display:flex;align-items:center;justify-content:space-between;min-height:44px;padding:0 6px;border:0;background:transparent;color:var(--ink-muted);font-size:12px;text-align:left; }
  .stat-expand:focus-visible { outline:2px solid var(--ink);outline-offset:2px; }
}
@media (max-width:359px) {
  .stat-cell-label { font-size:10px; }
  .stat-cell-num { font-size:19px; }
}
</style>
