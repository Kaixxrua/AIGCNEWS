/**
 * localStorage 中的访问令牌键：全局唯一真相。
 * apiClient / useEventSource / authStore 统一从这里读取，避免字面量散落。
 */
export const AUTH_TOKEN_KEY = 'auth_token'

export function readAuthToken(): string | null {
  try {
    return localStorage.getItem(AUTH_TOKEN_KEY)
  } catch {
    return null
  }
}

export function removeAuthToken(): void {
  try {
    localStorage.removeItem(AUTH_TOKEN_KEY)
  } catch {
    // store 的内存状态仍是权威来源
  }
}
