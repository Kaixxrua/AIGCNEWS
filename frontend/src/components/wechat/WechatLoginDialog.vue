<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { WeChatOfficialAccount } from '@/features/wechat/wechatModel'
import type { useWechatController } from '@/composables/useWechatController'

const props = defineProps<{
  modelValue: boolean
  controller: ReturnType<typeof useWechatController>
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
}>()

const { t } = useI18n()
const searchInput = ref('')

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

const statusLabel = computed(() => {
  const status = props.controller.loginAttempt.value?.status
  if (!status) return ''
  return t(`wechat.status.${status}`)
})

const statusHint = computed(() => {
  const status = props.controller.loginAttempt.value?.status
  switch (status) {
    case 'waiting_scan':
      return t('wechat.hint.openWechat')
    case 'scanned_waiting_confirmation':
      return t('wechat.hint.confirmOnPhone')
    case 'confirmed':
      return t('wechat.hint.almostDone')
    case 'qr_expired':
      return t('wechat.hint.qrExpired')
    case 'failed':
    case 'cancelled':
      return t('wechat.hint.loginFailed')
    default:
      return ''
  }
})

function onClose() {
  props.controller.closeLoginDialog()
}

function onSearchKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter') {
    props.controller.searchAccounts(searchInput.value)
  }
}

function saveAccount(account: WeChatOfficialAccount) {
  props.controller.saveAccount(account)
  props.controller.clearSearch()
  searchInput.value = ''
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      searchInput.value = ''
    }
  },
)

onUnmounted(() => {
  if (props.controller.isLoginDialogOpen.value) {
    props.controller.closeLoginDialog()
  }
})
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="visible"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
        @click.self="onClose"
      >
        <div class="glass-card w-full max-w-md overflow-hidden">
          <div class="monitor-divider flex items-center justify-between border-b p-4">
            <h3 class="text-sm font-semibold">{{ t('wechat.loginTitle') }}</h3>
            <button class="text-lg leading-none opacity-70 hover:opacity-100" @click="onClose">✕</button>
          </div>

          <div class="p-5">
            <p class="mb-4 text-xs leading-5 monitor-caption">{{ t('wechat.loginDescription') }}</p>

            <div class="monitor-surface flex flex-col items-center justify-center py-6">
              <div v-if="controller.qrCodeUrl.value" class="h-52 w-52 overflow-hidden rounded-lg bg-white p-2">
                <img :src="controller.qrCodeUrl.value" alt="WeChat QR Code" class="h-full w-full" />
              </div>
              <div v-else class="flex h-52 w-52 items-center justify-center rounded-lg monitor-empty">
                <span class="monitor-caption text-xs">{{ t('wechat.loadingQr') }}</span>
              </div>

              <div class="mt-4 text-center">
                <p class="text-sm font-semibold">{{ statusLabel }}</p>
                <p class="mt-1 text-xs monitor-caption">{{ statusHint }}</p>
              </div>

              <div v-if="controller.loginAttempt.value?.status === 'confirmed'" class="mt-4">
                <button class="monitor-btn-primary" @click="controller.confirmLogin">
                  {{ t('wechat.completeLogin') }}
                </button>
              </div>

              <div class="mt-4 flex gap-2">
                <button class="monitor-btn-secondary" @click="controller.startLogin">
                  {{ t('wechat.refreshQr') }}
                </button>
                <button class="monitor-btn-secondary" @click="onClose">
                  {{ t('wechat.cancel') }}
                </button>
              </div>
            </div>

            <div class="mt-5 monitor-surface p-4">
              <h4 class="text-xs font-semibold uppercase tracking-widest monitor-caption">{{ t('wechat.searchTitle') }}</h4>
              <div class="mt-2 flex gap-2">
                <input
                  v-model="searchInput"
                  type="text"
                  class="monitor-input flex-1 text-sm"
                  :placeholder="t('wechat.searchPlaceholder')"
                  @keydown="onSearchKeydown"
                />
                <button
                  class="monitor-btn-primary"
                  :disabled="controller.isSearching.value"
                  @click="controller.searchAccounts(searchInput)"
                >
                  {{ controller.isSearching.value ? t('wechat.searching') : t('wechat.search') }}
                </button>
              </div>

              <div v-if="controller.searchResults.value.length" class="mt-3 space-y-2 max-h-48 overflow-auto">
                <div
                  v-for="account in controller.searchResults.value"
                  :key="account.fakeid"
                  class="flex items-center justify-between gap-2 rounded-md p-2 monitor-surface"
                >
                  <div class="flex items-center gap-2 min-w-0">
                    <img v-if="account.avatar_url" :src="account.avatar_url" class="h-8 w-8 rounded-full object-cover" />
                    <div v-else class="monitor-avatar h-8 w-8 text-xs">
                      {{ (account.nickname || account.alias || '微').slice(0, 1) }}
                    </div>
                    <div class="min-w-0">
                      <p class="truncate text-xs font-semibold">{{ account.nickname || account.alias || t('wechat.unnamedAccount') }}</p>
                      <p class="truncate text-2xs monitor-caption">{{ account.signature }}</p>
                    </div>
                  </div>
                  <button class="monitor-btn-secondary shrink-0 text-xs" @click="saveAccount(account)">
                    {{ t('wechat.save') }}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.text-2xs {
  font-size: 0.65rem;
  line-height: 0.875rem;
}

.monitor-input {
  padding: 8px 10px;
  border: 1px solid var(--projects-accent);
  border-radius: 4px;
  background: var(--projects-paper-light);
  color: var(--ink);
  outline: none;
  transition: box-shadow 150ms ease, border-color 150ms ease;
}

.monitor-input:focus {
  border-color: var(--projects-accent);
  box-shadow: 3px 3px 0 var(--shadow-hard);
}
</style>
