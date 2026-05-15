import axios from 'axios'

function defaultApiBaseURL() {
  const basePath = import.meta.env.BASE_URL || '/'
  return `${basePath.replace(/\/$/, '')}/api`
}

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || defaultApiBaseURL(),
  timeout: 15000,
})
