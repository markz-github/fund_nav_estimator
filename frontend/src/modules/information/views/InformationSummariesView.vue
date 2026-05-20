<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { apiErrorMessage } from '../../../api/client'
import {
  generateSummary,
  listSummaryDocuments,
  retrySummaryDocument,
  type SummaryDocument,
} from '../api/videos'
import { statusClass } from '../utils/status'

const documents = ref<SummaryDocument[]>([])
const loading = ref(false)
const generating = ref(false)
const retryingDocumentId = ref<number | null>(null)
const message = ref('')
const notesDialogDocumentId = ref<number | null>(null)
const notesDialogDocument = computed(() => documents.value.find((item) => item.id === notesDialogDocumentId.value) ?? null)

async function loadDocuments(options?: { keepMessage?: boolean }) {
  loading.value = true
  if (!options?.keepMessage) message.value = ''
  try {
    documents.value = await listSummaryDocuments()
  } catch (error) {
    message.value = apiErrorMessage(error, '笔记汇总加载失败。')
  } finally {
    loading.value = false
  }
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

onMounted(loadDocuments)
</script>

<template>
  <main class="page-shell">
    <section class="detail-hero">
      <div>
        <p class="eyebrow">Documents</p>
        <h1>笔记汇总</h1>
        <p class="subtitle">查看每日汇总和手动选择笔记生成的 Hermes 汇总文档。</p>
      </div>
      <div class="section-actions">
        <span>{{ documents.length }} 篇</span>
        <button :disabled="generating" @click="runSummary">{{ generating ? '汇总中...' : '生成每日汇总' }}</button>
      </div>
    </section>

    <p v-if="message" class="message">{{ message }}</p>

    <div class="table-card">
      <table class="info-table">
        <colgroup>
          <col class="col-id" />
          <col class="col-title" />
          <col class="col-status" />
          <col class="col-time" />
          <col class="col-source" />
          <col class="col-task" />
          <col class="col-time" />
          <col class="col-actions-wide" />
        </colgroup>
        <thead>
          <tr>
            <th>ID</th>
            <th>汇总名称</th>
            <th>状态</th>
            <th>汇总日期</th>
            <th>平台</th>
            <th>Run ID</th>
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
            <td>
              <RouterLink :to="{ name: 'information-summary-detail', params: { documentId: document.id } }">
                {{ document.title }}
              </RouterLink>
            </td>
            <td><span class="status-pill" :class="statusClass(document.status)">{{ document.status_label }}</span></td>
            <td>{{ document.summary_date }}</td>
            <td>{{ document.platform }}</td>
            <td class="mono">{{ document.hermes_run_id ?? '-' }}</td>
            <td>{{ document.generated_at ?? document.summary_date }}</td>
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
            <span>{{ item.video_published_at ?? '-' }}</span>
          </li>
        </ul>
        <p v-else class="message">暂无关联笔记。</p>
      </section>
    </div>
  </main>
</template>
