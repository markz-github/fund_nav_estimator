<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { listErrors, listTaskLogs, type DataFetchError, type TaskLog } from '../api/operations'

const taskLogs = ref<TaskLog[]>([])
const errors = ref<DataFetchError[]>([])
const loading = ref(false)
const message = ref('')

async function loadOperations() {
  loading.value = true
  message.value = ''
  try {
    const [logsResult, errorsResult] = await Promise.all([listTaskLogs(), listErrors()])
    taskLogs.value = logsResult
    errors.value = errorsResult
  } catch (error) {
    message.value = '运行状态加载失败，请确认后端服务是否正常。'
  } finally {
    loading.value = false
  }
}

function statusClass(status: string) {
  if (status === 'success') return 'status-ok'
  if (status === 'failed') return 'status-danger'
  return 'status-warn'
}

onMounted(loadOperations)
</script>

<template>
  <main class="page-shell">
    <RouterLink class="back-link" to="/">返回基金池</RouterLink>

    <section class="detail-hero">
      <div>
        <p class="eyebrow">Operations</p>
        <h1>运行状态</h1>
        <p class="subtitle">查看定时任务执行日志和未处理的数据异常。</p>
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
      <span>{{ taskLogs.length }} 条</span>
    </section>

    <div class="table-card">
      <table>
        <thead>
          <tr>
            <th>任务</th>
            <th>类型</th>
            <th>状态</th>
            <th>开始时间</th>
            <th>耗时</th>
            <th>摘要</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="taskLogs.length === 0">
            <td colspan="6">暂无任务日志。</td>
          </tr>
          <tr v-for="log in taskLogs" :key="log.id">
            <td>{{ log.task_name }}</td>
            <td class="mono">{{ log.task_type }}</td>
            <td><span class="status-pill" :class="statusClass(log.status)">{{ log.status }}</span></td>
            <td>{{ log.started_at }}</td>
            <td>{{ log.duration_ms ?? '-' }} ms</td>
            <td>{{ log.message ?? '-' }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <section class="section-title spaced-title">
      <div>
        <p class="eyebrow">Data Errors</p>
        <h2>数据异常</h2>
      </div>
      <span>{{ errors.length }} 条</span>
    </section>

    <div class="table-card">
      <table>
        <thead>
          <tr>
            <th>来源</th>
            <th>类型</th>
            <th>目标代码</th>
            <th>发生时间</th>
            <th>错误信息</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="errors.length === 0">
            <td colspan="5">暂无未处理数据异常。</td>
          </tr>
          <tr v-for="error in errors" :key="error.id">
            <td>{{ error.source }}</td>
            <td class="mono">{{ error.data_type }}</td>
            <td class="mono">{{ error.target_code }}</td>
            <td>{{ error.occurred_at }}</td>
            <td>{{ error.error_message }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </main>
</template>
