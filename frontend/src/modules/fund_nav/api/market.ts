import { apiClient } from '../../../api/client'

export interface RefreshMarketResult {
  refreshed: boolean
  quote_count: number
}

export interface IndexQuoteSourceStatus {
  id: number
  source_key: string
  source_name: string
  source_description?: string | null
  source_type: string
  source_type_label: string
  exclude_rule_type: string
  exclude_rule_value: string | null
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

export interface IndexQuoteSymbol {
  id: number
  index_code: string
  source_key: string
  quote_symbol: string | null
  supported: number
  description: string | null
  created_at: string
  updated_at: string
}

export interface IndexQuoteSymbolPage {
  items: IndexQuoteSymbol[]
  total: number
  limit: number
  offset: number
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

export interface IndexQuoteSourceRuleUpdate {
  source_description?: string | null
  exclude_rule_type: string
  exclude_rule_value?: string | null
}

export async function updateIndexQuoteSource(
  sourceKey: string,
  payload: IndexQuoteSourceRuleUpdate,
): Promise<IndexQuoteSourceStatus> {
  const { data } = await apiClient.put<IndexQuoteSourceStatus>(`/market/index-quote-sources/${sourceKey}`, payload)
  return data
}

export interface IndexQuoteSymbolUpdate {
  index_code: string
  source_key: string
  quote_symbol?: string | null
  supported: number
  description?: string | null
}

export interface IndexQuoteSymbolQuery {
  index_code?: string
  source_key?: string
  limit?: number
  offset?: number
}

export async function listIndexQuoteSymbols(params: IndexQuoteSymbolQuery = {}): Promise<IndexQuoteSymbolPage> {
  const { data } = await apiClient.get<IndexQuoteSymbolPage>('/market/index-quote-symbols', { params })
  return data
}

export async function upsertIndexQuoteSymbol(payload: IndexQuoteSymbolUpdate): Promise<IndexQuoteSymbol> {
  const { data } = await apiClient.put<IndexQuoteSymbol>('/market/index-quote-symbols', payload)
  return data
}
