import { onUnmounted, ref } from 'vue'
import {
  OTP_COUNTDOWN_INTERVAL_MS,
  OTP_COUNTDOWN_SECONDS,
} from '../features/auth/authViewModel'

interface OtpCountdownOptions {
  clearBeforeStart?: boolean
}

export const useOtpCountdown = ({ clearBeforeStart = false }: OtpCountdownOptions = {}) => {
  const countdown = ref(0)
  let timer: ReturnType<typeof setInterval> | null = null

  const stop = () => {
    if (!timer) return
    clearInterval(timer)
    timer = null
  }

  const reset = () => {
    stop()
    countdown.value = 0
  }

  const start = () => {
    if (clearBeforeStart) stop()
    countdown.value = OTP_COUNTDOWN_SECONDS
    timer = setInterval(() => {
      countdown.value--
      if (countdown.value <= 0) reset()
    }, OTP_COUNTDOWN_INTERVAL_MS)
  }

  onUnmounted(stop)

  return {
    countdown,
    start,
    stop,
    reset,
  }
}
