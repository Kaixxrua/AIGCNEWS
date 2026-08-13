<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { MonitorNavCategory, MonitorSectionKey } from '@/features/monitor/monitorViewModel'

// 监控页左侧两级导航：大类可折叠（组件自持的纯展示状态），叶子点击即切换面板
const props = defineProps<{
  sections: readonly MonitorNavCategory[]
  active: MonitorSectionKey
  alertKeys: readonly MonitorSectionKey[]
}>()

const emit = defineEmits<{ select: [key: MonitorSectionKey] }>()
const { t } = useI18n()

// 默认全展开保证可发现性；折叠状态不影响移动端（CSS 强制摊平）
const collapsedKeys = ref<ReadonlySet<string>>(new Set())

const toggleCategory = (key: string) => {
  const next = new Set(collapsedKeys.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  collapsedKeys.value = next
}

const isCollapsed = (key: string) => collapsedKeys.value.has(key)
// 折叠时大类头接管红点，避免告警被藏进折叠区
const categoryShowsAlert = (category: MonitorNavCategory) =>
  isCollapsed(category.key) && category.children.some(leaf => props.alertKeys.includes(leaf.key))
</script>

<template>
  <nav class="monitor-nav" :aria-label="t('monitor.nav.ariaLabel')">
    <div v-for="category in sections" :key="category.key" class="monitor-nav-group">
      <button
        type="button"
        class="monitor-nav-group-header"
        :aria-expanded="isCollapsed(category.key) ? 'false' : 'true'"
        @click="toggleCategory(category.key)"
      >
        <component :is="category.icon" class="monitor-nav-icon" />
        <span class="monitor-nav-group-label">{{ t(category.labelKey) }}</span>
        <span
          v-if="categoryShowsAlert(category)"
          class="monitor-nav-alert monitor-nav-alert-inline"
          :title="t('navigation.monitorAlert')"
        />
        <svg class="monitor-nav-chevron" :class="{ collapsed: isCollapsed(category.key) }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
      </button>
      <div v-show="!isCollapsed(category.key)" class="monitor-nav-leaves">
        <button
          v-for="leaf in category.children"
          :key="leaf.key"
          type="button"
          class="monitor-nav-item monitor-nav-leaf"
          :class="{ active: leaf.key === active }"
          :aria-current="leaf.key === active ? 'true' : undefined"
          @click="emit('select', leaf.key)"
        >
          <span class="monitor-nav-label">{{ t(leaf.labelKey) }}</span>
          <span
            v-if="alertKeys.includes(leaf.key)"
            class="monitor-nav-alert"
            :title="t('navigation.monitorAlert')"
          />
        </button>
      </div>
    </div>
  </nav>
</template>
