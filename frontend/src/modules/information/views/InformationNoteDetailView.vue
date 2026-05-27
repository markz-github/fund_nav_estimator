<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { apiErrorMessage } from '../../../api/client'
import { formatDateTime } from '../../../utils/datetime'
import MarkdownContent from '../components/MarkdownContent.vue'
import { getVideoNote, getVideoNoteRawResponse, regenerateVideoNote, repollVideoNote, type VideoNoteDetail } from '../api/videos'
import { formatDurationSeconds } from '../utils/duration'

const route = useRoute()
const router = useRouter()
const note = ref<VideoNoteDetail | null>(null)
const loading = ref(false)
const message = ref('')
const rawExpanded = ref(false)
const rawLoading = ref(false)
const rawMessage = ref('')
const rawResponse = ref<string | null>(null)
const rawViewMode = ref<'text' | 'json'>('text')
const repolling = ref(false)
const regenerating = ref(false)
const confirmDialogOpen = ref(false)
const confirmAction = ref<'regenerate' | 'repoll' | null>(null)

const noteId = computed(() => Number(route.params.noteId))
const formattedRawResponse = computed(() => {
  if (!rawResponse.value) return ''
  if (rawViewMode.value === 'text') return rawResponse.value
  try {
    return JSON.stringify(JSON.parse(rawResponse.value), null, 2)
  } catch {
    return rawResponse.value
  }
})
const confirmTitle = computed(() => (confirmAction.value === 'repoll' ? '重新轮询' : '重新生成'))
const confirmCopy = computed(() => {
  if (!note.value) return ''
  if (confirmAction.value === 'repoll') return `确认按原任务 ID 重新轮询笔记 ${note.value.id} 吗？`
  return `确认重新生成笔记 ${note.value.id} 吗？旧正文和任务 ID 会被清空。`
})

async function loadNote() {
  if (!Number.isFinite(noteId.value) || noteId.value <= 0) return
  loading.value = true
  message.value = ''
  resetRawResponse()
  try {
    note.value = await getVideoNote(noteId.value)
  } catch (error) {
    note.value = null
    message.value = apiErrorMessage(error, '笔记详情加载失败。')
  } finally {
    loading.value = false
  }
}

function resetRawResponse() {
  rawExpanded.value = false
  rawLoading.value = false
  rawMessage.value = ''
  rawResponse.value = null
  rawViewMode.value = 'text'
}

async function toggleRawResponse() {
  rawExpanded.value = !rawExpanded.value
  if (!rawExpanded.value || rawResponse.value || rawLoading.value) return
  rawLoading.value = true
  rawMessage.value = ''
  try {
    const result = await getVideoNoteRawResponse(noteId.value)
    rawResponse.value = result.raw_response || ''
  } catch (error) {
    rawMessage.value = apiErrorMessage(error, 'Raw Response 加载失败。')
  } finally {
    rawLoading.value = false
  }
}

async function repollCurrentNote() {
  if (!note.value) return
  repolling.value = true
  message.value = ''
  try {
    await repollVideoNote(note.value.id)
    message.value = `已将笔记 ${note.value.id} 恢复为轮询中，系统会按原任务 ID 获取结果。`
    await loadNote()
  } catch (error) {
    message.value = apiErrorMessage(error, '重新轮询失败，请确认该笔记为失败状态且保留了任务 ID。')
  } finally {
    repolling.value = false
  }
}

async function regenerateCurrentNote() {
  if (!note.value) return
  regenerating.value = true
  message.value = ''
  try {
    await regenerateVideoNote(note.value.id)
    message.value = `已将笔记 ${note.value.id} 重新加入生成流程。`
    await loadNote()
  } catch (error) {
    message.value = apiErrorMessage(error, '重新生成失败，请确认该笔记已完成或已失败。')
  } finally {
    regenerating.value = false
  }
}

function openConfirmDialog(action: 'regenerate' | 'repoll') {
  confirmAction.value = action
  confirmDialogOpen.value = true
}

function closeConfirmDialog() {
  if (repolling.value || regenerating.value) return
  confirmDialogOpen.value = false
  confirmAction.value = null
}

async function confirmOperation() {
  if (confirmAction.value === 'regenerate') {
    await regenerateCurrentNote()
  } else if (confirmAction.value === 'repoll') {
    await repollCurrentNote()
  }
  closeConfirmDialog()
}

function goBack() {
  if (window.history.state?.back) {
    router.back()
    return
  }
  router.push({ name: 'information-notes' })
}

onMounted(loadNote)
watch(noteId, loadNote)
</script>

<template>
  <main class="page-shell">
    <section v-if="note" class="detail-hero">
      <div>
        <p class="eyebrow">Note Detail</p>
        <h2>{{ note.video_title ?? `视频 ${note.video_id}` }}</h2>
        <p class="subtitle">
          {{ note.video_platform ?? '-' }} ·
          <a v-if="note.source_url" :href="note.source_url" target="_blank" rel="noreferrer">
            {{ note.source_name ?? '发布账号' }}
          </a>
          <span v-else>{{ note.source_name ?? '未知账号' }}</span>
          · {{ formatDateTime(note.video_published_at) }}
          · 时长 {{ formatDurationSeconds(note.video_duration_seconds) }}
          · Provider {{ note.provider }}
          · <a v-if="note.video_url" :href="note.video_url" target="_blank" rel="noreferrer">打开视频</a>
        </p>
      </div>
      <div class="section-actions">
        <button
          v-if="note.status === 'done' || note.status === 'failed'"
          class="ghost"
          type="button"
          :disabled="regenerating"
          @click="openConfirmDialog('regenerate')"
        >
          {{ regenerating ? '生成中...' : '重新生成' }}
        </button>
        <button
          v-if="note.status === 'failed' && note.external_task_id"
          class="ghost"
          type="button"
          :disabled="repolling"
          @click="openConfirmDialog('repoll')"
        >
          {{ repolling ? '轮询中...' : '重新轮询' }}
        </button>
        <button class="ghost" type="button" @click="goBack">返回</button>
      </div>
       <div class="muted">
        <!-- <span class="status-pill" :class="statusClass(note.status)">{{ note.status }}</span> -->
        <span class="mono">note: {{ note.id }}</span>
        <RouterLink class="mono" :to="{ name: 'information-videos', query: { video_id: note.video_id } }">
          video: {{ note.video_id }}
        </RouterLink>
        <span class="mono">task: {{ note.external_task_id ?? '-' }}</span>
      </div>
    </section>

    <p v-if="message" class="message">{{ message }}</p>

    <section v-if="note" class="note-detail-layout">
      <section class="note-detail">
        <MarkdownContent v-if="note.note_text" :content="note.note_text" show-toc />
        <pre v-else>{{ note.error_message || '暂无正文。' }}</pre>

        <h4>Raw Response</h4>
        <div class="raw-panel">
          <div class="raw-toolbar">
            <button class="ghost" type="button" :disabled="rawLoading" @click="toggleRawResponse">
              {{ rawExpanded ? '收起 Raw' : '展开 Raw' }}
            </button>
            <div v-if="rawExpanded" class="view-toggle" aria-label="Raw Response 展示方式">
              <button type="button" :class="{ active: rawViewMode === 'text' }" @click="rawViewMode = 'text'">原文</button>
              <button type="button" :class="{ active: rawViewMode === 'json' }" @click="rawViewMode = 'json'">JSON</button>
            </div>
          </div>
          <p v-if="rawMessage" class="message">{{ rawMessage }}</p>
          <pre v-if="rawExpanded">{{ rawLoading ? 'Raw Response 加载中...' : formattedRawResponse || '暂无原始响应。' }}</pre>
        </div>
      </section>
    </section>

    <p v-else-if="!loading" class="message">暂无笔记详情。</p>

    <div v-if="confirmDialogOpen" class="modal-backdrop" @click.self="closeConfirmDialog">
      <section class="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="note-detail-confirm-title">
        <h2 id="note-detail-confirm-title">{{ confirmTitle }}</h2>
        <p class="dialog-copy">{{ confirmCopy }}</p>
        <div class="dialog-actions">
          <button class="ghost" type="button" :disabled="repolling || regenerating" @click="closeConfirmDialog">取消</button>
          <button type="button" :disabled="repolling || regenerating" @click="confirmOperation">
            {{ repolling || regenerating ? '处理中...' : '确认' }}
          </button>
        </div>
      </section>
    </div>
  </main>
</template>
