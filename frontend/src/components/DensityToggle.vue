<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ListChevronsDownUp, ListChevronsUpDown } from 'lucide-vue-next'
import { useAppDensity } from '@/composables/useAppDensity'
import { vSwap } from '@/motion/swap'

/** 报眉的版面密度开关：紧凑（默认）与舒适两档。和主题开关一样，图标与提示说的是按下去换成哪一档。 */
const { t } = useI18n()
const { density, comfortable, toggle } = useAppDensity()

const targetLabel = computed(() => t(comfortable.value ? 'density.toCompact' : 'density.toComfortable'))
</script>

<template>
  <button
    type="button"
    class="density-toggle"
    :aria-label="targetLabel"
    :title="targetLabel"
    @click="toggle"
  >
    <!-- 换档时新图标顺着展开或收拢的方向滑进来 -->
    <span v-swap="{ key: density, y: comfortable ? -4 : 4 }" class="density-toggle__glyph">
      <ListChevronsDownUp v-if="comfortable" :size="20" :stroke-width="1.7" aria-hidden="true" />
      <ListChevronsUpDown v-else :size="20" :stroke-width="1.7" aria-hidden="true" />
    </span>
  </button>
</template>

<style scoped>
.density-toggle {
  display: inline-grid;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: 50%;
  color: var(--ink-muted);
  background: transparent;
  cursor: pointer;
  transition: color 150ms ease, background-color 150ms ease, transform 150ms ease;
}

.density-toggle:hover {
  color: var(--ink);
  background: var(--acid-soft);
  transform: rotate(-3deg);
}

.density-toggle:active { transform: rotate(-3deg) scale(0.92); }
.density-toggle:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }

.density-toggle__glyph { display: inline-grid; place-items: center; }
/* 三条横线是版面，两枚箭头是动作：箭头用荧光笔色，和主题、语言开关的点缀一致 */
.density-toggle__glyph :deep(path:nth-of-type(n + 4)) { stroke: var(--acid); stroke-width: 2.2; }

@media (prefers-reduced-motion: reduce) {
  .density-toggle { transition: none; }
  .density-toggle:hover,
  .density-toggle:active { transform: none; }
}
</style>
