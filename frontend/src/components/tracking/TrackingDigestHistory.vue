<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { TrackingDigest } from '@/features/tracking/trackingModel'
import TrackingResults from './TrackingResults.vue'

const props = defineProps<{ digests: TrackingDigest[] }>()
const emit = defineEmits<{ viewed: [id: number] }>()
const { t } = useI18n()
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
      <select
        v-if="digests.length"
        v-model="issueId"
        class="tracking-input w-auto"
        :aria-label="t('tracking.selectIssue')"
      >
        <option v-for="issue in digests" :key="issue.id" :value="issue.id">{{ issue.issue_date }}</option>
      </select>
    </div>
    <p v-if="!digest" class="tracking-hint mt-3">{{ t('tracking.noDigest') }}</p>
    <template v-else>
      <p class="tracking-hint mt-2">
        {{ digest.issue_date }} · {{ t('tracking.deliveryStatus.' + digest.delivery_status) }}
      </p>
      <div :key="digest.id" ref="results">
        <TrackingResults :items="digest.items" :truncated="digest.truncated" />
      </div>
    </template>
  </div>
</template>
