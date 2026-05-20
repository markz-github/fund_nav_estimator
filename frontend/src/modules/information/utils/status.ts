const successStatuses = new Set(['done', 'success', 'enabled', 'note_done', 'article_summary_done', '正常'])
const failedStatuses = new Set(['failed', 'fail', 'error', 'cancelled', 'canceled', 'note_failed', 'article_summary_failed', '异常'])
const runningStatuses = new Set([
  'running',
  'pending',
  'note_running',
  'note_pending',
  'article_pending',
  'article_summary_running',
  'discovered',
  'processing',
  'in_progress',
])
const mutedStatuses = new Set(['skipped', 'disabled', '停用'])

export function statusClass(status: string | number | null | undefined) {
  const normalized = String(status ?? '').trim().toLowerCase()
  if (successStatuses.has(normalized) || successStatuses.has(String(status ?? '').trim())) return 'status-ok'
  if (failedStatuses.has(normalized) || failedStatuses.has(String(status ?? '').trim())) return 'status-danger'
  if (runningStatuses.has(normalized)) return 'status-warn'
  if (mutedStatuses.has(normalized) || mutedStatuses.has(String(status ?? '').trim())) return 'status-muted'
  return 'status-warn'
}
