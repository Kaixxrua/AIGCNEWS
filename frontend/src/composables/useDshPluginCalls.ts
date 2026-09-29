import type { Ref } from 'vue'
import { useLiveCallCount } from '@/composables/useLiveCallCount'

/* /dsh 页「dsh 插件调用」计数（live-stats 的 mcp_dsh_calls），见 useLiveCallCount。 */
export const useDshPluginCalls = (active: Ref<boolean>) => useLiveCallCount('mcp_dsh_calls', active)
