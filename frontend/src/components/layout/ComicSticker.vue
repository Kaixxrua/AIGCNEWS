<script setup lang="ts">
// Decorative comic stickers for the editorial homepage. Every variant is aria-hidden:
// the slogans repeat nothing a reader needs, and the slot text is purely ornamental.
defineProps<{ variant: 'burst' | 'shout' | 'label' }>()
</script>

<template>
  <span class="comic-sticker" :class="`comic-sticker--${variant}`" aria-hidden="true">
    <svg v-if="variant === 'burst'" class="comic-sticker__art" viewBox="0 0 216 92">
      <defs>
        <pattern id="comic-sticker-dots" width="5" height="5" patternUnits="userSpaceOnUse"><circle cx="2.5" cy="2.5" r="1" /></pattern>
      </defs>
      <g class="comic-sticker__impact">
        <path d="M100 17 L111 9" /><path d="M104 28 L118 24" /><path d="M94 8 L99 1" />
      </g>
      <path class="comic-sticker__shadow" transform="translate(4 4)" d="M95 37 L79 47 L90 57 L77 61 L85 78 L65 69 L63 84 L52 75 L43 88 L39 69 L21 82 L26 64 L12 63 L21 51 L3 44 L23 39 L10 24 L29 27 L25 10 L41 20 L47 7 L55 17 L69 4 L67 24 L83 21 L79 33Z" />
      <path class="comic-sticker__body" d="M95 37 L79 47 L90 57 L77 61 L85 78 L65 69 L63 84 L52 75 L43 88 L39 69 L21 82 L26 64 L12 63 L21 51 L3 44 L23 39 L10 24 L29 27 L25 10 L41 20 L47 7 L55 17 L69 4 L67 24 L83 21 L79 33Z" />
      <path class="comic-sticker__dots" fill="url(#comic-sticker-dots)" d="M95 37 L79 47 L90 57 L77 61 L85 78 L65 69 L63 84 L52 75 L43 88 L39 69 L21 82 L26 64 L12 63 L21 51 L3 44 L23 39 L10 24 L29 27 L25 10 L41 20 L47 7 L55 17 L69 4 L67 24 L83 21 L79 33Z" />
      <text class="comic-sticker__shout" x="49" y="58" text-anchor="middle" transform="rotate(-10 49 46)">AI!</text>
      <g transform="rotate(-6 140 71)">
        <path class="comic-sticker__shadow" transform="translate(3 3)" d="M72 60 L212 60 L202 71 L212 82 L72 82Z" />
        <path class="comic-sticker__ribbon" d="M72 60 L212 60 L202 71 L212 82 L72 82Z" />
        <text class="comic-sticker__ribbon-text" x="136" y="75.5" text-anchor="middle">BRIGHTER TOMORROW!</text>
      </g>
    </svg>

    <template v-else-if="variant === 'shout'">
      <svg class="comic-sticker__art" viewBox="0 0 232 70" preserveAspectRatio="none">
        <path class="comic-sticker__shadow" transform="translate(3 4)" d="M226 35 L207 39 L223 44 L198 46 L201 51 L181 52 L181 58 L157 55 L149 61 L132 58 L117 62 L104 57 L83 61 L78 54 L59 55 L57 50 L14 66 L44 45 L22 41 L33 37 L18 33 L37 29 L21 24 L46 22 L43 17 L63 16 L63 10 L87 13 L95 7 L112 10 L127 6 L140 11 L161 7 L166 14 L185 13 L187 18 L212 18 L200 25 L222 27 L211 31Z" />
        <path class="comic-sticker__body" d="M226 35 L207 39 L223 44 L198 46 L201 51 L181 52 L181 58 L157 55 L149 61 L132 58 L117 62 L104 57 L83 61 L78 54 L59 55 L57 50 L14 66 L44 45 L22 41 L33 37 L18 33 L37 29 L21 24 L46 22 L43 17 L63 16 L63 10 L87 13 L95 7 L112 10 L127 6 L140 11 L161 7 L166 14 L185 13 L187 18 L212 18 L200 25 L222 27 L211 31Z" />
      </svg>
      <svg class="comic-sticker__star" viewBox="0 0 48 56">
        <path d="m25 5 5 15 13 7-15 5-7 18-4-18L4 25l15-5Z" />
        <path class="comic-sticker__spark" d="m39 4 1.5 5L46 11l-5.5 2-2 5-1-5L32 11l5-2Z" />
      </svg>
      <span class="comic-sticker__text"><slot /></span>
    </template>

    <template v-else>
      <svg class="comic-sticker__art" viewBox="0 0 122 64">
        <defs>
          <pattern id="comic-sticker-label-dots" width="5" height="5" patternUnits="userSpaceOnUse"><circle cx="2.5" cy="2.5" r="1" /></pattern>
        </defs>
        <path class="comic-sticker__shadow" transform="translate(4 4)" d="M2 2 H118 V46 L102 60 H2Z" />
        <path class="comic-sticker__body" d="M2 2 H118 V46 L102 60 H2Z" />
        <path class="comic-sticker__dots" fill="url(#comic-sticker-label-dots)" d="M2 2 H118 V46 L102 60 H2Z" />
        <path class="comic-sticker__peel" d="M118 46 L102 60 L105 48Z" />
        <rect class="comic-sticker__tape" x="-8" y="-4" width="30" height="11" transform="rotate(-32 7 1)" />
      </svg>
      <span class="comic-sticker__text"><b>MORE</b><b>CREATORS!</b><small>A BRIGHTER WORLD</small></span>
    </template>
  </span>
</template>

<style scoped>
/* Placement and visibility (display) belong to the owner; the art only fills the box it is given. */
.comic-sticker { pointer-events:none;user-select:none; }
.comic-sticker__art { position:absolute;inset:0;width:100%;height:100%;overflow:visible; }
.comic-sticker__shadow { fill:var(--sticker-shadow); }
.comic-sticker__body { fill:var(--acid);stroke:var(--sticker-line);stroke-width:2.5;stroke-linejoin:round;vector-effect:non-scaling-stroke; }
.comic-sticker__dots { opacity:.16; }
.comic-sticker pattern circle { fill:var(--sticker-line); }
.comic-sticker__impact path { fill:none;stroke:var(--sticker-accent);stroke-width:3;stroke-linecap:round; }
.comic-sticker__shout { fill:var(--sticker-ink);font-size:35px;font-style:italic;font-weight:950;letter-spacing:-.02em; }
.comic-sticker__ribbon { fill:var(--sticker-line); }
.comic-sticker__ribbon-text { fill:var(--acid);font-size:10.5px;font-style:italic;font-weight:900;letter-spacing:0;white-space:pre;word-spacing:2px; }

/* Shout bubble: the text sits in HTML so it follows the locale and font metrics. */
.comic-sticker--shout .comic-sticker__art { transform:rotate(-3deg); }
.comic-sticker__star { position:absolute;left:-10px;top:-12px;width:42px;height:49px;overflow:visible;transform:rotate(-12deg); }
.comic-sticker__star path { fill:var(--comic-cyan-line);stroke:var(--sticker-line);stroke-width:2;stroke-linejoin:round; }
.comic-sticker__star .comic-sticker__spark { fill:var(--sticker-line);stroke:none; }
.comic-sticker--shout .comic-sticker__text { position:absolute;inset:6px 14px 14px 40px;display:flex;align-items:center;justify-content:center;color:var(--sticker-ink);font-size:20px;font-style:italic;font-weight:900;line-height:1;white-space:nowrap;transform:rotate(-4deg); }

/* Peeled label for the footer corner. */
.comic-sticker--label .comic-sticker__art { transform:rotate(-6deg); }
.comic-sticker__peel { fill:var(--sticker-peel);stroke:var(--sticker-line);stroke-width:2;stroke-linejoin:round; }
.comic-sticker__tape { fill:var(--sticker-tape); }
.comic-sticker--label .comic-sticker__text { position:absolute;inset:6px 10px 12px 10px;display:flex;flex-direction:column;justify-content:center;gap:1px;color:var(--sticker-ink);font-style:italic;line-height:1;transform:rotate(-6deg); }
.comic-sticker--label b { font-size:15px;font-weight:950;letter-spacing:-.01em; }
.comic-sticker--label small { margin-top:3px;padding-right:14px;font-size:8.5px;font-weight:850;letter-spacing:0;white-space:nowrap; }
</style>
