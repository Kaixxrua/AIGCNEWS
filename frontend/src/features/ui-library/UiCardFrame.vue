<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useResizeObserver } from '@vueuse/core'
const props = withDefaults(defineProps<{ src: string; id: string; title: string; width?: number }>(), { width: 640 })
const emit = defineEmits<{ ready: []; error: [] }>()
const frame = ref<HTMLIFrameElement>()
const container = ref<HTMLElement>()
const scale = ref(1)
useResizeObserver(container, entries => { scale.value = (entries[0]?.contentRect.width ?? props.width) / props.width })
function status(event: MessageEvent) {
  if (event.source !== frame.value?.contentWindow || event.data?.type !== 'ui-library-preview' || event.data.id !== props.id) return
  if (event.data.state === 'ready') emit('ready')
  else if (['error', 'unsupported'].includes(event.data.state)) emit('error')
}
function pointer(event?: MouseEvent) {
  const bounds = container.value?.getBoundingClientRect()
  if (!bounds) return
  frame.value?.contentWindow?.postMessage({ type: 'ui-library-pointer', leave: !event, x: event ? (event.clientX - bounds.left) / scale.value : 0, y: event ? (event.clientY - bounds.top) / scale.value : 0 }, '*')
}
defineExpose({ pointer })
onMounted(() => window.addEventListener('message', status))
onBeforeUnmount(() => window.removeEventListener('message', status))
</script>
<template>
  <span ref="container" class="ui-card-frame"><iframe ref="frame" :src="src" :title="title" sandbox="allow-scripts" referrerpolicy="no-referrer" tabindex="-1" aria-hidden="true" :style="{ width: width + 'px', height: width / 1.6 + 'px', transform: `scale(${scale})` }" @error="emit('error')" /></span>
</template>
<style scoped>
.ui-card-frame { display:block; overflow:hidden; }
.ui-card-frame iframe { width:640px; height:400px; border:0; transform-origin:top left; }
</style>
