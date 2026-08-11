/** /api/features wire 契约：可插拔采集源开关（字段缺失视为开启，fail-open） */
export interface FeaturesWireResponse {
  x_source?: boolean | null
  wechat_source?: boolean | null
}
