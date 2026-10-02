<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { X } from 'lucide-vue-next'
import { popIn, popOut } from '@/motion/presence'

/**
 * 列表键盘流的快捷键表：按 ? 在右下角浮出，再按 ?、Esc、点它外面或点 × 收起。不抢焦点，开着也能接着按 j / k。
 * actions 交代这一列表上 o、s、x 各做什么，没给的键不列；extra 是这一列表另有的键位。
 */
interface KeyRow { keys: string[]; label: string }

const props = defineProps<{
  actions: { open?: string; save?: string; toggle?: string }
  extra?: KeyRow[]
}>()
const open = defineModel<boolean>('open', { required: true })

const { t } = useI18n()
const sheet = ref<HTMLElement | null>(null)

const rows = computed<KeyRow[]>(() => [
  { keys: ['j', 'k'], label: t('listKeys.move') },
  ...(props.actions.open ? [{ keys: ['o', '↵'], label: props.actions.open }] : []),
  ...(props.actions.save ? [{ keys: ['s'], label: props.actions.save }] : []),
  ...(props.actions.toggle ? [{ keys: ['x'], label: props.actions.toggle }] : []),
  ...(props.extra ?? []),
  { keys: ['?'], label: t('listKeys.help') },
  { keys: ['Esc'], label: t('listKeys.escape') },
])

// 宽屏内容页的右下角立着页脚卷角贴纸，卷尖高过页脚；打开时量一下，有就让到它上面
const BOTTOM = 96
const bottom = ref(BOTTOM)
const clearPeel = () => {
  const peel = document.querySelector('.comic-footer-sticker')
  const top = peel && peel.getClientRects().length ? peel.getBoundingClientRect().top : Infinity
  bottom.value = Math.max(BOTTOM, Math.round(window.innerHeight - top + 12))
}

const onPointerdown = (event: PointerEvent) => {
  if (!sheet.value?.contains(event.target as Node)) open.value = false
}
watch(open, (on) => {
  if (on) {
    clearPeel()
    document.addEventListener('pointerdown', onPointerdown, true)
  } else document.removeEventListener('pointerdown', onPointerdown, true)
})
onBeforeUnmount(() => document.removeEventListener('pointerdown', onPointerdown, true))
</script>

<template>
  <Teleport to="body">
    <Transition :css="false" @enter="popIn" @leave="popOut">
      <aside v-if="open" ref="sheet" class="list-keys-sheet" :style="{ bottom: `${bottom}px` }" :aria-label="t('listKeys.title')">
        <header class="list-keys-sheet__head">
          <h2 class="list-keys-sheet__title">{{ t('listKeys.title') }}</h2>
          <button type="button" class="list-keys-sheet__close" :aria-label="t('listKeys.close')" @click="open = false">
            <X :size="14" :stroke-width="2.4" aria-hidden="true" />
          </button>
        </header>
        <dl class="list-keys-sheet__rows">
          <div v-for="row in rows" :key="row.keys.join(' ')" class="list-keys-sheet__row">
            <dt><kbd v-for="key in row.keys" :key="key">{{ key }}</kbd></dt>
            <dd>{{ row.label }}</dd>
          </div>
        </dl>
      </aside>
    </Transition>
  </Teleport>
</template>

<style scoped>
/* 安静但可发现：纸面卡片、硬边框、轻错版阴影，键帽与「收藏本站」引导同一配方。 */
.list-keys-sheet {
  position: fixed;
  right: 24px;
  z-index: 70;
  width: max-content;
  max-width: min(340px, calc(100vw - 48px));
  padding: 12px 14px 13px;
  border: 1px solid var(--rule-strong);
  border-radius: 8px;
  background: var(--paper-raised);
  box-shadow: 3px 3px 0 var(--shadow-ink-soft);
  color: var(--ink);
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
  transform-origin: 100% 100%;
}

.list-keys-sheet__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 8px;
}

.list-keys-sheet__title {
  margin: 0;
  font-size: 13px;
  font-weight: 800;
  line-height: 20px;
}

.list-keys-sheet__close {
  display: inline-grid;
  width: 22px;
  height: 22px;
  place-items: center;
  padding: 0;
  border: 1px solid var(--rule);
  border-radius: 4px;
  background: transparent;
  color: var(--ink-muted);
  cursor: pointer;
  transition: background 150ms ease, border-color 150ms ease, color 150ms ease;
}

.list-keys-sheet__close:hover {
  border-color: var(--rule-strong);
  background: var(--acid-soft);
  color: var(--ink);
}

.list-keys-sheet__close:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }

.list-keys-sheet__rows {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  gap: 6px 12px;
  margin: 0;
}

.list-keys-sheet__row { display: contents; }

.list-keys-sheet__row dt {
  display: flex;
  gap: 4px;
}

.list-keys-sheet__row dd {
  margin: 0;
  color: var(--ink-secondary);
  font-size: 12.5px;
  line-height: 22px;
}

.list-keys-sheet kbd {
  display: inline-grid;
  min-width: 22px;
  height: 21px;
  place-items: center;
  padding: 0 6px;
  border: 1px solid var(--rule-strong);
  border-radius: 5px;
  background: var(--paper);
  box-shadow: 0 1.5px 0 var(--rule-strong);
  color: var(--ink);
  font-family: inherit;
  font-size: 11.5px;
  font-weight: 800;
  line-height: 1;
}
</style>
