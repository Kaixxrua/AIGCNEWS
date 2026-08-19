import { api } from '@/services/http/apiClient'
import type {
  CreatePaymentOrderResponse,
  PaymentOrder,
  PaymentPlansResponse,
} from '@/features/payments/paymentModel'

export interface PaymentApi {
  listPlans(): Promise<PaymentPlansResponse>
  createOrder(
    planCode: string,
    channel: string,
    idempotencyKey: string,
  ): Promise<CreatePaymentOrderResponse>
  getOrder(orderNo: string): Promise<PaymentOrder>
}

export const paymentApi: PaymentApi = {
  async listPlans(): Promise<PaymentPlansResponse> {
    return (await api.get('/payments/plans')).data
  },

  async createOrder(
    planCode: string,
    channel: string,
    idempotencyKey: string,
  ): Promise<CreatePaymentOrderResponse> {
    return (
      await api.post('/payments/orders', {
        plan_code: planCode,
        channel,
        idempotency_key: idempotencyKey,
      })
    ).data
  },

  async getOrder(orderNo: string): Promise<PaymentOrder> {
    return (await api.get(`/payments/orders/${encodeURIComponent(orderNo)}`)).data
  },
}
