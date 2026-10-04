import { beforeAll, describe, expect, it } from 'vitest'
import { renderMarkdown } from '@/composables/useLatexRenderer'
import { paperAbstractMarkup, paperPlainText } from './paperLatex'

const NBSP = String.fromCharCode(0xa0)
const NARROW_NBSP = String.fromCharCode(0x202f)

// 样例取自 2026-10-04 线上的论文标题与摘要。
describe('paper LaTeX typesetting', () => {
  it('turns text-style commands into tags, nested ones included', () => {
    expect(paperAbstractMarkup(String.raw`We present \emph{The Harness of Harnesses} and \textbf{Aphanta}.`))
      .toBe('We present <em>The Harness of Harnesses</em> and <strong>Aphanta</strong>.')
    expect(paperAbstractMarkup(String.raw`\textit{\textbf{Knowing--Using Gap}}`)).toBe('<em><strong>Knowing–Using Gap</strong></em>')
    expect(paperAbstractMarkup(String.raw`\textbf{S\textsuperscript{3}Gym}`)).toBe('<strong>S<sup>3</sup>Gym</strong>')
    expect(paperAbstractMarkup(String.raw`\mbox{\textbf{Ventor-QTest}}`)).toBe('<strong>Ventor-QTest</strong>')
    expect(paperAbstractMarkup(String.raw`\underline{co}de and {\it Adaptive-masking} rest`))
      .toBe('<u>co</u>de and <em>Adaptive-masking</em> rest')
    expect(paperAbstractMarkup("\\texttt{--flag ``x''} and \\texttt{a\\_b}"))
      .toBe("<code>--flag &#96;&#96;x''</code> and <code>a&#95;b</code>")
  })

  it('keeps only the text where no markup is allowed', () => {
    expect(paperPlainText(String.raw`We present \emph{The Harness of Harnesses} and \textbf{S\textsuperscript{3}Gym}.`))
      .toBe('We present The Harness of Harnesses and S³Gym.')
    expect(paperPlainText(String.raw`\underline{co}de and {\it Adaptive-masking} rest`)).toBe('code and Adaptive-masking rest')
  })

  it('unescapes special characters, writing them as entities for markdown', () => {
    const source = String.raw`2\% of 158\,s, \#1, R\&D, \$400K`
    expect(paperAbstractMarkup(source)).toBe(`2% of 158${NARROW_NBSP}s, &#35;1, R&amp;D, &#36;400K`)
    expect(paperPlainText(source)).toBe(`2% of 158${NARROW_NBSP}s, #1, R&D, $400K`)
  })

  it('links \\href, \\url and a URL followed straight by its label', () => {
    expect(paperAbstractMarkup(String.raw`\href{https://github.com/a/b}{here} and \url{https://x.org/a\_b}`))
      .toBe('<a href="https://github.com/a/b">here</a> and <a href="https://x.org/a_b">https://x.org/a&#95;b</a>')
    expect(paperAbstractMarkup('on https://github.com/a/b{GitHub}.')).toBe('on <a href="https://github.com/a/b">GitHub</a>.')
    expect(paperPlainText('on https://github.com/a/b{GitHub}.')).toBe('on GitHub.')
    expect(paperAbstractMarkup(String.raw`\href{javascript:alert(1)}{x}`)).toBe('x')
  })

  it('drops citations with the space before them and keeps footnotes in brackets', () => {
    expect(paperAbstractMarkup(String.raw`verl~\cite{sheng2024} and effects~\citep[p.~3]{mankiw2020}, and more\footnote{see appendix}.`))
      .toBe('verl and effects, and more (see appendix).')
  })

  it('keeps the names of unknown macros and spells out symbols', () => {
    expect(paperPlainText(String.raw`\inter\ also \ours{}, a benchmark of 6{,}690`)).toBe('inter also ours, a benchmark of 6,690')
    expect(paperPlainText(String.raw`\textcolor{black}{a framework}, \eg, foo \eg. bar, 2\times faster, p\approx0.37`))
      .toBe('a framework, e.g., foo e.g. bar, 2× faster, p≈0.37')
  })

  it('sets quotes, dashes and ties like LaTeX, leaving options, arrows and approximate amounts alone', () => {
    expect(paperPlainText("a ``cold-start'' via GLM~5.1 at ~7M (~1% of (i)~the)"))
      .toBe(`a “cold-start” via GLM${NBSP}5.1 at ~7M (~1% of (i)${NBSP}the)`)
    expect(paperPlainText("idealized ''happy paths'', largely")).toBe('idealized “happy paths”, largely')
    expect(paperPlainText('a---b, human--AI, --flag, 0.84 -> 0.9')).toBe('a—b, human–AI, --flag, 0.84 -> 0.9')
    expect(paperPlainText('see https://a.org/~u/x--y for')).toBe('see https://a.org/~u/x--y for')
  })

  it('shows angle-bracket tokens instead of passing them on as HTML', () => {
    expect(paperAbstractMarkup('tokens such as </think> and <swi>')).toBe('tokens such as &lt;/think&gt; and &lt;swi&gt;')
    expect(paperPlainText('tokens such as </think> and <swi>')).toBe('tokens such as </think> and <swi>')
  })

  it('leaves formulas to KaTeX and keeps dollar prices from pairing up', () => {
    const source = String.raw`$\textbf{x}$ and $$\emph{y}$$ and \(\alpha\) at $4/$20`
    expect(paperAbstractMarkup(source)).toBe(String.raw`$\textbf{x}$ and $$\emph{y}$$ and \(\alpha\) at &#36;4/&#36;20`)
    expect(paperPlainText(source)).toBe(source)
  })

  it('composes accents, superscripts and subscripts', () => {
    expect(paperPlainText(String.raw`Schr\"odinger, caf\'{e}, \v{c}, don\'t`)).toBe("Schrödinger, café, č, don't")
    expect(paperAbstractMarkup('DR^{3}-Eval, x_{0.5}, 360^{circ}')).toBe('DR<sup>3</sup>-Eval, x<sub>0.5</sub>, 360°')
    expect(paperPlainText('DR^{3}-Eval, x_{0.5}, 360^{circ}')).toBe('DR³-Eval, x_0.5, 360°')
  })

  it('keeps stray braces and closes unfinished groups', () => {
    expect(paperAbstractMarkup(String.raw`6x faster}. and \textbf{unclosed`)).toBe('6x faster}. and <strong>unclosed</strong>')
    expect(paperAbstractMarkup(null)).toBe('')
    expect(paperPlainText(undefined)).toBe('')
  })
})

describe('typeset abstract through renderMarkdown', () => {
  beforeAll(() => {
    document.write('<!doctype html><html><body></body></html>')
    document.close()
  })

  it('renders styles, symbols and formulas with no LaTeX left over', () => {
    const html = renderMarkdown(paperAbstractMarkup(String.raw`We call it \emph{The Harness}, costing \$5 for 2\% of $x^2$ tokens such as <swi>.`))
    expect(html).toContain('<em>The Harness</em>')
    expect(html).toContain('costing $5 for 2% of')
    expect(html).toContain('class="katex"')
    expect(html).toContain('&lt;swi&gt;')
    expect(html).not.toMatch(/\\(?:emph|%|\$)/)
  })
})
