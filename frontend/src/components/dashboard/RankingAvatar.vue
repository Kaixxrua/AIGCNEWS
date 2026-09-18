<script setup lang="ts">
import ProjectLogo from '@/components/projects/ProjectLogo.vue'
import type { TopDoc } from '@/features/dashboard/dashboardViewModel'
defineProps<{ doc: TopDoc }>()
</script>

<template>
  <ProjectLogo class="ranking-avatar" :logo="doc.source === 'github' ? doc.image_url : undefined" :repository-url="doc.source === 'github' ? doc.url : undefined" :name="doc.title || doc.source" />
</template>

<style scoped>
.ranking-avatar { display: inline-flex; align-items: center; justify-content: center; flex: 0 0 32px; width: 32px; height: 32px; border-radius: 50%; overflow: hidden; background: var(--acid-soft); color: var(--ink); font-size: 14px; font-weight: 750; border: 1px solid var(--rule); }
.ranking-avatar img { width: 100%; height: 100%; object-fit: cover; }
</style>
