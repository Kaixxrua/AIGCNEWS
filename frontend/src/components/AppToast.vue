<script setup lang="ts">
import { useToasts } from '@/composables/useToast'

const { toasts } = useToasts()
</script>

<template>
  <div class="app-toast-stack" role="status" aria-live="polite">
    <TransitionGroup name="app-toast">
      <p v-for="item in toasts" :key="item.id" class="app-toast">
        {{ item.message }}
      </p>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.app-toast-stack {
  position: fixed;
  bottom: 28px;
  left: 50%;
  z-index: 120;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  pointer-events: none;
  transform: translateX(-50%);
}

.app-toast {
  margin: 0;
  border: 1px solid var(--ink, #11110f);
  border-radius: 6px;
  padding: 10px 18px;
  color: var(--paper-raised, #fffdf5);
  background: var(--ink, #11110f);
  box-shadow: 4px 4px 0 var(--toast-shadow);
  font-size: 13px;
  font-weight: 600;
  line-height: 1.4;
}

.app-toast-enter-active,
.app-toast-leave-active {
  transition: opacity 180ms ease, transform 180ms ease;
}
.app-toast-enter-from,
.app-toast-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
