import { api } from '../http/apiClient'

export interface AuthUserDTO {
  user_id: number
  email: string
  role: 'user' | 'admin'
  email_verified?: boolean
}

export interface LoginResponse {
  access_token: string
  role: string
}

export async function loginWithPassword(email: string, password: string): Promise<LoginResponse> {
  const res = await api.post<LoginResponse>('/auth/login', { email, password })
  return res.data
}

export async function fetchCurrentUser(): Promise<AuthUserDTO> {
  const res = await api.get<AuthUserDTO>('/auth/me')
  return res.data
}
