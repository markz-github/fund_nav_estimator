import axios from 'axios'

function defaultApiBaseURL() {
  const basePath = import.meta.env.BASE_URL || '/'
  return `${basePath.replace(/\/$/, '')}/api`
}

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || defaultApiBaseURL(),
  timeout: 15000,
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
