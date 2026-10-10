<script setup lang="ts">
import { useMediaQuery } from '@vueuse/core'

const reducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)')
</script>

<template>
  <Transition name="auth-dialog" :duration="reducedMotion ? 0 : { enter: 300, leave: 180 }" appear>
    <slot />
  </Transition>
</template>

<style>
.auth-dialog__panel .auth-page-header { animation: none; }
.auth-dialog-enter-active { transition: opacity 180ms var(--motion-ease-out); }
.auth-dialog-leave-active { transition: opacity 180ms var(--motion-ease-in); }
.auth-dialog-enter-active .auth-dialog__panel {
  transition: opacity 240ms var(--motion-ease-out) 40ms, transform 260ms var(--motion-ease-out) 40ms;
}
.auth-dialog-leave-active .auth-dialog__panel {
  transition: opacity 140ms ease, transform 180ms var(--motion-ease-in);
}
.auth-dialog-enter-from, .auth-dialog-leave-to { opacity: 0; }
.auth-dialog-enter-from .auth-dialog__panel { opacity: 0; transform: translateY(12px) scale(.985); }
.auth-dialog-leave-to .auth-dialog__panel { opacity: 0; transform: translateY(6px) scale(.99); }
@media (prefers-reduced-motion: reduce) {
  .auth-dialog-enter-active, .auth-dialog-leave-active,
  .auth-dialog-enter-active .auth-dialog__panel, .auth-dialog-leave-active .auth-dialog__panel { transition: none; }
  .auth-dialog-enter-from .auth-dialog__panel, .auth-dialog-leave-to .auth-dialog__panel { transform: none; }
}
</style>
