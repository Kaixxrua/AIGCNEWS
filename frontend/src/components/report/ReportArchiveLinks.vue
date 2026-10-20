<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/services/http/apiClient'
import type { ReportKey } from '@/features/report/reportViewModel'

const props = defineProps<{ source: ReportKey; date: string }>()
const { locale, t } = useI18n()
const items = ref<{ date: string; url: string }[]>([])
const sources = new Set(['all', 'arxiv', 'github', 'news', 'producthunt', 'hackernews'])

watch(() => [props.source, props.date, locale.value], async (_, __, onCleanup) => {
  items.value = []
  if (!sources.has(props.source) || !props.date) return
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  try {
    const response = await api.get<{ items: typeof items.value }>('/report/archive', {
      params: { source: props.source, date: props.date, locale: locale.value },
      signal: controller.signal,
    })
    if (!controller.signal.aborted) items.value = response.data.items
  } catch {
    // Navigation is optional; keep the current issue readable during a failed request.
  }
}, { immediate: true })
</script>

<template>
  <nav v-if="items.length" :aria-label="t('report.archiveTitle')" class="border-t border-stone-200 p-4 text-sm">
    <h2 class="mb-2 font-semibold text-stone-700">{{ t('report.archiveTitle') }}</h2>
    <ul class="flex flex-wrap gap-x-5 gap-y-2">
      <li v-for="item in items" :key="item.url">
        <a :href="item.url" class="inline-flex min-h-11 items-center text-stone-600 underline underline-offset-4 hover:text-stone-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4">
          <time :datetime="item.date">{{ item.date }}</time>
        </a>
      </li>
    </ul>
  </nav>
</template>
