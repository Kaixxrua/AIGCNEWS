import { computed, ref } from 'vue'
import { getSafeInternalRedirect } from '@/features/auth/authViewModel'

const open = ref(false)
const resetOpen = ref(false)
const redirect = ref('/')

export function useLoginPrompt() {
  const isOpen = computed({
    get: () => open.value,
    set: (value: boolean) => { open.value = value },
  })
  const redirectTarget = computed(() => redirect.value)
  const isResetOpen = computed({
    get: () => resetOpen.value,
    set: (value: boolean) => { resetOpen.value = value },
  })

  const rememberLoginRedirect = (target?: unknown) => {
    redirect.value = getSafeInternalRedirect(target)
  }

  const requestLogin = (target?: unknown) => {
    rememberLoginRedirect(target)
    open.value = true
  }

  const closeLoginPrompt = () => {
    open.value = false
  }

  const requestPasswordReset = (target?: unknown) => {
    rememberLoginRedirect(target)
    resetOpen.value = true
  }

  const closePasswordReset = () => {
    resetOpen.value = false
  }

  const consumeLoginRedirect = () => {
    const target = redirect.value
    redirect.value = '/'
    return target
  }

  return {
    isOpen,
    redirectTarget,
    isResetOpen,
    requestPasswordReset,
    closePasswordReset,
    rememberLoginRedirect,
    requestLogin,
    closeLoginPrompt,
    consumeLoginRedirect,
  }
}
