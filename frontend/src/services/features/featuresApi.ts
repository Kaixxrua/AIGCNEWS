import { api } from '@/services/http/apiClient'
import type { FeaturesWireResponse } from './featuresContracts'

export interface FeatureFlags {
  xSource: boolean
  wechatSource: boolean
  oauthProviders: string[]
  telegramPushEnabled: boolean
}

/**
 * 缺省 fail-open：字段缺失时保持界面完整可见。后端关闭源时 /api/features
 * 总是可达且明确返回 false；仅在端点不可达（部署不一致/网络异常）时才
 * 回退默认值——宁可显示入口后由后端 404/503 兜底，不误伤正常部署。
 */
export const DEFAULT_FEATURE_FLAGS: FeatureFlags = {
  xSource: true,
  wechatSource: true,
  oauthProviders: [],
  telegramPushEnabled: true,
}

export const fetchFeatures = async (signal?: AbortSignal): Promise<FeatureFlags> => {
  const response = await api.get<FeaturesWireResponse>('/features', { signal })
  return {
    xSource: response.data?.x_source ?? true,
    wechatSource: response.data?.wechat_source ?? true,
    oauthProviders: Array.isArray(response.data?.oauth_providers)
      ? response.data.oauth_providers.filter((provider): provider is string => typeof provider === 'string')
      : [],
    telegramPushEnabled: response.data?.telegram_push_enabled ?? true,
  }
}
