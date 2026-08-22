<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { Crown, Users } from 'lucide-vue-next'
import SpinnerLoader from '@/components/SpinnerLoader.vue'
import { useUserStatsController } from '@/composables/useUserStatsController'

const { t } = useI18n()

// 自包含面板：状态与请求都留在卡片内部，MonitorView 只需挂载，不占用页面控制器。
const { data, loading, errorMsg, load, dispose } = useUserStatsController({ translate: t })

// VIP 占比一位小数；零用户时展示 0.0 而不是 NaN
const memberShare = computed(() => {
  const stats = data.value
  if (!stats || stats.total_users <= 0) return '0.0'
  return ((stats.member_users / stats.total_users) * 100).toFixed(1)
})

onMounted(load)
onBeforeUnmount(dispose)
</script>

<template>
  <div class="user-stats-panel stagger-enter glass-card shrink-0 p-5" style="animation-delay: 0.2s">
    <div class="flex flex-wrap items-center gap-2">
      <Users class="h-4 w-4 monitor-caption" />
      <h3 class="monitor-section-title text-sm font-semibold">{{ t('monitor.userStats.title') }}</h3>
      <span v-if="data" class="monitor-badge tabular-nums">
        {{ t('monitor.userStats.memberShare', { share: memberShare }) }}
      </span>
    </div>
    <p class="monitor-caption mt-1.5 text-xs leading-5">{{ t('monitor.userStats.description') }}</p>

    <div v-if="errorMsg" class="mt-3 flex items-center justify-between rounded-md border px-4 py-2 text-xs monitor-status-error">
      <span>{{ errorMsg }}</span>
      <button class="ml-3 opacity-70 hover:opacity-100" @click="errorMsg = ''">✕</button>
    </div>

    <SpinnerLoader v-if="loading && !data" class="min-h-[120px]" />

    <template v-else-if="data">
      <hr class="monitor-divider mt-4 border-t" />
      <div class="user-stats-tiles mt-4">
        <div class="user-stat-tile">
          <Users class="h-4 w-4 user-stat-icon" />
          <span class="user-stat-value tabular-nums">{{ data.total_users }}</span>
          <span class="user-stat-label">{{ t('monitor.userStats.totalUsers') }}</span>
        </div>
        <div class="user-stat-tile">
          <Crown class="h-4 w-4 user-stat-icon user-stat-icon-vip" />
          <span class="user-stat-value tabular-nums">{{ data.member_users }}</span>
          <span class="user-stat-label">{{ t('monitor.userStats.memberUsers') }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* VIP 标记色取自 dataviz 验证过的分类槽位 4（黄），双模式各自取验证值 */
.user-stats-panel {
  --user-stats-vip: #eda100;
}

:root[data-theme='dark'] .user-stats-panel {
  --user-stats-vip: #c98500;
}

.user-stats-tiles {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.user-stat-tile {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  padding: 14px 16px;
  border: 1px solid var(--rule);
  border-radius: 10px;
}

.user-stat-icon {
  color: var(--ink-muted);
}

.user-stat-icon-vip {
  color: var(--user-stats-vip);
}

.user-stat-value {
  font-size: 26px;
  font-weight: 800;
  line-height: 1;
  color: var(--projects-accent);
}

.user-stat-label {
  font-size: 12px;
  color: var(--ink-muted);
}

@media (max-width: 560px) {
  .user-stats-tiles {
    grid-template-columns: 1fr;
  }
}
</style>
