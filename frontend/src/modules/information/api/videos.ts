import { apiClient } from '../../../api/client'

export interface VideoSource {
  id: number
  platform: string
  source_name: string
  source_url?: string | null
  external_source_id: string
  category: string
  enabled: number
  last_scanned_at?: string | null
  remark?: string | null
  information_count: number
  note_count: number
  status: string
  status_label: string
}

export interface PageResult<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface InformationSettings {
  bilibili_cookie: string
  article_filter_keywords: string
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
  content_type: string
  duration_seconds?: number | null
  ingest_method: string
  ingest_method_label: string
  author_name?: string | null
  published_at?: string | null
  status: string
  status_label: string
  category: string
}

export interface VideoNote {
  id: number
  video_id: number
  video_title?: string | null
  video_url?: string | null
  video_published_at?: string | null
  video_duration_seconds?: number | null
  source_id?: number | null
  source_name?: string | null
  source_url?: string | null
  provider: string
  external_task_id?: string | null
  status: string
  status_label: string
  note_text?: string | null
  error_message?: string | null
  generated_at?: string | null
}

export interface VideoNoteDetail extends VideoNote {
  video_title?: string | null
  video_url?: string | null
  video_duration_seconds?: number | null
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
  summary_task_config_id?: number | null
  summary_task_name?: string | null
  summary_date: string
  category: string
  title: string
  status: string
  status_label: string
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
  video_duration_seconds?: number | null
  source_id?: number | null
  source_name?: string | null
  source_url?: string | null
  category?: string | null
  status: string
  status_label: string
  generated_at?: string | null
}

export interface StatusOption {
  value: string
  label: string
}

export interface InformationStatusOptions {
  source_statuses: StatusOption[]
  video_statuses: StatusOption[]
  note_statuses: StatusOption[]
  summary_document_statuses: StatusOption[]
  task_statuses: StatusOption[]
  fund_nav_task_types: StatusOption[]
  information_task_types: StatusOption[]
}

export interface InformationVideoFilters {
  videoId?: number | null
  sourceId?: number | null
  status?: string
  category?: string
  ingestMethod?: string
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

export async function listVideoSourcesPage(filters?: { page?: number; pageSize?: number; enabledOnly?: boolean }) {
  const { data } = await apiClient.get<PageResult<VideoSource>>('/information/video-sources/page', {
    params: {
      page: filters?.page || undefined,
      page_size: filters?.pageSize || undefined,
      enabled_only: filters?.enabledOnly || undefined,
    },
  })
  return data
}

export async function getInformationStatusOptions() {
  const { data } = await apiClient.get<InformationStatusOptions>('/information/status-options')
  return data
}

export interface SummaryTaskConfig {
  id: number
  task_name: string
  platform: string
  category: string
  start_days_before: number
  cron_expression: string
  title_template: string
  summary_instruction: string
  push_to_wechat: number
  enabled: number
  created_at: string
  updated_at: string
}

export async function listInformationCategories() {
  const { data } = await apiClient.get<{ categories: string[] }>('/information/categories')
  return data.categories
}

export async function listSummaryTaskConfigs() {
  const { data } = await apiClient.get<SummaryTaskConfig[]>('/information/summary-task-configs')
  return data
}

export async function createSummaryTaskConfig(payload: Partial<SummaryTaskConfig>) {
  const { data } = await apiClient.post<SummaryTaskConfig>('/information/summary-task-configs', payload)
  return data
}

export async function updateSummaryTaskConfig(id: number, payload: Partial<SummaryTaskConfig>) {
  const { data } = await apiClient.patch<SummaryTaskConfig>(`/information/summary-task-configs/${id}`, payload)
  return data
}

export async function deleteSummaryTaskConfig(id: number) {
  await apiClient.delete(`/information/summary-task-configs/${id}`)
}

export async function runSummaryTaskConfigNow(id: number) {
  const { data } = await apiClient.post<{ status: string; message: string; document: SummaryDocument | null }>(
    `/information/summary-task-configs/${id}/run-now`,
    undefined,
    { timeout: 180000 },
  )
  return data
}

export async function createVideoSource(payload: {
  platform: string
  source_name: string
  source_url?: string
  external_source_id: string
  category?: string
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
      category: filters?.category || undefined,
      ingest_method: filters?.ingestMethod || undefined,
      published_from: apiDate(filters?.publishedFrom),
      published_to: apiDate(filters?.publishedTo),
    },
  })
  return data
}

export async function listInformationVideosPage(filters?: InformationVideoFilters & { page?: number; pageSize?: number }) {
  const { data } = await apiClient.get<PageResult<InformationVideo>>('/information/videos/page', {
    params: {
      page: filters?.page || undefined,
      page_size: filters?.pageSize || undefined,
      video_id: filters?.videoId || undefined,
      source_id: filters?.sourceId || undefined,
      status: filters?.status || undefined,
      category: filters?.category || undefined,
      ingest_method: filters?.ingestMethod || undefined,
      published_from: apiDate(filters?.publishedFrom),
      published_to: apiDate(filters?.publishedTo),
    },
  })
  return data
}

export async function addManualInformationLink(payload: { url: string; category: string }) {
  const { data } = await apiClient.post<InformationVideo>('/information/videos/manual-link', payload, { timeout: 60000 })
  return data
}

export async function listVideoNotes(filters?: {
  sourceId?: number | null
  videoId?: number | null
  status?: string
  publishedFrom?: string
  publishedTo?: string
}) {
  const { data } = await apiClient.get<VideoNote[]>('/information/video-notes', {
    params: {
      source_id: filters?.sourceId || undefined,
      video_id: filters?.videoId || undefined,
      status: filters?.status || undefined,
      published_from: apiDate(filters?.publishedFrom),
      published_to: apiDate(filters?.publishedTo),
    },
  })
  return data
}

export async function listVideoNotesPage(filters?: {
  sourceId?: number | null
  videoId?: number | null
  status?: string
  publishedFrom?: string
  publishedTo?: string
  page?: number
  pageSize?: number
}) {
  const { data } = await apiClient.get<PageResult<VideoNote>>('/information/video-notes/page', {
    params: {
      page: filters?.page || undefined,
      page_size: filters?.pageSize || undefined,
      source_id: filters?.sourceId || undefined,
      video_id: filters?.videoId || undefined,
      status: filters?.status || undefined,
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

export async function listSummaryDocuments(filters?: { summaryTaskConfigId?: number | null; manualSummary?: boolean; category?: string }) {
  const { data } = await apiClient.get<SummaryDocument[]>('/information/summary-documents', {
    params: {
      summary_task_config_id: filters?.summaryTaskConfigId || undefined,
      manual_summary: filters?.manualSummary || undefined,
      category: filters?.category || undefined,
    },
  })
  return data
}

export async function listSummaryDocumentsPage(filters?: {
  summaryTaskConfigId?: number | null
  manualSummary?: boolean
  category?: string
  page?: number
  pageSize?: number
}) {
  const { data } = await apiClient.get<PageResult<SummaryDocument>>('/information/summary-documents/page', {
    params: {
      page: filters?.page || undefined,
      page_size: filters?.pageSize || undefined,
      summary_task_config_id: filters?.summaryTaskConfigId || undefined,
      manual_summary: filters?.manualSummary || undefined,
      category: filters?.category || undefined,
    },
  })
  return data
}

export async function getSummaryDocument(documentId: number) {
  const { data } = await apiClient.get<SummaryDocument>(`/information/summary-documents/${documentId}`)
  return data
}

export async function deleteSummaryDocument(documentId: number) {
  await apiClient.delete(`/information/summary-documents/${documentId}`)
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

export async function retryVideoNote(videoId: number) {
  const { data } = await apiClient.post<{ status: string; message: string; count: number }>(
    `/information/videos/${videoId}/retry-note`,
  )
  return data
}

export async function repollVideoNote(noteId: number) {
  const { data } = await apiClient.post<{ status: string; message: string; count: number }>(
    `/information/video-notes/${noteId}/repoll`,
  )
  return data
}

export async function regenerateVideoNote(noteId: number) {
  const { data } = await apiClient.post<{ status: string; message: string; count: number }>(
    `/information/video-notes/${noteId}/regenerate`,
  )
  return data
}

export async function generateSummaryFromNotes(noteIds: number[], title?: string, summaryInstruction?: string) {
  const { data } = await apiClient.post<SummaryDocument>(
    '/information/actions/generate-summary-from-notes',
    { note_ids: noteIds, title: title?.trim() || undefined, summary_instruction: summaryInstruction?.trim() || undefined },
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
