import { apiClient } from './client'

export interface TaskLog {
  id: number
  task_name: string
  task_type: string
  status: string
  started_at: string
  finished_at?: string | null
  duration_ms?: number | null
  message?: string | null
}

export interface DataFetchError {
  id: number
  source: string
  data_type: string
  target_code: string
  error_message: string
  occurred_at: string
  resolved: number
}

export async function listTaskLogs(): Promise<TaskLog[]> {
  const { data } = await apiClient.get<TaskLog[]>('/tasks/logs')
  return data
}

export async function listErrors(): Promise<DataFetchError[]> {
  const { data } = await apiClient.get<DataFetchError[]>('/errors', {
    params: { unresolved_only: true },
  })
  return data
}
