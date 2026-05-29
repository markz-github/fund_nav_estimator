import MarkdownIt from 'markdown-it'
import katex from 'katex'
import type StateBlock from 'markdown-it/lib/rules_block/state_block.mjs'
import type StateInline from 'markdown-it/lib/rules_inline/state_inline.mjs'

export interface MarkdownHeading {
  id: string
  level: number
  text: string
}

function plainInlineText(value: string) {
  return value
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
    .trim()
}

function renderMath(value: string, displayMode: boolean) {
  return katex.renderToString(value, {
    displayMode,
    throwOnError: false,
    strict: false,
    trust: false,
  })
}

function markdownMathPlugin(md: MarkdownIt) {
  md.block.ruler.before('fence', 'math_block', (state: StateBlock, startLine: number, endLine: number, silent: boolean) => {
    const start = state.bMarks[startLine] + state.tShift[startLine]
    const max = state.eMarks[startLine]
    const firstLine = state.src.slice(start, max).trim()

    if (!firstLine.startsWith('$$')) return false

    const singleLine = firstLine.match(/^\$\$(.+)\$\$$/)
    if (singleLine) {
      if (silent) return true
      const token = state.push('math_block', 'math', 0)
      token.block = true
      token.content = singleLine[1].trim()
      token.map = [startLine, startLine + 1]
      state.line = startLine + 1
      return true
    }

    if (firstLine !== '$$') return false

    let nextLine = startLine + 1
    const contentLines: string[] = []
    while (nextLine < endLine) {
      const lineStart = state.bMarks[nextLine] + state.tShift[nextLine]
      const lineMax = state.eMarks[nextLine]
      const line = state.src.slice(lineStart, lineMax)
      if (line.trim() === '$$') break
      contentLines.push(line)
      nextLine += 1
    }

    if (nextLine >= endLine) return false
    if (silent) return true

    const token = state.push('math_block', 'math', 0)
    token.block = true
    token.content = contentLines.join('\n').trim()
    token.map = [startLine, nextLine + 1]
    state.line = nextLine + 1
    return true
  })

  md.inline.ruler.after('escape', 'math_inline', (state: StateInline, silent: boolean) => {
    if (state.src.charCodeAt(state.pos) !== 0x24) return false
    if (state.src.charCodeAt(state.pos + 1) === 0x24) return false

    const end = state.src.indexOf('$', state.pos + 1)
    if (end < 0) return false

    const content = state.src.slice(state.pos + 1, end).trim()
    if (!content) return false
    if (silent) return true

    const token = state.push('math_inline', 'math', 0)
    token.content = content
    state.pos = end + 1
    return true
  })
}

function quotedStrongPlugin(md: MarkdownIt) {
  md.inline.ruler.before('emphasis', 'quoted_strong', (state: StateInline, silent: boolean) => {
    const start = state.pos
    if (state.src.charCodeAt(start) !== 0x2a || state.src.charCodeAt(start + 1) !== 0x2a) return false
    const firstContentChar = state.src[start + 2]
    if (!firstContentChar || !'“"「『'.includes(firstContentChar)) return false

    const end = state.src.indexOf('**', start + 3)
    if (end < 0) return false
    const content = state.src.slice(start + 2, end)
    if (!content.trim()) return false
    if (silent) return true

    const openToken = state.push('strong_open', 'strong', 1)
    openToken.markup = '**'
    const textToken = state.push('text', '', 0)
    textToken.content = content
    const closeToken = state.push('strong_close', 'strong', -1)
    closeToken.markup = '**'
    state.pos = end + 2
    return true
  })
}

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: false,
})

quotedStrongPlugin(md)
markdownMathPlugin(md)

md.renderer.rules.heading_open = (tokens, index, options, env, self) => {
  const token = tokens[index]
  const level = Number(token.tag.replace('h', ''))
  if (level >= 1 && level <= 4) {
    env.headingIndex = (env.headingIndex || 0) + 1
    token.attrSet('id', `heading-${env.headingIndex}`)
  }
  return self.renderToken(tokens, index, options)
}

md.renderer.rules.link_open = (tokens, index, options, env, self) => {
  const token = tokens[index]
  const href = token.attrGet('href') || ''
  if (/^https?:\/\//i.test(href)) {
    token.attrSet('target', '_blank')
    token.attrSet('rel', 'noreferrer')
  }
  return self.renderToken(tokens, index, options)
}

md.renderer.rules.table_open = (tokens, index, options, env, self) => {
  return `<div class="markdown-table-wrap">${self.renderToken(tokens, index, options)}`
}

md.renderer.rules.table_close = (tokens, index, options, env, self) => {
  return `${self.renderToken(tokens, index, options)}</div>`
}

md.renderer.rules.math_block = (tokens, index) => {
  return `<div class="markdown-math-block">${renderMath(tokens[index].content, true)}</div>`
}

md.renderer.rules.math_inline = (tokens, index) => {
  return renderMath(tokens[index].content, false)
}

export function renderMarkdown(value: string) {
  return md.render(value, { headingIndex: 0 })
}

export function extractMarkdownHeadings(value: string): MarkdownHeading[] {
  const headings: MarkdownHeading[] = []
  for (const line of value.split(/\r?\n/)) {
    const heading = line.trim().match(/^(#{1,4})\s+(.+)$/)
    if (!heading) continue
    headings.push({
      id: `heading-${headings.length + 1}`,
      level: heading[1].length,
      text: plainInlineText(heading[2]),
    })
  }
  return headings
}
