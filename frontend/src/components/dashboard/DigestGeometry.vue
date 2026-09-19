<script setup lang="ts">
import { useDocumentVisibility, useElementVisibility, usePreferredReducedMotion } from '@vueuse/core'
import { onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
const host = ref<HTMLElement>()
const ready = ref(false)
const active = ref(true)
const visible = useElementVisibility(host)
const visibility = useDocumentVisibility()
const motion = usePreferredReducedMotion()
let dispose = () => {}
let sync = () => {}
let destroyed = false
onActivated(() => { active.value = true })
onDeactivated(() => { active.value = false })
watch([active, visible, visibility, motion], () => sync())
onBeforeUnmount(() => { destroyed = true; dispose() })
onMounted(async () => {
  const { createOrbitalSphereRenderer, ORBITAL_SPHERE_DEFAULTS } = await import('./orbitalSphereRenderer')
  if (destroyed || !host.value) return
  const element = host.value
  const canvas = document.createElement('canvas')
  let renderer: ReturnType<typeof createOrbitalSphereRenderer>
  const options = { ...ORBITAL_SPHERE_DEFAULTS, speed: 3, particleSize: .022, orbitOpacity: .4 }
  try { renderer = createOrbitalSphereRenderer(canvas, () => options) }
  catch { return }
  element.appendChild(canvas)
  let frame = 0, last = 0
  const pointer = (event: PointerEvent) => {
    if (motion.value === 'reduce') return
    const bounds = element.getBoundingClientRect()
    const x = (event.clientX - bounds.left - bounds.width / 2) / 260
    const y = (event.clientY - bounds.top - bounds.height / 2) / 260
    const influence = Math.max(0, 1 - Math.hypot(x, y))
    renderer.pointer(x * influence * 2, y * influence * 1.4)
  }
  const reset = () => renderer.pointer(0, 0)
  const draw = (time: number) => {
    renderer.render(last ? (time - last) / 1000 : 0)
    last = time
    frame = requestAnimationFrame(draw)
  }
  sync = () => {
    cancelAnimationFrame(frame)
    frame = 0; last = 0
    if (!active.value || !visible.value || visibility.value !== 'visible') return
    if (motion.value === 'reduce') { reset(); renderer.render(0) }
    else frame = requestAnimationFrame(draw)
  }
  const resize = new ResizeObserver(() => {
    renderer.resize(element.clientWidth, element.clientHeight)
    renderer.render(0)
  })
  resize.observe(element)
  renderer.resize(element.clientWidth, element.clientHeight)
  renderer.render(0)
  window.addEventListener('pointermove', pointer, { passive: true })
  document.documentElement.addEventListener('pointerleave', reset)
  ready.value = true
  sync()
  dispose = () => {
    cancelAnimationFrame(frame)
    resize.disconnect()
    window.removeEventListener('pointermove', pointer)
    document.documentElement.removeEventListener('pointerleave', reset)
    renderer.dispose()
    canvas.remove()
  }
})
</script>
<template>
  <div ref="host" class="digest-geometry" aria-hidden="true">
    <svg v-if="!ready" viewBox="0 0 160 150" fill="none">
      <path d="M12 103 64 53 121 12 153 45 91 145Z" fill="#ffffff18" stroke="#ffffffb0" />
      <path d="m12 103 79 42-27-92 57-41-30 133 62-100-89 8" stroke="#ffffff70" />
    </svg>
  </div>
</template>
<style scoped>
.digest-geometry { position: absolute; right: -22px; bottom: -32px; width: 210px; height: 180px; pointer-events: none; z-index: 0; }
.digest-geometry :deep(canvas), .digest-geometry svg { width: 100%; height: 100%; }
</style>
