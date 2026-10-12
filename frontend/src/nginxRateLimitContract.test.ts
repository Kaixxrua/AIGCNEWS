/// <reference types="node" />
import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

/**
 * nginx 限流分桶契约：
 * - 项目 logo 走独立的 api_logo 桶。一屏榜单/项目库会同时发几十个 logo 请求，
 *   与数据接口共用 api_general 时 logo 先把桶耗尽，随后的数据请求被 429；
 * - 数据接口（/api/、/api/mcp）仍走 api_general；认证端点临时取消 Nginx 限流；
 * - MCP OAuth 入口（/api/mcp/oauth）与 /api/mcp 是同一个 Go 网关，块内指令逐条一致；
 * - logo 块的转发口径与 /api/ 块一致（后端按 X-Forwarded-For 首跳取客户端）；
 * - 不能有正则 location 抢先匹配 logo 路径（nginx 中正则优先于普通前缀）。
 */

// vitest 从 frontend 根目录运行（npm scripts 与 CI 一致）。
const frontendRoot = process.cwd()

const nginxConf = readFileSync(`${frontendRoot}/nginx.conf`, 'utf-8')

const LOGO_PATH = '/api/projects/github/logo/'

// 取出 `location <修饰符+路径> {` 后的块体（按花括号配对，不依赖块内无嵌套）。
function extractLocationBody(conf: string, head: string): string {
  const start = conf.indexOf(`location ${head} {`)
  if (start < 0) throw new Error(`nginx.conf 缺少 location ${head} 块`)
  const open = conf.indexOf('{', start)
  let depth = 0
  for (let index = open; index < conf.length; index += 1) {
    if (conf[index] === '{') depth += 1
    if (conf[index] === '}') depth -= 1
    if (depth === 0) return conf.slice(open + 1, index)
  }
  throw new Error(`location ${head} 块花括号不配对`)
}

function limitZones(body: string): string[] {
  return [...body.matchAll(/^\s*limit_req\s+zone=(\w+)/gm)].map((match) => match[1] ?? '')
}

describe('nginx 限流分桶契约', () => {
  it('声明 api_logo 区，按客户端地址计数', () => {
    expect(nginxConf).toMatch(/^limit_req_zone\s+\$binary_remote_addr\s+zone=api_logo:\d+m\s+rate=\d+r\/s;/m)
  })

  it('logo 前缀块只用 api_logo 桶', () => {
    expect(limitZones(extractLocationBody(nginxConf, LOGO_PATH))).toEqual(['api_logo'])
  })

  it('数据接口的桶不变', () => {
    expect(limitZones(extractLocationBody(nginxConf, '/api/'))).toEqual(['api_general'])
    expect(limitZones(extractLocationBody(nginxConf, '= /api/mcp'))).toEqual(['api_general'])
  })

  it('认证端点临时取消 Nginx 限流，继续转发登录入口、回调与凭据接收请求', () => {
    const auth = extractLocationBody(nginxConf, '/api/auth/')
    expect(limitZones(auth)).toEqual([])
    expect(nginxConf).not.toMatch(/^\s*limit_req_zone\s+.*\bzone=api_auth:/m)
    expect(auth).toContain('proxy_pass $backend_upstream$request_uri;')
    expect(auth).toContain('proxy_set_header Host $host;')
    expect(auth).toContain('proxy_set_header X-Forwarded-For $remote_addr;')
    expect(auth).toContain('proxy_set_header X-Forwarded-Proto $scheme;')
  })

  it('MCP OAuth 入口与 /api/mcp 块指令逐条一致（同桶、同上游、同 SSE 设置）', () => {
    const directives = (body: string) =>
      body
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => line !== '' && !line.startsWith('#'))
    const oauth = directives(extractLocationBody(nginxConf, '= /api/mcp/oauth'))
    expect(oauth).toContain('proxy_pass $mcp_go_upstream$request_uri;')
    expect(oauth).toEqual(directives(extractLocationBody(nginxConf, '= /api/mcp')))
  })

  it('logo 块转发到主后端，转发头与 /api/ 块同口径', () => {
    const logo = extractLocationBody(nginxConf, LOGO_PATH)
    const api = extractLocationBody(nginxConf, '/api/')
    const forwarding = (body: string) =>
      body
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => /^proxy_(pass|http_version|set_header (Host|X-Real-IP|X-Forwarded-For|X-Forwarded-Proto))\s/.test(line))
    expect(forwarding(logo)).toContain('proxy_pass $backend_upstream$request_uri;')
    expect(forwarding(logo)).toContain('proxy_set_header X-Forwarded-For $remote_addr;')
    expect(forwarding(logo)).toEqual(forwarding(api))
  })

  it('没有正则 location 抢先匹配 logo 路径', () => {
    const sample = `${LOGO_PATH}openai/codex`
    const regexLocations = [...nginxConf.matchAll(/^\s*location\s+(~\*?)\s+(\S+)\s*\{/gm)]
    expect(regexLocations.length).toBeGreaterThan(0)
    for (const [, modifier, pattern] of regexLocations) {
      expect(new RegExp(pattern ?? '', modifier === '~*' ? 'i' : '').test(sample)).toBe(false)
    }
  })
})
