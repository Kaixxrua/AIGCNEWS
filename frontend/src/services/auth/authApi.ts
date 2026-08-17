import { api } from '@/services/http/apiClient'

export interface AuthUserDTO {
  user_id: number
  email: string
  role: 'user' | 'admin'
  email_verified?: boolean
  /** 会员档位（0045）：free / member；缺省按 free 处理 */
  membership_tier?: 'free' | 'member'
  /** 种子默认管理员仍使用公开默认密码时为真：前端常驻提醒改密 */
  password_change_required?: boolean
}

export interface LoginResponse {
  access_token: string
  role: string
  password_change_required?: boolean
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
