import axios from 'axios'

export const apiClient = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

export function apiErrorMessage(error: unknown, fallback: string) {
  if (axios.isAxiosError(error)) {
    if (isRequestTimeout(error)) {
      return '请求超时，数据源可能仍在处理中；请稍后刷新列表或查看运行状态。'
    }
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
  }
  return fallback
}

export function isRequestTimeout(error: unknown) {
  return axios.isAxiosError(error) && error.code === 'ECONNABORTED'
}
