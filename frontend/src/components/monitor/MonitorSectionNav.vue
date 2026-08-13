<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { MonitorSectionItem, MonitorSectionKey } from '@/features/monitor/monitorViewModel'

// 监控页左侧二级导航：纯哑组件，分组过滤与激活态都由父级持有
defineProps<{
  sections: readonly MonitorSectionItem[]
  active: MonitorSectionKey
  alertKeys: readonly MonitorSectionKey[]
}>()

const emit = defineEmits<{ select: [key: MonitorSectionKey] }>()
const { t } = useI18n()
</script>

<template>
  <nav class="monitor-nav" :aria-label="t('monitor.nav.ariaLabel')">
    <button
      v-for="section in sections"
      :key="section.key"
      type="button"
      class="monitor-nav-item"
      :class="{ active: section.key === active }"
      :aria-current="section.key === active ? 'true' : undefined"
      @click="emit('select', section.key)"
    >
      <component :is="section.icon" class="monitor-nav-icon" />
      <span class="monitor-nav-label">{{ t(section.labelKey) }}</span>
      <span
        v-if="alertKeys.includes(section.key)"
        class="monitor-nav-alert"
        :title="t('navigation.monitorAlert')"
      />
    </button>
  </nav>
</template>
