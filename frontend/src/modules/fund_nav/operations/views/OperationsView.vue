<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { routeNames } from '../../../../router/routeNames'
import { getTaskLogOptions, listTaskLogs, type OperationModule, type StatusOption, type TaskLog } from '../api/operations'

const route = useRoute()
const router = useRouter()
const operationModule: OperationModule = 'fund_nav'
const taskLogs = ref<TaskLog[]>([])
const totalLogs = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const message = ref('')
const selectedTaskType = ref('')
const selectedStatus = ref('')
const fundNavTaskTypes = ref<StatusOption[]>([])
const taskStatuses = ref<StatusOption[]>([])
const popover = ref({ text: '', top: 0, left: 0, visible: false })
const totalPages = computed(() => Math.max(1, Math.ceil(totalLogs.value / pageSize.value)))

function formatDateTime(value?: string | null) {
  if (!value) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(value))
}

function statusClass(status: string) {
  if (status === 'success') return 'status-ok'
  if (status === 'failed') return 'status-danger'
  return 'status-warn'
}

function taskTypeLabel(taskType: string) {
  return fundNavTaskTypes.value.find((option) => option.value === taskType)?.label ?? taskType
}

function filterQuery() {
  return {
    ...(selectedTaskType.value ? { task_type: selectedTaskType.value } : {}),
    ...(selectedStatus.value ? { status: selectedStatus.value } : {}),
    ...(currentPage.value > 1 ? { page: String(currentPage.value) } : {}),
  }
}

async function loadOperations() {
  loading.value = true
  message.value = ''
  try {
    const result = await listTaskLogs(operationModule, {
      taskType: selectedTaskType.value,
      status: selectedStatus.value,
      page: currentPage.value,
      pageSize: pageSize.value,
    })
    taskLogs.value = result.items
    totalLogs.value = result.total
    currentPage.value = result.page
    pageSize.value = result.page_size
  } catch {
    message.value = '运行状态加载失败，请确认后端服务是否正常。'
  } finally {
    loading.value = false
  }
}

async function loadOptions() {
  try {
    const options = await getTaskLogOptions()
    fundNavTaskTypes.value = options.fund_nav_task_types
    taskStatuses.value = options.task_statuses
  } catch {
    message.value = '枚举选项加载失败，请确认后端服务是否正常。'
  }
}

function applyQueryFilters() {
  selectedTaskType.value = typeof route.query.task_type === 'string' ? route.query.task_type : ''
  selectedStatus.value = typeof route.query.status === 'string' ? route.query.status : ''
  const queryPage = Number(route.query.page)
  currentPage.value = Number.isFinite(queryPage) && queryPage > 0 ? Math.floor(queryPage) : 1
}

async function applyFilters() {
  currentPage.value = 1
  await router.replace({ name: routeNames.operations, query: filterQuery() })
}

async function goToPage(page: number) {
  currentPage.value = Math.min(Math.max(1, page), totalPages.value)
  await router.replace({ name: routeNames.operations, query: filterQuery() })
}

function resetFilters() {
  selectedTaskType.value = ''
  selectedStatus.value = ''
  applyFilters()
}

function durationText(durationMs?: number | null) {
  return durationMs == null ? '-' : `${durationMs} ms`
}

function targetRoute(log: TaskLog) {
  if (log.target_type === 'fund' && log.target_id) {
    return { name: routeNames.fundDetail, params: { fundCode: log.target_id } }
  }
  return null
}

function showTextPopover(event: MouseEvent | FocusEvent, text?: string | null) {
  if (!text) return
  const element = event.currentTarget as HTMLElement
  const rect = element.getBoundingClientRect()
  const width = Math.min(720, window.innerWidth - 48)
  const pointerLeft = event instanceof MouseEvent ? event.clientX + 10 : rect.left
  const pointerTop = event instanceof MouseEvent ? event.clientY + 10 : rect.bottom + 6
  popover.value = {
    text,
    top: pointerTop,
    left: Math.min(Math.max(12, pointerLeft), window.innerWidth - width - 12),
    visible: true,
  }
}

function hideTextPopover() {
  popover.value.visible = false
}

onMounted(() => {
  applyQueryFilters()
  loadOptions()
  loadOperations()
})
watch(
  () => route.query,
  () => {
    applyQueryFilters()
    loadOperations()
  },
)
</script>

<template>
  <main class="page-shell">
    <RouterLink class="back-link" :to="{ name: routeNames.fundList }">返回基金池</RouterLink>
    <section class="detail-hero">
      <div>
        <p class="eyebrow">Operations</p>
        <h1>基金运行状态</h1>
        <p class="subtitle">查看基金净值、持仓、行情和估算相关任务日志。</p>
      </div>
      <button class="ghost" :disabled="loading" @click="loadOperations">
        {{ loading ? '刷新中...' : '刷新状态' }}
      </button>
    </section>

    <p v-if="message" class="message">{{ message }}</p>

    <section class="section-title">
      <div>
        <p class="eyebrow">Task Logs</p>
        <h2>任务日志</h2>
      </div>
      <span>第 {{ currentPage }} / {{ totalPages }} 页，共 {{ totalLogs }} 条</span>
    </section>

    <form class="filter-bar compact-filter" @submit.prevent="applyFilters">
      <label>
        任务类型
        <select v-model="selectedTaskType">
          <option value="">全部类型</option>
          <option v-for="taskType in fundNavTaskTypes" :key="taskType.value" :value="taskType.value">
            {{ taskType.label }}
          </option>
        </select>
      </label>
      <label>
        状态
        <select v-model="selectedStatus">
          <option value="">全部状态</option>
          <option v-for="status in taskStatuses" :key="status.value" :value="status.value">
            {{ status.label }}
          </option>
        </select>
      </label>
      <div class="filter-actions">
        <button class="ghost" type="submit" :disabled="loading">应用筛选</button>
        <button class="ghost" type="button" :disabled="loading || (!selectedTaskType && !selectedStatus)" @click="resetFilters">重置</button>
      </div>
    </form>

    <div class="table-card">
      <table class="operations-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>任务</th>
            <th>类型</th>
            <th>目标</th>
            <th>外部任务 ID</th>
            <th>状态</th>
            <th>开始时间</th>
            <th>耗时</th>
            <th>摘要</th>
            <th>错误信息</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="taskLogs.length === 0">
            <td colspan="10">暂无任务日志。</td>
          </tr>
          <tr v-for="log in taskLogs" :key="log.id">
            <td class="mono">{{ log.id }}</td>
            <td>{{ log.task_name }}</td>
            <td>
              <RouterLink :to="{ name: routeNames.operations, query: { ...filterQuery(), task_type: log.task_type } }">
                {{ taskTypeLabel(log.task_type) }}
              </RouterLink>
            </td>
            <td class="mono">
              <RouterLink v-if="targetRoute(log)" :to="targetRoute(log)!">
                {{ log.target_type }}:{{ log.target_id }}
              </RouterLink>
              <span v-else>{{ log.target_type && log.target_id ? `${log.target_type}:${log.target_id}` : '-' }}</span>
            </td>
            <td class="mono">{{ log.external_task_id ?? '-' }}</td>
            <td><span class="status-pill" :class="statusClass(log.status)">{{ log.status_label }}</span></td>
            <td>{{ formatDateTime(log.started_at) }}</td>
            <td>{{ durationText(log.duration_ms) }}</td>
            <td class="log-text-cell" @mouseenter="showTextPopover($event, log.message)" @mouseleave="hideTextPopover">
              <span class="log-text-preview">{{ log.message ?? '-' }}</span>
            </td>
            <td class="log-text-cell" @mouseenter="showTextPopover($event, log.error_message)" @mouseleave="hideTextPopover">
              <span class="log-text-preview">{{ log.error_message ?? '-' }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <nav class="pagination-bar" aria-label="任务日志分页">
      <button class="ghost" type="button" :disabled="loading || currentPage <= 1" @click="goToPage(currentPage - 1)">上一页</button>
      <span>第 {{ currentPage }} / {{ totalPages }} 页</span>
      <button class="ghost" type="button" :disabled="loading || currentPage >= totalPages" @click="goToPage(currentPage + 1)">下一页</button>
    </nav>
    <div
      v-if="popover.visible"
      class="log-text-popover"
      :style="{ top: `${popover.top}px`, left: `${popover.left}px` }"
      @mouseenter="popover.visible = true"
      @mouseleave="hideTextPopover"
    >
      {{ popover.text }}
    </div>
  </main>
</template>
