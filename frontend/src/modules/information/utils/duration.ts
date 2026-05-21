export function formatDurationSeconds(value?: number | null) {
  if (value === null || value === undefined || !Number.isFinite(value) || value < 0) return '-'
  const totalSeconds = Math.floor(value)
  const seconds = String(totalSeconds % 60).padStart(2, '0')
  const totalMinutes = Math.floor(totalSeconds / 60)
  const minutes = String(totalMinutes % 60).padStart(2, '0')
  const hours = Math.floor(totalMinutes / 60)
  if (hours > 0) return `${hours}:${minutes}:${seconds}`
  return `${totalMinutes}:${seconds}`
}
