<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { apiErrorMessage } from '../../../api/client'
import { formatDateTime } from '../../../utils/datetime'
import {
  createVideoSource,
  deleteVideoSource,
  listVideoSources,
  scanVideos,
  updateVideoSource,
  type VideoSource,
} from '../api/videos'
import { statusClass } from '../utils/status'

const sources = ref<VideoSource[]>([])
const loading = ref(false)
const savingSource = ref(false)
const scanning = ref(false)
const message = ref('')
const newSource = ref({ source_name: '', external_source_id: '', source_url: '', remark: '' })
const selectedSourceIds = ref<number[]>([])

const enabledSources = computed(() => sources.value.filter((source) => source.enabled))
const allSourcesSelected = computed(
  () =>
    enabledSources.value.length > 0 &&
    enabledSources.value.every((source) => selectedSourceIds.value.includes(source.id)),
)

async function loadSources(options?: { keepMessage?: boolean }) {
  loading.value = true
  if (!options?.keepMessage) message.value = ''
  try {
    sources.value = await listVideoSources()
    const sourceIdSet = new Set(sources.value.map((source) => source.id))
    selectedSourceIds.value = selectedSourceIds.value.filter((sourceId) => sourceIdSet.has(sourceId))
  } catch (error) {
    message.value = apiErrorMessage(error, '信息源加载失败。')
  } finally {
    loading.value = false
  }
}

async function submitSource() {
  if (!newSource.value.source_name.trim() || !newSource.value.external_source_id.trim()) return
  savingSource.value = true
  try {
    await createVideoSource({
      platform: 'bilibili',
      source_name: newSource.value.source_name.trim(),
      external_source_id: newSource.value.external_source_id.trim(),
      source_url: newSource.value.source_url.trim() || undefined,
      remark: newSource.value.remark.trim() || undefined,
    })
    newSource.value = { source_name: '', external_source_id: '', source_url: '', remark: '' }
    message.value = '信息源已添加。'
    await loadSources({ keepMessage: true })
  } catch (error) {
    message.value = apiErrorMessage(error, '新增信息源失败，请检查 UID 或主页 URL。')
  } finally {
    savingSource.value = false
  }
}

async function toggleSource(source: VideoSource) {
  await updateVideoSource(source.id, { enabled: source.enabled ? 0 : 1 })
  await loadSources()
}

async function removeSource(source: VideoSource) {
  await deleteVideoSource(source.id)
  await loadSources()
}

async function runScan() {
  scanning.value = true
  try {
    const targetSourceIds = selectedSourceIds.value.length > 0 ? selectedSourceIds.value : undefined
    const result = await scanVideos(targetSourceIds)
    const targetText = targetSourceIds ? `选中 ${targetSourceIds.length} 个账号` : '全部启用账号'
    message.value = `视频扫描已完成，${targetText}新增 ${result.count} 条。`
    await loadSources({ keepMessage: true })
  } catch (error) {
    message.value = apiErrorMessage(error, '视频扫描失败，请查看运行状态。')
  } finally {
    scanning.value = false
  }
}

function toggleSourceSelection(sourceId: number, checked: boolean) {
  if (checked) {
    selectedSourceIds.value = Array.from(new Set([...selectedSourceIds.value, sourceId]))
    return
  }
  selectedSourceIds.value = selectedSourceIds.value.filter((id) => id !== sourceId)
}

function toggleAllSources(checked: boolean) {
  selectedSourceIds.value = checked ? enabledSources.value.map((source) => source.id) : []
}

onMounted(loadSources)
</script>

<template>
  <main class="page-shell">
    <section class="detail-hero">
      <div>
        <p class="eyebrow">Sources</p>
        <h1>信息源管理</h1>
        <p class="subtitle">维护 B站来源账号，并手动扫描选中或全部启用账号。</p>
      </div>
      <div class="section-actions">
        <button class="ghost" :disabled="scanning" @click="runScan">
          {{ scanning ? '扫描中...' : selectedSourceIds.length ? `扫描选中 ${selectedSourceIds.length} 个账号` : '扫描全部账号' }}
        </button>
      </div>
    </section>

    <p v-if="message" class="message">{{ message }}</p>

    <form class="inline-add-form" @submit.prevent="submitSource">
      <input v-model="newSource.source_name" placeholder="账号名称" />
      <input v-model="newSource.external_source_id" placeholder="UID 或 space 主页 URL" />
      <input v-model="newSource.source_url" placeholder="主页 URL，可选" />
      <input v-model="newSource.remark" placeholder="备注" />
      <button type="submit" :disabled="savingSource">{{ savingSource ? '保存中...' : '添加来源' }}</button>
    </form>

    <div class="table-card spaced-title">
      <table class="info-table sources-table">
        <colgroup>
          <col class="col-check" />
          <col class="col-id" />
          <col class="col-platform" />
          <col class="col-source" />
          <col class="col-uid" />
          <col class="col-count" />
          <col class="col-count" />
          <col class="col-status-wide" />
          <col class="col-time" />
          <col class="col-actions-wide" />
        </colgroup>
        <thead>
          <tr>
            <th>
              <input
                class="row-check"
                type="checkbox"
                :checked="allSourcesSelected"
                :disabled="loading || enabledSources.length === 0"
                @change="toggleAllSources(($event.target as HTMLInputElement).checked)"
              />
            </th>
            <th>ID</th>
            <th>平台</th>
            <th>账号</th>
            <th>UID</th>
            <th>视频数</th>
            <th>笔记数</th>
            <th>状态</th>
            <th>最近扫描</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="sources.length === 0">
            <td colspan="10">暂无信息源。</td>
          </tr>
          <tr v-for="source in sources" :key="source.id">
            <td>
              <input
                class="row-check"
                type="checkbox"
                :checked="selectedSourceIds.includes(source.id)"
                :disabled="!source.enabled"
                @change="toggleSourceSelection(source.id, ($event.target as HTMLInputElement).checked)"
              />
            </td>
            <td class="mono">{{ source.id }}</td>
            <td>{{ source.platform }}</td>
            <td>
              <RouterLink :to="{ name: 'information-videos', query: { source_id: source.id } }">
                {{ source.source_name }}
              </RouterLink>
            </td>
            <td class="mono">{{ source.external_source_id }}</td>
            <td class="mono">
              <RouterLink :to="{ name: 'information-videos', query: { source_id: source.id } }">
                {{ source.video_count }}
              </RouterLink>
            </td>
            <td class="mono">
              <RouterLink :to="{ name: 'information-notes', query: { source_id: source.id } }">
                {{ source.note_count }}
              </RouterLink>
            </td>
            <td><span class="status-pill" :class="statusClass(source.status)">{{ source.status_label }}</span></td>
            <td>{{ formatDateTime(source.last_scanned_at) }}</td>
            <td>
              <button class="ghost" type="button" @click="toggleSource(source)">{{ source.enabled ? '停用' : '启用' }}</button>
              <button class="danger" type="button" @click="removeSource(source)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </main>
</template>
