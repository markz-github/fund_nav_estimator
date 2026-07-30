import { apiClient } from '../../../api/client'

export interface FundNavQualityTask {
  id: number
  status: string
  started_at: string
  finished_at?: string | null
  message?: string | null
}

export interface FundNavQualityIssue {
  id: number
  issue_type: string
  fund_code: string
  fund_name?: string | null
  latest_nav_date?: string | null
  expected_nav_date?: string | null
  nav_rule?: string | null
  mapping_type?: string | null
  action?: string | null
  reason?: string | null
  index_name?: string | null
  benchmark_text?: string | null
  mapping_source?: string | null
  failed_strategies?: string | null
  final_strategy?: string | null
  final_status?: string | null
  occurred_at: string
  message: string
}

export interface FundNavQualityReport {
  latest_task?: FundNavQualityTask | null
  issue_count: number
  issues: FundNavQualityIssue[]
}

export interface FundNavQualityFilters {
  occurredFrom?: string
  occurredTo?: string
}

export interface EstimateDriftFundSummary {
  fund_code: string
  fund_name: string
  comparable_count: number
  max_difference_rate?: string | null
  avg_difference_rate?: string | null
  recent_7_trading_day_difference_rate?: string | null
  latest_date?: string | null
  latest_difference_rate?: string | null
  threshold_exceeded_count: number
}

export interface EstimateDriftPoint {
  fund_code: string
  estimate_date: string
  estimate_time: string
  estimated_nav: string
  official_nav: string
  absolute_difference: string
  difference_rate: string
  coverage_ratio?: string | null
  base_nav_date: string
  threshold_exceeded: boolean
}

export interface EstimateDriftDetail {
  fund_code: string
  fund_name?: string | null
  start_date: string
  end_date: string
  threshold?: string | null
  comparable_count: number
  max_difference_rate?: string | null
  avg_difference_rate?: string | null
  threshold_exceeded_count: number
  points: EstimateDriftPoint[]
}

export interface EstimateDriftFilters {
  startDate?: string
  endDate?: string
  threshold?: string
  page?: number
  pageSize?: number
}

export interface EstimateDriftFundSummaryPage {
  items: EstimateDriftFundSummary[]
  total: number
  page: number
  page_size: number
}

export async function getFundNavQualityReport(filters?: FundNavQualityFilters): Promise<FundNavQualityReport> {
  const { data } = await apiClient.get<FundNavQualityReport>('/fund-nav/quality/nav', {
    params: {
      occurred_from: filters?.occurredFrom || undefined,
      occurred_to: filters?.occurredTo || undefined,
    },
  })
  return data
}

export async function listEstimateDriftFunds(filters?: EstimateDriftFilters): Promise<EstimateDriftFundSummaryPage> {
  const { data } = await apiClient.get<EstimateDriftFundSummaryPage>('/fund-nav/quality/estimate-drift/funds', {
    params: {
      start_date: filters?.startDate || undefined,
      end_date: filters?.endDate || undefined,
      threshold: filters?.threshold || undefined,
      page: filters?.page ?? 1,
      page_size: filters?.pageSize ?? 30,
    },
  })
  return data
}

export async function getEstimateDriftDetail(
  fundCode: string,
  filters?: EstimateDriftFilters,
): Promise<EstimateDriftDetail> {
  const { data } = await apiClient.get<EstimateDriftDetail>(`/fund-nav/quality/estimate-drift/funds/${fundCode}`, {
    params: {
      start_date: filters?.startDate || undefined,
      end_date: filters?.endDate || undefined,
      threshold: filters?.threshold || undefined,
    },
  })
  return data
}
