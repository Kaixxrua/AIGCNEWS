<script setup lang="ts">
import { computed, ref, watch } from 'vue'
const props = defineProps<{ logo?: string | null; repositoryUrl?: string; name?: string }>()
const failed = ref<string[]>([])
const loaded = ref(false)
const plate = ref<'light' | 'dark'>()
const cachedLogo = computed(() => {
  try {
    const url = new URL(props.repositoryUrl || '')
    const repository = url.pathname.replace(/^\/|\/$/g, '')
    return url.hostname === 'github.com' && /^[a-z\d-]+\/[a-z\d_.-]+$/i.test(repository)
      ? `/api/projects/github/logo/${repository}` : ''
  } catch { return '' }
})
const candidates = computed(() => [
  /^\/api\/projects\/github\/logo\/[a-z\d-]+\/[a-z\d_.-]+$/i.test(props.logo || '') ? props.logo! : '',
  cachedLogo.value,
].filter(Boolean))
const source = computed(() => candidates.value.find(url => !failed.value.includes(url)))
watch(source, () => { loaded.value = false; plate.value = undefined })
watch(() => [props.logo, props.repositoryUrl], () => { failed.value = [] })

// A wordmark shrinks to a sliver inside the round tile, so it yields to the initial.
// A mark drawn on transparency needs a plate it contrasts with in either theme.
const SAMPLE = 24
function inspect(img: HTMLImageElement): 'reject' | 'light' | 'dark' | undefined {
  const { naturalWidth: width, naturalHeight: height } = img
  if (!width || !height) return undefined
  if (width / height > 1.5 || width / height < 0.67) return 'reject'
  try {
    const context = document.createElement('canvas').getContext('2d', { willReadFrequently: true })
    if (!context) return undefined
    context.canvas.width = context.canvas.height = SAMPLE
    context.drawImage(img, 0, 0, SAMPLE, SAMPLE)
    const pixels = context.getImageData(0, 0, SAMPLE, SAMPLE).data
    let covered = 0
    let luminance = 0
    for (let i = 0; i < pixels.length; i += 4) {
      if (pixels[i + 3]! < 128) continue
      covered++
      luminance += 0.2126 * (pixels[i]! / 255) ** 2.2 + 0.7152 * (pixels[i + 1]! / 255) ** 2.2 + 0.0722 * (pixels[i + 2]! / 255) ** 2.2
    }
    if (!covered || covered > SAMPLE * SAMPLE * 0.95) return undefined
    return luminance / covered > 0.5 ? 'dark' : 'light'
  } catch { return undefined }
}
function onLoad(event: Event) {
  const verdict = inspect(event.target as HTMLImageElement)
  if (verdict === 'reject') { failed.value.push(source.value!); return }
  plate.value = verdict
  loaded.value = true
}
</script>

<template>
  <span class="project-logo" :class="plate && loaded ? `project-logo--${plate}` : undefined" aria-hidden="true">
    <span v-if="!source || !loaded">{{ (name || '?').slice(0, 1).toUpperCase() }}</span>
    <img v-if="source" :src="source" :class="{ loaded }" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" @load="onLoad" @error="failed.push(source!)" />
  </span>
</template>

<style scoped>
.project-logo { position: relative; display: inline-flex; align-items: center; justify-content: center; overflow: hidden; flex-shrink: 0; width: 32px; height: 32px; border-radius: 50%; background: var(--paper-muted); color: var(--ink); border: 1px solid var(--rule); }
.project-logo.project-logo--light { background: var(--logo-plate-light); }
.project-logo.project-logo--dark { background: var(--logo-plate-dark); }
.project-logo img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; opacity: 0; }
.project-logo img.loaded { opacity: 1; }
</style>
