<script setup lang="ts">
import { Crown } from 'lucide-vue-next'
import ProjectLogo from '@/components/projects/ProjectLogo.vue'
import type { TopDoc } from '@/features/dashboard/dashboardViewModel'
defineProps<{ doc: TopDoc; crowned?: boolean }>()
</script>

<template>
  <span class="ranking-avatar" :class="{ 'ranking-avatar--crowned': crowned }">
    <Crown v-if="crowned" class="ranking-crown" aria-hidden="true" />
    <ProjectLogo class="ranking-avatar__image" :logo="doc.source === 'github' ? doc.image_url : undefined" :repository-url="doc.source === 'github' ? doc.url : undefined" :name="doc.title || doc.source" />
  </span>
</template>

<style scoped>
.ranking-avatar { position: relative; display: inline-flex; align-items: center; justify-content: center; flex: 0 0 32px; width: 32px; height: 32px; border-radius: 50%; overflow: visible; background: var(--acid-soft); color: var(--ink); font-size: 14px; font-weight: 750; border: 1px solid var(--rule); }
.ranking-avatar__image { width: 100%; height: 100%; border: 0; background: transparent; }
.ranking-crown { position: absolute; z-index: 1; bottom: calc(100% - 3px); left: 50%; transform: translateX(-50%) rotate(-8deg); width: 42%; min-width: 15px; height: auto; color: #79520c; fill: #f8d45c; filter: drop-shadow(0 1px 0 #fff0b7); pointer-events: none; }
</style>
