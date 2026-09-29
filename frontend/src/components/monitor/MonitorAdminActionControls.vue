<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import { AlertTriangle, RefreshCcwDot, Repeat } from 'lucide-vue-next'

defineProps<{
  syncing: boolean
  taskRunning: boolean
  generatingBriefing: boolean
  clearingCache: boolean
  clearing: boolean
  showClearConfirm: boolean
}>()

const emit = defineEmits<{
  sync: [force: boolean]
  generateBriefings: [forceRegenerate: boolean]
  clearDashboardCache: []
  clearAllData: []
  'update:showClearConfirm': [visible: boolean]
}>()
</script>

<template>
  <button class="monitor-btn-primary" :disabled="syncing || taskRunning" @click="emit('sync', false)">
    <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
    {{ t(syncing ? 'monitor.syncing' : taskRunning ? 'monitor.taskRunning' : 'monitor.sync') }}
  </button>
  <button class="monitor-btn-secondary" :disabled="syncing || taskRunning" @click="emit('sync', true)">
    <Repeat class="h-3.5 w-3.5" />
    {{ t('monitor.forceSync') }}
  </button>
  <button class="monitor-btn-secondary" :disabled="generatingBriefing" @click="emit('generateBriefings', true)">
    <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
    {{ t(generatingBriefing ? 'monitor.generating' : 'monitor.generateDaily') }}
  </button>
  <button class="monitor-btn-secondary" :disabled="clearingCache" :title="t('monitor.cacheTitle')" @click="emit('clearDashboardCache')">
    <RefreshCcwDot class="h-3.5 w-3.5" />
    {{ t(clearingCache ? 'monitor.clearing' : 'monitor.refreshCache') }}
  </button>
  <button class="monitor-btn-danger" :disabled="clearing" @click="emit('update:showClearConfirm', true)">
    <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
    {{ t(clearing ? 'monitor.clearing' : 'monitor.clearData') }}
  </button>

  <Transition name="modal">
    <div v-if="showClearConfirm" class="monitor-modal-backdrop fixed inset-0 z-50 flex items-center justify-center" @click.self="emit('update:showClearConfirm', false)">
      <div class="monitor-modal w-full max-w-sm p-6 animate-slide-up">
        <div class="mb-4 flex items-center gap-3">
          <div class="monitor-avatar monitor-avatar-accent flex h-10 w-10 items-center justify-center">
            <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
          </div>
          <h3 class="text-base font-semibold monitor-title">{{ t('monitor.clearConfirmTitle') }}</h3>
        </div>
        <div class="mb-4 space-y-1.5 text-sm monitor-caption">
          <p>{{ t('monitor.clearDeletes') }}</p>
          <ul class="ml-2 space-y-1">
            <li>{{ t('monitor.clearSqlite') }}</li>
            <li>{{ t('monitor.clearMilvus') }}</li>
          </ul>
        </div>
        <p class="monitor-warning-box mb-5 flex items-center gap-1.5 px-3 py-2 text-xs font-medium">
          <AlertTriangle class="h-3.5 w-3.5 shrink-0" />
          {{ t('monitor.irreversible') }}
        </p>
        <div class="flex gap-2">
          <button class="monitor-btn-secondary flex-1" @click="emit('update:showClearConfirm', false)">{{ t('common.cancel') }}</button>
          <button class="monitor-btn-danger flex-1" @click="emit('clearAllData')">{{ t('monitor.confirmClear') }}</button>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.animate-slide-up {
  animation: slideUp 0.2s ease-out both;
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .animate-slide-up {
    animation: none;
  }
}
</style>
