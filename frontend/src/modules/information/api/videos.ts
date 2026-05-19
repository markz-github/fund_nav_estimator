import { apiClient } from '../../../api/client'

export interface VideoSource {
  id: number
  platform: string
  source_name: string
  source_url?: string | null
  external_source_id: string
  enabled: number
  last_scanned_at?: string | null
  remark?: string | null
  video_count: number
  note_count: number
}

export interface InformationSettings {
  bilibili_cookie: string
  bilinote_base_url: string
  bilinote_provider_id: string
  bilinote_model_name: string
  bilinote_quality: string
  hermes_base_url: string
  hermes_auth_header_name: string
  hermes_api_key: string
  hermes_model: string
  hermes_run_path: string
  hermes_status_path_template: string
  hermes_summary_instruction: string
  wechat_push_webhook_url: string
  wechat_push_token: string
  video_note_recent_days: string
}

export interface InformationVideo {
  id: number
  source_id: number
  source_name?: string | null
  platform: string
  external_video_id: string
  title: string
  video_url: string
  author_name?: string | null
  published_at?: string | null
  status: string
}

export interface VideoNote {
  id: number
  video_id: number
  video_title?: string | null
  video_url?: string | null
  video_published_at?: string | null
  source_id?: number | null
  source_name?: string | null
  source_url?: string | null
  provider: string
  external_task_id?: string | null
  status: string
  note_text?: string | null
  error_message?: string | null
  generated_at?: string | null
}

export interface VideoNoteDetail extends VideoNote {
  video_title?: string | null
  video_url?: string | null
  video_platform?: string | null
  video_external_id?: string | null
}

export interface VideoNoteRawResponse {
  id: number
  raw_response?: string | null
}

export interface SummaryDocument {
  id: number
  platform: string
  summary_date: string
  title: string
  status: string
  hermes_run_id?: string | null
  document_text?: string | null
  error_message?: string | null
  generated_at?: string | null
  notes: SummaryDocumentNote[]
}

export interface SummaryDocumentNote {
  id: number
  video_id: number
  video_title?: string | null
  video_url?: string | null
  video_published_at?: string | null
  source_id?: number | null
  source_name?: string | null
  source_url?: string | null
  status: string
  generated_at?: string | null
}

export interface InformationVideoFilters {
  videoId?: number | null
  sourceId?: number | null
  status?: string
  publishedFrom?: string
  publishedTo?: string
}

function apiDate(value?: string) {
  const match = value?.match(/(\d{4})[-/](\d{1,2})[-/](\d{1,2})/)
  if (!match) return undefined
  const [, year, month, day] = match
  return `${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`
}

export async function listVideoSources() {
  const { data } = await apiClient.get<VideoSource[]>('/information/video-sources')
  return data
}

export async function createVideoSource(payload: {
  platform: string
  source_name: string
  source_url?: string
  external_source_id: string
  remark?: string
}) {
  const { data } = await apiClient.post<VideoSource>('/information/video-sources', payload)
  return data
}

export async function updateVideoSource(id: number, payload: Partial<VideoSource>) {
  const { data } = await apiClient.patch<VideoSource>(`/information/video-sources/${id}`, payload)
  return data
}

export async function deleteVideoSource(id: number) {
  await apiClient.delete(`/information/video-sources/${id}`)
}

export async function getInformationSettings() {
  const { data } = await apiClient.get<InformationSettings>('/information/settings')
  return data
}

export async function updateInformationSettings(payload: Partial<InformationSettings>) {
  const { data } = await apiClient.put<InformationSettings>('/information/settings', payload)
  return data
}

export async function listInformationVideos(filters?: InformationVideoFilters) {
  const { data } = await apiClient.get<InformationVideo[]>('/information/videos', {
    params: {
      video_id: filters?.videoId || undefined,
      source_id: filters?.sourceId || undefined,
      status: filters?.status || undefined,
      published_from: apiDate(filters?.publishedFrom),
      published_to: apiDate(filters?.publishedTo),
    },
  })
  return data
}

export async function listVideoNotes(filters?: {
  sourceId?: number | null
  publishedFrom?: string
  publishedTo?: string
}) {
  const { data } = await apiClient.get<VideoNote[]>('/information/video-notes', {
    params: {
      source_id: filters?.sourceId || undefined,
      published_from: apiDate(filters?.publishedFrom),
      published_to: apiDate(filters?.publishedTo),
    },
  })
  return data
}

export async function getVideoNote(noteId: number) {
  const { data } = await apiClient.get<VideoNoteDetail>(`/information/video-notes/${noteId}`)
  return data
}

export async function getVideoNoteRawResponse(noteId: number) {
  const { data } = await apiClient.get<VideoNoteRawResponse>(`/information/video-notes/${noteId}/raw`)
  return data
}

export async function listSummaryDocuments() {
  const { data } = await apiClient.get<SummaryDocument[]>('/information/summary-documents')
  return data
}

export async function getSummaryDocument(documentId: number) {
  const { data } = await apiClient.get<SummaryDocument>(`/information/summary-documents/${documentId}`)
  return data
}

export async function scanVideos(sourceIds?: number[]) {
  const { data } = await apiClient.post<{ status: string; message: string; count: number }>(
    '/information/actions/scan-videos',
    sourceIds && sourceIds.length > 0 ? { source_ids: sourceIds } : undefined,
    { timeout: 60000 },
  )
  return data
}

export async function generateVideoNotes(videoIds?: number[]) {
  const { data } = await apiClient.post<{ status: string; message: string; count: number }>(
    '/information/actions/generate-video-notes',
    videoIds && videoIds.length > 0 ? { video_ids: videoIds } : undefined,
    { timeout: 180000 },
  )
  return data
}

export async function markVideoNotesFailed(videoIds: number[]) {
  const { data } = await apiClient.post<{ status: string; message: string; count: number }>(
    '/information/actions/mark-video-notes-failed',
    {
      video_ids: videoIds,
      error_message: '手动标记为失败',
    },
  )
  return data
}

export async function generateSummary() {
  const { data } = await apiClient.post<SummaryDocument | null>('/information/actions/generate-summary', undefined, {
    timeout: 180000,
  })
  return data
}

export async function generateSummaryFromNotes(noteIds: number[], title?: string) {
  const { data } = await apiClient.post<SummaryDocument>(
    '/information/actions/generate-summary-from-notes',
    { note_ids: noteIds, title: title?.trim() || undefined },
    { timeout: 180000 },
  )
  return data
}

export async function retrySummaryDocument(documentId: number) {
  const { data } = await apiClient.post<SummaryDocument>(
    `/information/summary-documents/${documentId}/retry`,
    undefined,
    { timeout: 180000 },
  )
  return data
}
