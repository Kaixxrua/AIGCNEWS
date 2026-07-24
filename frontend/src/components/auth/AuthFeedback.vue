<script setup lang="ts">
defineProps<{
  message: string
  type: 'error' | 'success'
}>()
</script>

<template>
  <Transition name="fade-msg">
    <div
      v-if="message"
      class="flex items-center gap-2 rounded-2xl px-4 py-2.5 text-sm border"
      :class="type === 'error'
        ? 'bg-rose-50 text-rose-600 border-rose-200'
        : 'bg-green-50 text-green-700 border-green-200'"
    >
      <svg v-if="type === 'error'" class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
      </svg>
      <svg v-else class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <polyline points="20 6 9 17 4 12"/>
      </svg>
      {{ message }}
    </div>
  </Transition>
</template>

<style scoped>
.fade-msg-enter-active,
.fade-msg-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}
.fade-msg-enter-from,
.fade-msg-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
