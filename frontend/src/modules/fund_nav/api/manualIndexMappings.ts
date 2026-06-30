import { apiClient } from '../../../api/client'

export interface ManualFundIndexMapping {
  id: number
  fund_code: string
  fund_name?: string | null
  index_code: string
  index_name: string
  benchmark_text?: string | null
  remark?: string | null
  created_at: string
  updated_at: string
}

export interface ManualFundIndexMappingPayload {
  fund_code: string
  fund_name?: string | null
  index_code: string
  index_name: string
  benchmark_text?: string | null
  remark?: string | null
}

export async function listManualIndexMappings(): Promise<ManualFundIndexMapping[]> {
  const { data } = await apiClient.get<ManualFundIndexMapping[]>('/funds/index-mappings/manual')
  return data
}

export async function saveManualIndexMapping(
  payload: ManualFundIndexMappingPayload,
): Promise<ManualFundIndexMapping> {
  const { data } = await apiClient.post<ManualFundIndexMapping>('/funds/index-mappings/manual', payload)
  return data
}

export async function deleteManualIndexMapping(fundCode: string): Promise<void> {
  await apiClient.delete(`/funds/index-mappings/manual/${fundCode}`)
}
