import { computed, ref } from 'vue'
import { getSafeInternalRedirect } from '@/features/auth/authViewModel'

const open = ref(false)
const redirect = ref('/')

export function useLoginPrompt() {
  const isOpen = computed({
    get: () => open.value,
    set: (value: boolean) => { open.value = value },
  })
  const redirectTarget = computed(() => redirect.value)

  const requestLogin = (target?: unknown) => {
    redirect.value = getSafeInternalRedirect(target)
    open.value = true
  }

  const closeLoginPrompt = () => {
    open.value = false
  }

  const consumeLoginRedirect = () => {
    const target = redirect.value
    redirect.value = '/'
    return target
  }

  return {
    isOpen,
    redirectTarget,
    requestLogin,
    closeLoginPrompt,
    consumeLoginRedirect,
  }
}
