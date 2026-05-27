<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { apiErrorMessage } from '../../../api/client'
import { formatDateTime } from '../../../utils/datetime'
import {
  generateSummaryFromNotes,
  getInformationSettings,
  getInformationStatusOptions,
  listVideoNotesPage,
  listVideoSources,
  regenerateVideoNote,
  repollVideoNote,
  type StatusOption,
  type VideoNote,
  type VideoSource,
} from '../api/videos'
import DateField from '../components/DateField.vue'
import { formatDurationSeconds } from '../utils/duration'
import { statusClass } from '../utils/status'

const route = useRoute()
const router = useRouter()
const sources = ref<VideoSource[]>([])
const notes = ref<VideoNote[]>([])
const totalNotes = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const noteStatusOptions = ref<StatusOption[]>([])
const selectedStatus = ref('')
const selectedVideoId = ref('')
const selectedSourceId = ref('')
const publishedFrom = ref(defaultPublishedFrom())
const publishedTo = ref('')
const sortBy = ref<'published_at' | 'title' | 'source' | 'status' | 'generated_at'>('published_at')
const sortOrder = ref<'asc' | 'desc'>('desc')
const loading = ref(false)
const generatingSummary = ref(false)
const message = ref('')
const selectedNoteIds = ref<number[]>([])
const customSummaryTitle = ref('')
const customSummaryInstruction = ref('')
const defaultSummaryInstruction = ref('')
const summaryDialogOpen = ref(false)
const repollingNoteId = ref<number | null>(null)
const regeneratingNoteId = ref<number | null>(null)

const sortedNotes = computed(() => {
  const items = [...notes.value]
  items.sort((left, right) => {
    const direction = sortOrder.value === 'asc' ? 1 : -1
    return noteSortValue(left, sortBy.value).localeCompare(noteSortValue(right, sortBy.value), 'zh-Hans-CN') * direction
  })
  return items
})

const selectableNotes = computed(() => sortedNotes.value.filter((note) => note.status === 'done' && note.note_text))
const totalPages = computed(() => Math.max(1, Math.ceil(totalNotes.value / pageSize.value)))
const hasActiveFilters = computed(
  () =>
    Boolean(selectedStatus.value || selectedVideoId.value || selectedSourceId.value || publishedTo.value) ||
    publishedFrom.value !== defaultPublishedFrom(),
)
const allSelectableNotesSelected = computed(
  () =>
    selectableNotes.value.length > 0 &&
    selectableNotes.value.every((note) => selectedNoteIds.value.includes(note.id)),
)

async function loadNotes() {
  loading.value = true
  message.value = ''
  try {
    const result = await listVideoNotesPage({
      page: currentPage.value,
      pageSize: pageSize.value,
      sourceId: selectedSourceId.value ? Number(selectedSourceId.value) : undefined,
      videoId: selectedVideoId.value ? Number(selectedVideoId.value) : undefined,
      status: selectedStatus.value || undefined,
      publishedFrom: publishedFrom.value || undefined,
      publishedTo: publishedTo.value || undefined,
    })
    notes.value = result.items
    totalNotes.value = result.total
    currentPage.value = result.page
    pageSize.value = result.page_size
    const noteIdSet = new Set(notes.value.map((note) => note.id))
    selectedNoteIds.value = selectedNoteIds.value.filter((noteId) => noteIdSet.has(noteId))
  } catch (error) {
    message.value = apiErrorMessage(error, '笔记列表加载失败。')
  } finally {
    loading.value = false
  }
}

async function loadSources() {
  try {
    sources.value = await listVideoSources()
  } catch (error) {
    message.value = apiErrorMessage(error, '信息源加载失败。')
  }
}

async function loadStatusOptions() {
  try {
    const result = await getInformationStatusOptions()
    noteStatusOptions.value = result.note_statuses
  } catch (error) {
    message.value = apiErrorMessage(error, '状态枚举加载失败。')
  }
}

async function loadDefaultSummaryInstruction() {
  try {
    const settings = await getInformationSettings()
    defaultSummaryInstruction.value = settings.hermes_summary_instruction || ''
  } catch {
    defaultSummaryInstruction.value = ''
  }
}

function applyQueryFilters() {
  selectedStatus.value = typeof route.query.status === 'string' ? route.query.status : ''
  selectedVideoId.value = typeof route.query.video_id === 'string' ? route.query.video_id : ''
  selectedSourceId.value = typeof route.query.source_id === 'string' ? route.query.source_id : ''
  const hasQueryFilter = Boolean(route.query.video_id || route.query.source_id || route.query.status)
  const allDatesSelected = route.query.date_range === 'all'
  publishedFrom.value =
    allDatesSelected
      ? ''
      : typeof route.query.published_from === 'string'
      ? displayDateValue(route.query.published_from)
      : hasQueryFilter
        ? ''
        : defaultPublishedFrom()
  publishedTo.value = allDatesSelected ? '' : displayDateValue(route.query.published_to)
  const queryPage = Number(route.query.page)
  currentPage.value = Number.isFinite(queryPage) && queryPage > 0 ? Math.floor(queryPage) : 1
}

function filterQuery() {
  const hasDateFilter = Boolean(publishedFrom.value || publishedTo.value)
  return {
    status: selectedStatus.value || undefined,
    video_id: selectedVideoId.value || undefined,
    source_id: selectedSourceId.value || undefined,
    published_from: publishedFrom.value || undefined,
    published_to: publishedTo.value || undefined,
    date_range: hasDateFilter ? undefined : 'all',
    page: currentPage.value > 1 ? String(currentPage.value) : undefined,
  }
}

async function applyFilters() {
  currentPage.value = 1
  await router.replace({ name: 'information-notes', query: filterQuery() })
  await loadNotes()
}

async function resetFilter() {
  selectedStatus.value = ''
  selectedVideoId.value = ''
  selectedSourceId.value = ''
  publishedFrom.value = defaultPublishedFrom()
  publishedTo.value = ''
  currentPage.value = 1
  await router.replace({ name: 'information-notes' })
  await loadNotes()
}

async function goToPage(page: number) {
  currentPage.value = Math.min(Math.max(1, page), totalPages.value)
  await router.replace({ name: 'information-notes', query: filterQuery() })
  await loadNotes()
}

function dateInputValue(date: Date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function displayDateValue(value: unknown) {
  if (typeof value !== 'string') return ''
  const match = value.match(/(\d{4})[-/](\d{1,2})[-/](\d{1,2})/)
  if (!match) return ''
  const [, year, month, day] = match
  return `${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`
}

function defaultPublishedFrom() {
  const date = new Date()
  date.setDate(date.getDate() - 3)
  return dateInputValue(date)
}

function noteSortValue(note: VideoNote, key: typeof sortBy.value) {
  if (key === 'published_at') return note.video_published_at || ''
  if (key === 'title') return note.video_title || ''
  if (key === 'source') return note.source_name || ''
  if (key === 'status') return note.status_label || note.status || ''
  return note.generated_at || ''
}

function toggleSort(key: typeof sortBy.value) {
  if (sortBy.value === key) {
    sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc'
    return
  }
  sortBy.value = key
  sortOrder.value = key === 'published_at' || key === 'generated_at' ? 'desc' : 'asc'
}

function sortIndicator(key: typeof sortBy.value) {
  if (sortBy.value !== key) return '↕'
  return sortOrder.value === 'asc' ? '↑' : '↓'
}

function toggleNoteSelection(noteId: number, checked: boolean) {
  if (checked) {
    selectedNoteIds.value = Array.from(new Set([...selectedNoteIds.value, noteId]))
    return
  }
  selectedNoteIds.value = selectedNoteIds.value.filter((id) => id !== noteId)
}

function toggleAllSelectableNotes(checked: boolean) {
  selectedNoteIds.value = checked ? selectableNotes.value.map((note) => note.id) : []
}

function openCustomSummaryDialog() {
  if (selectedNoteIds.value.length === 0) {
    message.value = '请先选择已完成的笔记。'
    return
  }
  customSummaryInstruction.value = defaultSummaryInstruction.value
  summaryDialogOpen.value = true
}

function closeCustomSummaryDialog() {
  if (generatingSummary.value) return
  summaryDialogOpen.value = false
}

async function runCustomSummary() {
  if (selectedNoteIds.value.length === 0) {
    message.value = '请先选择已完成的笔记。'
    summaryDialogOpen.value = false
    return
  }
  generatingSummary.value = true
  try {
    const result = await generateSummaryFromNotes(selectedNoteIds.value, customSummaryTitle.value, customSummaryInstruction.value)
    message.value = `自定义汇总已提交：${result.title}`
    selectedNoteIds.value = []
    customSummaryTitle.value = ''
    customSummaryInstruction.value = defaultSummaryInstruction.value
    summaryDialogOpen.value = false
  } catch (error) {
    message.value = apiErrorMessage(error, '自定义汇总生成失败，请查看运行状态。')
  } finally {
    generatingSummary.value = false
  }
}

async function repollFailedNote(note: VideoNote) {
  repollingNoteId.value = note.id
  try {
    await repollVideoNote(note.id)
    message.value = `已将笔记 ${note.id} 恢复为轮询中，系统会按原任务 ID 获取结果。`
    await loadNotes()
  } catch (error) {
    message.value = apiErrorMessage(error, '重新轮询失败，请确认该笔记为失败状态且保留了任务 ID。')
  } finally {
    repollingNoteId.value = null
  }
}

async function regenerateNote(note: VideoNote) {
  regeneratingNoteId.value = note.id
  try {
    await regenerateVideoNote(note.id)
    message.value = `已将笔记 ${note.id} 重新加入生成流程。`
    selectedNoteIds.value = selectedNoteIds.value.filter((id) => id !== note.id)
    await loadNotes()
  } catch (error) {
    message.value = apiErrorMessage(error, '重新生成失败，请确认该笔记已完成或已失败。')
  } finally {
    regeneratingNoteId.value = null
  }
}

onMounted(() => {
  applyQueryFilters()
  loadStatusOptions()
  loadDefaultSummaryInstruction()
  loadSources()
  loadNotes()
})

watch(
  () => route.query,
  () => {
    applyQueryFilters()
    loadNotes()
  },
)
</script>

<template>
  <main class="page-shell">
    <section class="detail-hero">
      <div>
        <p class="eyebrow">Notes</p>
        <h1>笔记管理</h1>
        <p class="subtitle">查看 Bilinote 笔记列表和生成状态。</p>
      </div>
      <!-- <div class="section-actions">
        <button class="ghost" :disabled="loading" @click="loadNotes">{{ loading ? '刷新中...' : '刷新笔记' }}</button>
      </div> -->
    </section>

    <p v-if="message" class="message">{{ message }}</p>

    <section class="section-title">
      <div>
        <p class="eyebrow">List</p>
        <h2>笔记列表</h2>
      </div>
      <div class="section-actions">
        <span>第 {{ currentPage }} / {{ totalPages }} 页，共 {{ totalNotes }} 条</span>
        <button
          class="ghost"
          type="button"
          :disabled="generatingSummary || selectedNoteIds.length === 0"
          @click="openCustomSummaryDialog"
        >
          {{ generatingSummary ? '汇总中...' : selectedNoteIds.length ? `汇总选中 ${selectedNoteIds.length} 条` : '汇总选中笔记' }}
        </button>
      </div>
    </section>

    <form class="filter-bar video-filter-bar" @submit.prevent="applyFilters">
      <div class="filter-row">
        <!-- <label>
          视频 ID
          <input v-model="selectedVideoId" type="number" min="1" placeholder="全部视频" />
        </label> -->
        <label>
          账号
          <select v-model="selectedSourceId">
            <option value="">全部账号</option>
            <option v-for="source in sources" :key="source.id" :value="String(source.id)">
              {{ source.source_name }}
            </option>
          </select>
        </label>
        <label>
          状态
          <select v-model="selectedStatus">
            <option value="">全部状态</option>
            <option v-for="status in noteStatusOptions" :key="status.value" :value="status.value">{{ status.label }}</option>
          </select>
        </label>
        <label>
          发布开始
          <DateField v-model="publishedFrom" placeholder="开始日期" />
        </label>
        <label>
          发布结束
          <DateField v-model="publishedTo" placeholder="结束日期" />
        </label>
        <div class="filter-actions">
          <button class="ghost" type="submit" :disabled="loading">应用筛选</button>
          <button class="ghost" type="button" :disabled="!hasActiveFilters" @click="resetFilter">重置</button>
        </div>
      </div>
    </form>

    <div class="table-card">
      <table class="info-table notes-table">
        <colgroup>
          <col class="col-check" />
          <col class="col-id" />
          <col class="col-title" />
          <col class="col-source" />
          <col class="col-duration" />
          <col class="col-time" />
          <col class="col-status" />
          <col class="col-time" />
          <col class="col-actions" />
        </colgroup>
        <thead>
          <tr>
            <th>
              <input
                class="row-check"
                type="checkbox"
                :checked="allSelectableNotesSelected"
                :disabled="loading || selectableNotes.length === 0"
                @change="toggleAllSelectableNotes(($event.target as HTMLInputElement).checked)"
              />
            </th>
            <th>ID</th>
            <th><button class="sort-header" type="button" @click="toggleSort('title')">视频 <span>{{ sortIndicator('title') }}</span></button></th>
            <th><button class="sort-header" type="button" @click="toggleSort('source')">发布账号 <span>{{ sortIndicator('source') }}</span></button></th>
            <th>时长</th>
            <th><button class="sort-header" type="button" @click="toggleSort('published_at')">发布时间 <span>{{ sortIndicator('published_at') }}</span></button></th>
            <th><button class="sort-header" type="button" @click="toggleSort('status')">状态 <span>{{ sortIndicator('status') }}</span></button></th>
            <th><button class="sort-header" type="button" @click="toggleSort('generated_at')">生成时间 <span>{{ sortIndicator('generated_at') }}</span></button></th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="sortedNotes.length === 0">
            <td colspan="9">暂无笔记。</td>
          </tr>
          <tr v-for="note in sortedNotes" :key="note.id">
            <td>
              <input
                class="row-check"
                type="checkbox"
                :checked="selectedNoteIds.includes(note.id)"
                :disabled="note.status !== 'done' || !note.note_text"
                @change="toggleNoteSelection(note.id, ($event.target as HTMLInputElement).checked)"
              />
            </td>
            <td class="mono">{{ note.id }}</td>
            <td>
              <RouterLink :to="{ name: 'information-videos', query: { video_id: note.video_id } }">
                {{ note.video_title || `视频 ${note.video_id}` }}
              </RouterLink>
            </td>
            <td>
              {{ note.source_name ?? '-' }}
            </td>
            <td class="mono">{{ formatDurationSeconds(note.video_duration_seconds) }}</td>
            <td>{{ formatDateTime(note.video_published_at) }}</td>
            <td>
              <span class="status-pill" :class="statusClass(note.status)">{{ note.status_label }}</span>
            </td>
            <td>{{ formatDateTime(note.generated_at) }}</td>
            <td>
              <template v-if="note.status === 'done' || note.status === 'failed'">
                <RouterLink v-if="note.status === 'done'" class="link-button" :to="`/information/notes/${note.id}`">查看</RouterLink>
                <button
                  class="link-button"
                  type="button"
                  :disabled="regeneratingNoteId === note.id"
                  @click="regenerateNote(note)"
                >
                  {{ regeneratingNoteId === note.id ? '生成中...' : '重新生成' }}
                </button>
                <button
                  v-if="note.status === 'failed' && note.external_task_id"
                  class="link-button"
                  type="button"
                  :disabled="repollingNoteId === note.id"
                  @click="repollFailedNote(note)"
                >
                  {{ repollingNoteId === note.id ? '轮询中...' : '重新轮询' }}
                </button>
              </template>
              <span v-else class="muted">-</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <nav class="pagination-bar" aria-label="笔记分页">
      <button class="ghost" type="button" :disabled="loading || currentPage <= 1" @click="goToPage(currentPage - 1)">上一页</button>
      <span>第 {{ currentPage }} / {{ totalPages }} 页</span>
      <button class="ghost" type="button" :disabled="loading || currentPage >= totalPages" @click="goToPage(currentPage + 1)">下一页</button>
    </nav>

    <div v-if="summaryDialogOpen" class="modal-backdrop" @click.self="closeCustomSummaryDialog">
      <section class="confirm-dialog custom-summary-dialog" role="dialog" aria-modal="true" aria-labelledby="custom-summary-title">
        <h2 id="custom-summary-title">手动汇总</h2>
        <p class="dialog-copy">已选择 <strong>{{ selectedNoteIds.length }}</strong> 条笔记。</p>
        <label>
          汇总名称
          <input v-model="customSummaryTitle" maxlength="200" placeholder="可选，留空则自动生成" />
        </label>
        <label>
          汇总说明
          <textarea v-model="customSummaryInstruction" rows="8" placeholder="可选，默认使用信息流设置中的默认汇总说明。" />
        </label>
        <div class="dialog-actions">
          <button class="ghost" type="button" :disabled="generatingSummary" @click="closeCustomSummaryDialog">取消</button>
          <button type="button" :disabled="generatingSummary" @click="runCustomSummary">
            {{ generatingSummary ? '提交中...' : '提交汇总' }}
          </button>
        </div>
      </section>
    </div>
  </main>
</template>
