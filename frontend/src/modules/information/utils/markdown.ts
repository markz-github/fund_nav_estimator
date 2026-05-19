function escapeHtml(value: string) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function renderInlineMarkdown(value: string) {
  return escapeHtml(value)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>')
}

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

function listDepth(indent: string) {
  const spaces = indent.replace(/\t/g, '    ').length
  if (spaces >= 4) return Math.floor(spaces / 4) + 1
  if (spaces >= 2) return 2
  return 1
}

function isTableSeparator(value: string) {
  const cells = splitTableRow(value)
  return cells.length > 0 && cells.every((cell) => /^:?-{3,}:?$/.test(cell.trim()))
}

function splitTableRow(value: string) {
  const trimmed = value.trim()
  if (!trimmed.includes('|')) return []
  const normalized = trimmed.replace(/^\|/, '').replace(/\|$/, '')
  return normalized.split('|').map((cell) => cell.trim())
}

export function renderMarkdown(value: string) {
  const lines = value.split(/\r?\n/)
  const html: string[] = []
  const listStack: { type: 'ul' | 'ol' }[] = []
  let headingIndex = 0

  function closeLists(targetDepth = 0) {
    while (listStack.length > targetDepth) {
      const list = listStack.pop()
      html.push(`</${list?.type}>`)
    }
  }

  function syncList(type: 'ul' | 'ol', depth: number, start?: number) {
    while (listStack.length > depth) {
      const closedList = listStack.pop()
      html.push(`</${closedList?.type}>`)
    }
    if (listStack.length === depth && listStack[depth - 1]?.type !== type) {
      const closedList = listStack.pop()
      if (closedList) html.push(`</${closedList.type}>`)
    }
    while (listStack.length < depth) {
      const startAttr = type === 'ol' && start && start > 1 ? ` start="${start}"` : ''
      html.push(`<${type}${startAttr}>`)
      listStack.push({ type })
    }
  }

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index]
    const trimmed = line.trim()
    if (!trimmed) {
      closeLists()
      continue
    }
    const tableHeaders = splitTableRow(line)
    if (tableHeaders.length > 0 && lines[index + 1] && isTableSeparator(lines[index + 1])) {
      closeLists()
      index += 2
      const rows: string[][] = []
      while (index < lines.length) {
        const row = splitTableRow(lines[index])
        if (row.length === 0) {
          index -= 1
          break
        }
        rows.push(row)
        index += 1
      }
      if (index >= lines.length) index -= 1
      html.push('<div class="markdown-table-wrap"><table><thead><tr>')
      for (const header of tableHeaders) {
        html.push(`<th>${renderInlineMarkdown(header)}</th>`)
      }
      html.push('</tr></thead><tbody>')
      for (const row of rows) {
        html.push('<tr>')
        for (let cellIndex = 0; cellIndex < tableHeaders.length; cellIndex += 1) {
          html.push(`<td>${renderInlineMarkdown(row[cellIndex] ?? '')}</td>`)
        }
        html.push('</tr>')
      }
      html.push('</tbody></table></div>')
      continue
    }
    if (/^---+$/.test(trimmed)) {
      closeLists()
      html.push('<hr>')
      continue
    }
    const heading = trimmed.match(/^(#{1,4})\s+(.+)$/)
    if (heading) {
      closeLists()
      const level = heading[1].length
      headingIndex += 1
      html.push(`<h${level} id="heading-${headingIndex}">${renderInlineMarkdown(heading[2])}</h${level}>`)
      continue
    }
    const listItem = line.match(/^(\s*)[-*]\s+(.+)$/)
    if (listItem) {
      const depth = listDepth(listItem[1])
      syncList('ul', depth)
      html.push(`<li>${renderInlineMarkdown(listItem[2])}</li>`)
      continue
    }
    const orderedListItem = line.match(/^(\s*)(\d+)[.)]\s+(.+)$/)
    if (orderedListItem) {
      const depth = listDepth(orderedListItem[1])
      syncList('ol', depth, Number(orderedListItem[2]))
      html.push(`<li>${renderInlineMarkdown(orderedListItem[3])}</li>`)
      continue
    }
    const quote = trimmed.match(/^>\s?(.+)$/)
    if (quote) {
      closeLists()
      html.push(`<blockquote>${renderInlineMarkdown(quote[1])}</blockquote>`)
      continue
    }
    closeLists()
    html.push(`<p>${renderInlineMarkdown(trimmed)}</p>`)
  }
  closeLists()
  return html.join('')
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
