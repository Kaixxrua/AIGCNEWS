<script setup lang="ts">
import { computed, ref, watch } from 'vue'

const props = defineProps<{ src?: string | null; name?: string | null }>()
const failed = ref(false)
watch(() => props.src, () => { failed.value = false })
const initial = computed(() => Array.from(props.name?.trim() || '?')[0]?.toLocaleUpperCase() || '?')
</script>

<template>
  <span class="user-avatar" aria-hidden="true">
    <img v-if="src && !failed" :src="src" alt="" @error="failed = true" />
    <span v-else>{{ initial }}</span>
  </span>
</template>

<style scoped>
.user-avatar {
  display: inline-flex;
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border: 1.5px solid var(--ink);
  border-radius: 50%;
  background: var(--paper-raised);
  color: var(--ink);
  font-size: 18px;
  font-weight: 800;
  line-height: 1;
}
.user-avatar img { width: 100%; height: 100%; object-fit: cover; }
</style>
