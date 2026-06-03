import { apiClient } from '../../../api/client'

export type HistorySyncMode = 'recent_days' | 'date_range'

export interface HistorySyncRequest {
  mode: HistorySyncMode
  recent_days?: number | null
  start_date?: string | null
  end_date?: string | null
  workers: number
}

export interface HistorySyncStartResult {
  pid: number
  started: boolean
  start_date: string
  end_date: string
  workers: number
  stdout_log: string
  stderr_log: string
  message: string
}

export interface ProgressCount {
  status: string
  count: number
}

export interface ProgressItem {
  symbol: string
  stock_name?: string | null
  status: string
  started_at?: string | null
  finished_at?: string | null
  duration_seconds?: number | null
  error?: string | null
}

export interface HistorySyncStatus {
  running: boolean
  pid?: number | null
  start_date: string
  end_date: string
  workers?: number | null
  stdout_log?: string | null
  stderr_log?: string | null
  counts: ProgressCount[]
  latest_done: ProgressItem[]
  running_items: ProgressItem[]
  failed_items: ProgressItem[]
}

export async function startHistorySync(payload: HistorySyncRequest): Promise<HistorySyncStartResult> {
  const { data } = await apiClient.post<HistorySyncStartResult>('/a-stocks/history-sync/start', payload, {
    timeout: 30000,
  })
  return data
}

export async function getHistorySyncStatus(filters?: { startDate?: string; endDate?: string }): Promise<HistorySyncStatus> {
  const { data } = await apiClient.get<HistorySyncStatus>('/a-stocks/history-sync/status', {
    params: {
      start_date: filters?.startDate || undefined,
      end_date: filters?.endDate || undefined,
    },
  })
  return data
}
