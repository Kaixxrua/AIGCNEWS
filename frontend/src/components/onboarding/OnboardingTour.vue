<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, toRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useMediaQuery } from '@vueuse/core'
import { ArrowLeft, ArrowRight, Compass, X } from 'lucide-vue-next'
import { useTour } from '@/features/onboarding/useTour'
import { tourStep } from '@/features/onboarding/signals'
import { placeCard, spotlightBox, type Box } from '@/features/onboarding/geometry'

const props = withDefaults(defineProps<{ blocked?: boolean }>(), { blocked: false })
const { t } = useI18n()
const compact = useMediaQuery('(max-width: 1023px)')
const { phase, index, step, steps, pageGuide, busy, navigationFailed, start, previous, next, skip } = useTour(toRef(props, 'blocked'), compact)
const dialog = ref<HTMLDialogElement>()
const card = ref<HTMLElement>()
const title = ref<HTMLElement>()
const hole = ref<Box | null>(null)
const position = ref({ left: '16px', top: '16px' })
const missing = ref(false)
const locating = ref(false)
const welcome = computed(() => phase.value === 'welcome')
const heading = computed(() => welcome.value ? t(pageGuide.value ? 'onboarding.pageWelcomeTitle' : 'onboarding.welcomeTitle') : t(`onboarding.steps.${step.value?.copy ?? step.value?.id}.title`))
const description = computed(() => welcome.value ? t(pageGuide.value ? 'onboarding.pageWelcomeBody' : 'onboarding.welcomeBody') : t(`onboarding.steps.${step.value?.copy ?? step.value?.id}.body`))
const holeStyle = computed(() => hole.value ? {
  left: `${hole.value.left}px`, top: `${hole.value.top}px`,
  width: `${hole.value.width}px`, height: `${hole.value.height}px`,
} : {})
let frame = 0
let changedAt = 0
let scrolled: Element | null = null

function findTarget(): HTMLElement | null {
  if (busy.value || navigationFailed.value || phase.value !== 'tour') return null
  for (const selector of step.value?.targets ?? []) {
    for (const element of document.querySelectorAll<HTMLElement>(selector)) {
      const rect = element.getBoundingClientRect()
      const style = getComputedStyle(element)
      if (rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none' && style.opacity !== '0') return element
    }
  }
  return null
}
function measure() {
  if (phase.value !== 'tour') return
  // Route transitions can briefly keep the departing view mounted.
  const settled = performance.now() - changedAt > 400
  const element = settled ? findTarget() : null
  if (element && element !== scrolled) {
    const margin = element.style.scrollMarginTop
    if (compact.value) element.style.scrollMarginTop = 'max(16px, env(safe-area-inset-top))'
    element.scrollIntoView({ block: compact.value ? 'start' : 'nearest', inline: 'nearest', behavior: 'instant' })
    element.style.scrollMarginTop = margin
    scrolled = element
  }
  const rect = element?.getBoundingClientRect()
  const box = rect ? spotlightBox(rect, innerWidth, innerHeight) : null
  if (JSON.stringify(box) !== JSON.stringify(hole.value)) hole.value = box
  locating.value = !welcome.value && !element && (busy.value || performance.now() - changedAt < 2200)
  missing.value = !welcome.value && !element && !locating.value
  if (card.value) {
    const dimensions = card.value.getBoundingClientRect()
    const surface = dialog.value!.getBoundingClientRect()
    const style = getComputedStyle(dialog.value!)
    const placed = placeCard(box, dimensions, surface.width, surface.height, {
      top: parseFloat(style.paddingTop), right: parseFloat(style.paddingRight),
      bottom: parseFloat(style.paddingBottom), left: parseFloat(style.paddingLeft),
    })
    const nextPosition = { left: `${Math.round(placed.left)}px`, top: `${Math.round(placed.top)}px` }
    if (position.value.left !== nextPosition.left || position.value.top !== nextPosition.top) position.value = nextPosition
  }
  frame = requestAnimationFrame(measure)
}

watch([phase, () => step.value?.id], async () => {
  tourStep.value = phase.value === 'tour' ? step.value?.id ?? null : null
  cancelAnimationFrame(frame)
  changedAt = performance.now()
  scrolled = null
  hole.value = null
  missing.value = false
  locating.value = phase.value === 'tour'
  await nextTick()
  if (phase.value === 'idle') { dialog.value?.close(); return }
  if (dialog.value && !dialog.value.open) dialog.value.showModal()
  title.value?.focus({ preventScroll: true })
  measure()
}, { flush: 'post' })

function keyboard(event: KeyboardEvent) {
  if (phase.value === 'idle') return
  // Keep background list shortcuts and quick search from opening another modal.
  // Native Tab/Enter still work, with focus contained by showModal().
  event.stopImmediatePropagation()
  if (event.key === 'Escape') { event.preventDefault(); skip() }
}
onMounted(() => document.addEventListener('keydown', keyboard, true))
onBeforeUnmount(() => {
  tourStep.value = null
  cancelAnimationFrame(frame)
  document.removeEventListener('keydown', keyboard, true)
  dialog.value?.close()
})
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" class="onboarding-dialog" :data-step="welcome ? 'welcome' : step?.id" aria-labelledby="onboarding-title" aria-describedby="onboarding-description" @cancel.prevent="skip">
      <div v-if="hole" class="onboarding-spotlight" :style="holeStyle" aria-hidden="true"></div>
      <div v-else class="onboarding-shade" aria-hidden="true"></div>
      <section ref="card" class="onboarding-card" :class="{ 'onboarding-card--welcome': welcome }" :style="welcome ? undefined : position">
        <header class="onboarding-topline">
          <span class="onboarding-edition">{{ t('onboarding.edition') }}</span>
          <button class="onboarding-close" type="button" :aria-label="t('onboarding.close')" @click="skip"><X :size="20" aria-hidden="true" /></button>
        </header>
        <div v-if="welcome" class="onboarding-emblem" aria-hidden="true"><Compass :size="46" :stroke-width="1.5" /><span>✦</span></div>
        <div v-else class="onboarding-progress" :aria-label="t('onboarding.progress', { current: index + 1, total: steps.length })">
          <span>{{ String(index + 1).padStart(2, '0') }}</span>
          <div class="onboarding-progress__track" aria-hidden="true"><div :style="{ width: `${(index + 1) / steps.length * 100}%` }"></div></div>
          <span>{{ String(steps.length).padStart(2, '0') }}</span>
        </div>
        <div class="onboarding-copy" aria-live="polite" aria-atomic="true">
          <h2 id="onboarding-title" ref="title" tabindex="-1">{{ heading }}</h2>
          <p id="onboarding-description">{{ description }}</p>
        </div>
        <p v-if="welcome" class="onboarding-note">{{ t(pageGuide ? 'onboarding.pageWelcomeNote' : 'onboarding.welcomeNote') }}</p>
        <p v-else-if="locating" class="onboarding-note" role="status">{{ t('onboarding.loading') }}</p>
        <p v-else-if="missing" class="onboarding-note" role="status">{{ t('onboarding.missing') }}</p>
        <footer class="onboarding-actions">
          <button type="button" class="onboarding-skip" @click="skip">{{ t('onboarding.skip') }}</button>
          <div class="onboarding-actions__steps">
            <button v-if="!welcome" type="button" class="onboarding-back" :disabled="index === 0 || busy || locating" @click="previous"><ArrowLeft :size="15" aria-hidden="true" />{{ t('onboarding.previous') }}</button>
            <button type="button" class="onboarding-next" :disabled="busy || locating" @click="welcome ? start() : next()">
              {{ t(welcome ? 'onboarding.start' : index === steps.length - 1 ? 'onboarding.finish' : 'onboarding.next') }}<ArrowRight :size="16" aria-hidden="true" />
            </button>
          </div>
        </footer>
      </section>
    </dialog>
  </Teleport>
</template>

<style scoped>
.onboarding-dialog { position: fixed; inset: 0; width: 100vw; height: 100dvh; max-width: none; max-height: none; margin: 0; padding: max(16px, env(safe-area-inset-top)) max(16px, env(safe-area-inset-right)) max(16px, env(safe-area-inset-bottom)) max(16px, env(safe-area-inset-left)); border: 0; background: transparent; overflow: hidden; color: var(--ink); }
.onboarding-dialog::backdrop { background: transparent; }
.onboarding-shade { position: absolute; inset: 0; background: rgb(15 19 16 / 64%); }
.onboarding-spotlight { position: absolute; border: 3px solid var(--acid, #c9ef42); border-radius: 7px; box-shadow: 0 0 0 9999px rgb(15 19 16 / 64%); pointer-events: none; }
.onboarding-card { position: absolute; width: 432px; max-width: calc(100vw - 32px); max-height: calc(100dvh - 32px); overflow-y: auto; padding: 22px 24px 20px; border: 2px solid var(--ink); border-radius: 3px 12px 4px 3px; background: var(--paper-raised, #fffdf3); box-shadow: 7px 7px 0 var(--ink); color: var(--ink); text-align: left; }
.onboarding-card--welcome { left: 50%; top: 50%; transform: translate(-50%, -50%); width: 492px; padding: 26px 30px 24px; background-image: radial-gradient(var(--rule) 0.65px, transparent 0.65px); background-size: 7px 7px; }
.onboarding-topline { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 18px; }
.onboarding-edition { display: inline-block; padding: 4px 9px; border: 1.5px solid var(--ink); background: var(--acid); color: var(--acid-ink, #141913); font-size: 11px; font-weight: 900; letter-spacing: 0.12em; transform: rotate(-2deg); }
.onboarding-close { display: grid; place-items: center; width: 28px; height: 28px; border: 0; background: transparent; color: inherit; cursor: pointer; }
.onboarding-emblem { position: relative; display: grid; place-items: center; width: 78px; height: 78px; margin: 2px 0 22px; border: 2px solid var(--ink); border-radius: 50%; background: var(--paper); box-shadow: 4px 4px 0 var(--ink); transform: rotate(-7deg); }
.onboarding-emblem span { position: absolute; right: -10px; top: -12px; font-size: 34px; color: var(--ink); }
.onboarding-card h2 { margin: 0 0 12px; font-size: 24px; line-height: 1.35; font-weight: 900; letter-spacing: -0.04em; outline: none; }
.onboarding-card--welcome h2 { max-width: 380px; font-size: 32px; }
.onboarding-card p { margin: 0; font-size: 14px; line-height: 1.85; color: var(--ink-muted); }
.onboarding-card .onboarding-note { margin-top: 14px; font-size: 11px; line-height: 1.6; }
.onboarding-progress { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; font-size: 11px; font-weight: 800; font-variant-numeric: tabular-nums; }
.onboarding-progress__track { height: 5px; flex: 1; border: 1px solid var(--ink); background: var(--paper); }
.onboarding-progress__track > div { height: 100%; background: var(--acid); }
.onboarding-actions { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px; margin-top: 22px; padding-top: 16px; border-top: 1px dashed var(--rule-strong); }
.onboarding-actions__steps { display: flex; flex-wrap: wrap; gap: 10px; margin-left: auto; }
.onboarding-skip { padding: 6px 0; border: 0; background: transparent; color: var(--ink-muted); font-size: 12px; text-decoration: underline; text-underline-offset: 4px; cursor: pointer; }
.onboarding-next, .onboarding-back { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 9px 11px; border: 1.5px solid var(--ink); color: var(--ink); background: var(--paper); font-size: 12px; font-weight: 800; cursor: pointer; }
.onboarding-next { background: var(--acid); color: var(--acid-ink, #141913); box-shadow: 3px 3px 0 var(--ink); }
.onboarding-dialog button:disabled { opacity: 0.45; cursor: wait; box-shadow: none; }
.onboarding-dialog button:focus-visible { outline: 3px solid var(--ink); outline-offset: 3px; }
.onboarding-dialog button:not(:disabled):hover { filter: brightness(0.94); }
@media (max-width: 1023px) {
  .onboarding-card {
    display: flex; flex-direction: column; padding: 16px;
    max-width: calc(100vw - max(16px, env(safe-area-inset-left)) - max(16px, env(safe-area-inset-right)));
    max-height: calc(100dvh - max(16px, env(safe-area-inset-top)) - max(16px, env(safe-area-inset-bottom)));
    overflow: hidden; box-shadow: 4px 4px 0 var(--ink);
  }
  .onboarding-card--welcome { width: 432px; }
  .onboarding-topline, .onboarding-progress, .onboarding-emblem, .onboarding-actions, .onboarding-note { flex-shrink: 0; }
  .onboarding-topline { margin-bottom: 10px; }
  .onboarding-close { width: 44px; height: 44px; margin: -8px -8px -8px 0; }
  .onboarding-emblem { width: 58px; height: 58px; margin-bottom: 18px; }
  .onboarding-emblem svg { width: 36px; height: 36px; }
  .onboarding-card h2 { font-size: 22px; margin-bottom: 10px; }
  .onboarding-card--welcome h2 { font-size: 28px; }
  .onboarding-card p { line-height: 1.75; }
  .onboarding-copy { min-height: 0; overflow-y: auto; overscroll-behavior: contain; }
  .onboarding-actions { gap: 6px; margin-top: 16px; padding-top: 10px; }
  .onboarding-actions__steps { gap: 8px; }
  .onboarding-skip, .onboarding-next, .onboarding-back { min-height: 44px; }
}
@media (max-width: 1023px) and (max-height: 600px) {
  .onboarding-card { padding: 12px 16px; }
  .onboarding-topline { margin-bottom: 8px; }
  .onboarding-card h2 { font-size: 20px; }
  .onboarding-progress { margin-bottom: 10px; }
  .onboarding-actions { margin-top: 10px; padding-top: 8px; }
}
@media (max-width: 1023px) and (max-height: 500px) { .onboarding-emblem { display: none; } }
</style>
