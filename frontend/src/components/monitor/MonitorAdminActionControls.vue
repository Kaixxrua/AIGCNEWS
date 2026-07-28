<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
import { AlertTriangle } from 'lucide-vue-next'

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
  <button class="btn-primary" :disabled="syncing || taskRunning" @click="emit('sync', false)">
    <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
    {{ t(syncing ? 'monitor.syncing' : taskRunning ? 'monitor.taskRunning' : 'monitor.sync') }}
  </button>
  <button class="btn-secondary" :disabled="syncing || taskRunning" @click="emit('sync', true)">{{ t('monitor.forceSync') }}</button>
  <button class="btn-secondary" :disabled="generatingBriefing" @click="emit('generateBriefings', true)">
    <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
    {{ t(generatingBriefing ? 'monitor.generating' : 'monitor.generateDaily') }}
  </button>
  <button class="btn-secondary" :disabled="clearingCache" :title="t('monitor.cacheTitle')" @click="emit('clearDashboardCache')">
    <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 00-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 00-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 000-7.78z"/></svg>
    {{ t(clearingCache ? 'monitor.clearing' : 'monitor.refreshCache') }}
  </button>
  <button class="btn-danger" :disabled="clearing" @click="emit('update:showClearConfirm', true)">
    <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/></svg>
    {{ t(clearing ? 'monitor.clearing' : 'monitor.clearData') }}
  </button>

  <Transition name="modal">
    <div v-if="showClearConfirm" class="fixed inset-0 z-50 flex items-center justify-center backdrop-blur-sm" style="background: rgba(0,0,0,0.15)" @click.self="emit('update:showClearConfirm', false)">
      <div class="w-full max-w-sm glass-card p-6 animate-slide-up" style="box-shadow: 0 4px 20px rgba(0,0,0,0.06)">
        <div class="mb-4 flex items-center gap-3">
          <div class="flex h-10 w-10 items-center justify-center rounded-2xl bg-rose-50">
            <svg class="h-5 w-5 text-rose-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
          </div>
          <h3 class="text-base font-semibold text-stone-800 font-serif">{{ t('monitor.clearConfirmTitle') }}</h3>
        </div>
        <div class="mb-4 space-y-1.5 text-sm text-stone-500">
          <p>{{ t('monitor.clearDeletes') }}</p>
          <ul class="ml-2 space-y-1 text-stone-400"><li>{{ t('monitor.clearSqlite') }}</li><li>{{ t('monitor.clearMilvus') }}</li></ul>
        </div>
        <p class="mb-5 rounded-2xl bg-rose-50 px-3 py-2 text-xs font-medium text-rose-600 border border-rose-200 flex items-center gap-1.5">
          <AlertTriangle class="h-3.5 w-3.5 shrink-0" />
          {{ t('monitor.irreversible') }}
        </p>
        <div class="flex gap-2">
          <button class="btn-secondary flex-1 justify-center" @click="emit('update:showClearConfirm', false)">{{ t('common.cancel') }}</button>
          <button class="btn-danger flex-1 justify-center" @click="emit('clearAllData')">{{ t('monitor.confirmClear') }}</button>
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
</style>
