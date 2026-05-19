<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { apiErrorMessage } from '../../../api/client'
import MarkdownContent from '../components/MarkdownContent.vue'
import { getVideoNote, getVideoNoteRawResponse, type VideoNoteDetail } from '../api/videos'

const route = useRoute()
const note = ref<VideoNoteDetail | null>(null)
const loading = ref(false)
const message = ref('')
const rawExpanded = ref(false)
const rawLoading = ref(false)
const rawMessage = ref('')
const rawResponse = ref<string | null>(null)
const rawViewMode = ref<'text' | 'json'>('text')

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
          {{ note.video_platform ?? '-' }} · {{ note.video_external_id ?? '-' }} ·
          <a v-if="note.source_url" :href="note.source_url" target="_blank" rel="noreferrer">
            {{ note.source_name ?? '发布账号' }}
          </a>
          <span v-else>{{ note.source_name ?? '未知账号' }}</span>
          · {{ note.video_published_at ?? '发布时间未知' }}
          · <a v-if="note.video_url" :href="note.video_url" target="_blank" rel="noreferrer">打开视频</a>
        </p>
      </div>
      <div class="section-actions">
        <button class="ghost" :disabled="loading" @click="loadNote">{{ loading ? '刷新中...' : '刷新详情' }}</button>
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
  </main>
</template>
