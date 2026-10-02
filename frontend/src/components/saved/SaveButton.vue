<script setup lang="ts">
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Bookmark } from 'lucide-vue-next'
import { canAnimate, popSpring } from '@/motion/motion'

/**
 * 收藏书签：空心是没收，实心是收下了，收下的那一下盖章式弹一下（减少动态时直接换）。读屏一直念「收藏」，
 * 收没收下由 aria-pressed 交代；悬停提示说清按下去会怎样。label 为真时书签旁边带字（推文详情的底栏）。
 */
const props = defineProps<{ saved: boolean; label?: boolean }>()
const emit = defineEmits<{ toggle: [] }>()
const { t } = useI18n()
const button = ref<HTMLButtonElement | null>(null)

watch(() => props.saved, (saved) => {
  const icon = button.value?.querySelector('svg')
  if (saved && icon && canAnimate(icon)) icon.animate([{ scale: '0.6' }, { scale: '1' }], { duration: 420, easing: popSpring() })
})
</script>

<template>
  <button
    ref="button"
    type="button"
    class="save-toggle"
    :class="{ 'is-saved': saved }"
    :aria-pressed="saved"
    :aria-label="t('saved.save')"
    :title="t(saved ? 'saved.unsaveTitle' : 'saved.saveTitle')"
    @click="emit('toggle')"
  >
    <Bookmark aria-hidden="true" />
    <span v-if="label">{{ t(saved ? 'saved.savedLabel' : 'saved.save') }}</span>
  </button>
</template>

<style scoped>
.save-toggle svg {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}

/* 收下了：书签填实，颜色随所在的钮 */
.save-toggle.is-saved svg { fill: currentColor; }
</style>
