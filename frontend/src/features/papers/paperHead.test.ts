import { describe, expect, it } from 'vitest'
import { paperBoardRank, paperDay, paperUpvotes, parsePaperAuthors, sameDayEntries, splitAuthors } from './paperHead'

describe('paper head model', () => {
  it('reads authors from the JSON string the API returns, and from arrays', () => {
    expect(parsePaperAuthors('["Hao Li", "MeiJia Chen", " "]')).toEqual(['Hao Li', 'MeiJia Chen'])
    expect(parsePaperAuthors(['Ada', '', 7, 'Grace '])).toEqual(['Ada', 'Grace'])
    expect(parsePaperAuthors('Single Author')).toEqual(['Single Author'])
    expect(parsePaperAuthors('[broken')).toEqual([])
    expect(parsePaperAuthors('{"name":"x"}')).toEqual(['{"name":"x"}'])
    expect(parsePaperAuthors(null)).toEqual([])
    expect(parsePaperAuthors('')).toEqual([])
  })

  it('folds author lists only when more than one name would hide', () => {
    expect(splitAuthors(['A', 'B', 'C', 'D'])).toEqual({ visible: ['A', 'B', 'C', 'D'], hidden: [] })
    expect(splitAuthors(['A', 'B', 'C', 'D', 'E'])).toEqual({ visible: ['A', 'B', 'C'], hidden: ['D', 'E'] })
    expect(splitAuthors([])).toEqual({ visible: [], hidden: [] })
  })

  it('names the Hugging Face board and rank, and ignores other channels', () => {
    expect(paperBoardRank({ source_channel: 'huggingface_monthly_html', rank_in_period: 1 })).toEqual({ board: 'monthly', rank: 1 })
    expect(paperBoardRank({ source_channel: 'huggingface_daily_html', rank_in_period: '7' })).toEqual({ board: 'daily', rank: 7 })
    expect(paperBoardRank({ source_channel: 'huggingface_weekly_html', rank_in_period: 0 })).toBeNull()
    expect(paperBoardRank({ source_channel: 'arxiv_api', rank_in_period: 3 })).toBeNull()
    expect(paperBoardRank({})).toBeNull()
  })

  it('shows Hugging Face upvotes only for board papers with votes', () => {
    expect(paperUpvotes({ source_channel: 'huggingface_daily_html', raw_score: 201.0 })).toBe(201)
    expect(paperUpvotes({ source_channel: 'huggingface_daily_html', raw_score: 0 })).toBeNull()
    expect(paperUpvotes({ source_channel: 'arxiv_api', raw_score: 12 })).toBeNull()
  })

  it('takes the board day from the published timestamp', () => {
    expect(paperDay('2026-10-01T02:42:45')).toBe('2026-10-01')
    expect(paperDay('soon')).toBeNull()
    expect(paperDay(undefined)).toBeNull()
  })

  it('lists the day board in order and marks the open paper', () => {
    const entries = sameDayEntries([
      { id: 'a', title: ' First ', raw_score: 161, source_channel: 'huggingface_daily_html' },
      { id: null, title: 'No id' },
      { id: 42, title: 'Third', raw_score: 3, source_channel: 'huggingface_daily_html' },
      { id: 'tex', title: String.raw`\textbf{Aphanta}: Steering--Free` },
    ], '42')
    expect(entries).toEqual([
      { id: 'a', title: 'First', upvotes: 161, rank: 1, current: false },
      { id: '42', title: 'Third', upvotes: 3, rank: 3, current: true },
      { id: 'tex', title: 'Aphanta: Steering–Free', upvotes: null, rank: 4, current: false },
    ])
  })
})
