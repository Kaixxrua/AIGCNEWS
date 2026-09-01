import { api } from '@/services/http/apiClient'

export interface OAuthIdentityDTO {
  provider: 'github' | 'google' | 'wechat' | string
  display_email?: string | null
  email_verified?: boolean
  linked_at?: string | null
}

export interface AuthUserDTO {
  user_id: number
  email: string | null
  /** 用户名（注册必填 / OAuth 首次登录自动回填）；旧数据可能为 null 或空串 */
  username?: string | null
  role: 'user' | 'admin'
  email_verified?: boolean
  /** 会员档位（0045）：free / member；缺省按 free 处理 */
  membership_tier?: 'free' | 'member'
  /** 会员到期时间（0048，ISO 字符串）；null/缺省 = 长期有效 */
  membership_expires_at?: string | null
  created_at?: string | null
  password_login_enabled?: boolean
  oauth_identities?: OAuthIdentityDTO[]
  /** 种子默认管理员仍使用公开默认密码时为真：前端常驻提醒改密 */
  password_change_required?: boolean
}

export interface LoginResponse {
  access_token: string
  role: string
  password_change_required?: boolean
}

export async function startOAuth(provider: string, redirectTo: string): Promise<void> {
  window.location.assign(`/api/auth/oauth/${encodeURIComponent(provider)}/start?redirect_to=${encodeURIComponent(redirectTo)}`)
}

export async function startOAuthBinding(provider: string, redirectTo: string): Promise<void> {
  window.location.assign(`/api/auth/oauth/${encodeURIComponent(provider)}/bind/start?redirect_to=${encodeURIComponent(redirectTo)}`)
}

export interface OAuthConsumeResponse extends LoginResponse {
  redirect_to: string
}

export async function consumeOAuthHandoff(): Promise<OAuthConsumeResponse> {
  const res = await api.post<OAuthConsumeResponse>('/auth/oauth/consume', undefined)
  return res.data
}

export interface OAuthBindConsumeResponse {
  provider: string
  status: 'bound' | 'already_bound' | 'conflict'
  redirect_to: string
}

export async function consumeOAuthBindingHandoff(): Promise<OAuthBindConsumeResponse> {
  const res = await api.post<OAuthBindConsumeResponse>('/auth/oauth/bind/consume', undefined)
  return res.data
}

export async function loginWithPassword(email: string, password: string): Promise<LoginResponse> {
  const res = await api.post<LoginResponse>('/auth/login', { email, password })
  return res.data
}

export async function fetchCurrentUser(): Promise<AuthUserDTO> {
  const res = await api.get<AuthUserDTO>('/auth/me')
  return res.data
}

/** 已登录改密发码：验证码发送到当前账号邮箱（purpose=password_change） */
export async function sendChangePasswordOtp(): Promise<{ detail: string }> {
  const res = await api.post<{ detail: string }>('/auth/me/send-password-change-otp')
  return res.data
}

/** 已登录改密：邮箱验证码校验（验证码替代当前密码；无 SMTP 的自托管环境无改密路径） */
export async function changePassword(emailCode: string, newPassword: string): Promise<{ detail: string }> {
  const res = await api.post<{ detail: string }>('/auth/me/password', {
    email_code: emailCode,
    new_password: newPassword,
  })
  return res.data
}

export async function updateProfile(username: string): Promise<AuthUserDTO> {
  const res = await api.patch<AuthUserDTO>('/auth/me/profile', { username })
  return res.data
}

/** 向数据库当前邮箱发送换绑验证码（无请求体，目标账户取自服务端会话） */
export async function sendEmailChangeCurrentOtp(): Promise<{ detail: string }> {
  const res = await api.post<{ detail: string }>('/auth/me/email-change/send-current')
  return res.data
}

/** 向新邮箱发送换绑验证码 */
export async function sendEmailChangeNewOtp(newEmail: string): Promise<{ detail: string }> {
  const res = await api.post<{ detail: string }>('/auth/me/email-change/send-new', { new_email: newEmail })
  return res.data
}

/** 双验证码确认换绑；返回服务端权威账户投影 */
export async function confirmEmailChange(newEmail: string, currentCode: string, newCode: string): Promise<AuthUserDTO> {
  const res = await api.post<AuthUserDTO>('/auth/me/email-change/confirm', {
    new_email: newEmail,
    current_code: currentCode,
    new_code: newCode,
  })
  return res.data
}
