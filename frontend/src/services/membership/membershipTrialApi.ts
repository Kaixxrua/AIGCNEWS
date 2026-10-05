import { api } from '@/services/http/apiClient'
import type { MembershipTrialStatus } from '@/features/membership/membershipTrial'

export interface MembershipTrialApi {
  getStatus(): Promise<MembershipTrialStatus>
  start(): Promise<MembershipTrialStatus>
}

export const membershipTrialApi: MembershipTrialApi = {
  async getStatus(): Promise<MembershipTrialStatus> {
    return (await api.get('/membership/trial')).data
  },

  async start(): Promise<MembershipTrialStatus> {
    return (await api.post('/membership/trial')).data
  },
}
