import { apiClient } from '../../../api/client'

export type OperationModule = 'fund_nav' | 'information'

export interface TaskLog {
  id: number
  task_name: string
  task_type: string
  target_type?: string | null
  target_id?: string | null
  external_task_id?: string | null
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

export async function listTaskLogs(module: OperationModule, taskType?: string): Promise<TaskLog[]> {
  const { data } = await apiClient.get<TaskLog[]>('/tasks/logs', {
    params: { module, task_type: taskType || undefined },
  })
  return data
}

export async function listErrors(module: OperationModule): Promise<DataFetchError[]> {
  const { data } = await apiClient.get<DataFetchError[]>('/errors', {
    params: { unresolved_only: true, module },
  })
  return data
}
