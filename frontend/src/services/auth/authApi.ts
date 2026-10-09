import { api } from '@/services/http/apiClient'

export interface OAuthIdentityDTO {
  provider: 'github' | 'google' | 'wechat' | 'qq' | 'linuxdo' | string
  display_email?: string | null
  email_verified?: boolean
  linked_at?: string | null
}

export interface AuthUserDTO {
  user_id: number
  email: string | null
  /** 用户名（注册必填 / OAuth 首次登录自动回填）；旧数据可能为 null 或空串 */
  username?: string | null
  /** Earliest next rename time; null means this account has not renamed yet. */
  username_change_available_at?: string | null
  avatar_url?: string | null
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

export interface TokenRotationDTO {
  access_token: string
  token_type: string
  changed: boolean
}

export interface LoginResponse {
  access_token: string
  role: string
  password_change_required?: boolean
}

export async function startOAuth(provider: string, redirectTo: string): Promise<void> {
  window.location.assign(`/api/auth/oauth/${encodeURIComponent(provider)}/start?redirect_to=${encodeURIComponent(redirectTo)}`)
}

export interface OAuthConsumeResponse extends LoginResponse {
  redirect_to: string
}

export async function consumeOAuthHandoff(): Promise<OAuthConsumeResponse> {
  const res = await api.post<OAuthConsumeResponse>('/auth/oauth/consume', undefined)
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

/** 已登录改密：邮箱验证码校验并返回已轮换的会话令牌。 */
export async function changePassword(emailCode: string, newPassword: string): Promise<TokenRotationDTO> {
  const res = await api.post<TokenRotationDTO>('/auth/me/password', {
    email_code: emailCode,
    new_password: newPassword,
  })
  return res.data
}

export async function updateProfile(username: string): Promise<AuthUserDTO> {
  const res = await api.patch<AuthUserDTO>('/auth/me/profile', { username })
  return res.data
}

/** 换绑邮箱：验证码发送到数据库当前邮箱（不携带任何请求体，目标账户由服务端会话裁决） */
export async function sendEmailChangeCurrentOtp(): Promise<{ detail: string }> {
  const res = await api.post<{ detail: string }>('/auth/me/email-change/send-current')
  return res.data
}

/** 换绑邮箱：验证码发送到新邮箱（应答口径恒定，不泄露邮箱占用状态） */
export async function sendEmailChangeNewOtp(newEmail: string): Promise<{ detail: string }> {
  const res = await api.post<{ detail: string }>('/auth/me/email-change/send-new', { new_email: newEmail })
  return res.data
}

/** 换绑邮箱确认：当前邮箱 + 新邮箱双验证码，返回换绑后的权威账户投影 */
export async function confirmEmailChange(newEmail: string, currentCode: string, newCode: string): Promise<AuthUserDTO> {
  const res = await api.post<AuthUserDTO>('/auth/me/email-change/confirm', {
    new_email: newEmail,
    current_code: currentCode,
    new_code: newCode,
  })
  return res.data
}

/** 已登录发起渠道绑定：整页跳转后端 bind/start，目标账户只存服务端 state */
export async function startOAuthBind(provider: string, redirectTo: string): Promise<void> {
  window.location.assign(`/api/auth/oauth/${encodeURIComponent(provider)}/bind/start?redirect_to=${encodeURIComponent(redirectTo)}`)
}

export interface OAuthBindConsumeResponse {
  provider: string
  /** bound = 本次新绑定；already_bound = 该渠道此前已绑定本账户（幂等） */
  status: 'bound' | 'already_bound'
  redirect_to: string
}

/** 完成渠道绑定：消费一次性绑定 handoff（cookie 流），绝不签发/轮换会话令牌 */
export async function consumeOAuthBindHandoff(): Promise<OAuthBindConsumeResponse> {
  const res = await api.post<OAuthBindConsumeResponse>('/auth/oauth/bind/consume', undefined)
  return res.data
}

/** Multipart upload; the browser supplies the boundary instead of the JSON default. */
export async function uploadAvatar(file: File): Promise<AuthUserDTO> {
  const form = new FormData()
  form.append('file', file)
  const res = await api.post<AuthUserDTO>('/auth/me/avatar', form, {
    headers: { 'Content-Type': undefined },
  })
  return res.data
}
