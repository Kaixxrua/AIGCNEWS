<script setup lang="ts">
import { computed, ref, watch } from 'vue'
const props = defineProps<{ logo?: string | null; repositoryUrl?: string; name?: string }>()
const failed = ref<string[]>([])
const loaded = ref(false)
const ownerAvatar = computed(() => {
  try {
    const url = new URL(props.repositoryUrl || '')
    const owner = url.pathname.split('/')[1]
    return url.hostname === 'github.com' && owner && /^[a-z\d-]+$/i.test(owner)
      ? `https://github.com/${owner}.png?size=128` : ''
  } catch { return '' }
})
const candidates = computed(() => [
  /^\/api\/projects\/github\/logo\/[a-z\d-]+\/[a-z\d_.-]+$/i.test(props.logo || '') ? props.logo! : '',
  ownerAvatar.value,
].filter(Boolean))
const source = computed(() => candidates.value.find(url => !failed.value.includes(url)))
watch(source, () => { loaded.value = false })
watch(() => [props.logo, props.repositoryUrl], () => { failed.value = [] })
</script>

<template>
  <span class="project-logo" aria-hidden="true">
    <span v-if="!source || !loaded">{{ (name || '?').slice(0, 1).toUpperCase() }}</span>
    <img v-if="source" :src="source" :class="{ loaded }" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" @load="loaded = true" @error="failed.push(source!)" />
  </span>
</template>

<style scoped>
.project-logo { position: relative; display: inline-flex; align-items: center; justify-content: center; overflow: hidden; flex-shrink: 0; width: 32px; height: 32px; border-radius: 50%; background: var(--acid-soft); color: var(--ink); border: 1px solid var(--rule); }
.project-logo img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; opacity: 0; }
.project-logo img.loaded { opacity: 1; }
</style>
