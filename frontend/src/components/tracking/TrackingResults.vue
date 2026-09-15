<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { TrackingItem } from '@/features/tracking/trackingModel'

const props = defineProps<{ items: TrackingItem[]; truncated?: boolean; preview?: boolean }>()
const { t } = useI18n()
const expanded = ref(false)
watch(
  () => props.items,
  () => {
    expanded.value = false
  },
)
const visible = computed(() => (expanded.value ? props.items : props.items.slice(0, 5)))
</script>

<template>
  <p v-if="!items.length" class="tracking-hint py-3">{{ t(preview ? 'tracking.noMatches' : 'tracking.noDigest') }}</p>
  <ol v-else class="tracking-results">
    <li v-for="item in visible" :key="item.key">
      <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <a :href="item.url" target="_blank" rel="noopener noreferrer" class="font-bold hover:underline">{{
          item.title
        }}</a>
        <span class="tracking-hint">{{ t('subscriptions.sources.' + item.source) }}</span>
      </div>
      <p class="mt-1 text-sm leading-relaxed">{{ item.summary }}</p>
      <p class="tracking-hint mt-1">{{ t('tracking.matched', { rules: item.matched_rules.join(' / ') }) }}</p>
    </li>
  </ol>
  <button
    v-if="items.length > 5"
    class="tracking-button mt-3"
    type="button"
    :aria-expanded="expanded"
    @click="expanded = !expanded"
  >
    {{ t(expanded ? 'tracking.collapse' : 'tracking.showAll', { count: items.length }) }}
  </button>
  <p v-if="truncated" class="tracking-hint mt-3">{{ t('tracking.truncated') }}</p>
</template>
