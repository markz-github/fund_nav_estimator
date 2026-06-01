<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { formatDateTime } from '../../../utils/datetime'
import { listTaskLogs, type TaskLog } from '../api/operations'
import { statusClass } from '../utils/status'

const router = useRouter()
const taskLogs = ref<TaskLog[]>([])
const totalLogs = ref(0)
const currentPage = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const message = ref('')
const selectedTaskType = ref('')
const selectedStatus = ref('')
const totalPages = computed(() => Math.max(1, Math.ceil(totalLogs.value / pageSize.value)))
const taskTypes = [
  { value: 'refresh_nav', label: '刷新基金官方净值' },
  { value: 'refresh_profile', label: '刷新基金名称和类型' },
  { value: 'refresh_holding', label: '刷新基金持仓' },
  { value: 'refresh_quote', label: '刷新持仓资产行情' },
  { value: 'estimate_nav', label: '估算基金当日净值' },
]
const taskStatuses = [
  { value: 'running', label: '运行中' },
  { value: 'success', label: '成功' },
  { value: 'partial', label: '部分成功' },
  { value: 'failed', label: '失败' },
  { value: 'skipped', label: '跳过' },
]

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
    const result = await listTaskLogs({
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

async function applyFilters() {
  currentPage.value = 1
  await router.replace({ name: 'fund-nav-operations', query: filterQuery() })
  await loadOperations()
}

async function goToPage(page: number) {
  currentPage.value = Math.min(Math.max(1, page), totalPages.value)
  await router.replace({ name: 'fund-nav-operations', query: filterQuery() })
  await loadOperations()
}

function resetFilters() {
  selectedTaskType.value = ''
  selectedStatus.value = ''
  applyFilters()
}

function taskTypeLabel(taskType: string) {
  return taskTypes.find((option) => option.value === taskType)?.label ?? taskType
}

onMounted(loadOperations)
</script>

<template>
  <main class="page-shell">
    <section class="detail-hero">
      <div>
        <p class="eyebrow">Operations</p>
        <h1>基金运行状态</h1>
        <p class="subtitle">查看基金净值、持仓、行情和估算相关任务日志。</p>
      </div>
      <button class="ghost" :disabled="loading" @click="loadOperations">{{ loading ? '刷新中...' : '刷新状态' }}</button>
    </section>
    <p v-if="message" class="message">{{ message }}</p>
    <form class="filter-bar compact-filter" @submit.prevent="applyFilters">
      <label>任务类型
        <select v-model="selectedTaskType">
          <option value="">全部类型</option>
          <option v-for="option in taskTypes" :key="option.value" :value="option.value">{{ option.label }}</option>
        </select>
      </label>
      <label>状态
        <select v-model="selectedStatus">
          <option value="">全部状态</option>
          <option v-for="option in taskStatuses" :key="option.value" :value="option.value">{{ option.label }}</option>
        </select>
      </label>
      <div class="filter-actions">
        <button class="ghost" type="submit" :disabled="loading">应用筛选</button>
        <button class="ghost" type="button" :disabled="loading || (!selectedTaskType && !selectedStatus)" @click="resetFilters">重置</button>
      </div>
    </form>
    <div class="table-card">
      <table class="operations-table">
        <thead><tr><th>ID</th><th>任务</th><th>类型</th><th>状态</th><th>开始时间</th><th>耗时</th><th>摘要</th></tr></thead>
        <tbody>
          <tr v-if="taskLogs.length === 0"><td colspan="7">暂无任务日志。</td></tr>
          <tr v-for="log in taskLogs" :key="log.id">
            <td class="mono">{{ log.id }}</td>
            <td>{{ log.task_name }}</td>
            <td><RouterLink :to="{ name: 'fund-nav-operations', query: { ...filterQuery(), task_type: log.task_type } }">{{ taskTypeLabel(log.task_type) }}</RouterLink></td>
            <td><span class="status-pill" :class="statusClass(log.status)">{{ log.status_label }}</span></td>
            <td>{{ formatDateTime(log.started_at) }}</td>
            <td>{{ log.duration_ms == null ? '-' : `${log.duration_ms} ms` }}</td>
            <td>{{ log.message ?? '-' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <nav class="pagination-bar" aria-label="任务日志分页">
      <button class="ghost" type="button" :disabled="loading || currentPage <= 1" @click="goToPage(currentPage - 1)">上一页</button>
      <span>第 {{ currentPage }} / {{ totalPages }} 页，共 {{ totalLogs }} 条</span>
      <button class="ghost" type="button" :disabled="loading || currentPage >= totalPages" @click="goToPage(currentPage + 1)">下一页</button>
    </nav>
  </main>
</template>
