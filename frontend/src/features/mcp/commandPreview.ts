/**
 * 终端预览：/mcp 的手动配置、/dsh 的提示词与安装命令一打开就能看全文，Token 的位置画成一块占位，页面上不出现真实 Token。
 *
 * 预览用一个只含大写字母的占位串代替 Token 去生成文本：JSON、YAML 或 Shell 引号转义都不会改动它，
 * 所以能在结果里原样找回来，切成「Token 占位」片段。
 */
export const COMMAND_TOKEN_SLOT = 'AIGCRADARTOKENSLOT'

export type CommandSegment =
  | { kind: 'text'; text: string }
  | { kind: 'token' }

export function splitCommandPreview(command: string, slot: string = COMMAND_TOKEN_SLOT): CommandSegment[] {
  const segments: CommandSegment[] = []
  command.split(slot).forEach((part, index) => {
    if (index > 0) segments.push({ kind: 'token' })
    if (part) segments.push({ kind: 'text', text: part })
  })
  return segments
}
