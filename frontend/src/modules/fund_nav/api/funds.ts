import { apiClient } from '../../../api/client'

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
  latest_estimate_date?: string | null
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

export interface FundNav {
  fund_code: string
  nav_date: string
  unit_nav: string
  accumulated_nav?: string | null
  daily_growth_rate?: string | null
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

export async function listFundNavHistory(fundCode: string, limit = 500): Promise<FundNav[]> {
  const { data } = await apiClient.get<FundNav[]>(`/funds/${fundCode}/navs`, {
    params: { limit },
  })
  return data
}

export async function refreshFundNavHistory(fundCode: string): Promise<FundNav[]> {
  const { data } = await apiClient.post<FundNav[]>(`/funds/${fundCode}/refresh-nav-history`, undefined, {
    timeout: 60000,
  })
  return data
}

export interface FundTaskSubmitResult {
  task_id: number
  task_log_id: number
  status: string
  reused: boolean
  message: string
}

export async function refreshFundHoldings(fundCode: string): Promise<FundTaskSubmitResult> {
  const { data } = await apiClient.post<FundTaskSubmitResult>(`/funds/${fundCode}/refresh-holdings`)
  return data
}

export async function deleteFund(fundCode: string): Promise<void> {
  await apiClient.delete(`/funds/${fundCode}`)
}

export async function refreshFundNav(fundCode: string): Promise<FundTaskSubmitResult> {
  const { data } = await apiClient.post<FundTaskSubmitResult>(`/funds/${fundCode}/refresh-nav`)
  return data
}

export async function refreshFundNavs(fundCodes: string[]): Promise<FundTaskSubmitResult> {
  const { data } = await apiClient.post<FundTaskSubmitResult>(
    '/funds/actions/refresh-navs',
    { fund_codes: fundCodes },
    { timeout: 180000 },
  )
  return data
}
