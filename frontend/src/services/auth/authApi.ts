import { api } from '@/services/http/apiClient'

export interface AuthUserDTO {
  user_id: number
  email: string
  role: 'user' | 'admin'
  email_verified?: boolean
  /** 会员档位（0045）：free / member；缺省按 free 处理（过期 member 由后端归一为 free） */
  membership_tier?: 'free' | 'member'
  /** 会员到期时间（0048，ISO 串）；null/缺省 = 长期有效 */
  membership_expires_at?: string | null
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

/** 已登录改密：当前密码校验（无需邮箱验证码，适配无 SMTP 的自托管环境） */
export async function changePassword(currentPassword: string, newPassword: string): Promise<{ detail: string }> {
  const res = await api.post<{ detail: string }>('/auth/me/password', {
    current_password: currentPassword,
    new_password: newPassword,
  })
  return res.data
}
