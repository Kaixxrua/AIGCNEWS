<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

const PROTOCOL = 'meadow-camp-presentation'
const frame = ref<HTMLIFrameElement | null>(null)
const container = ref<HTMLElement | null>(null)
const src = ref('')
const status = ref('waiting_for_core')
const failed = ref(false)
const fullscreenError = ref(false)
const expanded = ref(false)
let session = ''
let sequence = 0
let deadline: ReturnType<typeof setTimeout> | null = null

const labels: Record<string, string> = {
  waiting_for_core: '正在连接风起原野…',
  waiting_for_state: '原野核心已就绪，正在载入演示伙伴…',
  loading: '原野已显示，正在载入演示伙伴…',
  applying: '正在安置演示伙伴…',
  pack_ready: '伙伴资源已载入…',
  ready: '风起原野实时演示',
  missing_assets: '原野已载入，部分演示伙伴暂不可用。',
  unsafe_placement: '原野已载入，伙伴演出已暂停。',
  stale: '正在重新同步原野演示…',
  unavailable: '原野演示暂不可用。',
  error: '原野载入失败，可重新载入。',
  reload_required: '原野需要重新载入。',
}
const message = computed(() => failed.value ? '原野暂未连接，可重新载入。' : labels[status.value] ?? labels.unavailable)
const statusVisible = computed(() => failed.value || fullscreenError.value
  || ['missing_assets', 'unsafe_placement', 'unavailable', 'error', 'reload_required'].includes(status.value))

function sendDemo() {
  if (!session || !frame.value?.contentWindow) return
  frame.value.contentWindow.postMessage({
    protocol: PROTOCOL,
    version: 1,
    type: 'snapshot',
    session,
    sequence: ++sequence,
    snapshot: {
      mode: 'demo',
      heroAssetId: 'hero_ranger',
      petAssetId: 'pet_deer',
      bossAssetId: 'boss_ancient_guardian',
      elapsed: 0,
      duration: 0,
      roundId: '',
    },
  }, window.location.origin)
}

function receive(event: MessageEvent) {
  if (event.origin !== window.location.origin || event.source !== frame.value?.contentWindow) return
  const data = event.data
  if (!data || typeof data !== 'object' || data.protocol !== PROTOCOL || data.version !== 1
    || typeof data.session !== 'string' || !/^[a-f0-9]{32}$/.test(data.session)) return
  if (data.type === 'bridge_ready' && Object.keys(data).length === 4) {
    session = data.session
    sequence = 0
    failed.value = false
    if (deadline) {
      clearTimeout(deadline)
      deadline = null
    }
    sendDemo()
  } else if (data.type === 'presentation_status' && data.session === session
    && Object.keys(data).length === 5 && typeof data.status === 'string'
    && Object.prototype.hasOwnProperty.call(labels, data.status)) {
    status.value = data.status
    failed.value = false
  }
}

function reload() {
  session = ''
  sequence = 0
  failed.value = false
  fullscreenError.value = false
  status.value = 'waiting_for_core'
  if (deadline) clearTimeout(deadline)
  const url = new URL('/camp-scene/index.html', window.location.origin)
  url.searchParams.set('camp', '1')
  url.searchParams.set('view', String(Date.now()))
  src.value = url.href
  deadline = setTimeout(() => {
    if (!session) failed.value = true
  }, 30000)
}

async function toggleFullscreen() {
  try {
    if (document.fullscreenElement === container.value) await document.exitFullscreen()
    else await container.value?.requestFullscreen()
  } catch {
    fullscreenError.value = true
  }
}

function fullscreenChanged() {
  expanded.value = document.fullscreenElement === container.value
}

onMounted(() => {
  window.addEventListener('message', receive)
  document.addEventListener('fullscreenchange', fullscreenChanged)
  reload()
})
onBeforeUnmount(() => {
  window.removeEventListener('message', receive)
  document.removeEventListener('fullscreenchange', fullscreenChanged)
  if (deadline) clearTimeout(deadline)
  session = ''
})
</script>

<template>
  <section ref="container" class="godot-contact-scene" aria-label="风起原野实时场景">
    <iframe
      v-if="src"
      ref="frame"
      :src="src"
      title="风起原野：画质选择、昼夜切换与伙伴演示"
      referrerpolicy="no-referrer"
      allow="fullscreen"
      allowfullscreen
      @error="failed = true"
    />
    <p class="scene-status" :class="{ 'scene-status--visible': statusVisible }" role="status">
      {{ fullscreenError ? '浏览器未能进入全屏，原野仍可继续使用。' : message }}
    </p>
    <div class="scene-actions">
      <button type="button" :aria-label="expanded ? '退出全屏' : '全屏显示原野'" :title="expanded ? '退出全屏' : '全屏'" :aria-pressed="expanded" @click="toggleFullscreen">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path v-if="expanded" d="M9 4v5H4M15 4v5h5M9 20v-5H4m11 5v-5h5" />
          <path v-else d="M9 4H4v5m11-5h5v5M9 20H4v-5m11 5h5v-5" />
        </svg>
      </button>
      <button type="button" aria-label="重新载入原野" title="重载" @click="reload">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6v5h-5M19 11a7.5 7.5 0 1 0 .1 4" /></svg>
      </button>
    </div>
  </section>
</template>

<style scoped>
.godot-contact-scene { position:absolute;inset:0;overflow:hidden;background:#17201b }
.godot-contact-scene iframe { display:block;width:100%;height:100%;border:0;background:#17201b }
.scene-status { position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0 }
.scene-status--visible { z-index:2;top:.75rem;left:50%;width:min(32rem,calc(100% - 1.5rem));height:auto;margin:0;padding:.55rem .75rem;overflow:visible;clip:auto;white-space:normal;box-sizing:border-box;transform:translateX(-50%);color:#f3f1df;background:rgb(23 32 27/.9);border:1px solid #889383;border-radius:3px;font:700 .72rem/1.45 ui-monospace,monospace;text-align:center }
.scene-actions { position:absolute;z-index:3;top:.75rem;right:.75rem;display:flex;gap:.45rem }
.scene-actions button { display:grid;width:44px;height:44px;padding:0;place-items:center;color:#f5edcf;background:rgb(24 32 25/.82);border:1px solid rgb(229 205 143/.72);border-radius:3px;box-shadow:0 2px 10px rgb(0 0 0/.2);backdrop-filter:blur(6px);cursor:pointer }
.scene-actions button:hover { color:#fff8dc;background:rgb(65 74 48/.92);border-color:#f0d58e }
.scene-actions svg { width:21px;height:21px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:square;stroke-linejoin:miter }
.scene-actions button:focus-visible { outline:3px solid #e9cc83;outline-offset:2px }
.godot-contact-scene:fullscreen { width:100vw;height:100vh }
@media(max-width:40rem){.scene-actions{top:.5rem;right:.5rem}.scene-actions button{width:42px;height:42px}}
</style>
