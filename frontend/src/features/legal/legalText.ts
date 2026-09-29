/* 法律页正文的展示辅助。目录另有 01–09 编号，所以去掉标题自带的「一、」「1. 」序号；
   条目以「标签：」开头时（如「邮箱地址：」「处理时限：」）拆出标签单独加粗，便于扫读。
   标签须在 32 字以内且不含句读，冒号后还得有正文——句末的「请联系：」不拆。 */
export const tocLabel = (title: string) => title.replace(/^\s*(?:[一二三四五六七八九十]+、|\d+\.\s+)/, '')

const LEAD = /^([^，。,.;；:：]{1,32}?[:：])(\s*\S[\s\S]*)$/

export const splitLead = (text: string): [lead: string, rest: string] | null => {
  const match = LEAD.exec(text)
  return match ? [match[1]!, match[2]!] : null
}
