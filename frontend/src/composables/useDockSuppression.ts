import { computed, onActivated, onBeforeUnmount, onDeactivated, ref, watch } from 'vue'

// 模块级计数：任一全屏浮层（推文详情/图片放大等）打开期间 > 0。
// 计数而非布尔：多浮层/多视图叠加时后关者不抢回先开者的隐藏态。
const activeOverlayCount = ref(0)

/** 底部 dock 是否应隐藏（全屏浮层打开时避免遮挡卡片内容） */
export const dockSuppressed = computed(() => activeOverlayCount.value > 0)

/**
 * 声明「isOverlayOpen() 为 true 期间隐藏 dock」：watch 随源开合自动
 * 增减计数；组件卸载/keep-alive 停用时若仍占用自动归还，重新激活且
 * 浮层仍开着则恢复隐藏。调用方须在组件 setup 上下文使用。
 */
export function useDockSuppression(isOverlayOpen: () => boolean): void {
  let held = false
  const acquire = () => {
    if (held) return
    held = true
    activeOverlayCount.value += 1
  }
  const release = () => {
    if (!held) return
    held = false
    activeOverlayCount.value -= 1
  }
  watch(isOverlayOpen, (open) => (open ? acquire() : release()), { immediate: true })
  // keep-alive 视图带浮层被切走时归还（停用期间 watcher 仍存活，不重复计）；
  // 非 keep-alive 视图这两个钩子不触发，onBeforeUnmount 兜底
  onActivated(() => {
    if (isOverlayOpen()) acquire()
  })
  onDeactivated(release)
  onBeforeUnmount(release)
}
