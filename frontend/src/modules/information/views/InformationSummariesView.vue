<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { apiErrorMessage } from '../../../api/client'
import { formatDateTime } from '../../../utils/datetime'
import {
  generateSummary,
  getInformationStatusOptions,
  listSummaryDocuments,
  retrySummaryDocument,
  type StatusOption,
  type SummaryDocument,
} from '../api/videos'
import { statusClass } from '../utils/status'

const route = useRoute()
const router = useRouter()
const documents = ref<SummaryDocument[]>([])
const loading = ref(false)
const generating = ref(false)
const retryingDocumentId = ref<number | null>(null)
const message = ref('')
const notesDialogDocumentId = ref<number | null>(null)
const selectedSummaryType = ref('')
const summaryTypes = ref<StatusOption[]>([])
const notesDialogDocument = computed(() => documents.value.find((item) => item.id === notesDialogDocumentId.value) ?? null)

function summaryTypeLabel(type: string) {
  return summaryTypes.value.find((option) => option.value === type)?.label ?? type
}

async function loadDocuments(options?: { keepMessage?: boolean }) {
  loading.value = true
  if (!options?.keepMessage) message.value = ''
  try {
    documents.value = await listSummaryDocuments({ summaryType: selectedSummaryType.value })
  } catch (error) {
    message.value = apiErrorMessage(error, '笔记汇总加载失败。')
  } finally {
    loading.value = false
  }
}

async function loadOptions() {
  try {
    const options = await getInformationStatusOptions()
    summaryTypes.value = options.summary_types
  } catch (error) {
    message.value = apiErrorMessage(error, '汇总类型选项加载失败。')
  }
}

function applyQueryFilters() {
  selectedSummaryType.value = typeof route.query.summary_type === 'string' ? route.query.summary_type : ''
}

async function applySummaryTypeFilter() {
  await router.replace({
    name: 'information-summaries',
    query: selectedSummaryType.value ? { summary_type: selectedSummaryType.value } : undefined,
  })
  await loadDocuments()
}

function resetSummaryType() {
  selectedSummaryType.value = ''
  applySummaryTypeFilter()
}

async function runSummary() {
  generating.value = true
  try {
    const result = await generateSummary()
    message.value = result ? `Hermes 笔记汇总已提交：${result.title}` : '没有可汇总的已完成视频总结。'
    await loadDocuments({ keepMessage: true })
  } catch (error) {
    message.value = apiErrorMessage(error, '笔记汇总生成失败，请查看运行状态。')
  } finally {
    generating.value = false
  }
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
        <p class="subtitle">查看手动汇总、日汇总和周汇总生成的 Hermes 文档。</p>
      </div>
      <div class="section-actions">
        <span>{{ documents.length }} 篇</span>
        <button :disabled="generating" @click="runSummary">{{ generating ? '汇总中...' : '生成每日汇总' }}</button>
      </div>
    </section>

    <p v-if="message" class="message">{{ message }}</p>

    <form class="filter-bar compact-filter" @submit.prevent="applySummaryTypeFilter">
      <label>
        汇总类型
        <select v-model="selectedSummaryType">
          <option value="">全部类型</option>
          <option v-for="summaryType in summaryTypes" :key="summaryType.value" :value="summaryType.value">
            {{ summaryType.label }}
          </option>
        </select>
      </label>
      <div class="filter-actions">
        <button class="ghost" type="submit" :disabled="loading">应用筛选</button>
        <button class="ghost" type="button" :disabled="loading || !selectedSummaryType" @click="resetSummaryType">重置</button>
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
          <col class="col-source" />
          <col class="col-time" />
          <col class="col-actions-wide" />
        </colgroup>
        <thead>
          <tr>
            <th>ID</th>
            <th>汇总类型</th>
            <th>汇总名称</th>
            <th>状态</th>
            <th>汇总日期</th>
            <th>平台</th>
            <th>生成时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="documents.length === 0">
            <td colspan="8">暂无笔记汇总文档。</td>
          </tr>
          <tr v-for="document in documents" :key="document.id">
            <td class="mono">{{ document.id }}</td>
            <td>{{ summaryTypeLabel(document.summary_type) }}</td>
            <td>
              <RouterLink :to="{ name: 'information-summary-detail', params: { documentId: document.id } }">
                {{ document.title }}
              </RouterLink>
            </td>
            <td><span class="status-pill" :class="statusClass(document.status)">{{ document.status_label }}</span></td>
            <td>{{ document.summary_date }}</td>
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
