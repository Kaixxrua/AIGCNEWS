<script setup lang="ts">
defineProps<{
  title: string
  description: string
}>()
</script>

<template>
  <div class="mb-8 text-center stagger-enter">
    <div class="mb-4 inline-flex h-14 w-14 items-center justify-center rounded-3xl bg-stone-100">
      <slot />
    </div>
    <h1 class="text-2xl font-bold text-stone-800 tracking-tight font-serif">{{ title }}</h1>
    <p class="mt-1 text-sm text-stone-400">{{ description }}</p>
  </div>
</template>
