<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

/**
 * 联系页风起原野：默认只显示静态截图（零引擎下载、零 GPU 占用）。
 * 访客点「选择画质」→ 页内面板选档 →「开启」后才把 Godot 场景以 iframe 内嵌进同一张卡片；
 * 场景核心真正画出来之前截图一直盖在上面，之后淡出；「退出」卸载 iframe 回到截图。
 * 从不自动启动：画质只记为下次的默认选项（与场景内「画质」按钮共用同一个存储键）。
 * 文案随站点语言切换；iframe 里的场景外壳随 Godot 发布包冻结，只有中文。
 */
type Quality = 'lite' | 'balanced' | 'original'
type Phase = 'poster' | 'choosing' | 'loading' | 'live'
type Status = 'waiting_for_core' | 'waiting_for_state' | 'loading' | 'applying' | 'pack_ready' | 'ready'
  | 'missing_assets' | 'unsafe_placement' | 'stale' | 'unavailable' | 'error' | 'reload_required'

const PROTOCOL = 'meadow-camp-presentation'
const QUALITY_KEY = 'meadow-texture-quality-v1'
// 截图随私有发布包一起换；文件名不变，靠版本号绕开浏览器旧缓存。
const POSTER_VERSION = '20260929'
const poster = (width: number) => `/camp-scene/contact-poster-${width}.webp?v=${POSTER_VERSION}`
const posterSrc = poster(1600)
const posterSrcset = [960, 1600, 2400].map((width) => `${poster(width)} ${width}w`).join(', ')

const QUALITIES: readonly Quality[] = ['lite', 'balanced', 'original']
const isQuality = (value: unknown): value is Quality => QUALITIES.includes(value as Quality)

interface Copy {
  qualities: Record<Quality, { label: string, note: string, size: string }>
  statuses: Record<Status, string>
  fullscreenFailed: string
  notConnected: string
  loading: (quality: string, progress: string) => string
  /** 场景外壳 #loading-message 的原文（中文）→ 状态条里可显示的进度；不合适时给空串。 */
  progress: (shellText: string) => string
  scene: string
  frameTitle: string
  posterAlt: string
  reload: string
  posterBadge: string
  choose: string
  enterFullscreen: string
  exitFullscreen: string
  fullscreenTitle: string
  exitLive: string
  exitLiveTitle: string
  chooserNote: string
  chooserLegend: string
  recommended: string
  chooserHint: string
  cancel: string
  start: string
}

const COPY: Record<'zh' | 'en', Copy> = {
  zh: {
    qualities: {
      lite: { label: '极速', note: '先进入低细节场景，高清细节随后补齐', size: '首屏约 13 MB' },
      balanced: { label: '均衡', note: '部分地表材质轻度压缩', size: '约 113 MB' },
      original: { label: '原画', note: '无损纹理，保留全部细节', size: '约 126 MB' },
    },
    statuses: {
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
    },
    fullscreenFailed: '浏览器未能进入全屏，原野仍可继续使用。',
    notConnected: '原野暂未连接，可重新载入。',
    loading: (quality, progress) => `正在载入原野 · ${quality}${progress ? ` · ${progress}` : '…'}`,
    progress: (shellText) => (shellText.length <= 48 ? shellText : ''),
    scene: '风起原野实时场景',
    frameTitle: '风起原野：昼夜切换与伙伴演示',
    posterAlt: '风起原野静态截图：晴天草原、河上木桥与山顶城堡',
    reload: '重新载入',
    posterBadge: '静态预览',
    choose: '选择画质',
    enterFullscreen: '全屏显示原野',
    exitFullscreen: '退出全屏',
    fullscreenTitle: '全屏',
    exitLive: '退出实时场景，回到静态预览',
    exitLiveTitle: '退出实时场景',
    chooserNote: '三档都是完整的实时原野，点「开启」才开始下载。',
    chooserLegend: '场景画质',
    recommended: '推荐',
    chooserHint: '实时场景较吃显卡与内存，可随时点右上角 ✕ 退出，回到静态预览。',
    cancel: '取消',
    start: '开启',
  },
  en: {
    qualities: {
      lite: { label: 'Lite', note: 'Opens a low-detail scene first, then streams in the full detail', size: '~13 MB to start' },
      balanced: { label: 'Balanced', note: 'Some ground textures lightly compressed', size: '~113 MB' },
      original: { label: 'Original', note: 'Lossless textures with every detail', size: '~126 MB' },
    },
    statuses: {
      waiting_for_core: 'Connecting to Windrise Meadow…',
      waiting_for_state: 'The meadow is ready, loading the demo companions…',
      loading: 'The meadow is up, loading the demo companions…',
      applying: 'Placing the demo companions…',
      pack_ready: 'Companions loaded…',
      ready: 'Windrise Meadow live demo',
      missing_assets: 'The meadow loaded, but some demo companions are unavailable.',
      unsafe_placement: 'The meadow loaded; the companion show is paused.',
      stale: 'Resyncing the meadow demo…',
      unavailable: 'The meadow demo is unavailable right now.',
      error: 'The meadow failed to load. You can reload it.',
      reload_required: 'The meadow needs to be reloaded.',
    },
    fullscreenFailed: 'Your browser could not go full screen; the meadow still works here.',
    notConnected: 'The meadow has not connected yet. You can reload it.',
    loading: (quality, progress) => `Loading the meadow · ${quality}${progress ? ` · ${progress}` : '…'}`,
    // 外壳只写中文：英文界面只取其中的下载量（「正在接收引擎与素材 · 12.3 / 113.0 MiB（解压后）」）。
    progress: (shellText) => {
      const received = /(\d+(?:\.\d+)?) \/ (\d+(?:\.\d+)?) MiB/.exec(shellText)
      return received ? `${received[1]} / ${received[2]} MiB unpacked` : ''
    },
    scene: 'Windrise Meadow live scene',
    frameTitle: 'Windrise Meadow: day and night with a companion demo',
    posterAlt: 'Still of Windrise Meadow: a sunny meadow, a wooden bridge over the river and a castle on the hill',
    reload: 'Reload',
    posterBadge: 'Still preview',
    choose: 'Choose quality',
    enterFullscreen: 'Show the meadow full screen',
    exitFullscreen: 'Exit full screen',
    fullscreenTitle: 'Full screen',
    exitLive: 'Leave the live scene and go back to the still preview',
    exitLiveTitle: 'Leave the live scene',
    chooserNote: 'All three are the full live meadow. Nothing downloads until you press Start.',
    chooserLegend: 'Scene quality',
    recommended: 'Recommended',
    chooserHint: 'The live scene is heavy on graphics and memory. Press ✕ at the top right at any time to go back to the still preview.',
    cancel: 'Cancel',
    start: 'Start',
  },
}
const isStatus = (value: unknown): value is Status =>
  typeof value === 'string' && Object.prototype.hasOwnProperty.call(COPY.zh.statuses, value)

const emit = defineEmits<{ overlay: [open: boolean] }>()
const { locale } = useI18n()
const copy = computed(() => COPY[locale.value.startsWith('en') ? 'en' : 'zh'])
const qualityOptions = computed(() => QUALITIES.map((value) => ({ value, ...copy.value.qualities[value] })))

const frame = ref<HTMLIFrameElement | null>(null)
const container = ref<HTMLElement | null>(null)
const launcher = ref<HTMLButtonElement | null>(null)
const panel = ref<HTMLElement | null>(null)
const phase = ref<Phase>('poster')
const selected = ref<Quality>('lite')
const active = ref<Quality>('lite')
const src = ref('')
const status = ref<Status>('waiting_for_core')
const progress = ref('')
const failed = ref(false)
const fullscreenError = ref(false)
const expanded = ref(false)
let session = ''
let sequence = 0
let deadline: ReturnType<typeof setTimeout> | null = null
let progressTimer: ReturnType<typeof setInterval> | null = null

const FAILURES: readonly Status[] = ['unavailable', 'error', 'reload_required']

const loadFailed = computed(() => failed.value || (phase.value !== 'poster' && FAILURES.includes(status.value)))
const message = computed(() => {
  if (fullscreenError.value) return copy.value.fullscreenFailed
  if (failed.value) return copy.value.notConnected
  if (phase.value === 'loading' && !FAILURES.includes(status.value)) {
    return copy.value.loading(copy.value.qualities[active.value].label, copy.value.progress(progress.value))
  }
  return copy.value.statuses[status.value]
})
const statusVisible = computed(() => phase.value === 'loading' || failed.value || fullscreenError.value
  || (phase.value === 'live' && ['missing_assets', 'unsafe_placement', ...FAILURES].includes(status.value)))

function savedQuality(): Quality | null {
  try {
    const value = window.localStorage.getItem(QUALITY_KEY)
    return isQuality(value) ? value : null
  } catch {
    return null
  }
}

function remember(value: Quality) {
  try { window.localStorage.setItem(QUALITY_KEY, value) } catch { /* 隐私模式：只影响下次默认选项 */ }
}

function setPhase(next: Phase) {
  phase.value = next
  emit('overlay', next === 'choosing')
}

function clearTimers() {
  if (deadline) clearTimeout(deadline)
  if (progressTimer) clearInterval(progressTimer)
  deadline = null
  progressTimer = null
}

/** 截图盖住场景时，同源读取场景自带的下载进度文案，让等待有真实反馈（按语言取舍见 copy.progress）。 */
function readProgress() {
  try {
    progress.value = frame.value?.contentDocument?.getElementById('loading-message')?.textContent?.trim() ?? ''
  } catch {
    progress.value = ''
  }
}

function openChooser() {
  selected.value = savedQuality() ?? selected.value
  setPhase('choosing')
  void nextTick(() => panel.value?.querySelector<HTMLInputElement>('input:checked')?.focus())
}

function closeChooser() {
  setPhase('poster')
  void nextTick(() => launcher.value?.focus())
}

function start(value: Quality) {
  clearTimers()
  session = ''
  sequence = 0
  active.value = value
  status.value = 'waiting_for_core'
  progress.value = ''
  failed.value = false
  fullscreenError.value = false
  const url = new URL('/camp-scene/index.html', window.location.origin)
  url.searchParams.set('camp', '1')
  url.searchParams.set('quality', value)
  url.searchParams.set('view', String(Date.now()))
  src.value = url.href
  setPhase('loading')
  deadline = setTimeout(() => {
    if (!session) failed.value = true
  }, 30000)
  progressTimer = setInterval(readProgress, 500)
}

function enter() {
  remember(selected.value)
  start(selected.value)
}

function reload() {
  start(active.value)
}

function exitLive() {
  if (document.fullscreenElement === container.value) void document.exitFullscreen().catch(() => {})
  clearTimers()
  session = ''
  src.value = ''
  failed.value = false
  fullscreenError.value = false
  status.value = 'waiting_for_core'
  setPhase('poster')
  void nextTick(() => launcher.value?.focus())
}

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
  if (!src.value || event.origin !== window.location.origin || event.source !== frame.value?.contentWindow) return
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
    && Object.keys(data).length === 5 && isStatus(data.status)) {
    status.value = data.status
    failed.value = false
    // 除 waiting_for_core 与失败态外，任何状态都意味着原野核心已真实画出：揭开截图。
    if (phase.value === 'loading' && data.status !== 'waiting_for_core' && !FAILURES.includes(data.status)) {
      clearTimers()
      setPhase('live')
    }
  }
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
  selected.value = savedQuality() ?? 'lite'
  window.addEventListener('message', receive)
  document.addEventListener('fullscreenchange', fullscreenChanged)
})
onBeforeUnmount(() => {
  window.removeEventListener('message', receive)
  document.removeEventListener('fullscreenchange', fullscreenChanged)
  clearTimers()
  session = ''
  if (phase.value === 'choosing') emit('overlay', false)
})
</script>

<template>
  <section ref="container" class="godot-contact-scene" :class="`godot-contact-scene--${phase}`" :aria-label="copy.scene">
    <iframe
      v-if="src"
      ref="frame"
      :src="src"
      :title="copy.frameTitle"
      referrerpolicy="no-referrer"
      allow="fullscreen"
      @error="failed = true"
    />
    <div class="scene-poster" :class="{ 'scene-poster--hidden': phase === 'live' }" :aria-hidden="phase === 'live'">
      <img
        class="scene-poster-image"
        :src="posterSrc"
        :srcset="posterSrcset"
        sizes="100vw"
        :alt="copy.posterAlt"
        decoding="async"
        fetchpriority="high"
      >
    </div>

    <p class="scene-status" :class="{ 'scene-status--visible': statusVisible, 'scene-status--busy': phase === 'loading' && !loadFailed }" role="status">
      <span>{{ message }}</span>
      <button v-if="loadFailed" type="button" class="scene-status-retry" @click="reload">{{ copy.reload }}</button>
    </p>

    <div v-if="phase === 'poster'" class="scene-actions scene-actions--poster">
      <span class="scene-poster-badge" aria-hidden="true">{{ copy.posterBadge }}</span>
      <button ref="launcher" type="button" class="scene-launch" @click="openChooser">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l10-6.5z" /></svg>
        <span>{{ copy.choose }}</span>
      </button>
    </div>
    <div v-else-if="phase !== 'choosing'" class="scene-actions">
      <button v-if="phase === 'live'" type="button" :aria-label="expanded ? copy.exitFullscreen : copy.enterFullscreen" :title="expanded ? copy.exitFullscreen : copy.fullscreenTitle" :aria-pressed="expanded" @click="toggleFullscreen">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path v-if="expanded" d="M9 4v5H4M15 4v5h5M9 20v-5H4m11 5v-5h5" />
          <path v-else d="M9 4H4v5m11-5h5v5M9 20H4v-5m11 5h5v-5" />
        </svg>
      </button>
      <button type="button" :aria-label="copy.exitLive" :title="copy.exitLiveTitle" @click="exitLive">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
      </button>
    </div>

    <div v-if="phase === 'choosing'" class="scene-chooser" @keydown.esc.stop="closeChooser">
      <form ref="panel" class="scene-chooser-panel" role="group" aria-labelledby="scene-chooser-title" aria-describedby="scene-chooser-note" @submit.prevent="enter">
        <h2 id="scene-chooser-title" class="scene-chooser-title">{{ copy.choose }}</h2>
        <p id="scene-chooser-note" class="scene-chooser-note">{{ copy.chooserNote }}</p>
        <fieldset class="scene-chooser-options">
          <legend class="scene-sr-only">{{ copy.chooserLegend }}</legend>
          <label v-for="item in qualityOptions" :key="item.value" class="scene-option">
            <input v-model="selected" type="radio" name="contact-scene-quality" :value="item.value">
            <span class="scene-option-body">
              <strong>{{ item.label }}<em v-if="item.value === 'lite'">{{ copy.recommended }}</em></strong>
              <small>{{ item.note }}</small>
            </span>
            <span class="scene-option-size">{{ item.size }}</span>
          </label>
        </fieldset>
        <p class="scene-chooser-hint">{{ copy.chooserHint }}</p>
        <div class="scene-chooser-actions">
          <button type="button" class="scene-chooser-cancel" @click="closeChooser">{{ copy.cancel }}</button>
          <button type="submit" class="scene-chooser-enter">{{ copy.start }}</button>
        </div>
      </form>
    </div>
  </section>
</template>

<style scoped>
/* --scene-safe-top 由宿主页给出（桌面端站点顶栏压住卡片上缘时，与标题行对齐）；全屏时顶栏不在，回到贴边。 */
.godot-contact-scene { --scene-top:var(--scene-safe-top,.75rem);position:absolute;inset:0;overflow:hidden;background:#17201b }
.godot-contact-scene iframe { display:block;width:100%;height:100%;border:0;background:#17201b }
/* 截图盖在 iframe 之上直到原野核心画出；不对 iframe 做 opacity/visibility，避免浏览器节流其渲染。 */
.scene-poster { position:absolute;inset:0;z-index:1;background:#17201b;transition:opacity .45s ease,visibility 0s linear 0s }
.scene-poster--hidden { opacity:0;visibility:hidden;pointer-events:none;transition:opacity .45s ease,visibility 0s linear .45s }
.scene-poster-image { display:block;width:100%;height:100%;object-fit:cover;object-position:50% 58% }
.godot-contact-scene--loading .scene-poster-image,
.godot-contact-scene--choosing .scene-poster-image { filter:saturate(.8) brightness(.72) }

.scene-sr-only,
.scene-status { position:absolute;width:1px;height:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0 }
.scene-status--visible { z-index:2;top:50%;left:50%;display:flex;width:min(26rem,calc(100% - 1.5rem));height:auto;margin:0;padding:.55rem .75rem;overflow:hidden;clip:auto;white-space:normal;box-sizing:border-box;align-items:center;justify-content:center;gap:.75rem;transform:translate(-50%,-50%);color:#f3f1df;background:rgb(23 32 27/.9);border:1px solid #889383;border-radius:3px;font:700 .72rem/1.45 ui-monospace,monospace;text-align:center }
.scene-status--busy::after { content:'';position:absolute;left:0;bottom:0;width:30%;height:2px;background:#dbc570;animation:scene-busy 1.4s ease-in-out infinite }
@keyframes scene-busy { from { transform:translateX(-100%) } to { transform:translateX(340%) } }
.scene-status-retry { flex:0 0 auto;min-height:2rem;padding:.25rem .6rem;color:#172019;background:#dbc570;border:1px solid #f0dda0;border-radius:2px;font:inherit;cursor:pointer }

.scene-actions { position:absolute;z-index:3;top:var(--scene-top);right:.75rem;display:flex;align-items:center;gap:.45rem }
.scene-actions button { display:grid;width:44px;height:44px;padding:0;place-items:center;color:#f5edcf;background:rgb(24 32 25/.82);border:1px solid rgb(229 205 143/.72);border-radius:3px;box-shadow:0 2px 10px rgb(0 0 0/.2);backdrop-filter:blur(6px);cursor:pointer }
.scene-actions button:hover { color:#fff8dc;background:rgb(65 74 48/.92);border-color:#f0d58e }
.scene-actions svg { width:21px;height:21px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:square;stroke-linejoin:miter }
.scene-actions button:focus-visible,
.scene-chooser button:focus-visible,
.scene-status-retry:focus-visible { outline:3px solid #e9cc83;outline-offset:2px }
.scene-actions .scene-launch { display:inline-flex;width:auto;gap:.45rem;padding:0 .85rem 0 .7rem;font:700 .8125rem/1 ui-sans-serif,system-ui,sans-serif;letter-spacing:.02em;white-space:nowrap }
.scene-launch svg { width:16px;height:16px;fill:currentColor;stroke:none }
.scene-poster-badge { padding:.3rem .5rem;color:#e9e1c4;background:rgb(24 32 25/.66);border:1px solid rgb(229 205 143/.38);border-radius:2px;font:700 .625rem/1 ui-monospace,monospace;letter-spacing:.08em }

/* 页内画质面板：盖住截图的居中卡片，沿用联系条目的橄榄金像素框语言 */
.scene-chooser { position:absolute;inset:0;z-index:4;display:grid;padding:var(--scene-top) 1rem 1rem;overflow-y:auto;place-items:center;background:rgb(10 16 12/.46) }
.scene-chooser-panel { width:min(26rem,100%);box-sizing:border-box;padding:1.1rem 1.1rem 1rem;color:#f6efd8;background:linear-gradient(135deg,rgb(64 70 45/.96),rgb(25 36 27/.96)),rgb(25 36 27/.96);border:1px solid rgb(232 207 137/.74);box-shadow:0 18px 40px rgb(5 12 8/.45),inset 0 0 0 3px rgb(10 18 13/.36) }
.scene-chooser-title { margin:0;color:#fff8df;font:700 1.0625rem/1.3 'DM Sans',Inter,ui-sans-serif,system-ui,sans-serif;letter-spacing:-.01em }
.scene-chooser-note,
.scene-chooser-hint { margin:.45rem 0 0;color:#d2c8a5;font-size:.8125rem;line-height:1.6 }
.scene-chooser-hint { margin-top:.75rem;font-size:.75rem }
.scene-chooser-options { display:grid;gap:.5rem;margin:.9rem 0 0;padding:0;border:0 }
.scene-option { display:grid;grid-template-columns:auto minmax(0,1fr) auto;align-items:center;gap:.7rem;padding:.65rem .75rem;background:rgb(12 20 14/.42);border:1px solid rgb(232 207 137/.28);cursor:pointer }
.scene-option:hover { border-color:rgb(232 207 137/.6) }
.scene-option:has(input:checked) { background:rgb(219 197 112/.14);border-color:#dbc570 }
.scene-option input { width:1rem;height:1rem;margin:0;accent-color:#dbc570 }
.scene-option-body { display:grid;min-width:0;gap:.15rem }
.scene-option-body strong { display:flex;align-items:center;gap:.45rem;color:#fff8df;font-size:.9375rem }
.scene-option-body em { padding:.1rem .35rem;color:#172019;background:#dcc676;font:700 .625rem/1.3 ui-monospace,monospace;font-style:normal;letter-spacing:.06em }
.scene-option-body small { color:#d2c8a5;font-size:.75rem;line-height:1.5 }
.scene-option-size { color:#efe4bd;font:600 .6875rem/1.4 ui-monospace,monospace;white-space:nowrap }
.scene-chooser-actions { display:flex;justify-content:flex-end;gap:.6rem;margin-top:.9rem }
.scene-chooser-actions button { min-height:2.5rem;padding:.45rem 1rem;border-radius:2px;font:700 .875rem/1 ui-sans-serif,system-ui,sans-serif;cursor:pointer }
.scene-chooser-cancel { color:#f5edcf;background:transparent;border:1px solid rgb(229 205 143/.5) }
.scene-chooser-cancel:hover { background:rgb(65 74 48/.6) }
.scene-chooser-enter { color:#172019;background:#dbc570;border:1px solid #f0dda0 }
.scene-chooser-enter:hover { color:#fff8df;background:#52603d }

.godot-contact-scene:fullscreen { --scene-top:.75rem;width:100vw;height:100vh }
@media(max-width:40rem){
  .scene-actions{top:.5rem;right:.5rem}
  .scene-actions button{width:42px;height:42px}
  .scene-poster-badge{display:none}
  .scene-option{grid-template-columns:auto minmax(0,1fr)}
  .scene-option-size{grid-column:2}
}
@media (prefers-reduced-motion: reduce) {
  .scene-poster,
  .scene-poster--hidden { transition:none }
  .scene-status--busy::after { animation:none;width:100%;opacity:.5 }
}
</style>
