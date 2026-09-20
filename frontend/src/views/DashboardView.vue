<script setup lang="ts">
import { useMediaQuery } from '@vueuse/core'
import DesktopDashboardView from './DesktopDashboardView.vue'
import MobileDashboardView from './MobileDashboardView.vue'

defineOptions({ name: 'DashboardView' })
const desktop = useMediaQuery('(min-width: 1024px)')
</script>

<template>
  <DesktopDashboardView v-if="desktop" />
  <MobileDashboardView v-else />
</template>
