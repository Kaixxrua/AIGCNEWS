import { nextTick, onBeforeUnmount, watch, type Ref } from 'vue'

/*
 * 模态框的键盘约定：打开时焦点移进框内，Tab / Shift+Tab 只在框内循环，Esc 关闭，
 * 关闭后焦点回到打开前的位置。登录、注册、找回密码互相切换时，后开的框接手前一个框
 * 记下的返回位置；先关的框不会把焦点从新框里抢走。
 */

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

interface ReturnPosition {
  returnTo: HTMLElement | null
}

interface OpenDialog extends ReturnPosition {
  root: () => HTMLElement | null | undefined
}

// 按打开顺序排列；只有最上层的框响应按键。
const openDialogs: OpenDialog[] = []
// 刚关、焦点还没还回去的框。同一轮里接着打开的框接手它的返回位置：
// 从找回密码切回登录时，找回密码框先卸载，登录框随后才打开。
let handOff: ReturnPosition | null = null

const dialogContaining = (element: Element | null) =>
  element ? openDialogs.find(dialog => dialog.root()?.contains(element)) : undefined

export function useDialogFocus(isOpen: () => boolean, root: Ref<HTMLElement | null | undefined>, close: () => void) {
  let entry: OpenDialog | null = null

  const onKeydown = (event: KeyboardEvent) => {
    if (!entry || openDialogs[openDialogs.length - 1] !== entry || event.isComposing) return
    const container = root.value
    if (!container) return
    if (event.key === 'Escape') {
      event.preventDefault()
      close()
      return
    }
    if (event.key !== 'Tab') return
    const items = Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE))
      .filter(item => !item.closest('[hidden], [inert]'))
    const first = items[0]
    const last = items[items.length - 1]
    if (!first || !last) {
      event.preventDefault()
      container.focus()
      return
    }
    const active = document.activeElement
    const inside = active instanceof Node && active !== container && container.contains(active)
    if (!inside || active === (event.shiftKey ? first : last)) {
      event.preventDefault()
      ;(event.shiftKey ? last : first).focus()
    }
  }

  const capture = async () => {
    if (entry) return
    const active = document.activeElement
    const previous = dialogContaining(active) ?? handOff
    handOff = null
    entry = {
      root: () => root.value,
      returnTo: previous ? previous.returnTo : active instanceof HTMLElement && active !== document.body ? active : null,
    }
    openDialogs.push(entry)
    document.addEventListener('keydown', onKeydown)
    await nextTick()
    const container = root.value
    if (entry && container && !container.contains(document.activeElement)) container.focus()
  }

  const release = () => {
    if (!entry) return
    document.removeEventListener('keydown', onKeydown)
    openDialogs.splice(openDialogs.indexOf(entry), 1)
    const pending: ReturnPosition = { returnTo: entry.returnTo }
    entry = null
    handOff = pending
    // 等这一轮渲染完再还：框开着时 dock 被藏起来，卸载的那一刻打开它的按钮还聚焦不了。
    // 新框已经接手返回位置、或者焦点已经在新框里，就不抢回来。
    void nextTick(() => {
      if (handOff !== pending) return
      handOff = null
      if (dialogContaining(document.activeElement)) return
      if (pending.returnTo?.isConnected) pending.returnTo.focus()
    })
  }

  watch(isOpen, (open) => {
    if (open) void capture()
    else void nextTick().then(() => { if (!isOpen()) release() })
  }, { immediate: true, flush: 'post' })

  onBeforeUnmount(release)
}
