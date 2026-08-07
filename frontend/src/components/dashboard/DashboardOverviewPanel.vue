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
  userParts: { registered: number; today: number }
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
      <span v-if="card.key === 'user_count'" class="stat-cell-num" :class="card.numColor"><RollingNumber :value="userParts.registered" /><span>+</span><RollingNumber :value="userParts.today" /></span>
      <RollingNumber v-else :value="visitorValues[index] ?? 0" grouping class="stat-cell-num" :class="card.numColor" />
    </div>
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
  font-size: 10px;
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
</style>
