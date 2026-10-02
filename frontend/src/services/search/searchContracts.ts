/**
 * /api/search wire 契约（站内速查 ⌘K）：每组给前几条与命中总数；X 源关闭时没有 tweets 组；
 * 某组查询失败时组名列进 failed，其余组照常返回。
 */
export interface SearchGroupWire<T> {
  total?: number | null
  items?: T[] | null
}

export interface SearchProjectWire {
  full_name?: string | null
  url?: string | null
  description?: string | null
  description_zh?: string | null
  description_en?: string | null
  stars?: number | null
  language?: string | null
}

export interface SearchPaperWire {
  id?: string | null
  title?: string | null
  summary?: string | null
  date?: string | null
  authors?: string[] | null
  author_count?: number | null
}

export interface SearchBriefingWire {
  id?: number | null
  /** 这一期的日期 YYYY-MM-DD。 */
  date?: string | null
  /** 简报种类：all、arxiv、github、news、producthunt、hackernews、x、dailyhot。 */
  type?: string | null
  /** 这一期的标题。 */
  title?: string | null
  /** 命中那一条的条目名（「**名称**：正文」里的名称），没有时为空。 */
  lead?: string | null
  /** 截在命中处的一段正文。 */
  snippet?: string | null
}

export interface SearchTweetWire {
  id?: string | null
  text?: string | null
  url?: string | null
  author?: string | null
  date?: string | null
}

export interface SearchWireResponse {
  q?: string | null
  groups?: {
    projects?: SearchGroupWire<SearchProjectWire> | null
    papers?: SearchGroupWire<SearchPaperWire> | null
    briefings?: SearchGroupWire<SearchBriefingWire> | null
    tweets?: SearchGroupWire<SearchTweetWire> | null
  } | null
  failed?: string[] | null
}
