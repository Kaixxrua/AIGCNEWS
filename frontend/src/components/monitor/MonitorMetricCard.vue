<script setup lang="ts">
// Adapted from shadcn/ui dashboard-01 SectionCards, MIT; see adjacent license.
defineProps<{ label: string; value: string | number; note?: string }>()
</script>

<template>
  <article class="metric-card">
    <header class="relative">
      <p class="monitor-caption text-xs">{{ label }}</p>
      <p class="mt-2 text-2xl font-semibold tabular-nums">{{ value }}</p>
    </header>
    <footer v-if="note || $slots.default" class="mt-4 flex flex-col items-start gap-1 text-xs monitor-caption">
      <slot>{{ note }}</slot>
    </footer>
  </article>
</template>

<style scoped>
.metric-card {
  min-width: 0;
  padding: 20px;
  border: 1px solid var(--rule);
  border-radius: 12px;
  background: linear-gradient(to top, color-mix(in srgb, var(--projects-accent) 5%, transparent), transparent);
  color: var(--ink);
  box-shadow: 0 1px 2px rgb(0 0 0 / 3%);
}
</style>
