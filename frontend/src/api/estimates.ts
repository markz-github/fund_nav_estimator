import { apiClient } from './client'

export interface FundEstimate {
  fund_code: string
  estimate_date: string
  estimate_time: string
  base_nav_date: string
  base_unit_nav: string
  estimated_growth_rate?: string | null
  estimated_nav?: string | null
  coverage_ratio?: string | null
  source_snapshot?: string | null
}

export async function latestEstimates(): Promise<FundEstimate[]> {
  const { data } = await apiClient.get<FundEstimate[]>('/estimates/latest')
  return data
}

export interface RunEstimatesResult {
  estimated_count: number
  skipped_count: number
  skipped: Array<{
    fund_code: string
    reason: string
  }>
}

export interface RefreshQuotesAndRunEstimatesResult extends RunEstimatesResult {
  fund_codes: string[]
  quote_count: number
}

export async function runEstimates(): Promise<RunEstimatesResult> {
  const { data } = await apiClient.post<RunEstimatesResult>('/estimates/actions/run', undefined, {
    timeout: 120000,
  })
  return data
}

export async function refreshQuotesAndRunEstimates(
  fundCodes: string[],
): Promise<RefreshQuotesAndRunEstimatesResult> {
  const { data } = await apiClient.post<RefreshQuotesAndRunEstimatesResult>(
    '/estimates/actions/refresh-quotes-and-run',
    { fund_codes: fundCodes },
    { timeout: 180000 },
  )
  return data
}
