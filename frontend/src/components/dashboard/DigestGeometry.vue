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
  const THREE = await import('three')
  if (destroyed || !host.value) return
  let renderer: InstanceType<typeof THREE.WebGLRenderer>
  try { renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true }) }
  catch { return }
  const element = host.value
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.5))
  renderer.setSize(210, 180)
  renderer.setClearColor(0x000000, 0)
  element.appendChild(renderer.domElement)
  const scene = new THREE.Scene()
  const camera = new THREE.PerspectiveCamera(35, 210 / 180, .1, 20)
  camera.position.z = 6
  const crystal = new THREE.Group()
  const geometry = new THREE.OctahedronGeometry(1.15)
  geometry.scale(.72, 1.35, .62)
  const material = new THREE.MeshPhysicalMaterial({
    color: 0xdde7df, metalness: .25, roughness: .17, clearcoat: 1,
    transparent: true, opacity: .32, flatShading: true, side: THREE.DoubleSide, depthWrite: false,
  })
  const edges = new THREE.EdgesGeometry(geometry)
  const wire = new THREE.LineBasicMaterial({ color: 0xe7efe5, transparent: true, opacity: .7 })
  crystal.add(new THREE.Mesh(geometry, material), new THREE.LineSegments(edges, wire))
  crystal.rotation.set(.18, .35, -.48)
  scene.add(crystal, new THREE.HemisphereLight(0xf4fff0, 0x26352d, 2))
  const key = new THREE.DirectionalLight(0xffffff, 3)
  key.position.set(-3, 4, 5)
  const rim = new THREE.DirectionalLight(0xc8fc4c, 1.2)
  rim.position.set(3, -1, 2)
  scene.add(key, rim)
  let targetX = 0, targetY = 0, tiltX = 0, tiltY = 0, orbit = .35, last = 0
  const pointer = (event: PointerEvent) => {
    const bounds = element.getBoundingClientRect()
    const x = (event.clientX - bounds.left - bounds.width / 2) / 220
    const y = (event.clientY - bounds.top - bounds.height / 2) / 220
    const influence = Math.max(0, 1 - Math.hypot(x, y))
    targetX = y * influence * .9
    targetY = x * influence * 1.4
  }
  const reset = () => { targetX = 0; targetY = 0 }
  const draw = (time: number) => {
    const dt = last ? Math.min((time - last) / 1000, .05) : 0
    last = time
    orbit += dt * .23
    const ease = 1 - Math.exp(-dt * 6)
    tiltX += (targetX - tiltX) * ease
    tiltY += (targetY - tiltY) * ease
    crystal.rotation.set(.18 + tiltX, orbit + tiltY, -.48 + tiltY * .3)
    renderer.render(scene, camera)
  }
  sync = () => {
    last = 0
    renderer.setAnimationLoop(null)
    if (!active.value || !visible.value || visibility.value !== 'visible') return
    if (motion.value === 'reduce') {
      crystal.rotation.set(.18, .35, -.48)
      renderer.render(scene, camera)
    } else renderer.setAnimationLoop(draw)
  }
  window.addEventListener('pointermove', pointer, { passive: true })
  document.documentElement.addEventListener('pointerleave', reset)
  renderer.render(scene, camera)
  ready.value = true
  sync()
  dispose = () => {
    renderer.setAnimationLoop(null)
    window.removeEventListener('pointermove', pointer)
    document.documentElement.removeEventListener('pointerleave', reset)
    geometry.dispose(); edges.dispose(); material.dispose(); wire.dispose(); renderer.dispose()
    renderer.domElement.remove()
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
