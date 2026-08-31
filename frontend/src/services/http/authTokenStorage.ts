/**
 * localStorage 中的访问令牌键：全局唯一真相。
 * apiClient / useEventSource / authStore 统一从这里读取，避免字面量散落。
 */
export const AUTH_TOKEN_KEY = 'auth_token'

let runtimeAuthToken: string | null | undefined

function readStoredAuthToken(): string | null {
  try {
    return localStorage.getItem(AUTH_TOKEN_KEY)
  } catch {
    return null
  }
}

/**
 * 当前页面的认证令牌以内存状态为准；首次初始化前才回退到 localStorage。
 * 这样即使浏览器禁止持久化，登录后的 API 请求仍能携带令牌。
 */
export function readAuthToken(): string | null {
  return runtimeAuthToken === undefined ? readStoredAuthToken() : runtimeAuthToken
}

export function setRuntimeAuthToken(token: string | null): void {
  runtimeAuthToken = token
}

export function removeAuthToken(): void {
  runtimeAuthToken = null
  try {
    localStorage.removeItem(AUTH_TOKEN_KEY)
  } catch {
    // store 的内存状态仍是权威来源
  }
}
