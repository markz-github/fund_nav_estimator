<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { apiErrorMessage } from '../../../api/client'
import {
  getHistorySyncStatus,
  startHistorySync,
  type HistorySyncMode,
  type HistorySyncStatus,
  type ProgressItem,
} from '../api/history'

const mode = ref<HistorySyncMode>('recent_days')
const recentDays = ref(10)
const startDate = ref(dateInputValue(offsetDate(-9)))
const endDate = ref(dateInputValue(new Date()))
const workers = ref(8)
const loading = ref(false)
const starting = ref(false)
const message = ref('')
const status = ref<HistorySyncStatus | null>(null)
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
    status.value = await getHistorySyncStatus()
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

function itemName(item: ProgressItem) {
  return item.stock_name ? `${item.symbol} ${item.stock_name}` : item.symbol
}

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
        <div v-else class="a-stock-date-grid">
          <label>
            开始日期
            <input v-model="startDate" type="date" />
          </label>
          <label>
            结束日期
            <input v-model="endDate" type="date" />
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
          <tr v-if="!status?.running_items.length">
            <td colspan="3">暂无正在处理的股票。</td>
          </tr>
          <tr v-for="item in status?.running_items" :key="item.symbol">
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
          <tr v-if="!status?.latest_done.length">
            <td colspan="3">暂无完成记录。</td>
          </tr>
          <tr v-for="item in status?.latest_done" :key="item.symbol">
            <td>{{ itemName(item) }}</td>
            <td>{{ formatDateTime(item.finished_at) }}</td>
            <td>{{ durationText(item.duration_seconds) }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <section v-if="status?.failed_items.length" class="section-title">
      <div>
        <p class="eyebrow">Failed</p>
        <h2>失败记录</h2>
      </div>
      <span>{{ failedCount }} 只</span>
    </section>
    <div v-if="status?.failed_items.length" class="table-card">
      <table class="a-stock-table">
        <thead>
          <tr>
            <th>股票</th>
            <th>完成时间</th>
            <th>错误</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in status.failed_items" :key="item.symbol">
            <td>{{ itemName(item) }}</td>
            <td>{{ formatDateTime(item.finished_at) }}</td>
            <td class="log-text-preview">{{ item.error ?? '-' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </main>
</template>
