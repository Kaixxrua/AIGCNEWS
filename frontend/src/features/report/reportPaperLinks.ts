// 简报条目里的论文链接：Hugging Face 论文页（含镜像 hf-mirror.com）、arXiv、alphaXiv。认出其中的 arXiv 编号，
// 宽屏上点开时不离开简报，在右侧看这篇的详情。只认新式编号（2609.33439），老式（cs/0101001）简报里不会出现。

import type { BroadsheetItem } from './reportBroadsheet'

export interface PaperLink {
  /** 不带版本号的 arXiv 编号，如 2609.33439。 */
  arxivId: string
  href: string
  /** 链接文字去掉「来源」一类的尾巴：「Raven来源」→「Raven」；只剩「论文」「Paper」这类泛称时为空串。 */
  label: string
}

const PAPER_HOST = /^(?:www\.)?(?:hf-mirror\.com|huggingface\.co|arxiv\.org|export\.arxiv\.org|alphaxiv\.org)$/i
const PAPER_PATH = /^\/(?:papers|abs|pdf|html|overview)\/(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?\/?$/
// 链接文字结尾的「来源」「原文」「Source」等，与它前面的「的」、空格、冒号
const LABEL_TAIL = /[\s:：·-]*(?:的)?(?:论文)?(?:来源|原文|出处|链接|主页|地址)$|[\s:：·-]*(?:paper|source|link|arxiv|abstract)$/i
const GENERIC_LABEL = /^(?:论文|文章|原文|来源|paper|source|link|arxiv|hf|hugging\s*face)?$/i

/** 链接指向的论文的 arXiv 编号（不带版本号）；不是论文链接为 null。 */
export function paperArxivId(href: string | null | undefined): string | null {
  if (!href) return null
  let url: URL
  try {
    url = new URL(href)
  } catch {
    return null
  }
  if (!/^https?:$/.test(url.protocol) || !PAPER_HOST.test(url.hostname)) return null
  const match = PAPER_PATH.exec(url.pathname)
  if (!match) return null
  // Hugging Face 只有 /papers/ 是论文页；arXiv、alphaXiv 没有 /papers/。
  const huggingFace = /(?:^|\.)(?:hf-mirror\.com|huggingface\.co)$/i.test(url.hostname)
  return huggingFace === url.pathname.startsWith('/papers/') ? match[1]! : null
}

export function paperLinkLabel(text: string): string {
  const trimmed = text.replace(/\s+/g, ' ').trim()
  const label = trimmed.replace(LABEL_TAIL, '').trim()
  return GENERIC_LABEL.test(label) ? '' : label
}

/** 一段（已消毒的）HTML 里的论文链接，按出现顺序，同一篇只留第一次。 */
export function paperLinksIn(html: string): PaperLink[] {
  if (!html || !html.includes('href')) return []
  const template = document.createElement('template')
  template.innerHTML = html
  const links: PaperLink[] = []
  for (const anchor of Array.from(template.content.querySelectorAll('a[href]'))) {
    const href = anchor.getAttribute('href') ?? ''
    const arxivId = paperArxivId(href)
    if (arxivId && !links.some(link => link.arxivId === arxivId)) links.push({ arxivId, href, label: paperLinkLabel(anchor.textContent ?? '') })
  }
  return links
}

/** 条目讲到的论文：先是条目底行的出处（简报按约定把论文链接放在那里），再是正文、标题里提到的。 */
export function itemPaperLinks(item: Pick<BroadsheetItem, 'source' | 'body' | 'lead' | 'note'>): PaperLink[] {
  const links: PaperLink[] = []
  for (const html of [item.source, item.body, item.lead, item.note]) {
    for (const link of paperLinksIn(html)) if (!links.some(known => known.arxivId === link.arxivId)) links.push(link)
  }
  return links
}
