<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { apiErrorMessage } from '../../../api/client'
import MarkdownContent from '../components/MarkdownContent.vue'
import { getSummaryDocument, type SummaryDocument } from '../api/videos'
import { statusClass } from '../utils/status'

const route = useRoute()
const document = ref<SummaryDocument | null>(null)
const loading = ref(false)
const message = ref('')

const documentId = computed(() => Number(route.params.documentId))

function summaryTypeLabel(type: string) {
  const labels: Record<string, string> = {
    manual: '手动汇总',
    daily: '日汇总',
    weekly: '周汇总',
  }
  return labels[type] ?? type
}

async function loadDocument() {
  if (!Number.isFinite(documentId.value) || documentId.value <= 0) return
  loading.value = true
  message.value = ''
  try {
    document.value = await getSummaryDocument(documentId.value)
  } catch (error) {
    document.value = null
    message.value = apiErrorMessage(error, '笔记汇总详情加载失败。')
  } finally {
    loading.value = false
  }
}

onMounted(loadDocument)
watch(documentId, loadDocument)
</script>

<template>
  <main class="page-shell">
    <section v-if="document" class="detail-hero">
      <div>
        <p class="eyebrow">Summary Detail</p>
        <h1>{{ document.title }}</h1>
        <p class="subtitle">
          {{ summaryTypeLabel(document.summary_type) }} · {{ document.summary_date }} · {{ document.platform }} · <span class="mono">document: {{ document.id }}</span>
        </p>
      </div>
      <div class="section-actions">
        <RouterLink class="link-button" :to="{ name: 'information-summaries' }">返回列表</RouterLink>
      </div>
      <span class="status-pill" :class="statusClass(document.status)">{{ document.status_label }}</span>
    </section>

    <p v-if="message" class="message">{{ message }}</p>

    <section v-if="document" class="summary-detail-layout">
      <section class="note-detail summary-document-panel">
        <MarkdownContent v-if="document.document_text" :content="document.document_text" show-toc />
        <pre v-else>{{ document.error_message || '暂无正文。' }}</pre>
      </section>

      <aside class="summary-note-list">
        <div class="summary-note-list-header">
          <h3>关联笔记</h3>
          <span>{{ document.notes.length }} 篇</span>
        </div>
        <ul v-if="document.notes.length > 0">
          <li v-for="item in document.notes" :key="item.id">
            <RouterLink :to="{ name: 'information-note-detail', params: { noteId: item.id } }">
              #{{ item.id }} {{ item.video_title ?? `视频 ${item.video_id}` }}
            </RouterLink>
            <span>{{ item.source_name ?? '-' }}</span>
            <span>{{ item.video_published_at ?? '-' }}</span>
          </li>
        </ul>
        <p v-else class="muted">暂无关联笔记。</p>
      </aside>
    </section>

    <p v-else-if="!loading" class="message">暂无笔记汇总详情。</p>
  </main>
</template>
