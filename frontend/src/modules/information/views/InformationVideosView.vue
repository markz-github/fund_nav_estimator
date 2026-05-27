<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { apiErrorMessage } from '../../../api/client'
import { formatDateTime } from '../../../utils/datetime'
import {
  addManualInformationLink,
  generateVideoNotes,
  getInformationStatusOptions,
  listInformationCategories,
  listInformationVideosPage,
  listVideoNotes,
  listVideoSources,
  markVideoNotesFailed,
  retryVideoNote,
  type InformationVideo,
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
const videos = ref<InformationVideo[]>([])
const totalVideos = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const notes = ref<VideoNote[]>([])
const videoStatusOptions = ref<StatusOption[]>([])
const categories = ref<string[]>(['财经'])
const loading = ref(false)
const runningAction = ref('')
const message = ref('')
const selectedVideoIds = ref<number[]>([])
const retryingVideoId = ref<number | null>(null)
const manualLinkDialogOpen = ref(false)
const savingManualLink = ref(false)
const confirmDialogOpen = ref(false)
const confirmAction = ref<'markFailed' | 'retry' | null>(null)
const confirmVideo = ref<InformationVideo | null>(null)
const manualLinkDraft = ref({
  url: '',
  category: '',
})
const sortBy = ref<'published_at' | 'title' | 'source' | 'status'>('published_at')
const sortOrder = ref<'asc' | 'desc'>('desc')
const videoFilters = ref({
  videoId: '',
  sourceId: '',
  status: '',
  category: '',
  ingestMethod: '',
  publishedFrom: defaultPublishedFrom(),
  publishedTo: '',
})

const notesByVideoId = computed(() => {
  const latestNotes = new Map<number, VideoNote>()
  for (const note of notes.value) {
    const current = latestNotes.get(note.video_id)
    if (!current || note.id > current.id) latestNotes.set(note.video_id, note)
  }
  return latestNotes
})
const allVideosSelected = computed(
  () => sortedVideos.value.length > 0 && sortedVideos.value.every((video) => selectedVideoIds.value.includes(video.id)),
)
const totalPages = computed(() => Math.max(1, Math.ceil(totalVideos.value / pageSize.value)))
const sortedVideos = computed(() => {
  const items = [...videos.value]
  items.sort((left, right) => {
    const direction = sortOrder.value === 'asc' ? 1 : -1
    const leftValue = videoSortValue(left, sortBy.value)
    const rightValue = videoSortValue(right, sortBy.value)
    return leftValue.localeCompare(rightValue, 'zh-Hans-CN') * direction
  })
  return items
})
const confirmTitle = computed(() => {
  if (confirmAction.value === 'markFailed') return '置为失败'
  if (confirmAction.value === 'retry') return '重试笔记'
  return '确认操作'
})
const confirmCopy = computed(() => {
  if (confirmAction.value === 'markFailed') return `确认将选中的 ${selectedVideoIds.value.length} 条内容置为失败吗？`
  if (confirmAction.value === 'retry' && confirmVideo.value) return `确认重新生成内容 ${confirmVideo.value.id} 的笔记吗？`
  return ''
})

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

async function loadAll(options?: { keepMessage?: boolean }) {
  loading.value = true
  if (!options?.keepMessage) message.value = ''
  try {
    const [sourceResult, videoResult, noteResult] = await Promise.all([
      listVideoSources(),
      listInformationVideosPage({
        page: currentPage.value,
        pageSize: pageSize.value,
        videoId: videoFilters.value.videoId ? Number(videoFilters.value.videoId) : undefined,
        sourceId: videoFilters.value.sourceId ? Number(videoFilters.value.sourceId) : undefined,
        status: videoFilters.value.status || undefined,
        category: videoFilters.value.category || undefined,
        ingestMethod: videoFilters.value.ingestMethod || undefined,
        publishedFrom: videoFilters.value.publishedFrom || undefined,
        publishedTo: videoFilters.value.publishedTo || undefined,
      }),
      listVideoNotes(),
    ])
    sources.value = sourceResult
    videos.value = videoResult.items
    totalVideos.value = videoResult.total
    currentPage.value = videoResult.page
    pageSize.value = videoResult.page_size
    notes.value = noteResult
    const videoIdSet = new Set(videoResult.items.map((video) => video.id))
    selectedVideoIds.value = selectedVideoIds.value.filter((videoId) => videoIdSet.has(videoId))
  } catch (error) {
    message.value = apiErrorMessage(error, '信息源数据加载失败，请确认后端服务和数据库。')
  } finally {
    loading.value = false
  }
}

async function loadStatusOptions() {
  try {
    const result = await getInformationStatusOptions()
    videoStatusOptions.value = result.video_statuses
    categories.value = await listInformationCategories()
  } catch (error) {
    message.value = apiErrorMessage(error, '状态枚举加载失败。')
  }
}

function applyQueryFilters() {
  const hasQueryFilter = Boolean(route.query.video_id || route.query.source_id || route.query.status || route.query.category || route.query.ingest_method)
  const allDatesSelected = route.query.date_range === 'all'
  videoFilters.value = {
    videoId: typeof route.query.video_id === 'string' ? route.query.video_id : '',
    sourceId: typeof route.query.source_id === 'string' ? route.query.source_id : '',
    status: typeof route.query.status === 'string' ? route.query.status : '',
    category: typeof route.query.category === 'string' ? route.query.category : '',
    ingestMethod: typeof route.query.ingest_method === 'string' ? route.query.ingest_method : '',
    publishedFrom:
      allDatesSelected
        ? ''
        : typeof route.query.published_from === 'string'
        ? displayDateValue(route.query.published_from)
        : hasQueryFilter
          ? ''
          : defaultPublishedFrom(),
    publishedTo: allDatesSelected ? '' : displayDateValue(route.query.published_to),
  }
  const queryPage = Number(route.query.page)
  currentPage.value = Number.isFinite(queryPage) && queryPage > 0 ? Math.floor(queryPage) : 1
}

function filterQuery() {
  const hasDateFilter = Boolean(videoFilters.value.publishedFrom || videoFilters.value.publishedTo)
  return {
    video_id: videoFilters.value.videoId || undefined,
    source_id: videoFilters.value.sourceId || undefined,
    status: videoFilters.value.status || undefined,
    category: videoFilters.value.category || undefined,
    ingest_method: videoFilters.value.ingestMethod || undefined,
    published_from: videoFilters.value.publishedFrom || undefined,
    published_to: videoFilters.value.publishedTo || undefined,
    date_range: hasDateFilter ? undefined : 'all',
    page: currentPage.value > 1 ? String(currentPage.value) : undefined,
  }
}

async function runAction(action: 'notes' | 'markFailed') {
  runningAction.value = action
  try {
    if (action === 'notes') {
      const targetVideoIds = selectedVideoIds.value.length > 0 ? selectedVideoIds.value : undefined
      const result = await generateVideoNotes(targetVideoIds)
      const targetText = targetVideoIds ? `选中 ${targetVideoIds.length} 条内容` : '待处理内容'
      message.value = `笔记任务已触发，${targetText}本次提交 ${result.count} 条；结果会由定时任务自动轮询。`
    } else {
      if (selectedVideoIds.value.length === 0) {
        message.value = '请先选择要置为失败的内容。'
        return
      }
      const result = await markVideoNotesFailed(selectedVideoIds.value)
      message.value = `已将 ${result.count} 条笔记任务置为失败。`
    }
    await loadAll({ keepMessage: true })
  } catch (error) {
    message.value = apiErrorMessage(error, '手动任务执行失败，请确认后端服务是否启动，或查看运行状态页。')
  } finally {
    runningAction.value = ''
  }
}

async function retryFailedVideo(video: InformationVideo) {
  retryingVideoId.value = video.id
  try {
    await retryVideoNote(video.id)
    message.value = `已将内容 ${video.id} 重新加入笔记生成流程。`
    await loadAll({ keepMessage: true })
  } catch (error) {
    message.value = apiErrorMessage(error, '重试失败，请确认该内容仍处于失败状态，或查看运行状态页。')
  } finally {
    retryingVideoId.value = null
  }
}

function openConfirmDialog(action: 'markFailed' | 'retry', video?: InformationVideo) {
  confirmAction.value = action
  confirmVideo.value = video || null
  confirmDialogOpen.value = true
}

function closeConfirmDialog() {
  if (runningAction.value || retryingVideoId.value !== null) return
  confirmDialogOpen.value = false
  confirmAction.value = null
  confirmVideo.value = null
}

async function confirmOperation() {
  if (confirmAction.value === 'markFailed') {
    await runAction('markFailed')
  } else if (confirmAction.value === 'retry' && confirmVideo.value) {
    await retryFailedVideo(confirmVideo.value)
  }
  closeConfirmDialog()
}

function openManualLinkDialog() {
  manualLinkDraft.value = {
    url: '',
    category: videoFilters.value.category || '',
  }
  manualLinkDialogOpen.value = true
}

function closeManualLinkDialog() {
  if (savingManualLink.value) return
  manualLinkDialogOpen.value = false
}

async function submitManualLink() {
  const url = manualLinkDraft.value.url.trim()
  const category = manualLinkDraft.value.category.trim()
  if (!url || !category) {
    message.value = '请填写链接和分类。'
    return
  }
  savingManualLink.value = true
  try {
    const video = await addManualInformationLink({ url, category })
    message.value = `已添加内容 ${video.id}，后续将按现有队列生成笔记。`
    manualLinkDialogOpen.value = false
    currentPage.value = 1
    await router.replace({
      name: 'information-videos',
      query: {
        video_id: String(video.id),
        date_range: 'all',
      },
    })
    await loadAll({ keepMessage: true })
  } catch (error) {
    message.value = apiErrorMessage(error, '添加链接失败，请确认链接可访问且属于支持的平台。')
  } finally {
    savingManualLink.value = false
  }
}

function toggleVideoSelection(videoId: number, checked: boolean) {
  if (checked) {
    selectedVideoIds.value = Array.from(new Set([...selectedVideoIds.value, videoId]))
    return
  }
  selectedVideoIds.value = selectedVideoIds.value.filter((id) => id !== videoId)
}

function toggleAllVideos(checked: boolean) {
  selectedVideoIds.value = checked ? sortedVideos.value.map((video) => video.id) : []
}

async function applyVideoFilters() {
  currentPage.value = 1
  await router.replace({ name: 'information-videos', query: filterQuery() })
  await loadAll()
}

async function resetVideoFilters() {
  videoFilters.value = {
    videoId: '',
    sourceId: '',
    status: '',
    category: '',
    ingestMethod: '',
    publishedFrom: defaultPublishedFrom(),
    publishedTo: '',
  }
  currentPage.value = 1
  await router.replace({ name: 'information-videos', query: filterQuery() })
  await loadAll()
}

async function goToPage(page: number) {
  currentPage.value = Math.min(Math.max(1, page), totalPages.value)
  await router.replace({ name: 'information-videos', query: filterQuery() })
  await loadAll()
}

function videoSortValue(video: InformationVideo, key: typeof sortBy.value) {
  if (key === 'published_at') return video.published_at || ''
  if (key === 'title') return video.title || ''
  if (key === 'source') return video.source_name || video.author_name || ''
  return video.status_label || video.status || ''
}

function toggleSort(key: typeof sortBy.value) {
  if (sortBy.value === key) {
    sortOrder.value = sortOrder.value === 'asc' ? 'desc' : 'asc'
    return
  }
  sortBy.value = key
  sortOrder.value = key === 'published_at' ? 'desc' : 'asc'
}

function sortIndicator(key: typeof sortBy.value) {
  if (sortBy.value !== key) return '↕'
  return sortOrder.value === 'asc' ? '↑' : '↓'
}

onMounted(() => {
  applyQueryFilters()
  loadStatusOptions()
  loadAll()
})

watch(
  () => route.query,
  () => {
    applyQueryFilters()
    loadAll()
  },
)
</script>

<template>
  <main class="page-shell">
    <section class="detail-hero">
      <div>
        <p class="eyebrow">Feeds</p>
        <h1>信息管理</h1>
        <p class="subtitle">查看已扫描视频和图文投稿，提交对应笔记任务，并跟踪最新笔记状态。</p>
      </div>
    </section>

    <p v-if="message" class="message">{{ message }}</p>

    <section class="section-title">
      <div>
        <p class="eyebrow">List</p>
        <h2>信息源与笔记</h2>
      </div>
      <div class="section-actions">
        <span>第 {{ currentPage }} / {{ totalPages }} 页，共 {{ totalVideos }} 条</span>
        <button type="button" @click="openManualLinkDialog">添加链接</button>
        <button class="ghost" :disabled="runningAction === 'notes'" @click="runAction('notes')">
          {{ runningAction === 'notes' ? '生成中...' : selectedVideoIds.length ? `生成选中 ${selectedVideoIds.length} 条笔记` : '生成待处理笔记' }}
        </button>
        <button class="danger" :disabled="runningAction === 'markFailed' || selectedVideoIds.length === 0" @click="openConfirmDialog('markFailed')">
          {{ runningAction === 'markFailed' ? '处理中...' : selectedVideoIds.length ? `置为失败 ${selectedVideoIds.length} 条` : '置为失败' }}
        </button>
      </div>
    </section>

    <form class="filter-bar video-filter-bar" @submit.prevent="applyVideoFilters">
      <div class="filter-row">
        <!-- <label>
          内容 ID
          <input v-model="videoFilters.videoId" type="number" min="1" placeholder="全部内容" />
        </label> -->
        <label>
          账号
          <select v-model="videoFilters.sourceId">
            <option value="">全部账号</option>
            <option v-for="source in sources" :key="source.id" :value="String(source.id)">
              {{ source.source_name }}
            </option>
          </select>
        </label>
        <label>
          状态
          <select v-model="videoFilters.status">
            <option value="">全部状态</option>
            <option v-for="status in videoStatusOptions" :key="status.value" :value="status.value">
              {{ status.label }}
            </option>
          </select>
        </label>
        <label>
          分类
          <select v-model="videoFilters.category">
            <option value="">全部分类</option>
            <option v-for="category in categories" :key="category" :value="category">
              {{ category }}
            </option>
          </select>
        </label>
        <label>
          入库方式
          <select v-model="videoFilters.ingestMethod">
            <option value="">全部方式</option>
            <option value="scan">扫描入库</option>
            <option value="manual">手动添加</option>
          </select>
        </label>
        <label>
          发布开始
          <DateField v-model="videoFilters.publishedFrom" placeholder="开始日期" />
        </label>
        <label>
          发布结束
          <DateField v-model="videoFilters.publishedTo" placeholder="结束日期" />
        </label>
        <div class="filter-actions">
          <button class="ghost" type="submit" :disabled="loading">应用筛选</button>
          <button class="ghost" type="button" :disabled="loading" @click="resetVideoFilters">近 3 天</button>
        </div>
      </div>
    </form>

    <div class="table-card">
      <table class="info-table videos-table">
        <colgroup>
          <col class="col-check" />
          <col class="col-id" />
          <col class="col-type" />
          <col class="col-ingest" />
          <col class="col-title" />
          <col class="col-source" />
          <col class="col-category" />
          <col class="col-duration" />
          <col class="col-status" />
          <col class="col-time" />
          <col class="col-status" />
        </colgroup>
        <thead>
          <tr>
            <th>
              <input
                class="row-check"
                type="checkbox"
                :checked="allVideosSelected"
                :disabled="loading || sortedVideos.length === 0"
                @change="toggleAllVideos(($event.target as HTMLInputElement).checked)"
              />
            </th>
            <th>ID</th>
            <th>类型</th>
            <th>入库方式</th>
            <th>
              <button class="sort-header" type="button" @click="toggleSort('title')">标题 <span>{{ sortIndicator('title') }}</span></button>
            </th>
            <th>
              <button class="sort-header" type="button" @click="toggleSort('source')">账号 <span>{{ sortIndicator('source') }}</span></button>
            </th>
            <th>分类</th>
            <th>时长</th>
            <th>
              <button class="sort-header" type="button" @click="toggleSort('status')">状态 <span>{{ sortIndicator('status') }}</span></button>
            </th>
            <th>
              <button class="sort-header" type="button" @click="toggleSort('published_at')">发布时间 <span>{{ sortIndicator('published_at') }}</span></button>
            </th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="sortedVideos.length === 0">
            <td colspan="11">暂无内容。</td>
          </tr>
          <tr v-for="video in sortedVideos" :key="video.id">
            <td>
              <input
                class="row-check"
                type="checkbox"
                :checked="selectedVideoIds.includes(video.id)"
                @change="toggleVideoSelection(video.id, ($event.target as HTMLInputElement).checked)"
              />
            </td>
            <td class="mono">{{ video.id }}</td>
            <td>
              <span class="status-pill" :class="video.content_type === 'article' ? 'status-muted' : 'status-ok'">
                {{ video.content_type === 'article' ? '图文' : '视频' }}
              </span>
            </td>
            <td>
              <span class="status-pill" :class="video.ingest_method === 'manual' ? 'status-warn' : 'status-muted'">
                {{ video.ingest_method_label }}
              </span>
            </td>
            <td><a :href="video.video_url" target="_blank" rel="noreferrer">{{ video.title }}</a></td>
            <td>{{ video.source_name ?? video.author_name ?? '-' }}</td>
            <td>{{ video.category }}</td>
            <td class="mono">{{ video.content_type === 'article' ? '-' : formatDurationSeconds(video.duration_seconds) }}</td>
            <td>
              <span class="status-pill" :class="statusClass(video.status)">{{ video.status_label }}</span>
            </td>
            <td>{{ formatDateTime(video.published_at) }}</td>
            <td>
              <RouterLink
                v-if="notesByVideoId.get(video.id)?.status === 'done'"
                class="link-button"
                :to="`/information/notes/${notesByVideoId.get(video.id)?.id}`"
              >
                查看
              </RouterLink>
              <button
                v-else-if="video.status === 'note_failed'"
                class="link-button"
                type="button"
                :disabled="retryingVideoId === video.id"
                @click="openConfirmDialog('retry', video)"
              >
                {{ retryingVideoId === video.id ? '重试中...' : '重试' }}
              </button>
              <span v-else class="muted">-</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <nav class="pagination-bar" aria-label="信息分页">
      <button class="ghost" type="button" :disabled="loading || currentPage <= 1" @click="goToPage(currentPage - 1)">上一页</button>
      <span>第 {{ currentPage }} / {{ totalPages }} 页</span>
      <button class="ghost" type="button" :disabled="loading || currentPage >= totalPages" @click="goToPage(currentPage + 1)">下一页</button>
    </nav>

    <div v-if="manualLinkDialogOpen" class="modal-backdrop" @click.self="closeManualLinkDialog">
      <section class="confirm-dialog summary-task-dialog" role="dialog" aria-modal="true" aria-labelledby="manual-link-title">
        <h2 id="manual-link-title">添加链接</h2>
        <form class="settings-grid" @submit.prevent="submitManualLink">
          <label class="settings-wide">
            链接
            <input v-model="manualLinkDraft.url" type="url" required placeholder="https://www.bilibili.com/video/BV..." />
          </label>
          <label>
            分类
            <input v-model="manualLinkDraft.category" list="manual-link-categories" required placeholder="输入或选择分类" />
            <datalist id="manual-link-categories">
              <option v-for="category in categories" :key="category" :value="category" />
            </datalist>
          </label>
          <div class="form-actions settings-wide">
            <button class="ghost" type="button" :disabled="savingManualLink" @click="closeManualLinkDialog">取消</button>
            <button type="submit" :disabled="savingManualLink">{{ savingManualLink ? '添加中...' : '添加' }}</button>
          </div>
        </form>
      </section>
    </div>

    <div v-if="confirmDialogOpen" class="modal-backdrop" @click.self="closeConfirmDialog">
      <section class="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="information-video-confirm-title">
        <h2 id="information-video-confirm-title">{{ confirmTitle }}</h2>
        <p class="dialog-copy">{{ confirmCopy }}</p>
        <div class="dialog-actions">
          <button class="ghost" type="button" :disabled="Boolean(runningAction) || retryingVideoId !== null" @click="closeConfirmDialog">取消</button>
          <button
            type="button"
            :class="{ danger: confirmAction === 'markFailed' }"
            :disabled="Boolean(runningAction) || retryingVideoId !== null"
            @click="confirmOperation"
          >
            {{ runningAction || retryingVideoId !== null ? '处理中...' : '确认' }}
          </button>
        </div>
      </section>
    </div>
  </main>
</template>
