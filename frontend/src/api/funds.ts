import { apiClient } from './client'

export interface Fund {
  id: number
  fund_code: string
  fund_name: string
  fund_type?: string | null
  enabled: number
  remark?: string | null
  tracked_index_code?: string | null
  tracked_index_name?: string | null
  tracked_index_source?: string | null
  tracked_index_confidence?: string | null
  latest_unit_nav?: string | null
  latest_nav_date?: string | null
  latest_daily_growth_rate?: string | null
  latest_estimated_nav?: string | null
  latest_estimated_growth_rate?: string | null
  latest_estimate_time?: string | null
  latest_coverage_ratio?: string | null
}

export type FundSortBy = 'latest_estimated_growth_rate'
export type SortOrder = 'asc' | 'desc'

export interface FundHolding {
  fund_code: string
  report_period: string
  asset_code: string
  asset_name: string
  asset_type: string
  market?: string | null
  holding_ratio: string
  holding_value?: string | null
  source: string
}

export async function listFunds(options?: { sortBy?: FundSortBy | null; sortOrder?: SortOrder }): Promise<Fund[]> {
  const { data } = await apiClient.get<Fund[]>('/funds', {
    params: options?.sortBy
      ? {
          sort_by: options.sortBy,
          sort_order: options.sortOrder ?? 'desc',
        }
      : undefined,
  })
  return data
}

export async function createFund(fundCode: string, remark?: string): Promise<Fund> {
  const { data } = await apiClient.post<Fund>('/funds', {
    fund_code: fundCode,
    remark,
  }, { timeout: 60000 })
  return data
}

export async function getFund(fundCode: string): Promise<Fund> {
  const { data } = await apiClient.get<Fund>(`/funds/${fundCode}`)
  return data
}

export async function listFundHoldings(fundCode: string): Promise<FundHolding[]> {
  const { data } = await apiClient.get<FundHolding[]>(`/funds/${fundCode}/holdings`)
  return data
}

export interface RefreshHoldingsResult {
  fund_code: string
  refreshed: boolean
  holding_count: number
}

export interface RefreshNavResult {
  fund_code: string
  refreshed: boolean
  from_cache?: boolean
  nav_date?: string | null
  unit_nav?: string | null
}

export interface RefreshFundNavsResult {
  fund_codes: string[]
  refreshed_count: number
  from_cache_count: number
  failed_count: number
  results: RefreshNavResult[]
}

export async function refreshFundHoldings(fundCode: string): Promise<RefreshHoldingsResult> {
  const { data } = await apiClient.post<RefreshHoldingsResult>(`/funds/${fundCode}/refresh-holdings`)
  return data
}

export async function deleteFund(fundCode: string): Promise<void> {
  await apiClient.delete(`/funds/${fundCode}`)
}

export async function refreshFundNav(fundCode: string): Promise<RefreshNavResult> {
  const { data } = await apiClient.post<RefreshNavResult>(`/funds/${fundCode}/refresh-nav`)
  return data
}

export async function refreshFundNavs(fundCodes: string[]): Promise<RefreshFundNavsResult> {
  const { data } = await apiClient.post<RefreshFundNavsResult>(
    '/funds/actions/refresh-navs',
    { fund_codes: fundCodes },
    { timeout: 180000 },
  )
  return data
}
