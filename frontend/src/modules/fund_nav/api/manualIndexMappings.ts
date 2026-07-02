import { apiClient } from '../../../api/client'

export interface ManualFundIndexMapping {
  id: number
  fund_code: string
  fund_name?: string | null
  mapping_type: 'index' | 'target_etf'
  target_code: string
  target_name: string
  target_market?: string | null
  holding_ratio?: string | null
  holding_value?: string | null
  report_period?: string | null
  benchmark_text?: string | null
  remark?: string | null
  created_at: string
  updated_at: string
}

export interface ManualFundIndexMappingPayload {
  fund_code: string
  fund_name?: string | null
  mapping_type: 'index' | 'target_etf'
  target_code: string
  target_name: string
  target_market?: string | null
  holding_ratio?: string | null
  holding_value?: string | null
  report_period?: string | null
  benchmark_text?: string | null
  remark?: string | null
}

export interface PendingManualFundMapping {
  id: number
  fund_code: string
  fund_name?: string | null
  mapping_type: 'index' | 'target_etf'
  reason?: string | null
  action?: string | null
  occurred_at: string
  message: string
}

export async function listManualIndexMappings(): Promise<ManualFundIndexMapping[]> {
  const { data } = await apiClient.get<ManualFundIndexMapping[]>('/funds/index-mappings/manual')
  return data
}

export async function listPendingManualIndexMappings(): Promise<PendingManualFundMapping[]> {
  const { data } = await apiClient.get<PendingManualFundMapping[]>('/funds/index-mappings/manual/pending')
  return data
}

export async function saveManualIndexMapping(
  payload: ManualFundIndexMappingPayload,
): Promise<ManualFundIndexMapping> {
  const { data } = await apiClient.post<ManualFundIndexMapping>('/funds/index-mappings/manual', payload)
  return data
}

export async function deleteManualIndexMapping(
  fundCode: string,
  mappingType: ManualFundIndexMapping['mapping_type'],
): Promise<void> {
  await apiClient.delete(`/funds/index-mappings/manual/${fundCode}`, {
    params: { mapping_type: mappingType },
  })
}

export async function deletePendingManualIndexMapping(issueId: number): Promise<void> {
  await apiClient.delete(`/funds/index-mappings/manual/pending/${issueId}`)
}
