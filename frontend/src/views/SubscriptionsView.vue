<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { RefreshCw } from 'lucide-vue-next'
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
      <!-- 页头 -->
      <div class="flex flex-wrap items-center justify-between gap-3 shrink-0">
        <div>
          <h1 class="text-2xl font-bold tracking-tight">{{ t('subscriptions.title') }}</h1>
          <p class="mt-0.5 text-sm text-ink-muted">{{ t('tracking.description') }}</p>
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

      <section class="glass-card flex shrink-0 flex-col gap-3 p-4" aria-labelledby="push-channels-title">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <h2 id="push-channels-title" class="text-base font-bold text-ink">{{ t('subscriptions.channels.title') }}</h2>
          <span class="rounded-full border border-rule px-2.5 py-1 text-xs font-medium text-ink-muted">
            {{ t('tracking.channelsComingSoon') }}
          </span>
        </div>
        <p class="text-sm leading-relaxed text-ink-muted">{{ t('tracking.channelsComingSoonHint') }}</p>
      </section>
    </div>
  </div>
</template>

<style scoped>
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
