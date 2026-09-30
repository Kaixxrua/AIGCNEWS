<script setup lang="ts">
// Decorative torn-paper comic stickers for the editorial homepage: transparent WebP layers lifted pixel
// for pixel out of the approved concept images and laid over the page (see public/assets/comic/README.md).
// Every variant is aria-hidden: the slogans repeat nothing a reader needs. The two corners carry their
// English slogans in the art. The shout carries the Chinese slogan as painted; any other slogan is lettered
// live onto a copy with the painting's lettering removed.
import { computed } from 'vue'
import { letteringEm } from './comicLettering'

const props = defineProps<{ variant: 'corner' | 'shout' | 'peel'; text?: string }>()

// Intrinsic sizes, so the boxes never shift while the images load.
const ART = {
  corner: { src: '/assets/comic/tear-corner-v2.webp', width: 852, height: 345 },
  shout: { src: '/assets/comic/tear-shout.webp', width: 1101, height: 324 },
  peel: { src: '/assets/comic/tear-peel.webp', width: 1100, height: 713 },
} as const
const PAINTED_SHOUT = '让创造更自由！'
const BLANK_SHOUT = '/assets/comic/tear-shout-blank.webp'

// The painted slogan's centre line in the shout image's pixels, its angle, and the length it spans.
const SHOUT_TEXT = { x: 524, y: 157, angle: -9.8, size: 118, maxLength: 640 }

const slogan = computed(() => {
  const text = props.variant === 'shout' ? props.text?.trim() : ''
  if (!text || text === PAINTED_SHOUT) return null
  // textLength pins the slogan to its measured advance, capped to the painted slogan's span, so a late or
  // missing font never spills it out of the rip.
  return { text, length: Math.min(letteringEm(text) * SHOUT_TEXT.size, SHOUT_TEXT.maxLength) }
})
const art = computed(() => (slogan.value ? { ...ART.shout, src: BLANK_SHOUT } : ART[props.variant]))
</script>

<template>
  <span class="comic-sticker" :class="`comic-sticker--${variant}`" aria-hidden="true">
    <img class="comic-sticker__art" :src="art.src" :width="art.width" :height="art.height" alt="" loading="lazy" decoding="async" draggable="false">
    <svg v-if="slogan" class="comic-sticker__slogan" :viewBox="`0 0 ${art.width} ${art.height}`">
      <text
        class="comic-sticker__lettering"
        :x="SHOUT_TEXT.x"
        :y="SHOUT_TEXT.y"
        :transform="`rotate(${SHOUT_TEXT.angle} ${SHOUT_TEXT.x} ${SHOUT_TEXT.y})`"
        :font-size="SHOUT_TEXT.size"
        :textLength="slogan.length"
        lengthAdjust="spacingAndGlyphs"
        text-anchor="middle"
        dominant-baseline="central"
      >{{ slogan.text }}</text>
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
.comic-sticker--shout .comic-sticker__art { object-position:center bottom; }
.comic-sticker--peel .comic-sticker__art { object-position:right bottom; }
/* The paper is cream-white; dim it with the rest of the page in the dark theme. */
:root[data-theme='dark'] .comic-sticker__art { filter:brightness(.84) saturate(.9); }

/* Black brush lettering straight on the colour, like the painted slogan. */
.comic-sticker__lettering { fill:var(--sticker-ink);font-family:'AIGC Comic Lettering','DM Sans',sans-serif;font-weight:400;font-synthesis:none;letter-spacing:0; }
</style>
