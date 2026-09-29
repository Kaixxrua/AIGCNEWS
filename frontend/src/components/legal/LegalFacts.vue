<script setup lang="ts">
import type { Component } from 'vue'

defineProps<{ facts: { icon: Component; label: string; value: string }[] }>()
</script>

<template>
  <ul class="legal-facts">
    <li v-for="fact in facts" :key="fact.label" class="legal-fact">
      <component :is="fact.icon" aria-hidden="true" />
      <span>{{ fact.label }}</span>
      <strong>{{ fact.value }}</strong>
    </li>
  </ul>
</template>

<style scoped>
/* 摘自正文的要点数字，只在桌面漫画版展示（comic-pages.css）；窄屏正文已写明。 */
.legal-facts{display:none}
</style>
