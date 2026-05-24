<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { apiErrorMessage } from '../../../api/client'
import { formatDateTime } from '../../../utils/datetime'
import {
  listInformationCategories,
  listSummaryDocumentsPage,
  listSummaryTaskConfigs,
  retrySummaryDocument,
  type SummaryDocument,
  type SummaryTaskConfig,
} from '../api/videos'
import { statusClass } from '../utils/status'

const route = useRoute()
const router = useRouter()
const documents = ref<SummaryDocument[]>([])
const totalDocuments = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const retryingDocumentId = ref<number | null>(null)
const message = ref('')
const notesDialogDocumentId = ref<number | null>(null)
const selectedSummaryTaskConfigId = ref('')
const selectedCategory = ref('')
const summaryTaskConfigs = ref<SummaryTaskConfig[]>([])
const categories = ref<string[]>(['财经'])
const MANUAL_SUMMARY_FILTER = 'manual'
const totalPages = computed(() => Math.max(1, Math.ceil(totalDocuments.value / pageSize.value)))
const notesDialogDocument = computed(() => documents.value.find((item) => item.id === notesDialogDocumentId.value) ?? null)

function summaryTaskLabel(document: SummaryDocument) {
  return document.summary_task_name || '手动汇总'
}

async function loadDocuments(options?: { keepMessage?: boolean }) {
  loading.value = true
  if (!options?.keepMessage) message.value = ''
  try {
    const manualSummary = selectedSummaryTaskConfigId.value === MANUAL_SUMMARY_FILTER
    const result = await listSummaryDocumentsPage({
      page: currentPage.value,
      pageSize: pageSize.value,
      summaryTaskConfigId: selectedSummaryTaskConfigId.value && !manualSummary ? Number(selectedSummaryTaskConfigId.value) : undefined,
      manualSummary,
      category: selectedCategory.value,
    })
    documents.value = result.items
    totalDocuments.value = result.total
    currentPage.value = result.page
    pageSize.value = result.page_size
  } catch (error) {
    message.value = apiErrorMessage(error, '笔记汇总加载失败。')
  } finally {
    loading.value = false
  }
}

async function loadOptions() {
  try {
    const [taskConfigs, categoryResult] = await Promise.all([listSummaryTaskConfigs(), listInformationCategories()])
    summaryTaskConfigs.value = taskConfigs
    categories.value = categoryResult
  } catch (error) {
    message.value = apiErrorMessage(error, '汇总任务选项加载失败。')
  }
}

function applyQueryFilters() {
  selectedSummaryTaskConfigId.value = typeof route.query.summary_task_config_id === 'string' ? route.query.summary_task_config_id : ''
  selectedCategory.value = typeof route.query.category === 'string' ? route.query.category : ''
  const queryPage = Number(route.query.page)
  currentPage.value = Number.isFinite(queryPage) && queryPage > 0 ? Math.floor(queryPage) : 1
}

async function applySummaryFilter() {
  currentPage.value = 1
  await router.replace({
    name: 'information-summaries',
    query: {
      ...(selectedSummaryTaskConfigId.value ? { summary_task_config_id: selectedSummaryTaskConfigId.value } : {}),
      ...(selectedCategory.value ? { category: selectedCategory.value } : {}),
      ...(currentPage.value > 1 ? { page: String(currentPage.value) } : {}),
    },
  })
  await loadDocuments()
}

function resetSummaryFilter() {
  selectedSummaryTaskConfigId.value = ''
  selectedCategory.value = ''
  currentPage.value = 1
  applySummaryFilter()
}

async function goToPage(page: number) {
  currentPage.value = Math.min(Math.max(1, page), totalPages.value)
  await router.replace({
    name: 'information-summaries',
    query: {
      ...(selectedSummaryTaskConfigId.value ? { summary_task_config_id: selectedSummaryTaskConfigId.value } : {}),
      ...(selectedCategory.value ? { category: selectedCategory.value } : {}),
      ...(currentPage.value > 1 ? { page: String(currentPage.value) } : {}),
    },
  })
  await loadDocuments()
}

async function retryDocument(documentId: number) {
  retryingDocumentId.value = documentId
  message.value = ''
  try {
    const result = await retrySummaryDocument(documentId)
    message.value = result.status === 'failed' ? `汇总重试失败：${result.error_message || result.title}` : `汇总重试已提交：${result.title}`
    await loadDocuments({ keepMessage: true })
  } catch (error) {
    message.value = apiErrorMessage(error, '汇总重试失败，请查看运行状态。')
  } finally {
    retryingDocumentId.value = null
  }
}

function openNotesDialog(documentId: number) {
  notesDialogDocumentId.value = documentId
}

function closeNotesDialog() {
  notesDialogDocumentId.value = null
}

onMounted(() => {
  applyQueryFilters()
  loadOptions()
  loadDocuments()
})

watch(
  () => route.query,
  () => {
    applyQueryFilters()
    loadDocuments()
  },
)
</script>

<template>
  <main class="page-shell">
    <section class="detail-hero">
      <div>
        <p class="eyebrow">Documents</p>
        <h1>笔记汇总</h1>
        <p class="subtitle">查看手动汇总和汇总任务生成的 Hermes 文档。</p>
      </div>
      <div class="section-actions">
        <span>第 {{ currentPage }} / {{ totalPages }} 页，共 {{ totalDocuments }} 篇</span>
      </div>
    </section>

    <p v-if="message" class="message">{{ message }}</p>

    <form class="filter-bar compact-filter" @submit.prevent="applySummaryFilter">
      <label>
        汇总任务
        <select v-model="selectedSummaryTaskConfigId">
          <option value="">全部任务</option>
          <option :value="MANUAL_SUMMARY_FILTER">手动汇总</option>
          <option v-for="config in summaryTaskConfigs" :key="config.id" :value="String(config.id)">
            {{ config.task_name }}
          </option>
        </select>
      </label>
      <label>
        分类
        <select v-model="selectedCategory">
          <option value="">全部分类</option>
          <option v-for="category in categories" :key="category" :value="category">
            {{ category }}
          </option>
        </select>
      </label>
      <div class="filter-actions">
        <button class="ghost" type="submit" :disabled="loading">应用筛选</button>
        <button class="ghost" type="button" :disabled="loading || (!selectedSummaryTaskConfigId && !selectedCategory)" @click="resetSummaryFilter">重置</button>
      </div>
    </form>

    <div class="table-card">
      <table class="info-table">
        <colgroup>
          <col class="col-id" />
          <col class="col-type" />
          <col class="col-title" />
          <col class="col-status" />
          <col class="col-time" />
          <col class="col-category" />
          <col class="col-source" />
          <col class="col-time" />
          <col class="col-actions-wide" />
        </colgroup>
        <thead>
          <tr>
            <th>ID</th>
            <th>汇总任务</th>
            <th>汇总名称</th>
            <th>状态</th>
            <th>汇总日期</th>
            <th>分类</th>
            <th>平台</th>
            <th>生成时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="documents.length === 0">
            <td colspan="9">暂无笔记汇总文档。</td>
          </tr>
          <tr v-for="document in documents" :key="document.id">
            <td class="mono">{{ document.id }}</td>
            <td>{{ summaryTaskLabel(document) }}</td>
            <td>
              <RouterLink :to="{ name: 'information-summary-detail', params: { documentId: document.id } }">
                {{ document.title }}
              </RouterLink>
            </td>
            <td><span class="status-pill" :class="statusClass(document.status)">{{ document.status_label }}</span></td>
            <td>{{ document.summary_date }}</td>
            <td>{{ document.category }}</td>
            <td>{{ document.platform }}</td>
            <td>{{ document.generated_at ? formatDateTime(document.generated_at) : document.summary_date }}</td>
            <td>
              <div class="quick-actions">
                <RouterLink class="link-button" :to="{ name: 'information-summary-detail', params: { documentId: document.id } }">
                  查看详情
                </RouterLink>
                <button class="ghost" type="button" @click="openNotesDialog(document.id)">查看关联笔记</button>
                <button
                  v-if="document.status === 'failed'"
                  class="ghost"
                  type="button"
                  :disabled="retryingDocumentId === document.id"
                  @click="retryDocument(document.id)"
                >
                  {{ retryingDocumentId === document.id ? '重试中...' : '重试' }}
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <nav class="pagination-bar" aria-label="笔记汇总分页">
      <button class="ghost" type="button" :disabled="loading || currentPage <= 1" @click="goToPage(currentPage - 1)">上一页</button>
      <span>第 {{ currentPage }} / {{ totalPages }} 页</span>
      <button class="ghost" type="button" :disabled="loading || currentPage >= totalPages" @click="goToPage(currentPage + 1)">下一页</button>
    </nav>

    <div v-if="notesDialogDocument" class="modal-backdrop" @click.self="closeNotesDialog">
      <section class="related-notes-dialog" role="dialog" aria-modal="true" aria-labelledby="related-notes-title">
        <div class="related-notes-header">
          <div>
            <p class="eyebrow">Related Notes</p>
            <h2 id="related-notes-title">关联笔记</h2>
            <p>{{ notesDialogDocument.title }} · {{ notesDialogDocument.notes.length }} 篇</p>
          </div>
          <button class="ghost" type="button" @click="closeNotesDialog">关闭</button>
        </div>
        <ul v-if="notesDialogDocument.notes.length > 0" class="related-notes-list">
          <li v-for="item in notesDialogDocument.notes" :key="item.id">
            <RouterLink :to="{ name: 'information-note-detail', params: { noteId: item.id } }">
              #{{ item.id }} {{ item.video_title ?? `视频 ${item.video_id}` }}
            </RouterLink>
            <span>{{ item.source_name ?? '-' }}</span>
            <span>{{ formatDateTime(item.video_published_at) }}</span>
          </li>
        </ul>
        <p v-else class="message">暂无关联笔记。</p>
      </section>
    </div>
  </main>
</template>
