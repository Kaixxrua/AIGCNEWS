<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Star } from 'lucide-vue-next'

/** 顶栏收藏入口 —— 跳转项目库「我的收藏」视图；未登录落地后由项目页引导登录 */
const { t } = useI18n()
const route = useRoute()

const isActive = computed(() => route.path === '/projects' && route.query.source === 'favorites')
</script>

<template>
  <RouterLink
    class="favorites-link"
    :class="{ 'favorites-link--active': isActive }"
    :to="{ path: '/projects', query: { source: 'favorites' } }"
    :aria-label="t('common.myFavorites')"
    :title="t('common.myFavorites')"
  >
    <Star
      class="favorites-link__icon"
      :size="18"
      :stroke-width="1.8"
      :fill="isActive ? 'currentColor' : 'none'"
      aria-hidden="true"
    />
  </RouterLink>
</template>

<style scoped>
.favorites-link {
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

.favorites-link:hover {
  color: var(--ink);
  background: var(--acid-soft);
  transform: rotate(-3deg);
}

.favorites-link:active { transform: rotate(-3deg) scale(0.92); }
.favorites-link:focus-visible { outline: 2px solid var(--acid); outline-offset: 2px; }

.favorites-link--active,
.favorites-link--active:hover {
  color: var(--acid);
  background: var(--acid-soft);
}

@media (prefers-reduced-motion: reduce) {
  .favorites-link { transition: none; }
  .favorites-link:hover,
  .favorites-link:active { transform: none; }
}
</style>
