<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { apiErrorMessage } from '../../../api/client'
import {
  getHistorySyncStatus,
  listHistorySyncTasks,
  rerunHistorySyncTask,
  startHistorySync,
  stopHistorySync,
  type HistorySyncTask,
  type HistorySyncMode,
  type HistorySyncStatus,
} from '../api/history'
import { routeNames } from '../../../router/routeNames'

const mode = ref<HistorySyncMode>('recent_days')
const recentDays = ref(10)
const startDate = ref(dateInputValue(offsetDate(-9)))
const endDate = ref(dateInputValue(new Date()))
const workers = ref(8)
const loading = ref(false)
const starting = ref(false)
const stopping = ref(false)
const message = ref('')
const status = ref<HistorySyncStatus | null>(null)
const tasks = ref<HistorySyncTask[]>([])
const rerunningTaskId = ref<number | null>(null)
let refreshTimer: number | undefined
const doneCount = computed(() => countByStatus('done'))
const runningCount = computed(() => countByStatus('running'))
const failedCount = computed(() => countByStatus('failed'))
const totalTracked = computed(() => doneCount.value + runningCount.value + failedCount.value)

function offsetDate(days: number) {
  const value = new Date()
  value.setDate(value.getDate() + days)
  return value
}

function dateInputValue(value: Date) {
  return value.toISOString().slice(0, 10)
}

function syncRecentDateRange() {
  if (mode.value !== 'recent_days') return
  const days = Math.min(3650, Math.max(1, Math.floor(Number(recentDays.value) || 1)))
  if (recentDays.value !== days) {
    recentDays.value = days
  }
  startDate.value = dateInputValue(offsetDate(-(days - 1)))
  endDate.value = dateInputValue(new Date())
}

function countByStatus(targetStatus: string) {
  return status.value?.counts.find((item) => item.status === targetStatus)?.count ?? 0
}

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

function durationText(value?: number | null) {
  if (value == null) return '-'
  if (value < 60) return `${value.toFixed(1)} 秒`
  return `${(value / 60).toFixed(1)} 分钟`
}

async function refreshStatus() {
  loading.value = true
  try {
    const [nextStatus, nextTasks] = await Promise.all([getHistorySyncStatus(), listHistorySyncTasks()])
    status.value = nextStatus
    tasks.value = nextTasks
    updateAutoRefresh()
  } catch (error) {
    message.value = apiErrorMessage(error, 'A 股行情同步状态加载失败，请确认后端服务。')
  } finally {
    loading.value = false
  }
}

function updateAutoRefresh() {
  if (refreshTimer !== undefined) {
    window.clearInterval(refreshTimer)
    refreshTimer = undefined
  }
  if (!status.value?.running) return
  refreshTimer = window.setInterval(() => {
    refreshStatus()
  }, 10000)
}

async function submitSync() {
  starting.value = true
  message.value = ''
  try {
    const result = await startHistorySync({
      mode: mode.value,
      recent_days: mode.value === 'recent_days' ? recentDays.value : null,
      start_date: mode.value === 'date_range' ? startDate.value : null,
      end_date: mode.value === 'date_range' ? endDate.value : null,
      workers: workers.value,
    })
    message.value = result.message
    await refreshStatus()
  } catch (error) {
    message.value = apiErrorMessage(error, 'A 股历史行情同步任务启动失败。')
  } finally {
    starting.value = false
  }
}

async function stopSync() {
  stopping.value = true
  message.value = ''
  try {
    const result = await stopHistorySync()
    message.value = result.message
    await refreshStatus()
  } catch (error) {
    message.value = apiErrorMessage(error, 'A 股历史行情同步任务停止失败。')
  } finally {
    stopping.value = false
  }
}

async function rerunTask(task: HistorySyncTask) {
  rerunningTaskId.value = task.id
  message.value = ''
  try {
    const result = await rerunHistorySyncTask(task.id)
    message.value = result.message
    await refreshStatus()
  } catch (error) {
    message.value = apiErrorMessage(error, '任务重跑提交失败。')
  } finally {
    rerunningTaskId.value = null
  }
}

function statusText(value: string) {
  const map: Record<string, string> = {
    pending: '等待中',
    running: '运行中',
    success: '成功',
    partial: '部分完成',
    failed: '失败',
    skipped: '已跳过',
    stopped: '已停止',
  }
  return map[value] ?? value
}

watch([mode, recentDays], syncRecentDateRange, { immediate: true })

onMounted(refreshStatus)
onUnmounted(() => {
  if (refreshTimer !== undefined) {
    window.clearInterval(refreshTimer)
  }
})
</script>

<template>
  <main class="page-shell">
    <section class="detail-hero">
      <div>
        <p class="eyebrow">A-Share Market Data</p>
        <h1>A 股历史行情同步</h1>
        <p class="subtitle">在服务器上启动和观察 A 股日 K 历史行情更新任务。</p>
      </div>
      <button class="ghost" :disabled="loading" @click="refreshStatus">
        {{ loading ? '刷新中...' : '刷新状态' }}
      </button>
      <button class="danger" :disabled="stopping || !status?.running" @click="stopSync">
        {{ stopping ? '停止中...' : '停止任务' }}
      </button>
    </section>

    <p v-if="message" class="message">{{ message }}</p>

    <section class="a-stock-sync-layout">
      <form class="add-card a-stock-sync-form" @submit.prevent="submitSync">
        <div>
          <p class="eyebrow">Run Task</p>
          <h2>启动更新</h2>
        </div>
        <label>
          更新范围
          <select v-model="mode">
            <option value="recent_days">最近 N 天</option>
            <option value="date_range">指定日期区间</option>
          </select>
        </label>
        <label v-if="mode === 'recent_days'">
          最近天数
          <input v-model.number="recentDays" type="number" min="1" max="3650" />
        </label>
        <div class="a-stock-date-grid">
          <label>
            {{ mode === 'recent_days' ? '开始日期（自动）' : '开始日期' }}
            <input v-model="startDate" type="date" :disabled="mode === 'recent_days'" />
          </label>
          <label>
            {{ mode === 'recent_days' ? '结束日期（自动）' : '结束日期' }}
            <input v-model="endDate" type="date" :disabled="mode === 'recent_days'" />
          </label>
        </div>
        <label>
          线程数
          <input v-model.number="workers" type="number" min="1" max="16" />
        </label>
        <button type="submit" :disabled="starting || status?.running">
          {{ starting ? '提交中...' : status?.running ? '任务运行中' : '启动同步' }}
        </button>
      </form>

      <section class="add-card a-stock-status-card">
        <div>
          <p class="eyebrow">Progress</p>
          <h2>当前状态</h2>
        </div>
        <dl class="a-stock-stat-grid">
          <div>
            <dt>进程</dt>
            <dd>{{ status?.running ? `运行中 PID ${status.pid}` : '未运行' }}</dd>
          </div>
          <div>
            <dt>日期范围</dt>
            <dd>{{ status?.start_date ?? '-' }} - {{ status?.end_date ?? '-' }}</dd>
          </div>
          <div>
            <dt>已完成</dt>
            <dd>{{ doneCount }}</dd>
          </div>
          <div>
            <dt>执行中</dt>
            <dd>{{ runningCount }}</dd>
          </div>
          <div>
            <dt>失败</dt>
            <dd>{{ failedCount }}</dd>
          </div>
          <div>
            <dt>已跟踪</dt>
            <dd>{{ totalTracked }}</dd>
          </div>
        </dl>
        <p class="muted">日志：{{ status?.stdout_log ?? '-' }}</p>
      </section>
    </section>

    <section class="section-title">
      <div>
        <p class="eyebrow">Tasks</p>
        <h2>同步任务</h2>
      </div>
      <span>{{ tasks.length }} 条</span>
    </section>
    <div class="table-card">
      <table class="a-stock-table">
        <thead>
          <tr>
            <th>任务</th>
            <th>状态</th>
            <th>日期范围</th>
            <th>成功</th>
            <th>失败</th>
            <th>执行中</th>
            <th>开始时间</th>
            <th>耗时</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!tasks.length">
            <td colspan="9">暂无同步任务。</td>
          </tr>
          <tr v-for="task in tasks" :key="task.id">
            <td>#{{ task.id }}</td>
            <td>{{ statusText(task.status) }}</td>
            <td>{{ task.start_date }} - {{ task.end_date }}</td>
            <td>{{ task.success_count }}</td>
            <td>{{ task.failed_count }}</td>
            <td>{{ task.running_count }}</td>
            <td>{{ formatDateTime(task.started_at) }}</td>
            <td>{{ durationText(task.duration_seconds) }}</td>
            <td>
              <div class="quick-actions">
                <RouterLink
                  class="link-button"
                  :to="{ name: routeNames.aStockHistoryTask, params: { taskId: task.id } }"
                >
                  详情
                </RouterLink>
                <button
                  type="button"
                  :disabled="status?.running || rerunningTaskId === task.id"
                  @click="rerunTask(task)"
                >
                  {{ rerunningTaskId === task.id ? '提交中...' : '重跑任务' }}
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </main>
</template>
