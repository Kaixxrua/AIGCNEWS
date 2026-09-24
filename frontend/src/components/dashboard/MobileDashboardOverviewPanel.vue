<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import RollingNumber from './RollingNumber.vue'
import { LibraryBig, Github, FilePlus, Blocks } from 'lucide-vue-next'
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
        <span v-else-if="uiCount === null" class="stat-cell-num">—</span>
        <RollingNumber v-else :value="uiCount" grouping class="stat-cell-num" />
      </span>
    </RouterLink>
  </div>
</template>

<style scoped>
.stat-strip { container-type: inline-size; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; min-width: 0; }
.stat-cell { display: flex; align-items: center; gap: 9px; padding: 12px 10px; min-height: 78px; min-width: 0; border: 1px solid var(--rule); border-radius: 11px; background: var(--paper-light); text-align: left; color: var(--ink); }
.stat-cell-icon { flex: 0 0 30px; width: 30px; height: 30px; padding: 7px; border-radius: 50%; background: var(--paper); }
.stat-cell-icon :deep(svg) { width: 100%; height: 100%; }
.stat-cell--github .stat-cell-icon, .stat-cell--ui .stat-cell-icon { background: var(--acid-soft); }
.stat-cell--new .stat-cell-icon { color: var(--tone-mint); }
.stat-cell-icon--ui { display: grid; grid-template-columns: 1fr 1fr; gap: 2px; }
.stat-cell-icon--ui span { border: 1px solid currentColor; border-radius: 1px; }
.stat-cell-body { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.stat-cell-label { font-size: 12px; color: var(--ink); line-height: 1.3; white-space: normal; overflow-wrap: anywhere; }
.stat-cell-num { font-size: clamp(16px, 2.3cqw, 23px); font-weight: 800; line-height: 1.2; letter-spacing: -.04em; font-variant-numeric: tabular-nums; }
.stat-cell--github:hover, .stat-cell--ui:hover { border-color: var(--muted); background: var(--acid-soft); }
.stat-cell--github:focus-visible, .stat-cell--ui:focus-visible { outline: 2px solid var(--ink); outline-offset: 3px; }
.stat-cell-num--loading { width: 35px; height: 20px; border-radius: 4px; background: var(--rule); }
@media (min-width: 1200px) and (max-width: 1499px) { .stat-cell { gap: 5px; padding: 12px 7px; } .stat-cell-icon { flex-basis: 24px; width: 24px; height: 24px; padding: 5px; } .stat-cell-label { font-size: 10px; } }
@media (max-width: 639px) { .stat-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); } .stat-cell { padding: 12px 8px; } .stat-cell-icon { display: none; } }
@container (max-width: 900px) { .stat-cell-icon { display: none; } }
/* Semantic colors remain visible even when compact layouts omit icons. */
.stat-cell--total { background: #19251d; color: #f5f8ef; }
.stat-cell--total .stat-cell-label { color: #dbe7d6; }
.stat-cell--github .stat-cell-num { color: #437319; }
.stat-cell--new .stat-cell-num { color: #087b69; }
.stat-cell--ui .stat-cell-num { color: #bd601e; }

.stat-cell-icon { width: 40px; height: 40px; flex-basis: 40px; padding: 7px; border-radius: 8px; }
.stat-cell--total .stat-cell-icon { color: #e0ff88; background: #354731; }
.stat-cell--github .stat-cell-icon { color: #305916; background: #e5f2cd; }
.stat-cell--new .stat-cell-icon { color: #006c5c; background: #d8f1e8; }
.stat-cell--ui .stat-cell-icon { color: #a64b10; background: #ffead5; }

</style>
