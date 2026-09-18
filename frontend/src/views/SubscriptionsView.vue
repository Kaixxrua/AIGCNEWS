<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { RefreshCw, Sparkles } from 'lucide-vue-next'
import PersonalTrackingSection from '@/components/tracking/PersonalTrackingSection.vue'
import { useSubscriptionsController } from '@/composables/useSubscriptionsController'
defineOptions({ name: 'SubscriptionsView' })

const { t, te } = useI18n()
const ctl = useSubscriptionsController()
const errorText = computed(() => {
  const key = `subscriptions.errors.${ctl.error.value}`
  return ctl.error.value && te(key) ? t(key) : ctl.error.value
})
onMounted(() => {
  void ctl.loadAll()
})
</script>

<template>
  <div class="subs-page flex h-full min-h-0 flex-col overflow-hidden">
    <div class="subs-scroll flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-6 pb-24">
      <div class="subs-heading flex flex-wrap items-end justify-between gap-4 shrink-0">
        <div>
          <p class="subs-eyebrow"><Sparkles class="h-3.5 w-3.5" />{{ t('tracking.eyebrow') }}</p>
          <h1 class="mt-2 text-3xl font-black tracking-[-0.04em] sm:text-4xl">{{ t('subscriptions.title') }}</h1>
          <p class="mt-2 max-w-2xl text-sm leading-relaxed text-ink-secondary">{{ t('tracking.pageDescription') }}</p>
        </div>
        <button
          type="button"
          class="inline-flex items-center gap-1.5 rounded-[4px] border border-ink px-2.5 py-1.5 text-xs font-bold transition-colors hover:bg-accent"
          :disabled="ctl.loading.value"
          @click="ctl.loadAll"
        >
          <RefreshCw class="h-3.5 w-3.5" :class="{ 'animate-spin': ctl.loading.value }" />
          {{ t('subscriptions.refresh') }}
        </button>
      </div>

      <p v-if="errorText" class="shrink-0 rounded-[4px] border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-700">
        {{ errorText }}
      </p>
      <PersonalTrackingSection :channels="ctl.channels.value" />
    </div>
  </div>
</template>

<style scoped>
.subs-heading {
  padding: 4px 2px 10px;
}

.subs-eyebrow {
  @apply inline-flex items-center gap-1.5 text-[11px] font-black uppercase tracking-[0.18em] text-ink-secondary;
}

/* Keep the tracking and channel cards readable on narrow screens. */
@media (max-width: 639px) {
  .subs-scroll {
    padding: 12px 12px 80px;
    gap: 12px;
  }

  .subs-scroll :deep(.glass-card) {
    padding: 12px;
  }
}
</style>
