export function formatDateTime(value?: string | Date | null) {
  if (!value) return '-'
  if (value instanceof Date) return formatDateParts(value)

  const text = String(value).trim()
  const match = text.match(
    /^(\d{4})-(\d{2})-(\d{2})[T\s](\d{2}):(\d{2})(?::(\d{2}))?/,
  )
  if (match) {
    const [, year, month, day, hour, minute, second = '00'] = match
    return `${year}-${month}-${day} ${hour}:${minute}:${second}`
  }

  const parsed = new Date(text)
  if (!Number.isNaN(parsed.getTime())) return formatDateParts(parsed)
  return text
}

export function formatDate(value?: string | Date | null) {
  if (!value) return '-'
  if (value instanceof Date) return formatDateParts(value).slice(0, 10)

  const text = String(value).trim()
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (match) {
    const [, year, month, day] = match
    return `${year}-${month}-${day}`
  }

  const parsed = new Date(text)
  if (!Number.isNaN(parsed.getTime())) return formatDateParts(parsed).slice(0, 10)
  return text
}

function formatDateParts(value: Date) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  const hour = String(value.getHours()).padStart(2, '0')
  const minute = String(value.getMinutes()).padStart(2, '0')
  const second = String(value.getSeconds()).padStart(2, '0')
  return `${year}-${month}-${day} ${hour}:${minute}:${second}`
}
