import hljs from 'highlight.js/lib/core'
import javascript from 'highlight.js/lib/languages/javascript'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import css from 'highlight.js/lib/languages/css'
import glsl from 'highlight.js/lib/languages/glsl'
import json from 'highlight.js/lib/languages/json'

hljs.registerLanguage('xml', xml)
hljs.registerLanguage('javascript', javascript)
hljs.registerLanguage('typescript', typescript)
hljs.registerLanguage('css', css)
hljs.registerLanguage('glsl', glsl)
hljs.registerLanguage('json', json)

const languages: Record<string, string> = { ts: 'typescript', tsx: 'typescript', js: 'javascript', jsx: 'javascript', vue: 'xml', html: 'xml', css: 'css', glsl: 'glsl', frag: 'glsl', vert: 'glsl', json: 'json' }
export function highlightSource(code: string, filename: string) {
  const extension = filename.split('.').pop()?.toLowerCase() ?? ''
  const language = languages[extension]
  // highlight.js escapes source HTML. Unrecognized files (including licenses) stay plain text.
  const html = language ? hljs.highlight(code, { language, ignoreIllegals: true }).value
    : code.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  return { html, label: language ? extension.toUpperCase() : 'TEXT' }
}
