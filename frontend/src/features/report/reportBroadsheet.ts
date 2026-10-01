// 桌面大报版式（≥1024px）：把渲染、消毒过的简报 HTML 拆成「刊头说明 / 分节 / 条目」三层，交给
// ReportBroadsheet 排成多栏。只在已消毒的节点上拆分、序列化，不增删文字；条目打头的粗体（**名称**：正文）
// 升格为标题句，名称后的分隔符（：、——、—）随之去掉，名称后的括注（如仓库名）单列一格；条目结尾的出处链接
// 挪到条目底行。

export interface BroadsheetItem {
  /** 有序列表里的序号；无序列表为 null。 */
  number: number | null
  /** 标题句：打头粗体的内部 HTML。粗体与正文连成一句（**CoWA** provides…）或条目不以粗体打头时为空串。 */
  lead: string
  /** 标题句后的括注，连括号保留，如（feder-cr/dots）。 */
  note: string
  /** 正文 HTML；分出标题句、出处时已去掉打头的粗体与分隔符、结尾的出处。 */
  body: string
  /** 条目结尾的出处链接 HTML，连同其前的「来源：」与链接间的顿号；没有为空串。 */
  source: string
}

export type BroadsheetBlock =
  /** 相邻的顶层段落；ems 是按字宽估的总长（汉字记 1，拉丁字符记 0.55），用来决定分不分栏。 */
  | { kind: 'prose'; paragraphs: string[]; ems: number }
  | { kind: 'items'; ordered: boolean; items: BroadsheetItem[] }
  /** 「生成日期：…」「Edition date: …」一类说明行。 */
  | { kind: 'meta'; html: string }
  /** 其余块（小标题、引用、公式、表格等）原样保留。 */
  | { kind: 'raw'; html: string }

export interface BroadsheetSection {
  /** h2 的内部 HTML（含标签 code）。 */
  heading: string
  blocks: BroadsheetBlock[]
}

export interface Broadsheet {
  /** 第一个 h2 之前的内容（报名 h1 除外）：说明行与导语。 */
  intro: BroadsheetBlock[]
  sections: BroadsheetSection[]
  /** 文末单独成段的生成日期说明（综合简报写在最后），没有为空串。 */
  dateline: string
}

const META_RE = /^(?:生成日期|生成时间|榜单日期|报告日期|Generated|Generation date|Edition date|Ranking date|Report date)\s*[：:]/i
// 名称与正文之间的分隔符：冒号、破折号（一字线或两个），或两侧带空格的连字符。
const SEPARATOR_RE = /^(?:\s*(?:[：:]|—{1,2}|–)\s*|\s+-\s+)/
// 名称后紧跟括注再接分隔符：**dots**（feder-cr/dots）：…
const NOTE_RE = /^\s*([（(][^（）()]{1,120}[）)])\s*(?:[：:]|—{1,2}|–)\s*/
const TRAILING_COLON_RE = /\s*[：:]\s*$/
// 简报约定每条以 Markdown 链接附上来源：「…。[来源](…)」「…。[论文原文](…)」「…。来源：[A](…)、[B](…)」。
const SOURCE_LABEL_RE = /(?:来源|出处|原文|Sources?|Via)\s*[：:]\s*$/i
// 几条出处链接之间只隔着顿号、逗号、斜杠或空白
const SOURCE_JOINER_RE = /^[\s、，,/|·]*$/
const SENTENCE_END_RE = /[。！？!?.…；;）)」』”’"】\]]$/

const ELEMENT = 1
const TEXT = 3

const isBlank = (node: Node) => node.nodeType === TEXT && !(node.textContent ?? '').trim()

const firstMeaningful = (parent: Node): ChildNode | null => {
  for (const node of Array.from(parent.childNodes)) if (!isBlank(node)) return node
  return null
}

const lastMeaningful = (parent: Node): ChildNode | null => {
  const nodes = Array.from(parent.childNodes)
  for (let index = nodes.length - 1; index >= 0; index--) if (!isBlank(nodes[index]!)) return nodes[index]!
  return null
}

const isElement = (node: Node | null, tag?: string): node is Element =>
  node?.nodeType === ELEMENT && (!tag || (node as Element).tagName === tag)

const isMeta = (el: Element) => META_RE.test((el.textContent ?? '').trim())

const ems = (text: string) => {
  let width = 0
  for (const char of text) width += char.charCodeAt(0) > 0x2e7f ? 1 : 0.55
  return Math.round(width)
}

const serialize = (node: Node) => (isElement(node) ? node.outerHTML : node.textContent ?? '')

/** 去掉开头的空白文本节点与文本开头的空白。 */
const trimStart = (parent: Node) => {
  for (const node of Array.from(parent.childNodes)) {
    if (isBlank(node)) {
      node.remove()
      continue
    }
    if (node.nodeType === TEXT) node.textContent = (node.textContent ?? '').replace(/^\s+/, '')
    return
  }
}

/** 正文：宿主（松散列表是首段 p，紧凑列表是 li 本身）的内容，加上首段之后的其余块。 */
const bodyOf = (li: Element, host: Element) => {
  trimStart(host)
  if (host === li) return li.innerHTML.trim()
  const rest: string[] = []
  for (let node = host.nextSibling; node; node = node.nextSibling) rest.push(serialize(node))
  return (host.innerHTML + rest.join('')).trim()
}

/** 打头的粗体升格为标题句：从宿主里去掉粗体与其后的分隔符，返回标题句与括注；不升格时宿主不动，都为空串。 */
const takeLead = (host: Element): Pick<BroadsheetItem, 'lead' | 'note'> => {
  const none = { lead: '', note: '' }
  const strong = firstMeaningful(host)
  if (!isElement(strong, 'STRONG')) return none

  const next = strong.nextSibling
  let note = ''
  if (TRAILING_COLON_RE.test(strong.textContent ?? '') && strong.lastChild?.nodeType === TEXT) {
    // **要点：**正文：冒号写在粗体里
    strong.lastChild.textContent = (strong.lastChild.textContent ?? '').replace(TRAILING_COLON_RE, '')
  } else if (next?.nodeType === TEXT) {
    const text = next.textContent ?? ''
    const withNote = NOTE_RE.exec(text)
    const separator = withNote ? null : SEPARATOR_RE.exec(text)
    if (withNote) {
      note = withNote[1] ?? ''
      next.textContent = text.slice(withNote[0].length)
    } else if (separator) {
      next.textContent = text.slice(separator[0].length)
    } else {
      // 粗体是句子的主语（**CoWA** provides…）：不拆，整句留在正文里。
      return none
    }
  } else if (isElement(next, 'BR')) {
    next.remove()
  } else if (next) {
    return none
  }
  const lead = strong.innerHTML.trim()
  strong.remove()
  return { lead, note }
}

/**
 * 取出条目结尾的出处链接（连同其前的「来源：」与链接间的顿号）并从条目里去掉，排到条目底行，正文截断时也能直接点到。
 * 链接嵌在句子里（前文不以句末标点收尾、也没有「来源：」）或取走后正文就空了，则留在原处。
 */
const takeSource = (li: Element): string => {
  // 松散列表的出处写在最后一段末尾
  let tail: Element = li
  for (let last = lastMeaningful(tail); isElement(last, 'P'); last = lastMeaningful(tail)) tail = last
  const run: ChildNode[] = []
  for (let node = lastMeaningful(tail); node; node = node.previousSibling) {
    if (isElement(node, 'A')) run.unshift(node)
    else if (run.length && node.nodeType === TEXT && SOURCE_JOINER_RE.test(node.textContent ?? '') && isElement(node.previousSibling, 'A')) run.unshift(node)
    else break
  }
  const first = run[0]
  if (!first) return ''

  const previous = first.previousSibling
  const label = previous?.nodeType === TEXT ? SOURCE_LABEL_RE.exec(previous.textContent ?? '')?.[0] ?? '' : ''
  const range = document.createRange()
  range.setStart(li, 0)
  range.setEndBefore(first)
  const preceding = range.toString()
  const before = preceding.slice(0, preceding.length - label.length).trim()
  if (!before || (!label && !SENTENCE_END_RE.test(before))) return ''

  const holder = document.createElement('span')
  if (label && previous) {
    previous.textContent = (previous.textContent ?? '').slice(0, -label.length)
    holder.append(label)
  }
  holder.append(...run)
  if (tail !== li && tail !== firstMeaningful(li) && !lastMeaningful(tail)) tail.remove()
  return holder.innerHTML
}

const splitItem = (li: Element): Omit<BroadsheetItem, 'number'> => {
  const firstChild = firstMeaningful(li)
  const host = isElement(firstChild, 'P') ? firstChild : li
  const { lead, note } = takeLead(host)
  const source = takeSource(li)
  return { lead, note, body: bodyOf(li, host), source }
}

const parseItems = (list: Element): BroadsheetBlock => {
  const ordered = list.tagName === 'OL'
  const start = ordered ? Number.parseInt(list.getAttribute('start') ?? '', 10) || 1 : 1
  const items: BroadsheetItem[] = []
  for (const child of Array.from(list.children)) {
    const number = ordered ? start + items.length : null
    if (child.tagName === 'LI') items.push({ number, ...splitItem(child) })
    else items.push({ number, lead: '', note: '', body: child.outerHTML, source: '' })
  }
  return { kind: 'items', ordered, items }
}

const pushParagraph = (blocks: BroadsheetBlock[], el: Element) => {
  const last = blocks[blocks.length - 1]
  const width = ems(el.textContent ?? '')
  if (last?.kind === 'prose') {
    last.paragraphs.push(el.innerHTML)
    last.ems += width
  } else {
    blocks.push({ kind: 'prose', paragraphs: [el.innerHTML], ems: width })
  }
}

export const parseBroadsheet = (html: string): Broadsheet => {
  const template = document.createElement('template')
  template.innerHTML = html
  const sheet: Broadsheet = { intro: [], sections: [], dateline: '' }
  const nodes = Array.from(template.content.childNodes).filter(node => node.nodeType === ELEMENT || !isBlank(node))
  const tail = nodes[nodes.length - 1]
  if (isElement(tail ?? null, 'P') && isMeta(tail as Element) && nodes.some(node => isElement(node, 'H2'))) {
    sheet.dateline = (tail as Element).innerHTML
    nodes.pop()
  }

  let blocks = sheet.intro
  let titled = false
  for (const node of nodes) {
    if (!isElement(node)) {
      if (node.nodeType !== TEXT) continue
      // 顶层散落的文字（流式生成到一半时偶有）当作一段。
      const paragraph = document.createElement('p')
      paragraph.textContent = node.textContent ?? ''
      pushParagraph(blocks, paragraph)
      continue
    }
    switch (node.tagName) {
      case 'H1':
        // 报名与当前分区签重复，桌面版向来不显示；之后再出现的 h1 原样保留。
        if (!titled && !sheet.sections.length) {
          titled = true
          continue
        }
        blocks.push({ kind: 'raw', html: node.outerHTML })
        break
      case 'H2': {
        const section: BroadsheetSection = { heading: node.innerHTML, blocks: [] }
        sheet.sections.push(section)
        blocks = section.blocks
        break
      }
      case 'P':
        if (!sheet.sections.length && isMeta(node)) blocks.push({ kind: 'meta', html: node.innerHTML })
        else pushParagraph(blocks, node)
        break
      case 'OL':
      case 'UL':
        blocks.push(parseItems(node))
        break
      default:
        blocks.push({ kind: 'raw', html: node.outerHTML })
    }
  }
  return sheet
}
