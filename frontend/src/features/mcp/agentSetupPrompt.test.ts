import { describe, expect, it } from 'vitest'
import { buildDshAgentPrompt, buildMcpAgentPrompt } from './agentSetupPrompt'
import { COMMAND_TOKEN_SLOT, splitCommandPreview } from './commandPreview'
import { DSH_PATCH_PATH, DSH_PLUGIN_INSTALL_METHODS } from './dshPlugin'
import { MCP_OAUTH_ENDPOINT } from './mcpOAuth'

const MANUAL_PAGE = 'https://aigcnews.cn/mcp'

describe('buildMcpAgentPrompt', () => {
  it('connects every client to the OAuth endpoint pinned on aigcnews.cn', () => {
    // 资源地址钉在 aigcnews.cn（backend/tests/test_mcp_oauth_metadata_contract.py），提示词不能跟页面 origin 走。
    expect(MCP_OAUTH_ENDPOINT).toBe('https://aigcnews.cn/api/mcp/oauth')
    const prompt = buildMcpAgentPrompt('zh-CN', MANUAL_PAGE)

    expect(prompt).toContain(`claude mcp add --scope user --transport http aigc-news ${MCP_OAUTH_ENDPOINT}`)
    expect(prompt).toContain('claude mcp login aigc-news')
    expect(prompt).toContain(`codex mcp add aigc-news --url ${MCP_OAUTH_ENDPOINT}`)
    expect(prompt).toContain(`code --add-mcp '{"name":"aigc-news","type":"http","url":"${MCP_OAUTH_ENDPOINT}"}'`)
    expect(prompt).toContain(`"aigc-news": { "type": "remote", "url": "${MCP_OAUTH_ENDPOINT}", "enabled": true }`)
    expect(prompt).toContain('opencode mcp auth aigc-news')
  })

  it('carries no token, so guests can copy it and it is safe in chat history', () => {
    for (const locale of ['zh-CN', 'en-US']) {
      const prompt = buildMcpAgentPrompt(locale, MANUAL_PAGE)
      expect(prompt).not.toMatch(/aigc_mcp_|Bearer\s|Authorization"?\s*:/)
    }
  })

  it('sends clients without OAuth back to the manual setup on the page they came from', () => {
    const backup = 'https://aigcradar.online/mcp'

    expect(buildMcpAgentPrompt('zh-CN', backup)).toContain(`改用 ${backup} 页面里的「手动配置」`)
    expect(buildMcpAgentPrompt('en-US', backup)).toContain(`use Manual setup on ${backup} instead`)
    expect(buildMcpAgentPrompt('en-US', backup)).toContain(MCP_OAUTH_ENDPOINT)
  })

  it('follows the interface language and falls back to English', () => {
    expect(buildMcpAgentPrompt('zh-CN', MANUAL_PAGE)).toMatch(/^请帮我把 AIGC Radar MCP 接入/)
    expect(buildMcpAgentPrompt('zh', MANUAL_PAGE)).toMatch(/^请帮我把/)
    expect(buildMcpAgentPrompt('en-US', MANUAL_PAGE)).toMatch(/^Please connect AIGC Radar MCP/)
    expect(buildMcpAgentPrompt('ja-JP', MANUAL_PAGE)).toMatch(/^Please connect/)
  })
})

describe('buildDshAgentPrompt', () => {
  const token = 'aigc_mcp_example123'

  it('installs from npm first, falls back to GitHub and patches the web profile with the token', () => {
    for (const locale of ['zh-CN', 'en-US']) {
      const prompt = buildDshAgentPrompt(locale, token)
      for (const method of DSH_PLUGIN_INSTALL_METHODS) expect(prompt).toContain(method.command)
      expect(prompt.indexOf(DSH_PLUGIN_INSTALL_METHODS[0]!.command)).toBeLessThan(prompt.indexOf(DSH_PLUGIN_INSTALL_METHODS[1]!.command))
      expect(prompt).toContain(DSH_PATCH_PATH)
      expect(prompt).toContain([
        '```yaml',
        '- replace:',
        '    - id: aigc-radar',
        '      name: dsh-aigc-radar',
        '      config:',
        `        mcpToken: '${token}'`,
        '```',
      ].join('\n'))
      expect(prompt.split(token)).toHaveLength(2)
    }
  })

  it('asks the agent to keep the token out of replies and repositories', () => {
    expect(buildDshAgentPrompt('zh-CN', token)).toContain('不要在回复、日志或代码提交里复述它')
    expect(buildDshAgentPrompt('en-US', token)).toContain('do not repeat it in replies, logs or commits')
  })

  it('previews with the slot standing in for the token', () => {
    const segments = splitCommandPreview(buildDshAgentPrompt('zh-CN', COMMAND_TOKEN_SLOT))

    expect(segments.filter((segment) => segment.kind === 'token')).toHaveLength(1)
  })
})
