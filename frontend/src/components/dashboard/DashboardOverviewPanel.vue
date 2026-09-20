<script setup lang="ts">
import { computed } from 'vue'
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
const metrics = computed(() => [
  { key: 'total', label: 'dashboard.editorial.total', value: props.statValues[0], icon: LibraryBig },
  { key: 'github', label: 'dashboard.editorial.github', value: props.statValues[1], icon: Github },
  { key: 'new', label: 'dashboard.stats.newDocuments', value: props.visitorValues[2], icon: FilePlus },
  { key: 'visitors', label: 'dashboard.stats.todayVisitors', value: props.visitorValues[0], icon: CircleUserRound },
  { key: 'total-visitors', label: 'dashboard.stats.totalVisitors', value: props.visitorValues[1], icon: UsersRound },
])
</script>

<template>
  <div class="stat-strip" :aria-busy="loading">
    <component :is="card.key === 'github' ? 'button' : 'div'" v-for="card in metrics" :key="card.key"
      class="stat-cell" :class="`stat-cell--${card.key}`"
      :type="card.key === 'github' ? 'button' : undefined"
      :aria-pressed="card.key === 'github' ? activeTab === 'github' : undefined"
      @click="card.key === 'github' && emit('selectSource', 'github')">
      <span class="stat-cell-icon" aria-hidden="true"><component :is="card.icon" :stroke-width="2.5" /></span>
      <span class="stat-cell-body"><span class="stat-cell-label">{{ t(card.label) }}</span>
        <RollingNumber :value="card.value ?? 0" grouping class="stat-cell-num" />
      </span>
    </component>
    <RouterLink :to="{ name: 'ui-library' }" class="stat-cell stat-cell--ui" :aria-label="t('dashboard.editorial.uiTotal')" :aria-busy="uiLoading">
      <span class="stat-cell-icon" aria-hidden="true"><Blocks :stroke-width="2.5" /></span>
      <span class="stat-cell-body"><span class="stat-cell-label">{{ t('dashboard.editorial.uiTotal') }}</span>
        <span v-if="uiLoading" class="stat-cell-num stat-cell-num--loading" aria-hidden="true" />
        <span v-else class="stat-cell-num">{{ uiCount === null ? '—' : uiCount.toLocaleString() }}</span>
      </span>
    </RouterLink>
  </div>
</template>

<style scoped>

.stat-strip { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:7px; min-width:0; }
.stat-cell { --metric:#b7ef44; display:flex; align-items:center; gap:10px; min-width:0; min-height:94px; padding:12px 10px; border:2px solid var(--rule-strong);border-bottom-width:2.5px;border-left-width:2.3px; border-radius:5px 8px 4px 6px; box-shadow:inset -2px -2px 0 color-mix(in srgb,var(--metric) 20%,transparent); background:linear-gradient(130deg,var(--paper-raised),color-mix(in srgb,var(--metric) 5%,var(--paper-raised))); color:var(--ink); text-align:left; }
.stat-cell-icon { display:grid; place-items:center; flex:0 0 49px; width:49px; height:53px; padding:9px; border-radius:45%; background:color-mix(in srgb,var(--metric) 30%,var(--paper-raised)); color:var(--ink); }
.stat-cell-icon :deep(svg) { width:100%; height:100%; }
.stat-cell-body { display:flex; flex-direction:column; gap:4px; min-width:0; }
.stat-cell-label { font-size:12px; line-height:1.35; white-space:nowrap; }
.stat-cell-num { font-size:clamp(18px,1.45vw,25px); font-weight:850; line-height:1.15; letter-spacing:-.04em; font-variant-numeric:tabular-nums; }
.stat-cell--github { --metric:#67ef85; }
.stat-cell--new,.stat-cell--total-visitors { --metric:#6bd4ff; }
.stat-cell--visitors { --metric:#b0a0ff; }
.stat-cell--ui { --metric:#ffd591; }
.stat-cell--ui .stat-cell-icon,.stat-cell--ui .stat-cell-num { color:#ef531c; }
.stat-cell--visitors .stat-cell-icon { color:#693de8; }
.stat-cell--total-visitors .stat-cell-icon { color:#1677e9; }
.stat-cell--github:hover,.stat-cell--ui:hover { border-color:var(--acid); }
.stat-cell--github:focus-visible,.stat-cell--ui:focus-visible { outline:2px solid var(--ink); outline-offset:3px; }
.stat-cell-num--loading { width:35px; height:23px; border-radius:4px; background:var(--rule); }
:root[data-theme='dark'] .stat-cell { border-color:var(--rule);border-width:1px; }
:root[data-theme='dark'] .stat-cell-icon { background:color-mix(in srgb,var(--metric) 22%,var(--paper-raised)); color:var(--metric); }
@media (max-width:1450px) { .stat-cell { padding:9px 6px; gap:6px; }.stat-cell-icon { width:36px; height:42px; flex-basis:36px; padding:6px; }.stat-cell-label { font-size:10px; } }
@media (max-width:1199px) { .stat-strip { grid-template-columns:repeat(3,minmax(0,1fr)); }.stat-cell { min-height:76px; }.stat-cell-icon { width:42px;flex-basis:42px; } }
@media (max-width:639px) { .stat-strip { grid-template-columns:repeat(3,minmax(0,1fr)); }.stat-cell { min-height:74px; }.stat-cell-icon { width:32px;flex-basis:32px; }.stat-cell-num { font-size:20px; } }

</style>
