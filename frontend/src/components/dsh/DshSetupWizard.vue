<script setup lang="ts">
import { computed, onBeforeUnmount, proxyRefs, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/authStore'
import { useLoginPrompt } from '@/composables/useLoginPrompt'
import { useDshSetupController, type DshIdentity } from '@/composables/useDshSetupController'
import { DSH_PLUGIN_INSTALL_METHODS } from '@/features/mcp/dshPlugin'
import { useClipboard } from '@/composables/useClipboard'
import { showToast } from '@/composables/useToast'
import { useDshInstallController } from '@/composables/useDshInstallController'

const { t } = useI18n()
const auth = useAuthStore()
const { requestLogin } = useLoginPrompt()
const { copy } = useClipboard()
const installCopy = useDshInstallController({
  copy,
  onCopyError: () => showToast(t('mcp.copyFailed')),
})
const controller = proxyRefs(useDshSetupController())
const identities: { id: DshIdentity; title: string; description: string }[] = [
  { id: 'guest', title: 'dsh.wizard.identityGuest', description: 'dsh.wizard.identityGuestDescription' },
  { id: 'user', title: 'dsh.wizard.identityUser', description: 'dsh.wizard.identityUserDescription' },
  { id: 'vip', title: 'dsh.wizard.identityVip', description: 'dsh.wizard.identityVipDescription' },
]
// 已登录用户看不到 Free 卡：账号配额路径由 VIP 卡门禁里的「按普通用户继续」承接
const visibleIdentities = computed(() => identities.filter((entry) => entry.id !== 'user' || !auth.isLoggedIn))
const installMethods = DSH_PLUGIN_INSTALL_METHODS
const currentTitle = computed(() => ['dsh.wizard.stepIdentity', 'dsh.wizard.stepInstall', 'dsh.wizard.stepCommand'][controller.step])
const onNext = async () => {
  const result = await controller.next(auth.isLoggedIn, auth.isMember)
  if (result === 'login') requestLogin('/dsh')
}
watch(() => [auth.isLoggedIn, auth.isMember] as const, async ([loggedIn, isMember]) => {
  controller.syncAuth(loggedIn, isMember)
  if (loggedIn && controller.step === 0 && controller.identity !== 'guest') await onNext()
}, { immediate: true })
onBeforeUnmount(installCopy.dispose)
</script>

<template>
  <section class="dsh-wizard glass-card p-5 md:p-6" :aria-label="t('dsh.wizard.ariaLabel')">
    <ol class="flex flex-wrap items-center gap-2"><li v-for="(key, index) in ['dsh.wizard.stepIdentity','dsh.wizard.stepInstall','dsh.wizard.stepCommand']" :key="key"><button type="button" class="border px-3 py-2 text-xs font-bold" :class="controller.step === index ? 'bg-[var(--acid)]' : 'bg-card'" @click="index <= controller.step && (controller.step = index)">{{ index + 1 }}. {{ t(key) }}</button></li></ol>
    <p class="mt-3 text-xs text-stone-500">{{ t(currentTitle + 'Description') }}</p>
    <div v-if="controller.step === 0" class="mt-5 grid gap-3 md:grid-cols-3">
      <button v-for="identity in visibleIdentities" :key="identity.id" type="button" class="border p-4 text-left" :class="controller.identity === identity.id ? 'border-ink bg-[var(--acid-soft)]' : 'border-stone-200 bg-card'" @click="controller.identity = identity.id"><strong class="block text-sm">{{ t(identity.title) }}</strong><span class="mt-2 block text-xs leading-5 text-stone-500">{{ t(identity.description) }}</span></button>
      <div v-if="controller.identity === 'vip' && auth.isLoggedIn && !auth.isMember" class="md:col-span-3 rounded border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800">{{ t('dsh.wizard.vipRequired') }} <RouterLink to="/membership" class="font-bold underline">{{ t('dsh.wizard.vipCta') }}</RouterLink> <button type="button" class="ml-2 underline" @click="controller.identity = 'user'">{{ t('dsh.wizard.continueAsFree') }}</button></div>
    </div>
    <div v-else-if="controller.step === 1" class="mt-5 grid gap-3">
      <button v-for="method in installMethods" :key="method.id" type="button" class="border p-4 text-left" :class="controller.selectedMethod === method.id ? 'border-ink bg-[var(--acid-soft)]' : 'border-stone-200 bg-card'" @click="controller.selectedMethod = method.id"><strong>{{ t(method.titleKey) }}</strong><span v-if="method.recommended" class="ml-2 border border-ink px-2 py-0.5 text-2xs">{{ t('dsh.recommended') }}</span><span class="mt-1 block text-xs text-stone-500">{{ t(method.descriptionKey) }}</span></button>
    </div>
    <div v-else class="mt-5 space-y-4">
      <p class="text-xs font-semibold uppercase tracking-[.18em] text-stone-400">{{ t('dsh.wizard.commandLabel') }}</p>
      <template v-if="controller.creating"><p class="text-xs text-stone-500">{{ t('dsh.wizard.tokenCreating') }}</p></template>
      <template v-else-if="controller.error"><p class="rounded bg-rose-50 p-3 text-xs text-rose-700">{{ t(controller.error) }} <button type="button" class="underline" @click="controller.generate">{{ t('dsh.wizard.tokenRetry') }}</button></p></template>
      <template v-else>
        <code class="block overflow-x-auto whitespace-nowrap border border-stone-700 bg-stone-900 p-3 font-mono text-xs text-white">{{ controller.installLine }}</code>
        <button type="button" class="btn-primary text-xs" @click="installCopy.copyValue('dsh-install-line', controller.installLine)">{{ t(installCopy.copiedKey === 'dsh-install-line' ? 'mcp.copied' : 'dsh.copy') }}</button>
        <template v-if="controller.token">
          <p class="text-xs text-stone-500">{{ t('dsh.wizard.tokenCommandNote') }}</p>
          <p class="text-xs text-amber-700">{{ t('dsh.wizard.oneTimeTokenWarning') }}</p>
        </template>
        <p v-else class="text-xs text-stone-500">{{ t('dsh.wizard.anonymousHint') }}</p>
      </template>
    </div>
    <div class="mt-6 flex items-center justify-between border-t border-stone-200 pt-4"><button type="button" class="btn-secondary text-xs" :disabled="controller.step === 0" @click="controller.previous">← {{ t('mcp.wizard.prev') }}</button><span class="text-2xs text-stone-400">{{ t('mcp.wizard.stepProgress', { current: controller.step + 1, total: 3 }) }}</span><button type="button" class="btn-primary text-xs" :disabled="controller.step === 2 || (controller.identity === 'vip' && auth.isLoggedIn && !auth.isMember)" @click="onNext">{{ t('mcp.wizard.next') }} →</button></div>
  </section>
</template>

<style scoped>.text-2xs { font-size: .68rem; } .dsh-wizard { border: 1px solid var(--ink); }</style>
