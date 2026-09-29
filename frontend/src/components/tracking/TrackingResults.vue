<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { BookOpenText, Bot, Flame, Github, MessagesSquare, Newspaper, Radar } from 'lucide-vue-next'
import { XLogoIcon } from '@/components/icons/XLogoIcon'
import type { TrackingItem } from '@/features/tracking/trackingModel'

// collapsed: how many results show before "show all" (the desktop digest shows three, as its panel is drawn).
const props = withDefaults(defineProps<{ items: TrackingItem[]; truncated?: boolean; preview?: boolean; collapsed?: number }>(), {
  collapsed: 5,
})
const { t } = useI18n()
const expanded = ref(false)
watch(
  () => props.items,
  () => {
    expanded.value = false
  },
)
const visible = computed(() => (expanded.value ? props.items : props.items.slice(0, props.collapsed)))
// 桌面漫画版在每条结果前画来源图标（与首页来源一致）；窄屏不显示。
const sourceIcons: Record<string, unknown> = {
  github: Github,
  arxiv: BookOpenText,
  news: Newspaper,
  producthunt: Bot,
  hackernews: MessagesSquare,
  x: XLogoIcon,
  dailyhot: Flame,
}
</script>

<template>
  <p v-if="!items.length" class="tracking-hint py-3">{{ t(preview ? 'tracking.noMatches' : 'tracking.noDigest') }}</p>
  <ol v-else class="tracking-results">
    <li v-for="item in visible" :key="item.key">
      <span class="tracking-result-icon" :data-source="item.source" aria-hidden="true"
        ><component :is="sourceIcons[item.source] ?? Radar"
      /></span>
      <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <a :href="item.url" target="_blank" rel="noopener noreferrer" class="font-bold hover:underline">{{
          item.title
        }}</a>
        <span class="tracking-hint">{{ t('subscriptions.sources.' + item.source) }}</span>
      </div>
      <p class="tracking-result-summary mt-1 text-sm leading-relaxed">{{ item.summary }}</p>
      <p class="tracking-hint tracking-result-match mt-1">{{ t('tracking.matched', { rules: item.matched_rules.join(' / ') }) }}</p>
    </li>
  </ol>
  <button
    v-if="items.length > collapsed"
    class="tracking-button mt-3"
    type="button"
    :aria-expanded="expanded"
    @click="expanded = !expanded"
  >
    {{ t(expanded ? 'tracking.collapse' : 'tracking.showAll', { count: items.length }) }}
  </button>
  <p v-if="truncated" class="tracking-hint mt-3">{{ t('tracking.truncated') }}</p>
</template>
