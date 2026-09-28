<script setup lang="ts">
// Decorative torn-paper comic stickers for the editorial homepage. Every variant is aria-hidden:
// the slogans repeat nothing a reader needs.
import { computed, onBeforeUnmount, onMounted, ref, useId } from 'vue'
import { BURST, LABEL, buildShout } from './comicTear'

const props = defineProps<{ variant: 'burst' | 'shout' | 'label'; text?: string }>()

const uid = `comic-${useId().replace(/[^\w-]/g, '')}`
const root = ref<HTMLElement | null>(null)
const box = ref({ width: 0, height: 0 })
let observer: ResizeObserver | null = null

// The shout tears to the exact box it gets; burst and label scale a fixed drawing.
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
    <svg v-if="variant === 'burst'" class="comic-sticker__art" :viewBox="`0 0 ${BURST.width} ${BURST.height}`">
      <defs>
        <clipPath :id="`${uid}-hole`"><path :d="BURST.hole" /></clipPath>
        <pattern :id="`${uid}-dots`" width="4.5" height="4.5" patternUnits="userSpaceOnUse"><circle cx="2.25" cy="2.25" r=".95" /></pattern>
      </defs>
      <path class="comic-sticker__fiber" :d="BURST.rim" />
      <g :clip-path="`url(#${uid}-hole)`">
        <path class="comic-sticker__lime" :d="BURST.hole" />
        <path class="comic-sticker__focus" :d="BURST.focus" />
        <path class="comic-sticker__halftone" :fill="`url(#${uid}-dots)`" :d="BURST.hole" />
      </g>
      <path class="comic-sticker__seam" :d="BURST.hole" />
      <image href="/assets/comic/sticker-robot-burst.webp" v-bind="BURST.robot" />
      <path class="comic-sticker__cover" :d="BURST.cover" />
      <path class="comic-sticker__fiber comic-sticker__fiber--bare" :d="BURST.lipFiber" />
      <path class="comic-sticker__seam" :d="BURST.lipSeam" />
      <path class="comic-sticker__edge" :d="BURST.lip" />
      <g v-for="(flap, i) in BURST.flaps" :key="i">
        <path class="comic-sticker__flap" :d="flap.body" />
        <path class="comic-sticker__seam" :d="flap.crease" />
      </g>
      <path v-for="(d, i) in BURST.scraps" :key="`s${i}`" class="comic-sticker__flap" :d="d" />
      <path class="comic-sticker__shadow" transform="translate(3 3)" :d="BURST.balloon" />
      <path class="comic-sticker__balloon" :d="BURST.balloon" />
      <text class="comic-sticker__lettering" :x="BURST.shout.x" :y="BURST.shout.y" :font-size="BURST.shout.size" :textLength="BURST.shout.length" lengthAdjust="spacingAndGlyphs" text-anchor="middle" :transform="rotate(BURST.shout.angle, BURST.shout.cx, BURST.shout.cy)">AI!</text>
      <g :transform="BURST.ribbon.transform">
        <path class="comic-sticker__shadow" transform="translate(3 3)" :d="BURST.ribbon.body" />
        <path class="comic-sticker__ribbon" :d="BURST.ribbon.body" />
        <text class="comic-sticker__lettering" :x="BURST.ribbon.text.x" :y="BURST.ribbon.text.y" :font-size="BURST.ribbon.text.size" :textLength="BURST.ribbon.text.length" lengthAdjust="spacingAndGlyphs" text-anchor="middle">BRIGHTER TOMORROW!</text>
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
        <path class="comic-sticker__cyan-deep" :d="shout.hole" />
        <path class="comic-sticker__cyan" :d="shout.shade" />
        <path class="comic-sticker__halftone comic-sticker__halftone--cyan" :fill="`url(#${uid}-dots)`" :d="shout.hole" />
      </g>
      <path class="comic-sticker__seam" :d="shout.hole" />
      <path v-for="(d, i) in shout.scraps" :key="`s${i}`" class="comic-sticker__flap" :d="d" />
      <g :transform="rotate(-shout.text.angle, shout.text.cx, shout.text.cy)" :font-size="shout.text.size.toFixed(1)">
        <text class="comic-sticker__lettering comic-sticker__lettering--shadow" :x="shout.text.x + shout.text.size * 0.07" :y="shout.text.y + shout.text.size * 0.08" :textLength="shout.text.length" lengthAdjust="spacingAndGlyphs" text-anchor="middle">{{ text }}</text>
        <text class="comic-sticker__lettering comic-sticker__lettering--outline" :x="shout.text.x" :y="shout.text.y" :textLength="shout.text.length" lengthAdjust="spacingAndGlyphs" text-anchor="middle">{{ text }}</text>
        <text class="comic-sticker__lettering comic-sticker__lettering--heavy" :x="shout.text.x" :y="shout.text.y" :textLength="shout.text.length" lengthAdjust="spacingAndGlyphs" text-anchor="middle">{{ text }}</text>
      </g>
    </svg>

    <svg v-else-if="variant === 'label'" class="comic-sticker__art" :viewBox="`0 0 ${LABEL.width} ${LABEL.height}`">
      <defs>
        <clipPath :id="`${uid}-corner`"><path :d="LABEL.reveal" /></clipPath>
        <pattern :id="`${uid}-dots`" width="5.5" height="5.5" patternUnits="userSpaceOnUse"><circle cx="2.75" cy="2.75" r="1.2" /></pattern>
      </defs>
      <g :clip-path="`url(#${uid}-corner)`">
        <path class="comic-sticker__lime" :d="LABEL.reveal" />
        <path class="comic-sticker__focus" :d="LABEL.focus" />
        <path class="comic-sticker__halftone" :fill="`url(#${uid}-dots)`" :d="LABEL.reveal" />
      </g>
      <path class="comic-sticker__fiber comic-sticker__fiber--bare" :d="LABEL.fiber" />
      <path class="comic-sticker__seam" :d="LABEL.seam" />
      <path class="comic-sticker__edge" :d="LABEL.edge" />
      <image href="/assets/comic/sticker-robot-fist.webp" v-bind="LABEL.fist" />
      <g :transform="LABEL.caption.transform">
        <rect class="comic-sticker__shadow" v-bind="LABEL.caption.rect" transform="translate(3 3)" />
        <rect class="comic-sticker__caption" v-bind="LABEL.caption.rect" />
        <text v-for="line in LABEL.lines" :key="line.text" class="comic-sticker__lettering" x="43" :y="line.y" :font-size="line.size" :textLength="line.length" lengthAdjust="spacingAndGlyphs" text-anchor="middle">{{ line.text }}</text>
        <text class="comic-sticker__lettering comic-sticker__small" x="43" :y="LABEL.small.y" :font-size="LABEL.small.size" :textLength="LABEL.small.length" lengthAdjust="spacingAndGlyphs" text-anchor="middle">{{ LABEL.small.text }}</text>
      </g>
    </svg>
  </span>
</template>

<style scoped>
/* Placement, size and visibility (display) belong to the owner; the art only fills the box it is given. */
.comic-sticker { pointer-events:none;user-select:none; }
.comic-sticker--label { container-type:inline-size; }
.comic-sticker__art { position:absolute;inset:0;width:100%;height:100%;overflow:visible; }
/* The rip is torn to its box, so nothing it draws may leave the slot beside the account menu. */
.comic-sticker--shout .comic-sticker__art { overflow:hidden; }

.comic-sticker__fiber { fill:var(--tear-fiber);stroke:var(--sticker-line);stroke-width:2.2;stroke-linejoin:round; }
.comic-sticker__fiber--bare { stroke:none; }
.comic-sticker__edge { fill:none;stroke:var(--sticker-line);stroke-width:2.2;stroke-linejoin:round;stroke-linecap:round; }
.comic-sticker__seam { fill:none;stroke:var(--sticker-line);stroke-width:1;stroke-linejoin:round;stroke-linecap:round;opacity:.72; }
.comic-sticker__cover { fill:var(--paper); }
.comic-sticker__flap { fill:var(--tear-fiber);stroke:var(--sticker-line);stroke-width:1.6;stroke-linejoin:round; }
.comic-sticker__lime { fill:var(--acid); }
.comic-sticker__cyan { fill:var(--comic-cyan-line); }
.comic-sticker__cyan-deep { fill:var(--tear-cyan-deep); }
.comic-sticker__splat { fill:var(--comic-cyan-line); }
.comic-sticker__focus { fill:none;stroke:var(--sticker-line);stroke-width:.8;opacity:.4; }
.comic-sticker pattern circle { fill:var(--sticker-line); }
.comic-sticker__halftone { opacity:.2; }
.comic-sticker__halftone--cyan { opacity:.3; }
.comic-sticker__line { fill:none;stroke:var(--sticker-line);stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round; }
.comic-sticker__line--thin { stroke-width:1.3; }
.comic-sticker__shadow { fill:var(--sticker-shadow); }
.comic-sticker__balloon, .comic-sticker__caption { fill:var(--tear-fiber);stroke:var(--sticker-line);stroke-width:2.4;stroke-linejoin:round; }
.comic-sticker__caption { stroke-width:2; }
.comic-sticker__ribbon { fill:var(--acid);stroke:var(--sticker-line);stroke-width:2;stroke-linejoin:round; }

.comic-sticker__lettering { fill:var(--sticker-ink);font-family:'AIGC Comic Lettering','DM Sans',sans-serif;font-weight:400;font-synthesis:none;letter-spacing:0; }
.comic-sticker__lettering--shadow { fill:var(--sticker-shadow);stroke:var(--sticker-shadow);stroke-width:.22em;stroke-linejoin:round; }
.comic-sticker__lettering--outline { stroke:var(--tear-fiber);stroke-width:.2em;stroke-linejoin:round;paint-order:stroke; }
.comic-sticker__lettering--heavy { stroke:var(--sticker-ink);stroke-width:.035em;stroke-linejoin:round; }

/* The 1600–1799px footer box is ~130px wide, where the small line would drop below 7px. */
@container (max-width: 139px) {
  .comic-sticker__small { display:none; }
}
</style>
