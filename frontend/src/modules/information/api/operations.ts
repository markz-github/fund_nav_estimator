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
  error_message?: string | null
  status_label: string
}

export interface TaskLogPage {
  items: TaskLog[]
  total: number
  page: number
  page_size: number
}

export async function listTaskLogs(
  module: OperationModule,
  filters?: { taskType?: string; status?: string; page?: number; pageSize?: number },
): Promise<TaskLogPage> {
  const { data } = await apiClient.get<TaskLogPage>('/tasks/logs', {
    params: {
      module,
      task_type: filters?.taskType || undefined,
      status: filters?.status || undefined,
      page: filters?.page || undefined,
      page_size: filters?.pageSize || undefined,
    },
  })
  return data
}
