import { apiClient } from '../../../api/client'

export interface RefreshMarketResult {
  refreshed: boolean
  quote_count: number
}

export interface IndexQuoteSourceStatus {
  id: number
  source_key: string
  source_name: string
  source_type: string
  source_type_label: string
  priority: number
  enabled: number
  success_count: number
  failure_count: number
  consecutive_failures: number
  success_rate: string | null
  failure_rate: string | null
  effective_priority: string
  auto_disabled_until: string | null
  last_success_at: string | null
  last_failure_at: string | null
  last_error: string | null
  status_label: string
}

export async function refreshMarketQuotes(): Promise<RefreshMarketResult> {
  const { data } = await apiClient.post<RefreshMarketResult>('/market/refresh', undefined, {
    timeout: 120000,
  })
  return data
}

export async function listIndexQuoteSources(): Promise<IndexQuoteSourceStatus[]> {
  const { data } = await apiClient.get<IndexQuoteSourceStatus[]>('/market/index-quote-sources')
  return data
}
