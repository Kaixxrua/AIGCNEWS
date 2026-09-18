<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { TopDoc } from '@/features/dashboard/dashboardViewModel'
const props = defineProps<{ doc: TopDoc }>()
const failed = ref(false)
const avatar = computed(() => {
  if (props.doc.source !== 'github' || !props.doc.url) return ''
  try {
    const url = new URL(props.doc.url)
    const owner = url.pathname.split('/')[1]
    return url.hostname === 'github.com' && owner && /^[a-z\d-]+$/i.test(owner)
      ? `https://github.com/${owner}.png?size=128` : ''
  } catch { return '' }
})
watch(avatar, () => { failed.value = false })
</script>

<template>
  <span class="ranking-avatar" aria-hidden="true">
    <img v-if="avatar && !failed" :src="avatar" alt="" loading="lazy" referrerpolicy="no-referrer" @error="failed = true" />
    <span v-else>{{ (doc.title || doc.source || '?').slice(0, 1).toUpperCase() }}</span>
  </span>
</template>

<style scoped>
.ranking-avatar { display: inline-flex; align-items: center; justify-content: center; flex: 0 0 32px; width: 32px; height: 32px; border-radius: 50%; overflow: hidden; background: var(--acid-soft); color: var(--ink); font-size: 14px; font-weight: 750; border: 1px solid var(--rule); }
.ranking-avatar img { width: 100%; height: 100%; object-fit: cover; }
</style>
