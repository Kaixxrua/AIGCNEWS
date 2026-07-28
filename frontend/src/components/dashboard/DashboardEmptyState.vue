<script setup lang="ts">
import { useI18n } from 'vue-i18n'
const { t } = useI18n()
defineProps<{
  variant: 'embargoed' | 'no-data'
}>()
</script>

<template>
  <div
    v-if="variant === 'embargoed'"
    class="dashboard-empty-state stagger-enter flex flex-col items-center justify-center flex-1 min-h-0 py-20 text-center"
    style="animation-delay: 0.4s"
  >
    <div class="relative mb-6">
      <div class="absolute inset-0 w-24 h-24 rounded-full bg-gradient-to-br from-amber-100 to-orange-50 blur-xl opacity-60" />
      <div class="relative w-24 h-24 rounded-2xl bg-gradient-to-br from-amber-50 to-orange-50 border border-amber-200/60 flex items-center justify-center shadow-sm">
        <svg class="w-12 h-12 text-amber-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/><circle cx="12" cy="16" r="1.5" fill="currentColor" stroke="none"/><line x1="12" y1="12.5" x2="12" y2="14"/>
        </svg>
      </div>
    </div>
    <h3 class="text-xl font-semibold text-stone-700 font-serif tracking-tight">{{ t('dashboard.embargoTitle') }}</h3>
    <p class="mt-2 text-sm text-stone-400 leading-relaxed max-w-xs">
      {{ t('dashboard.embargoDescription', { time: '15:00', timezone: 'UTC+8' }) }}
    </p>
    <div class="mt-5 flex items-center gap-1.5 text-xs text-stone-300">
      <span class="inline-block w-1.5 h-1.5 rounded-full bg-amber-300 animate-pulse" />
      {{ t('dashboard.archiving') }}
    </div>
  </div>

  <div
    v-else
    class="dashboard-empty-state stagger-enter flex flex-col items-center justify-center flex-1 min-h-0 py-24 text-center"
    style="animation-delay: 0.5s"
  >
    <div class="w-16 h-16 mb-4 rounded-full flex items-center justify-center bg-stone-100">
      <svg class="w-8 h-8 text-stone-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/><line x1="9" y1="16" x2="15" y2="16"/>
      </svg>
    </div>
    <h3 class="text-lg font-medium text-stone-500 font-serif">{{ t('dashboard.noDateData') }}</h3>
    <p class="mt-1 text-sm text-stone-400">{{ t('dashboard.chooseOtherDate') }}</p>
  </div>
</template>

<style scoped>
.dashboard-empty-state :deep(.bg-gradient-to-br) { background-image: none; background-color: var(--acid); }
.dashboard-empty-state :deep(.blur-xl) { filter: none; }
</style>
