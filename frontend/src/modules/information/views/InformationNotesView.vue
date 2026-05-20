<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { apiErrorMessage } from '../../../api/client'
import { generateSummaryFromNotes, listVideoNotes, listVideoSources, type VideoNote, type VideoSource } from '../api/videos'
import DateField from '../components/DateField.vue'
import { statusClass } from '../utils/status'

const route = useRoute()
const router = useRouter()
const sources = ref<VideoSource[]>([])
const notes = ref<VideoNote[]>([])
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

const filteredNotes = computed(() =>
  notes.value.filter((note) => {
    if (selectedStatus.value && note.status !== selectedStatus.value) return false
    if (selectedVideoId.value && note.video_id !== Number(selectedVideoId.value)) return false
    if (selectedSourceId.value && note.source_id !== Number(selectedSourceId.value)) return false
    return true
  }),
)
const sortedNotes = computed(() => {
  const items = [...filteredNotes.value]
  items.sort((left, right) => {
    const direction = sortOrder.value === 'asc' ? 1 : -1
    return noteSortValue(left, sortBy.value).localeCompare(noteSortValue(right, sortBy.value), 'zh-Hans-CN') * direction
  })
  return items
})

const statusOptions = computed(() => Array.from(new Set(notes.value.map((note) => note.status))).sort())
const selectableNotes = computed(() => sortedNotes.value.filter((note) => note.status === 'done' && note.note_text))
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
    notes.value = await listVideoNotes({
      sourceId: selectedSourceId.value ? Number(selectedSourceId.value) : undefined,
      publishedFrom: publishedFrom.value || undefined,
      publishedTo: publishedTo.value || undefined,
    })
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
    message.value = apiErrorMessage(error, '视频来源加载失败。')
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
  }
}

async function applyFilters() {
  await router.replace({ name: 'information-notes', query: filterQuery() })
  await loadNotes()
}

async function resetFilter() {
  selectedStatus.value = ''
  selectedVideoId.value = ''
  selectedSourceId.value = ''
  publishedFrom.value = defaultPublishedFrom()
  publishedTo.value = ''
  await router.replace({ name: 'information-notes' })
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
  if (key === 'status') return note.status || ''
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

async function runCustomSummary() {
  if (selectedNoteIds.value.length === 0) {
    message.value = '请先选择已完成的笔记。'
    return
  }
  generatingSummary.value = true
  try {
    const result = await generateSummaryFromNotes(selectedNoteIds.value, customSummaryTitle.value)
    message.value = `自定义汇总已提交：${result.title}`
    selectedNoteIds.value = []
    customSummaryTitle.value = ''
  } catch (error) {
    message.value = apiErrorMessage(error, '自定义汇总生成失败，请查看运行状态。')
  } finally {
    generatingSummary.value = false
  }
}

onMounted(() => {
  applyQueryFilters()
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
        <span>{{ sortedNotes.length }} / {{ notes.length }} 条</span>
        <input
          v-model="customSummaryTitle"
          class="inline-title-input"
          type="text"
          maxlength="200"
          placeholder="汇总名称（可选）"
        />
        <button
          class="ghost"
          type="button"
          :disabled="generatingSummary || selectedNoteIds.length === 0"
          @click="runCustomSummary"
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
            <option v-for="status in statusOptions" :key="status" :value="status">{{ status }}</option>
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
          <col class="col-time" />
          <col class="col-status" />
          <col class="col-provider" />
          <col class="col-task" />
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
            <th><button class="sort-header" type="button" @click="toggleSort('published_at')">发布时间 <span>{{ sortIndicator('published_at') }}</span></button></th>
            <th><button class="sort-header" type="button" @click="toggleSort('status')">状态 <span>{{ sortIndicator('status') }}</span></button></th>
            <th>Provider</th>
            <th>外部任务 ID</th>
            <th><button class="sort-header" type="button" @click="toggleSort('generated_at')">生成时间 <span>{{ sortIndicator('generated_at') }}</span></button></th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="sortedNotes.length === 0">
            <td colspan="10">暂无笔记。</td>
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
            <td>{{ note.video_published_at ?? '-' }}</td>
            <td>
              <span class="status-pill" :class="statusClass(note.status)">{{ note.status }}</span>
            </td>
            <td>{{ note.provider }}</td>
            <td class="mono">{{ note.external_task_id ?? '-' }}</td>
            <td>{{ note.generated_at ?? '-' }}</td>
            <td>
              <RouterLink v-if="note.status === 'done'" class="link-button" :to="`/information/notes/${note.id}`">查看</RouterLink>
              <span v-else class="muted">-</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </main>
</template>
