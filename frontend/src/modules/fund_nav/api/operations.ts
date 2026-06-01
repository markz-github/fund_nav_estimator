import { apiClient } from '../../../api/client'

export interface TaskLog {
  id: number
  task_name: string
  task_type: string
  status: string
  started_at: string
  duration_ms?: number | null
  message?: string | null
  status_label: string
}

export interface TaskLogPage {
  items: TaskLog[]
  total: number
  page: number
  page_size: number
}

export async function listTaskLogs(
  filters?: { taskType?: string; status?: string; page?: number; pageSize?: number },
): Promise<TaskLogPage> {
  const { data } = await apiClient.get<TaskLogPage>('/tasks/logs', {
    params: {
      task_type: filters?.taskType || undefined,
      status: filters?.status || undefined,
      page: filters?.page || undefined,
      page_size: filters?.pageSize || undefined,
    },
  })
  return data
}
