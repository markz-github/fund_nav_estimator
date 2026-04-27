import { apiClient } from './client'

export interface RefreshMarketResult {
  refreshed: boolean
  quote_count: number
}

export async function refreshMarketQuotes(): Promise<RefreshMarketResult> {
  const { data } = await apiClient.post<RefreshMarketResult>('/market/refresh', undefined, {
    timeout: 120000,
  })
  return data
}
