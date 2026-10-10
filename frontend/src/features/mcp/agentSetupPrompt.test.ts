import { describe, expect, it } from 'vitest'
import { buildDshAgentPrompt, buildMcpAgentPrompt } from './agentSetupPrompt'
import { COMMAND_TOKEN_SLOT, splitCommandPreview } from './commandPreview'
import { DSH_PATCH_PATH, DSH_PLUGIN_INSTALL_METHODS } from './dshPlugin'
import { MCP_INSTALL_CODE_REDEEM_PATH, MCP_TOKEN_PLACEHOLDER } from './installCode'
import { MCP_OAUTH_ENDPOINT } from './mcpOAuth'

const MANUAL_PAGE = 'https://aigcnews.cn/mcp'
const DSH_PAGE = 'https://aigcnews.cn/dsh'
const CODE = 'aigc_ic_Example-Code_0123456789abcdefghijklmnopqrstuvw'
/** 真 Token 形如 aigc_mcp_ + 43 位 urlsafe；提示词里只许出现前缀本身（dsh 脚本校验兑换结果时用）。 */
const REAL_TOKEN = /aigc_mcp_[A-Za-z0-9_-]{8,}/

const tokenSlots = (text: string) => splitCommandPreview(text).filter((segment) => segment.kind === 'token')

describe('buildMcpAgentPrompt', () => {
  it('connects every client to the OAuth endpoint pinned on aigcnews.cn', () => {
    // 资源地址钉在 aigcnews.cn（backend/tests/test_mcp_oauth_metadata_contract.py），提示词不能跟页面 origin 走。
    expect(MCP_OAUTH_ENDPOINT).toBe('https://aigcnews.cn/api/mcp/oauth')
    for (const code of [null, CODE]) {
      const prompt = buildMcpAgentPrompt('zh-CN', MANUAL_PAGE, code)

      expect(prompt).toContain(`claude mcp add --scope user --transport http aigc-news ${MCP_OAUTH_ENDPOINT}`)
      expect(prompt).toContain('claude mcp login aigc-news')
      expect(prompt).toContain(`codex mcp add aigc-news --url ${MCP_OAUTH_ENDPOINT}`)
      expect(prompt).toContain(`code --add-mcp '{"name":"aigc-news","type":"http","url":"${MCP_OAUTH_ENDPOINT}"}'`)
      expect(prompt).toContain(`"aigc-news": { "type": "remote", "url": "${MCP_OAUTH_ENDPOINT}", "enabled": true }`)
      expect(prompt).toContain('opencode mcp auth aigc-news')
    }
  })

  it('carries no token, with or without an install code, so it is safe in chat history', () => {
    for (const locale of ['zh-CN', 'en-US']) {
      expect(buildMcpAgentPrompt(locale, MANUAL_PAGE)).not.toMatch(/aigc_mcp_|Bearer\s|Authorization"?\s*:/)
      expect(buildMcpAgentPrompt(locale, MANUAL_PAGE, CODE)).not.toMatch(REAL_TOKEN)
    }
  })

  it('sends guests whose client lacks OAuth back to the manual setup on the page they came from', () => {
    const backup = 'https://aigcradar.online/mcp'

    expect(buildMcpAgentPrompt('zh-CN', backup)).toContain(`改用 ${backup} 页面里的「手动配置」`)
    expect(buildMcpAgentPrompt('en-US', backup)).toContain(`use Manual setup on ${backup} instead`)
    expect(buildMcpAgentPrompt('en-US', backup)).toContain(MCP_OAUTH_ENDPOINT)
    expect(buildMcpAgentPrompt('en-US', backup)).not.toContain('install code')
  })

  it('lets a signed-in reader’s non-OAuth client trade the install code for a token without printing it', () => {
    for (const locale of ['zh-CN', 'en-US']) {
      const prompt = buildMcpAgentPrompt(locale, MANUAL_PAGE, CODE)
      const command = prompt.split('\n').find((line) => line.includes('curl'))!.trim()

      expect(command).toMatch(
        new RegExp(`^T="\\$\\(curl -fsS -X POST https://aigcnews\\.cn${MCP_INSTALL_CODE_REDEEM_PATH} `),
      )
      expect(command).toContain(`-H 'Accept: text/plain' -d '{"code":"${CODE}","client_name":"<`)
      expect(command).toContain(`&& [ -n "$T" ] && perl -pi -e "s/${MCP_TOKEN_PLACEHOLDER}/$T/g" <`)
      expect(prompt).toContain(`https://aigcnews.cn/api/mcp${locale === 'zh-CN' ? '，' : ','}`)
      expect(prompt).toContain(`Bearer ${MCP_TOKEN_PLACEHOLDER}`)
      expect(prompt.split(CODE)).toHaveLength(3)
    }
    expect(buildMcpAgentPrompt('zh-CN', MANUAL_PAGE, CODE)).toContain('Token 不会出现在输出里，你也不要读取、打印或复述它')
    expect(buildMcpAgentPrompt('en-US', MANUAL_PAGE, CODE)).toContain('The token never appears in the output; do not read, print or repeat it')
  })

  it('redeems on the entry the page was opened from', () => {
    const prompt = buildMcpAgentPrompt('en-US', 'https://aigcradar.online/mcp', CODE)

    expect(prompt).toContain(`curl -fsS -X POST https://aigcradar.online${MCP_INSTALL_CODE_REDEEM_PATH} `)
    expect(prompt).toContain('URL https://aigcradar.online/api/mcp,')
    expect(prompt).toContain('copy a fresh prompt from https://aigcradar.online/mcp')
    expect(prompt).not.toContain(`https://aigcnews.cn${MCP_INSTALL_CODE_REDEEM_PATH}`)
  })

  it('confirms the connection with get_my_quota, which does not use quota', () => {
    for (const code of [null, CODE]) {
      expect(buildMcpAgentPrompt('zh-CN', MANUAL_PAGE, code)).toContain('调用 aigc-news 的 get_my_quota 工具确认接通（它不消耗调用额度）')
      expect(buildMcpAgentPrompt('en-US', MANUAL_PAGE, code)).toContain('call the aigc-news get_my_quota tool to confirm the connection (it does not use any call quota)')
    }
  })

  it('previews the install code as slots', () => {
    expect(tokenSlots(buildMcpAgentPrompt('zh-CN', MANUAL_PAGE, COMMAND_TOKEN_SLOT))).toHaveLength(2)
    expect(tokenSlots(buildMcpAgentPrompt('zh-CN', MANUAL_PAGE))).toHaveLength(0)
  })

  it('follows the interface language and falls back to English', () => {
    expect(buildMcpAgentPrompt('zh-CN', MANUAL_PAGE)).toMatch(/^请帮我把 AIGC Radar MCP 接入/)
    expect(buildMcpAgentPrompt('zh', MANUAL_PAGE)).toMatch(/^请帮我把/)
    expect(buildMcpAgentPrompt('en-US', MANUAL_PAGE)).toMatch(/^Please connect AIGC Radar MCP/)
    expect(buildMcpAgentPrompt('ja-JP', MANUAL_PAGE, CODE)).toMatch(/^Please connect/)
  })
})

describe('buildDshAgentPrompt', () => {
  const redeemLine = (prompt: string) => prompt.split('\n').find((line) => line.includes('node -e'))!.trim()
  const script = (line: string) => line.slice('node -e "'.length, -1)

  it('installs from npm first, falls back to GitHub and patches the web profile with a placeholder', () => {
    for (const locale of ['zh-CN', 'en-US']) {
      const prompt = buildDshAgentPrompt(locale, CODE, DSH_PAGE)
      for (const method of DSH_PLUGIN_INSTALL_METHODS) expect(prompt).toContain(method.command)
      expect(prompt.indexOf(DSH_PLUGIN_INSTALL_METHODS[0]!.command)).toBeLessThan(prompt.indexOf(DSH_PLUGIN_INSTALL_METHODS[1]!.command))
      expect(prompt).toContain(DSH_PATCH_PATH)
      expect(prompt).toContain([
        '```yaml',
        '- replace:',
        '    - id: aigc-radar',
        '      name: dsh-aigc-radar',
        '      config:',
        `        mcpToken: '${MCP_TOKEN_PLACEHOLDER}'`,
        '```',
      ].join('\n'))
      expect(prompt).not.toMatch(REAL_TOKEN)
      expect(prompt.split(CODE)).toHaveLength(2)
    }
  })

  it('redeems the code with one node command that survives any shell’s double quotes', () => {
    const line = redeemLine(buildDshAgentPrompt('zh-CN', CODE, DSH_PAGE))

    expect(line).toMatch(/^node -e ".*"$/)
    const body = script(line)
    // bash 双引号会改写 $ 与反引号、交互式 bash 会展开 !，cmd 与 PowerShell 的双引号也不容内层双引号。
    expect(body).not.toMatch(/["$`!]/)
    expect(() => new Function(body)).not.toThrow()
    expect(body).toContain(`fetch('https://aigcnews.cn${MCP_INSTALL_CODE_REDEEM_PATH}'`)
    expect(body).toContain(`body:JSON.stringify({code:'${CODE}'})`)
    expect(body).toContain("accept:'text/plain'")
    expect(body).toContain(`s.split('${MCP_TOKEN_PLACEHOLDER}').join(t)`)
    expect(body).toContain("join(require('os').homedir(),'.dsh','profiles','web','cordis.patch.yml')")
  })

  it('redeems on the entry the page was opened from', () => {
    const prompt = buildDshAgentPrompt('en-US', CODE, 'https://aigcradar.online/dsh')

    expect(redeemLine(prompt)).toContain(`fetch('https://aigcradar.online${MCP_INSTALL_CODE_REDEEM_PATH}'`)
    expect(prompt).toContain('copy a fresh prompt from https://aigcradar.online/dsh')
  })

  it('keeps the token out of the agent’s output', () => {
    expect(buildDshAgentPrompt('zh-CN', CODE, DSH_PAGE)).toContain('Token 不会出现在输出里，你也不要读取、打印或复述它（也别用 --dump-config 查看配置）')
    expect(buildDshAgentPrompt('en-US', CODE, DSH_PAGE)).toContain('do not use --dump-config to look at the configuration either')
  })

  it('previews with the slot standing in for the install code', () => {
    expect(tokenSlots(buildDshAgentPrompt('zh-CN', COMMAND_TOKEN_SLOT, DSH_PAGE))).toHaveLength(1)
  })
})
