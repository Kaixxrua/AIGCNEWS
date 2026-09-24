<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { authorAvatarUrl, authorDisplayName } from '@/features/xboard/xBoardViewModel'
import { Crown } from 'lucide-vue-next'
import ProjectLogo from '@/components/projects/ProjectLogo.vue'
import type { TopDoc } from '@/features/dashboard/dashboardViewModel'
const props = defineProps<{ doc: TopDoc; crowned?: boolean }>()
const imageUrl = computed(() => {
  if (props.doc.source === 'x') return authorAvatarUrl(props.doc)
  if (props.doc.source !== 'producthunt') return undefined
  const value = props.doc.image_url || props.doc.link_card?.image_url || ''
  try {
    const url = new URL(value)
    return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined
  } catch { return undefined }
})
const failed = ref(false)
const loaded = ref(false)
watch(imageUrl, () => { failed.value = false; loaded.value = false })
const name = computed(() => props.doc.source === 'x'
  ? authorDisplayName(props.doc) || 'X'
  : props.doc.title || props.doc.source || '?')
</script>

<template>
  <span class="ranking-avatar" :class="{ 'ranking-avatar--crowned': crowned }">
    <Crown v-if="crowned" class="ranking-crown" aria-hidden="true" />
    <ProjectLogo v-if="doc.source === 'github'" class="ranking-avatar__image" :logo="doc.image_url" :repository-url="doc.url" :name="doc.title || doc.source" />
    <span v-else class="ranking-avatar__image ranking-avatar__fallback" aria-hidden="true">
      <span v-if="!imageUrl || failed || !loaded">{{ name.slice(0, 1).toUpperCase() }}</span>
      <img v-if="imageUrl && !failed" :key="imageUrl" :src="imageUrl" :class="{ loaded }" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" @load="loaded = true" @error="failed = true" />
    </span>
  </span>
</template>

<style scoped>
.ranking-avatar { position: relative; display: inline-flex; align-items: center; justify-content: center; flex: 0 0 32px; width: 32px; height: 32px; border-radius: 50%; overflow: visible; background: var(--acid-soft); color: var(--ink); font-size: 14px; font-weight: 750; border: 1px solid var(--rule); }
.ranking-avatar__image { width: 100%; height: 100%; border: 0; background: transparent; }
.ranking-avatar__fallback { position: relative; display: inline-flex; align-items: center; justify-content: center; overflow: hidden; border-radius: inherit; }
.ranking-avatar__fallback img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; opacity: 0; }
.ranking-avatar__fallback img.loaded { opacity: 1; }
.ranking-crown { position: absolute; z-index: 1; bottom: calc(100% - 3px); left: 50%; transform: translateX(-50%) rotate(-8deg); width: 42%; min-width: 15px; height: auto; color: var(--podium-gold-ink); fill: var(--podium-gold); filter: drop-shadow(0 1px 0 var(--podium-gold-soft)); pointer-events: none; }
</style>
