<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '../stores/authStore'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const email    = ref('')
const password = ref('')
const loading  = ref(false)
const errorMsg = ref('')

const handleLogin = async () => {
  errorMsg.value = ''
  if (!email.value.trim() || !password.value.trim()) {
    errorMsg.value = '请填写邮箱和密码'
    return
  }
  loading.value = true
  try {
    await authStore.login(email.value.trim(), password.value)
    // 登录成功后跳转到原来要访问的页面，或默认跳 /
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    await router.push(redirect)
  } catch (e: unknown) {
    const err = e as { response?: { data?: { detail?: string } }; message?: string }
    errorMsg.value =
      err?.response?.data?.detail || err?.message || '登录失败，请检查邮箱和密码'
  } finally {
    loading.value = false
  }
}

const handleKeydown = (e: KeyboardEvent) => {
  if (e.key === 'Enter') handleLogin()
}
</script>

<template>
  <div class="flex h-full items-center justify-center p-6">
    <div class="w-full max-w-sm">

      <!-- 标题区 -->
      <div class="mb-8 text-center stagger-enter">
        <div class="mb-4 inline-flex h-14 w-14 items-center justify-center rounded-3xl bg-stone-100">
          <svg class="h-7 w-7 text-stone-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M12 2a10 10 0 100 20 10 10 0 000-20z"/>
            <path d="M9.5 9.5a2.5 2.5 0 015 0c0 2-2 3-2.5 4"/>
            <circle cx="12" cy="17" r=".5" fill="currentColor"/>
          </svg>
        </div>
        <h1 class="text-2xl font-bold text-stone-800 tracking-tight font-serif">AIGC 资讯 · 登录</h1>
        <p class="mt-1 text-sm text-stone-400">欢迎回来，请登录您的账号</p>
      </div>

      <!-- 表单卡片 -->
      <div class="glass-card p-6 space-y-4 stagger-enter" style="animation-delay: 0.1s">

        <!-- 邮箱 -->
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-stone-500">邮箱</label>
          <input
            v-model="email"
            type="email"
            class="input"
            placeholder="you@example.com"
            autocomplete="email"
            :disabled="loading"
            @keydown="handleKeydown"
          />
        </div>

        <!-- 密码 -->
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-stone-500">密码</label>
          <input
            v-model="password"
            type="password"
            class="input"
            placeholder="请输入密码"
            autocomplete="current-password"
            :disabled="loading"
            @keydown="handleKeydown"
          />
        </div>

        <!-- 错误提示 -->
        <Transition name="fade-msg">
          <div
            v-if="errorMsg"
            class="flex items-center gap-2 rounded-2xl bg-rose-50 px-4 py-2.5 text-sm text-rose-600 border border-rose-200"
          >
            <svg class="h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
            {{ errorMsg }}
          </div>
        </Transition>

        <!-- 登录按钮 -->
        <button
          class="btn-primary w-full justify-center py-3"
          :disabled="loading"
          @click="handleLogin"
        >
          <span v-if="loading" class="h-4 w-4 rounded-full border-2 border-white/40 border-t-white animate-spin" />
          <svg v-else class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4"/>
            <polyline points="10 17 15 12 10 7"/>
            <line x1="15" y1="12" x2="3" y2="12"/>
          </svg>
          {{ loading ? '登录中…' : '登录' }}
        </button>
      </div>

      <!-- 底部注册链接 -->
      <p class="mt-5 text-center text-sm text-stone-400 stagger-enter" style="animation-delay: 0.2s">
        还没有账号？
        <RouterLink to="/register" class="font-medium text-stone-600 underline underline-offset-2 hover:text-stone-800 transition-colors">
          立即注册
        </RouterLink>
      </p>

    </div>
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
