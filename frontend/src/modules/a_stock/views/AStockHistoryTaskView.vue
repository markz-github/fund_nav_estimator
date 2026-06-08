<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiErrorMessage } from '../../../api/client'
import { routeNames } from '../../../router/routeNames'
import {
  getHistorySyncTask,
  getHistorySyncStatus,
  rerunHistorySyncTask,
  stopHistorySync,
  type HistorySyncTaskDetail,
  type ProgressItem,
} from '../api/history'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const rerunning = ref(false)
const stopping = ref(false)
const message = ref('')
const task = ref<HistorySyncTaskDetail | null>(null)
const syncRunning = ref(false)
let refreshTimer: number | undefined

const taskId = computed(() => Number(route.params.taskId))
const doneCount = computed(() => countByStatus('done'))
const runningCount = computed(() => countByStatus('running'))
const failedCount = computed(() => countByStatus('failed'))

function countByStatus(targetStatus: string) {
  return task.value?.counts.find((item) => item.status === targetStatus)?.count ?? 0
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

function statusText(value?: string | null) {
  const map: Record<string, string> = {
    pending: '等待中',
    running: '运行中',
    success: '成功',
    partial: '部分完成',
    failed: '失败',
    skipped: '已跳过',
    stopped: '已停止',
  }
  return value ? map[value] ?? value : '-'
}

function itemName(item: ProgressItem) {
  return item.stock_name ? `${item.symbol} ${item.stock_name}` : item.symbol
}

async function refreshTask() {
  loading.value = true
  try {
    const [nextTask, nextStatus] = await Promise.all([getHistorySyncTask(taskId.value), getHistorySyncStatus()])
    task.value = nextTask
    syncRunning.value = nextStatus.running
    updateAutoRefresh()
  } catch (error) {
    message.value = apiErrorMessage(error, '任务详情加载失败。')
  } finally {
    loading.value = false
  }
}

function updateAutoRefresh() {
  if (refreshTimer !== undefined) {
    window.clearInterval(refreshTimer)
    refreshTimer = undefined
  }
  if (task.value?.status !== 'running' && !syncRunning.value) return
  refreshTimer = window.setInterval(() => {
    refreshTask()
  }, 10000)
}

async function rerunTask() {
  if (!task.value) return
  if (syncRunning.value) return
  rerunning.value = true
  message.value = ''
  try {
    const result = await rerunHistorySyncTask(task.value.id)
    message.value = result.message
    if (result.task_id) {
      await router.push({ name: routeNames.aStockHistoryTask, params: { taskId: result.task_id } })
    } else {
      await refreshTask()
    }
  } catch (error) {
    message.value = apiErrorMessage(error, '任务重跑提交失败。')
  } finally {
    rerunning.value = false
  }
}

async function stopSync() {
  if (!syncRunning.value) return
  stopping.value = true
  message.value = ''
  try {
    const result = await stopHistorySync()
    message.value = result.message
    await refreshTask()
  } catch (error) {
    message.value = apiErrorMessage(error, 'A 股历史行情同步任务停止失败。')
  } finally {
    stopping.value = false
  }
}

onMounted(refreshTask)
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
        <p class="eyebrow">A-Share Task</p>
        <h1>同步任务详情</h1>
        <p class="subtitle">查看单次 A 股历史行情同步任务的处理明细。</p>
      </div>
      <div class="quick-actions">
        <button class="ghost" type="button" @click="router.push({ name: routeNames.aStockHistory })">返回列表</button>
        <button class="ghost" :disabled="loading" type="button" @click="refreshTask">
          {{ loading ? '刷新中...' : '刷新' }}
        </button>
        <button class="danger" type="button" :disabled="stopping || !syncRunning" @click="stopSync">
          {{ stopping ? '停止中...' : '停止任务' }}
        </button>
        <button type="button" :disabled="rerunning || syncRunning" @click="rerunTask">
          {{ rerunning ? '提交中...' : syncRunning ? '任务运行中' : '重跑任务' }}
        </button>
      </div>
    </section>

    <p v-if="message" class="message">{{ message }}</p>

    <section class="add-card a-stock-status-card">
      <div>
        <p class="eyebrow">Summary</p>
        <h2>任务 #{{ task?.id ?? taskId }}</h2>
      </div>
      <dl class="a-stock-stat-grid">
        <div>
          <dt>状态</dt>
          <dd>{{ statusText(task?.status) }}</dd>
        </div>
        <div>
          <dt>日期范围</dt>
          <dd>{{ task?.start_date ?? '-' }} - {{ task?.end_date ?? '-' }}</dd>
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
          <dt>耗时</dt>
          <dd>{{ durationText(task?.duration_seconds) }}</dd>
        </div>
      </dl>
      <p class="muted">日志：{{ task?.stdout_log ?? '-' }}</p>
      <p class="muted">摘要：{{ task?.message ?? '-' }}</p>
    </section>

    <section class="section-title">
      <div>
        <p class="eyebrow">Running</p>
        <h2>正在处理</h2>
      </div>
      <span>{{ runningCount }} 只</span>
    </section>
    <div class="table-card">
      <table class="a-stock-table">
        <thead>
          <tr>
            <th>股票</th>
            <th>开始时间</th>
            <th>耗时</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!task?.running_items.length">
            <td colspan="3">暂无正在处理的股票。</td>
          </tr>
          <tr v-for="item in task?.running_items" :key="item.symbol">
            <td>{{ itemName(item) }}</td>
            <td>{{ formatDateTime(item.started_at) }}</td>
            <td>{{ durationText(item.duration_seconds) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <section class="section-title">
      <div>
        <p class="eyebrow">Latest Done</p>
        <h2>最近完成</h2>
      </div>
      <span>{{ doneCount }} 只已完成</span>
    </section>
    <div class="table-card">
      <table class="a-stock-table">
        <thead>
          <tr>
            <th>股票</th>
            <th>完成时间</th>
            <th>耗时</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!task?.latest_done.length">
            <td colspan="3">暂无完成记录。</td>
          </tr>
          <tr v-for="item in task?.latest_done" :key="item.symbol">
            <td>{{ itemName(item) }}</td>
            <td>{{ formatDateTime(item.finished_at) }}</td>
            <td>{{ durationText(item.duration_seconds) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <section v-if="task?.failed_items.length" class="section-title">
      <div>
        <p class="eyebrow">Failed</p>
        <h2>失败记录</h2>
      </div>
      <span>{{ failedCount }} 只</span>
    </section>
    <div v-if="task?.failed_items.length" class="table-card">
      <table class="a-stock-table">
        <thead>
          <tr>
            <th>股票</th>
            <th>完成时间</th>
            <th>错误</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in task.failed_items" :key="item.symbol">
            <td>{{ itemName(item) }}</td>
            <td>{{ formatDateTime(item.finished_at) }}</td>
            <td class="log-text-preview">{{ item.error ?? '-' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </main>
</template>
