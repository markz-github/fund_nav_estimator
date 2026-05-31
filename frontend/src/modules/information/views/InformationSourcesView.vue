<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { apiErrorMessage } from '../../../api/client'
import { formatDateTime } from '../../../utils/datetime'
import {
  createVideoSource,
  deleteVideoSource,
  listInformationCategories,
  listVideoSourcesPage,
  scanVideos,
  updateVideoSource,
  type VideoSource,
} from '../api/videos'
import { statusClass } from '../utils/status'

const sources = ref<VideoSource[]>([])
const totalSources = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const savingSource = ref(false)
const scanning = ref(false)
const message = ref('')
const sourceFormMessage = ref('')
const categories = ref<string[]>(['财经'])
const dialogMode = ref<'add' | 'edit' | null>(null)
const editingSourceId = ref<number | null>(null)
const sourceDraft = ref(emptySourceDraft())
const selectedSourceIds = ref<number[]>([])
const confirmAction = ref<'disable' | 'delete' | null>(null)
const confirmSource = ref<VideoSource | null>(null)

function isSystemSource(source: VideoSource) {
  return source.id < 0 || source.external_source_id === 'manual' || source.platform === 'system'
}

const enabledSources = computed(() => sources.value.filter((source) => source.enabled && !isSystemSource(source)))
const sourceDialogOpen = computed(() => dialogMode.value !== null)
const sourceDialogTitle = computed(() => (dialogMode.value === 'edit' ? '修改信息源' : '添加信息源'))
const confirmDialogOpen = computed(() => confirmAction.value !== null && confirmSource.value !== null)
const confirmDialogTitle = computed(() => (confirmAction.value === 'delete' ? '删除信息源' : '停用信息源'))
const confirmDialogText = computed(() => {
  const source = confirmSource.value
  if (!source) return ''
  if (confirmAction.value === 'delete') return `确认删除信息源“${source.source_name}”吗？删除后该来源将不再显示。`
  return `确认停用信息源“${source.source_name}”吗？停用后不会再参与自动或手动扫描。`
})
const totalPages = computed(() => Math.max(1, Math.ceil(totalSources.value / pageSize.value)))
const allSourcesSelected = computed(
  () =>
    enabledSources.value.length > 0 &&
    enabledSources.value.every((source) => selectedSourceIds.value.includes(source.id)),
)

function emptySourceDraft() {
  return {
    source_name: '',
    external_source_id: '',
    source_url: '',
    category: '财经',
    remark: '',
  }
}

async function loadSources(options?: { keepMessage?: boolean }) {
  loading.value = true
  if (!options?.keepMessage) message.value = ''
  try {
    const [sourceResult, categoryResult] = await Promise.all([
      listVideoSourcesPage({ page: currentPage.value, pageSize: pageSize.value }),
      listInformationCategories(),
    ])
    sources.value = sourceResult.items
    totalSources.value = sourceResult.total
    currentPage.value = sourceResult.page
    pageSize.value = sourceResult.page_size
    categories.value = categoryResult
    const sourceIdSet = new Set(sources.value.map((source) => source.id))
    selectedSourceIds.value = selectedSourceIds.value.filter((sourceId) => sourceIdSet.has(sourceId))
  } catch (error) {
    message.value = apiErrorMessage(error, '信息源加载失败。')
  } finally {
    loading.value = false
  }
}

async function submitSource() {
  const sourceName = sourceDraft.value.source_name.trim()
  const externalSourceId = sourceDraft.value.external_source_id.trim()
  sourceFormMessage.value = ''
  if (!sourceName) {
    sourceFormMessage.value = '请填写账号名称。'
    return
  }
  if (!externalSourceId) {
    sourceFormMessage.value = '请填写 UID 或主页。'
    return
  }
  savingSource.value = true
  try {
    const payload = {
      platform: 'bilibili',
      source_name: sourceName,
      external_source_id: externalSourceId,
      source_url: sourceDraft.value.source_url.trim() || undefined,
      category: sourceDraft.value.category.trim() || '财经',
      remark: sourceDraft.value.remark.trim() || undefined,
    }
    if (dialogMode.value === 'edit' && editingSourceId.value !== null) {
      await updateVideoSource(editingSourceId.value, payload)
      message.value = '信息源已保存。'
    } else {
      await createVideoSource(payload)
      message.value = '信息源已添加。'
    }
    dialogMode.value = null
    editingSourceId.value = null
    sourceFormMessage.value = ''
    await loadSources({ keepMessage: true })
  } catch (error) {
    sourceFormMessage.value = apiErrorMessage(
      error,
      dialogMode.value === 'edit' ? '保存信息源失败，请检查 UID 或主页 URL。' : '新增信息源失败，请检查 UID 或主页 URL。',
    )
  } finally {
    savingSource.value = false
  }
}

function openAddDialog() {
  sourceDraft.value = emptySourceDraft()
  editingSourceId.value = null
  sourceFormMessage.value = ''
  dialogMode.value = 'add'
}

function openEditDialog(source: VideoSource) {
  if (isSystemSource(source)) return
  sourceDraft.value = {
    source_name: source.source_name,
    external_source_id: source.external_source_id,
    source_url: source.source_url ?? '',
    category: source.category || '财经',
    remark: source.remark ?? '',
  }
  editingSourceId.value = source.id
  sourceFormMessage.value = ''
  dialogMode.value = 'edit'
}

function closeSourceDialog() {
  if (savingSource.value) return
  dialogMode.value = null
  editingSourceId.value = null
  sourceFormMessage.value = ''
}

async function toggleSource(source: VideoSource) {
  if (isSystemSource(source)) return
  if (source.enabled) {
    openConfirmDialog('disable', source)
    return
  }
  await updateVideoSource(source.id, { enabled: 1 })
  await loadSources()
}

function openConfirmDialog(action: 'disable' | 'delete', source: VideoSource) {
  if (isSystemSource(source)) return
  confirmAction.value = action
  confirmSource.value = source
}

function closeConfirmDialog() {
  if (savingSource.value) return
  confirmAction.value = null
  confirmSource.value = null
}

async function removeSource(source: VideoSource) {
  if (isSystemSource(source)) return
  openConfirmDialog('delete', source)
}

async function confirmDangerAction() {
  const action = confirmAction.value
  const source = confirmSource.value
  if (!action || !source) return
  savingSource.value = true
  try {
    if (action === 'delete') {
      await deleteVideoSource(source.id)
      message.value = `信息源“${source.source_name}”已删除。`
    } else {
      await updateVideoSource(source.id, { enabled: 0 })
      selectedSourceIds.value = selectedSourceIds.value.filter((sourceId) => sourceId !== source.id)
      message.value = `信息源“${source.source_name}”已停用。`
    }
    confirmAction.value = null
    confirmSource.value = null
    await loadSources({ keepMessage: true })
  } catch (error) {
    message.value = apiErrorMessage(error, action === 'delete' ? '删除信息源失败。' : '停用信息源失败。')
  } finally {
    savingSource.value = false
  }
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

async function goToPage(page: number) {
  currentPage.value = Math.min(Math.max(1, page), totalPages.value)
  await loadSources()
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
        <span>第 {{ currentPage }} / {{ totalPages }} 页，共 {{ totalSources }} 个</span>
        <button type="button" @click="openAddDialog">添加来源</button>
        <button class="ghost" :disabled="scanning" @click="runScan">
          {{ scanning ? '扫描中...' : selectedSourceIds.length ? `扫描选中 ${selectedSourceIds.length} 个账号` : '扫描全部账号' }}
        </button>
      </div>
    </section>

    <p v-if="message" class="message">{{ message }}</p>

    <datalist id="source-categories">
      <option v-for="category in categories" :key="category" :value="category" />
    </datalist>

    <div class="table-card spaced-title">
      <table class="info-table sources-table">
        <colgroup>
          <col class="col-check" />
          <col class="col-id" />
          <col class="col-platform" />
          <col class="col-source" />
          <col class="col-uid" />
          <col class="col-category" />
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
            <th>分类</th>
            <th>信息数</th>
            <th>笔记数</th>
            <th>状态</th>
            <th>最近扫描</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="sources.length === 0">
            <td colspan="11">暂无信息源。</td>
          </tr>
          <tr v-for="source in sources" :key="source.id">
            <td>
              <input
                class="row-check"
                type="checkbox"
                :checked="selectedSourceIds.includes(source.id)"
                :disabled="!source.enabled || isSystemSource(source)"
                @change="toggleSourceSelection(source.id, ($event.target as HTMLInputElement).checked)"
              />
            </td>
            <td class="mono">{{ source.id }}</td>
            <td>{{ source.platform }}</td>
            <td>
              <RouterLink :to="{ name: 'information-videos', query: { source_id: source.id } }">
                {{ source.source_name }}
                <span v-if="isSystemSource(source)" class="muted">系统内置</span>
              </RouterLink>
            </td>
            <td class="mono">{{ source.external_source_id }}</td>
            <td>{{ source.category }}</td>
            <td class="mono">
              <RouterLink :to="{ name: 'information-videos', query: { source_id: source.id } }">
                {{ source.information_count }}
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
              <div v-if="!isSystemSource(source)" class="quick-actions">
                <button class="ghost" type="button" :disabled="savingSource" @click="openEditDialog(source)">修改</button>
                <button class="ghost" type="button" :disabled="savingSource" @click="toggleSource(source)">{{ source.enabled ? '停用' : '启用' }}</button>
                <button class="danger" type="button" :disabled="savingSource" @click="removeSource(source)">删除</button>
              </div>
              <span v-else class="muted">系统内置</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <nav class="pagination-bar" aria-label="信息源分页">
      <button class="ghost" type="button" :disabled="loading || currentPage <= 1" @click="goToPage(currentPage - 1)">上一页</button>
      <span>第 {{ currentPage }} / {{ totalPages }} 页</span>
      <button class="ghost" type="button" :disabled="loading || currentPage >= totalPages" @click="goToPage(currentPage + 1)">下一页</button>
    </nav>

    <div v-if="sourceDialogOpen" class="modal-backdrop" @click.self="closeSourceDialog">
      <section class="confirm-dialog summary-task-dialog" role="dialog" aria-modal="true" aria-labelledby="source-dialog-title">
        <h2 id="source-dialog-title">{{ sourceDialogTitle }}</h2>
        <p v-if="sourceFormMessage" class="message">{{ sourceFormMessage }}</p>
        <form class="settings-grid" @submit.prevent="submitSource">
          <label>账号名称<input v-model="sourceDraft.source_name" required /></label>
          <label>UID 或主页<input v-model="sourceDraft.external_source_id" required placeholder="UID 或 space 主页 URL" /></label>
          <label class="settings-wide">主页 URL<input v-model="sourceDraft.source_url" placeholder="可选" /></label>
          <label>分类<input v-model="sourceDraft.category" list="source-categories" placeholder="财经" /></label>
          <label class="settings-wide">备注<input v-model="sourceDraft.remark" /></label>
        </form>
        <div class="dialog-actions">
          <button class="ghost" type="button" :disabled="savingSource" @click="closeSourceDialog">取消</button>
          <button type="button" :disabled="savingSource" @click="submitSource">
            {{ savingSource ? '保存中...' : (dialogMode === 'edit' ? '保存修改' : '添加来源') }}
          </button>
        </div>
      </section>
    </div>

    <div v-if="confirmDialogOpen" class="modal-backdrop" @click.self="closeConfirmDialog">
      <section class="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="source-confirm-title">
        <h2 id="source-confirm-title">{{ confirmDialogTitle }}</h2>
        <p class="dialog-copy">{{ confirmDialogText }}</p>
        <div class="dialog-actions">
          <button class="ghost" type="button" :disabled="savingSource" @click="closeConfirmDialog">取消</button>
          <button class="danger" type="button" :disabled="savingSource" @click="confirmDangerAction">
            {{ savingSource ? '处理中...' : '确认' }}
          </button>
        </div>
      </section>
    </div>
  </main>
</template>
