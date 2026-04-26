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
