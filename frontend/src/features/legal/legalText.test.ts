import { describe, expect, it } from 'vitest'
import { splitLead, tocLabel } from './legalText'

describe('legal text helpers', () => {
  it('drops the numbering a title already carries', () => {
    expect(tocLabel('一、AI 生成内容免责声明（最重要）')).toBe('AI 生成内容免责声明（最重要）')
    expect(tocLabel('6. Account security and responsibility')).toBe('Account security and responsibility')
    expect(tocLabel('支付与订单信息')).toBe('支付与订单信息')
    expect(tocLabel('Contact · Copyright and compliance')).toBe('Contact · Copyright and compliance')
  })

  it('splits a leading label and keeps the spacing after it', () => {
    expect(splitLead('邮箱地址：用于注册、登录验证。')).toEqual(['邮箱地址：', '用于注册、登录验证。'])
    expect(splitLead('Password (stored as a hash): Passwords are hashed.')).toEqual(['Password (stored as a hash):', ' Passwords are hashed.'])
  })

  it('leaves sentences that only end in a colon or start with a clause alone', () => {
    expect(splitLead('如有隐私问题，请联系：')).toBeNull()
    expect(splitLead('您可以随时：')).toBeNull()
    expect(splitLead('When using RAG chat, news search, or other features, you agree to these rules: be kind.')).toBeNull()
    expect(splitLead('我们不会向第三方出售或出租您的信息。')).toBeNull()
  })
})
