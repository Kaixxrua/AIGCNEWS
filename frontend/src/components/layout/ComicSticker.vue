<script setup lang="ts">
// Decorative torn-paper comic stickers for the editorial homepage. Every variant is aria-hidden:
// the slogans repeat nothing a reader needs.
import { computed, onBeforeUnmount, onMounted, ref, useId } from 'vue'
import { CORNER, PEEL, buildShout } from './comicTear'

const props = defineProps<{ variant: 'corner' | 'shout' | 'peel'; text?: string }>()

const uid = `comic-${useId().replace(/[^\w-]/g, '')}`
const root = ref<HTMLElement | null>(null)
const box = ref({ width: 0, height: 0 })
let observer: ResizeObserver | null = null

// The shout tears to the exact box it gets; the torn corners scale a fixed drawing.
onMounted(() => {
  if (props.variant !== 'shout' || typeof ResizeObserver === 'undefined' || !root.value) return
  observer = new ResizeObserver(([entry]) => {
    if (entry) box.value = { width: Math.floor(entry.contentRect.width), height: Math.floor(entry.contentRect.height) }
  })
  observer.observe(root.value)
})
onBeforeUnmount(() => observer?.disconnect())

const shout = computed(() => props.variant === 'shout' ? buildShout(box.value.width, box.value.height, props.text ?? '') : null)
const rotate = (angle: number, cx: number, cy: number) => `rotate(${angle.toFixed(2)} ${cx.toFixed(1)} ${cy.toFixed(1)})`
</script>

<template>
  <span ref="root" class="comic-sticker" :class="[`comic-sticker--${variant}`, shout && `comic-sticker--${shout.tier}`]" aria-hidden="true">
    <svg v-if="variant === 'corner'" class="comic-sticker__art" :viewBox="`0 0 ${CORNER.width} ${CORNER.height}`">
      <defs>
        <clipPath :id="`${uid}-hole`"><path :d="CORNER.hole" /></clipPath>
        <pattern :id="`${uid}-dots`" width="5" height="5" patternUnits="userSpaceOnUse"><circle cx="2.5" cy="2.5" r="1.05" /></pattern>
      </defs>
      <g :clip-path="`url(#${uid}-hole)`">
        <path class="comic-sticker__lime" :d="CORNER.hole" />
        <path class="comic-sticker__focus" :d="CORNER.focus" />
        <path class="comic-sticker__halftone" :fill="`url(#${uid}-dots)`" :d="CORNER.hole" />
      </g>
      <path class="comic-sticker__fiber comic-sticker__fiber--bare" :d="CORNER.fiber" />
      <path class="comic-sticker__seam" :d="CORNER.seam" />
      <path class="comic-sticker__edge" :d="CORNER.edge" />
      <path v-for="(d, i) in CORNER.scraps" :key="`s${i}`" class="comic-sticker__flap" :d="d" />
      <path v-for="(d, i) in CORNER.impact" :key="`i${i}`" class="comic-sticker__line" :d="d" />
      <path class="comic-sticker__shadow" transform="translate(3 3)" :d="CORNER.bolt" />
      <path class="comic-sticker__bolt" :d="CORNER.bolt" />
      <g :transform="rotate(CORNER.shout.angle, CORNER.shout.cx, CORNER.shout.cy)" :font-size="CORNER.shout.size">
        <text class="comic-sticker__lettering comic-sticker__lettering--shadow" :x="CORNER.shout.x + 3.5" :y="CORNER.shout.y + 4" :textLength="CORNER.shout.length" lengthAdjust="spacingAndGlyphs" text-anchor="middle">AI!</text>
        <text class="comic-sticker__lettering comic-sticker__lettering--hero" :x="CORNER.shout.x" :y="CORNER.shout.y" :textLength="CORNER.shout.length" lengthAdjust="spacingAndGlyphs" text-anchor="middle">AI!</text>
      </g>
      <g :transform="CORNER.ribbon.transform">
        <path class="comic-sticker__shadow" transform="translate(2.5 2.5)" :d="CORNER.ribbon.body" />
        <path class="comic-sticker__ribbon" :d="CORNER.ribbon.body" />
        <text class="comic-sticker__lettering" :x="CORNER.ribbon.text.x" :y="CORNER.ribbon.text.y" :font-size="CORNER.ribbon.text.size" :textLength="CORNER.ribbon.text.length" lengthAdjust="spacingAndGlyphs" text-anchor="middle">BRIGHTER TOMORROW!</text>
      </g>
    </svg>

    <svg v-else-if="variant === 'shout' && shout" class="comic-sticker__art" :viewBox="`0 0 ${shout.width} ${shout.height}`">
      <defs>
        <clipPath :id="`${uid}-rip`"><path :d="shout.hole" /></clipPath>
        <pattern :id="`${uid}-dots`" width="6" height="6" patternUnits="userSpaceOnUse"><circle cx="3" cy="3" r="1.25" /></pattern>
      </defs>
      <path v-for="(d, i) in shout.speed" :key="`v${i}`" class="comic-sticker__line" :d="d" />
      <path v-for="(d, i) in shout.splats" :key="`p${i}`" class="comic-sticker__splat" :d="d" />
      <circle v-for="(drop, i) in shout.drops" :key="`d${i}`" class="comic-sticker__splat" v-bind="drop" />
      <path v-if="shout.crack" class="comic-sticker__line comic-sticker__line--thin" :d="shout.crack" />
      <path class="comic-sticker__fiber" :d="shout.rim" />
      <g :clip-path="`url(#${uid}-rip)`">
        <path class="comic-sticker__shout-deep" :d="shout.hole" />
        <path class="comic-sticker__shout-fill" :d="shout.shade" />
        <path class="comic-sticker__halftone comic-sticker__halftone--shout" :fill="`url(#${uid}-dots)`" :d="shout.hole" />
      </g>
      <path class="comic-sticker__seam" :d="shout.hole" />
      <path v-for="(d, i) in shout.scraps" :key="`s${i}`" class="comic-sticker__flap" :d="d" />
      <g :transform="rotate(-shout.text.angle, shout.text.cx, shout.text.cy)" :font-size="shout.text.size.toFixed(1)">
        <text class="comic-sticker__lettering comic-sticker__lettering--shadow" :x="shout.text.x + shout.text.size * 0.07" :y="shout.text.y + shout.text.size * 0.08" :textLength="shout.text.length" lengthAdjust="spacingAndGlyphs" text-anchor="middle">{{ text }}</text>
        <text class="comic-sticker__lettering comic-sticker__lettering--outline" :x="shout.text.x" :y="shout.text.y" :textLength="shout.text.length" lengthAdjust="spacingAndGlyphs" text-anchor="middle">{{ text }}</text>
        <text class="comic-sticker__lettering comic-sticker__lettering--heavy" :x="shout.text.x" :y="shout.text.y" :textLength="shout.text.length" lengthAdjust="spacingAndGlyphs" text-anchor="middle">{{ text }}</text>
      </g>
    </svg>

    <svg v-else-if="variant === 'peel'" class="comic-sticker__art" :viewBox="`0 0 ${PEEL.width} ${PEEL.height}`">
      <defs>
        <clipPath :id="`${uid}-hole`"><path :d="PEEL.hole" /></clipPath>
        <pattern :id="`${uid}-dots`" width="6" height="6" patternUnits="userSpaceOnUse"><circle cx="3" cy="3" r="1.3" /></pattern>
      </defs>
      <g :clip-path="`url(#${uid}-hole)`">
        <path class="comic-sticker__lime" :d="PEEL.hole" />
        <path class="comic-sticker__focus" :d="PEEL.focus" />
        <path class="comic-sticker__halftone" :fill="`url(#${uid}-dots)`" :d="PEEL.hole" />
        <image href="/assets/comic/sticker-robot-burst.webp" v-bind="PEEL.robot" />
      </g>
      <path class="comic-sticker__fiber comic-sticker__fiber--bare" :d="PEEL.fiber" />
      <path class="comic-sticker__seam" :d="PEEL.seam" />
      <path class="comic-sticker__edge" :d="PEEL.edge" />
      <path v-for="(d, i) in PEEL.scraps" :key="`s${i}`" class="comic-sticker__flap" :d="d" />
      <g :transform="PEEL.caption.transform">
        <rect class="comic-sticker__shadow" v-bind="PEEL.caption.rect" transform="translate(3 3)" />
        <rect class="comic-sticker__caption" v-bind="PEEL.caption.rect" />
        <text v-for="line in PEEL.lines" :key="line.text" class="comic-sticker__lettering" :x="PEEL.caption.rect.x + PEEL.caption.rect.width / 2" :y="line.y" :font-size="line.size" :textLength="line.length" lengthAdjust="spacingAndGlyphs" text-anchor="middle">{{ line.text }}</text>
        <text class="comic-sticker__lettering" :x="PEEL.caption.rect.x + PEEL.caption.rect.width / 2" :y="PEEL.small.y" :font-size="PEEL.small.size" :textLength="PEEL.small.length" lengthAdjust="spacingAndGlyphs" text-anchor="middle">{{ PEEL.small.text }}</text>
      </g>
    </svg>
  </span>
</template>

<style scoped>
/* Placement, size and visibility (display) belong to the owner; the art only fills the box it is given. */
.comic-sticker { pointer-events:none;user-select:none; }
.comic-sticker__art { position:absolute;inset:0;width:100%;height:100%;overflow:visible; }
/* The rip is torn to its box, so nothing it draws may leave the slot beside the account menu. */
.comic-sticker--shout .comic-sticker__art { overflow:hidden; }

.comic-sticker__fiber { fill:var(--tear-fiber);stroke:var(--sticker-line);stroke-width:2.2;stroke-linejoin:round; }
.comic-sticker__fiber--bare { stroke:none; }
.comic-sticker__edge { fill:none;stroke:var(--sticker-line);stroke-width:2.4;stroke-linejoin:round;stroke-linecap:round; }
.comic-sticker__seam { fill:none;stroke:var(--sticker-line);stroke-width:1;stroke-linejoin:round;stroke-linecap:round;opacity:.72; }
.comic-sticker__flap { fill:var(--tear-fiber);stroke:var(--sticker-line);stroke-width:1.6;stroke-linejoin:round; }
.comic-sticker__lime { fill:var(--acid); }
.comic-sticker__shout-fill { fill:var(--shout-fill); }
.comic-sticker__shout-deep { fill:var(--shout-deep); }
.comic-sticker__splat { fill:var(--shout-deep); }
.comic-sticker__focus { fill:none;stroke:var(--sticker-line);stroke-width:.8;opacity:.4; }
.comic-sticker pattern circle { fill:var(--sticker-line); }
.comic-sticker__halftone { opacity:.2; }
.comic-sticker__halftone--shout { opacity:.24; }
.comic-sticker__line { fill:none;stroke:var(--sticker-line);stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round; }
.comic-sticker__line--thin { stroke-width:1.3; }
.comic-sticker__shadow { fill:var(--sticker-shadow); }
.comic-sticker__caption { fill:var(--tear-fiber);stroke:var(--sticker-line);stroke-width:2;stroke-linejoin:round; }
.comic-sticker__ribbon { fill:var(--tear-fiber);stroke:var(--sticker-line);stroke-width:2;stroke-linejoin:round; }
.comic-sticker__bolt { fill:var(--sticker-bolt);stroke:var(--sticker-line);stroke-width:2.4;stroke-linejoin:round; }

.comic-sticker__lettering { fill:var(--sticker-ink);font-family:'AIGC Comic Lettering','DM Sans',sans-serif;font-weight:400;font-synthesis:none;letter-spacing:0; }
.comic-sticker__lettering--shadow { fill:var(--sticker-shadow);stroke:var(--sticker-shadow);stroke-width:.22em;stroke-linejoin:round; }
.comic-sticker__lettering--outline { stroke:var(--tear-fiber);stroke-width:.2em;stroke-linejoin:round;paint-order:stroke; }
.comic-sticker__lettering--heavy { stroke:var(--sticker-ink);stroke-width:.035em;stroke-linejoin:round; }
/* Hero lettering: paper-white letters inside a heavy ink outline, as in the masthead corner's "AI!". */
.comic-sticker__lettering--hero { fill:var(--tear-fiber);stroke:var(--sticker-line);stroke-width:.1em;stroke-linejoin:round;paint-order:stroke; }
</style>
