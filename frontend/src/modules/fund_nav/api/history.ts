import { apiClient } from '../../../api/client'

export type FundNavHistorySyncMode = 'recent_days' | 'date_range'

export interface FundNavHistorySyncRequest {
  mode: FundNavHistorySyncMode
  recent_days?: number | null
  start_date?: string | null
  end_date?: string | null
  workers: number
}

export interface FundNavHistorySyncStartResult {
  task_id?: number | null
  pid: number
  started: boolean
  start_date: string
  end_date: string
  workers: number
  stdout_log: string
  stderr_log: string
  message: string
}

export interface FundNavHistoryProgressCount {
  status: string
  count: number
}

export interface FundNavHistoryProgressItem {
  fund_code: string
  fund_name?: string | null
  status: string
  started_at?: string | null
  finished_at?: string | null
  duration_seconds?: number | null
  error?: string | null
}

export interface FundNavHistorySyncStatus {
  running: boolean
  task_id?: number | null
  pid?: number | null
  start_date: string
  end_date: string
  workers?: number | null
  stdout_log?: string | null
  stderr_log?: string | null
  counts: FundNavHistoryProgressCount[]
  latest_done: FundNavHistoryProgressItem[]
  running_items: FundNavHistoryProgressItem[]
  failed_items: FundNavHistoryProgressItem[]
}

export interface FundNavHistoryTask {
  id: number
  task_type: string
  status: string
  start_date: string
  end_date: string
  workers: number
  total_count: number
  success_count: number
  failed_count: number
  running_count: number
  skipped_count: number
  retry_count: number
  pid?: number | null
  stdout_log?: string | null
  stderr_log?: string | null
  message?: string | null
  started_at?: string | null
  finished_at?: string | null
  duration_seconds?: number | null
  created_at: string
}

export interface FundNavHistoryTaskDetail extends FundNavHistoryTask {
  counts: FundNavHistoryProgressCount[]
  latest_done: FundNavHistoryProgressItem[]
  running_items: FundNavHistoryProgressItem[]
  failed_items: FundNavHistoryProgressItem[]
}

export async function startFundNavHistorySync(payload: FundNavHistorySyncRequest): Promise<FundNavHistorySyncStartResult> {
  const { data } = await apiClient.post<FundNavHistorySyncStartResult>('/fund-nav/history-sync/start', payload, {
    timeout: 30000,
  })
  return data
}

export async function stopFundNavHistorySync(): Promise<{ stopped: boolean; message: string; task_id?: number | null; pid?: number | null }> {
  const { data } = await apiClient.post<{ stopped: boolean; message: string; task_id?: number | null; pid?: number | null }>(
    '/fund-nav/history-sync/stop',
  )
  return data
}

export async function getFundNavHistorySyncStatus(): Promise<FundNavHistorySyncStatus> {
  const { data } = await apiClient.get<FundNavHistorySyncStatus>('/fund-nav/history-sync/status')
  return data
}

export async function listFundNavHistorySyncTasks(): Promise<FundNavHistoryTask[]> {
  const { data } = await apiClient.get<{ tasks: FundNavHistoryTask[] }>('/fund-nav/history-sync/tasks')
  return data.tasks
}

export async function getFundNavHistorySyncTask(taskId: number): Promise<FundNavHistoryTaskDetail> {
  const { data } = await apiClient.get<FundNavHistoryTaskDetail>(`/fund-nav/history-sync/tasks/${taskId}`)
  return data
}

export async function rerunFundNavHistorySyncTask(taskId: number): Promise<FundNavHistorySyncStartResult> {
  const { data } = await apiClient.post<FundNavHistorySyncStartResult>(`/fund-nav/history-sync/tasks/${taskId}/rerun`)
  return data
}
