/**
 * 接入命令预览：/mcp 与 /dsh 在桌面上一打开就把命令摆出来，Token 的位置画成一块占位，页面上不出现真实 Token。
 *
 * 预览用一个只含大写字母的占位串代替 Token 去生成命令：生成器对它做 JSON、YAML 或 Shell 引号转义都不会改动它，
 * 所以能在结果里原样找回来，切成「Token 占位」片段。命令提示符下的 PowerShell -EncodedCommand 把整段脚本
 * （连同 Token）编成了 base64，用占位串编出来的 base64 没有意义，整段换成一块「编码脚本」占位。
 */
export const COMMAND_TOKEN_SLOT = 'AIGCRADARTOKENSLOT'

export type CommandSegment =
  | { kind: 'text'; text: string }
  | { kind: 'token' }
  | { kind: 'encoded' }

const ENCODED_COMMAND = /(-EncodedCommand\s+)([A-Za-z0-9+/]+=*)/g

export function splitCommandPreview(command: string, slot: string = COMMAND_TOKEN_SLOT): CommandSegment[] {
  const segments: CommandSegment[] = []
  const pushText = (text: string) => {
    text.split(slot).forEach((part, index) => {
      if (index > 0) segments.push({ kind: 'token' })
      if (part) segments.push({ kind: 'text', text: part })
    })
  }
  let cursor = 0
  for (const match of command.matchAll(ENCODED_COMMAND)) {
    const start = (match.index ?? 0) + match[1]!.length
    pushText(command.slice(cursor, start))
    segments.push({ kind: 'encoded' })
    cursor = start + match[2]!.length
  }
  pushText(command.slice(cursor))
  return segments
}
