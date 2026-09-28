<script setup lang="ts">
// Decorative torn-paper comic stickers for the editorial homepage: painted, transparent WebP layers
// laid over the page (see public/assets/comic/README.md). Every variant is aria-hidden: the slogans
// repeat nothing a reader needs. The two corners have their English slogans painted in; the rip
// beside the account menu is painted blank, so its localized slogan is live text.
import { computed } from 'vue'
import { letteringEm } from './comicLettering'

const props = defineProps<{ variant: 'corner' | 'shout' | 'peel'; text?: string }>()

// Intrinsic sizes, so the boxes never shift while the images load.
const ART = {
  corner: { src: '/assets/comic/tear-corner.webp', width: 720, height: 406 },
  shout: { src: '/assets/comic/tear-rip.webp', width: 900, height: 229 },
  peel: { src: '/assets/comic/tear-peel.webp', width: 720, height: 720 },
} as const

// Where the slogan sits in the rip's lime opening, in the rip image's pixels: the opening's fitted centre
// line, and the widest span along it that stays lime 40px either side (x 268–674), less the shadow offset.
const RIP_TEXT = { x: 471, y: 139, angle: -4.7, size: 70, maxLength: 380 }

const art = computed(() => ART[props.variant])
const slogan = computed(() => {
  const text = props.variant === 'shout' ? props.text?.trim() : ''
  if (!text) return null
  // textLength pins the slogan to its measured advance, capped to the opening, so a late or missing
  // font never spills it out of the rip.
  return { text, length: Math.min(letteringEm(text) * RIP_TEXT.size, RIP_TEXT.maxLength) }
})
</script>

<template>
  <span class="comic-sticker" :class="`comic-sticker--${variant}`" aria-hidden="true">
    <img class="comic-sticker__art" :src="art.src" :width="art.width" :height="art.height" alt="" loading="lazy" decoding="async" draggable="false">
    <svg v-if="slogan" class="comic-sticker__slogan" :viewBox="`0 0 ${art.width} ${art.height}`">
      <g :transform="`rotate(${RIP_TEXT.angle} ${RIP_TEXT.x} ${RIP_TEXT.y})`" :font-size="RIP_TEXT.size">
        <text class="comic-sticker__lettering comic-sticker__lettering--shadow" :x="RIP_TEXT.x + 7" :y="RIP_TEXT.y + 8" :textLength="slogan.length" lengthAdjust="spacingAndGlyphs" text-anchor="middle" dominant-baseline="central">{{ slogan.text }}</text>
        <text class="comic-sticker__lettering" :x="RIP_TEXT.x" :y="RIP_TEXT.y" :textLength="slogan.length" lengthAdjust="spacingAndGlyphs" text-anchor="middle" dominant-baseline="central">{{ slogan.text }}</text>
      </g>
    </svg>
  </span>
</template>

<style scoped>
/* Placement, size and visibility (display) belong to the owner; the art fills the box it is given,
   which the owner sizes to the image's aspect ratio. */
.comic-sticker { pointer-events:none;user-select:none; }
.comic-sticker__art,.comic-sticker__slogan { position:absolute;inset:0;width:100%;height:100%;overflow:visible; }
.comic-sticker__art { object-fit:contain; }
.comic-sticker--corner .comic-sticker__art { object-position:left top; }
.comic-sticker--peel .comic-sticker__art { object-position:right bottom; }
/* The paper is painted cream-white; dim it with the rest of the page in the dark theme. */
:root[data-theme='dark'] .comic-sticker__art { filter:brightness(.84) saturate(.9); }

.comic-sticker__lettering { fill:var(--sticker-ink);stroke:var(--tear-fiber);stroke-width:.16em;stroke-linejoin:round;paint-order:stroke;font-family:'AIGC Comic Lettering','DM Sans',sans-serif;font-weight:400;font-synthesis:none;letter-spacing:0; }
.comic-sticker__lettering--shadow { fill:var(--sticker-shadow);stroke:var(--sticker-shadow); }
</style>
