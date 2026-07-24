<script setup lang="ts">
defineProps<{
  email: string
  emailValid: boolean
  loading: boolean
  otpLoading: boolean
  otpBtnDisabled: boolean
  countdown: number
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:email': [value: string]
  sendOtp: []
}>()
</script>

<template>
  <div class="space-y-1.5">
    <label class="text-xs font-medium text-stone-500">邮箱</label>
    <div class="flex flex-col gap-2 sm:flex-row">
      <input
        :value="email"
        type="email"
        class="input flex-1"
        placeholder="you@example.com"
        autocomplete="email"
        :disabled="loading || disabled"
        @input="emit('update:email', ($event.target as HTMLInputElement).value)"
      />
      <button
        class="shrink-0 inline-flex w-full items-center justify-center gap-1.5 rounded-full px-4 py-2.5 text-xs font-medium sm:w-auto transition-all duration-150 active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-40"
        style="background: rgba(255,255,255,0.80); border: 1px solid rgba(168,162,158,0.25); color: #57534e; backdrop-filter: blur(10px); white-space: nowrap"
        :disabled="otpBtnDisabled || loading"
        @click="emit('sendOtp')"
      >
        <span v-if="otpLoading" class="h-3.5 w-3.5 rounded-full border-2 border-stone-300 border-t-stone-600 animate-spin" />
        <span v-else-if="countdown > 0">重新获取({{ countdown }}s)</span>
        <span v-else>获取验证码</span>
      </button>
    </div>
    <Transition name="fade-msg">
      <p v-if="email && !emailValid" class="text-2xs text-rose-500 pl-1">请输入正确格式的邮箱地址</p>
    </Transition>
  </div>
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
