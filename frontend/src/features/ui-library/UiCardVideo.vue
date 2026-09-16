<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'

defineProps<{ src: string; title: string }>()
const emit = defineEmits<{ ready: []; error: [] }>()
const video = ref<HTMLVideoElement>()
let disposed = false
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
  <video ref="video" :src="src" :aria-label="title" autoplay muted loop playsinline preload="auto" tabindex="-1" aria-hidden="true" @playing="ready" @error="!disposed && emit('error')" />
</template>
