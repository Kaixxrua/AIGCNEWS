<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMediaQuery } from '@vueuse/core'
import { Download, TrendingUp } from 'lucide-vue-next'
import type { TrackingDigest, TrackingExportFormat } from '@/features/tracking/trackingModel'
import TrackingResults from './TrackingResults.vue'

const props = defineProps<{
  digests: TrackingDigest[]
  // Retained for callers using the previous component contract.
  member?: boolean
  exporting?: TrackingExportFormat | ''
  exportError?: string
}>()
const emit = defineEmits<{ viewed: [id: number]; export: [format: TrackingExportFormat] }>()
const exportFormats: readonly TrackingExportFormat[] = ['csv', 'json']
const { t, locale } = useI18n()
const desktop = useMediaQuery('(min-width: 1024px)')
// 日均保留一位小数：2 写成 2，0.7 写成 0.7
const dailyAverage = (value: number) => new Intl.NumberFormat(locale.value, { maximumFractionDigits: 1 }).format(value)
const issueId = ref<number>()
const digest = computed(() => props.digests.find((item) => item.id === issueId.value) ?? props.digests[0])
const results = ref<HTMLElement>()
let observer: IntersectionObserver | undefined
let visible = false
let displayedId: number | undefined
let retry: ReturnType<typeof setInterval> | undefined
function acknowledge() {
  if (visible && !document.hidden && results.value?.isConnected && displayedId === digest.value?.id && digest.value?.items.length) {
    emit('viewed', displayedId!)
  }
}
watch([results, () => digest.value?.id], () => {
  observer?.disconnect()
  visible = false
  displayedId = digest.value?.id
  const firstResult = results.value?.querySelector('li')
  if (!firstResult || typeof IntersectionObserver === 'undefined') return
  const observedId = displayedId
  observer = new IntersectionObserver(([entry]) => {
    if (observedId !== digest.value?.id) return
    visible = !!entry?.isIntersecting && entry.intersectionRatio >= 0.5
    acknowledge()
  }, { threshold: 0.5 })
  observer.observe(firstResult)
}, { flush: 'post' })
onMounted(() => {
  document.addEventListener('visibilitychange', acknowledge)
  window.addEventListener('focus', acknowledge)
  retry = setInterval(acknowledge, 30_000)
})
onBeforeUnmount(() => {
  observer?.disconnect()
  clearInterval(retry)
  document.removeEventListener('visibilitychange', acknowledge)
  window.removeEventListener('focus', acknowledge)
})
watch(
  () => props.digests,
  (issues) => {
    if (!issues.some((issue) => issue.id === issueId.value)) issueId.value = issues[0]?.id
  },
  { immediate: true },
)
</script>

<template>
  <div class="tracking-digest">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <h3 class="font-bold">{{ t('tracking.digestTitle') }}</h3>
      <div v-if="digests.length" class="tracking-digest-tools">
        <div class="tracking-export" role="group" :aria-label="t('tracking.exportLabel')">
          <span class="tracking-export-label" aria-hidden="true"><Download />{{ t('tracking.exportShort') }}</span>
          <button
            v-for="format in exportFormats"
            :key="format"
            type="button"
            class="tracking-button tracking-export-button"
            :title="t('tracking.exportTitle.' + format)"
            :disabled="!!exporting"
            :aria-busy="exporting === format"
            @click="emit('export', format)"
          >
            {{ format.toUpperCase() }}
          </button>
        </div>
        <select v-model="issueId" class="tracking-input w-auto" :aria-label="t('tracking.selectIssue')">
          <option v-for="issue in digests" :key="issue.id" :value="issue.id">{{ issue.issue_date }}</option>
        </select>
      </div>
    </div>
    <p v-if="exportError" role="alert" class="tracking-error tracking-export-error">
      {{ t('tracking.errors.' + exportError) }}
    </p>
    <p v-if="!digest" class="tracking-hint mt-3">{{ t('tracking.noDigest') }}</p>
    <template v-else>
      <p class="tracking-hint mt-2">
        {{ digest.issue_date }} · {{ t('tracking.deliveryStatus.' + digest.delivery_status) }}
      </p>
      <div v-if="digest.surges?.length" class="tracking-surges">
        <p class="tracking-surges-title"><TrendingUp aria-hidden="true" />{{ t('tracking.surgeTitle') }}</p>
        <ul>
          <li v-for="surge in digest.surges" :key="surge.query">
            {{ t('tracking.surgeLine', { query: surge.query, count: surge.count, baseline: dailyAverage(surge.baseline) }) }}
          </li>
        </ul>
      </div>
      <div :key="digest.id" ref="results">
        <TrackingResults :items="digest.items" :truncated="digest.truncated" :collapsed="desktop ? 3 : 5" />
      </div>
    </template>
  </div>
</template>
