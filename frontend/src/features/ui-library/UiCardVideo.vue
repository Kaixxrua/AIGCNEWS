<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps<{ src: string; title: string; playing: boolean }>()
const emit = defineEmits<{ ready: []; error: [] }>()
const video = ref<HTMLVideoElement>()
let disposed = false
async function syncPlayback() {
  await nextTick()
  const element = video.value
  if (!element || disposed) return
  if (props.playing) await element.play().catch(() => undefined)
  else element.pause()
}
watch(() => props.playing, syncPlayback, { immediate: true })
function ready() {
  const element = video.value
  if (!element) return
  if (element.requestVideoFrameCallback) element.requestVideoFrameCallback(() => { if (!disposed) emit('ready') })
  else emit('ready')
}
onBeforeUnmount(() => {
  disposed = true
  if (!video.value) return
  video.value.pause()
  video.value.removeAttribute('src')
  video.value.load()
})
</script>

<template>
  <video ref="video" :src="src" :aria-label="title" muted loop playsinline preload="auto" tabindex="-1" aria-hidden="true" @canplay="syncPlayback" @playing="ready" @error="!disposed && emit('error')" />
</template>
