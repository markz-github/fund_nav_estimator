<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { listErrors, listTaskLogs, type DataFetchError, type OperationModule, type TaskLog } from '../api/operations'
import { statusClass } from '../utils/status'

const route = useRoute()
const router = useRouter()
const taskLogs = ref<TaskLog[]>([])
const errors = ref<DataFetchError[]>([])
const loading = ref(false)
const message = ref('')
const selectedTaskType = ref('')

const taskTypeOptions = {
  fund_nav: [
    'refresh_nav',
    'refresh_profile',
    'refresh_holding',
    'refresh_quote',
    'estimate_nav',
  ],
  information: [
    'scan_information_videos',
    'generate_information_video_notes',
    'submit_information_video_note_task',
    'poll_information_video_notes',
    'generate_information_summary_documents',
    'generate_information_custom_summary',
    'retry_information_summary_document',
    'push_information_summary_documents',
  ],
}

const operationModule = computed<OperationModule>(() =>
  route.path.startsWith('/fund-nav') ? 'fund_nav' : 'information',
)
const pageTitle = computed(() => (operationModule.value === 'fund_nav' ? '基金运行状态' : '信息流运行状态'))
const pageSubtitle = computed(() =>
  operationModule.value === 'fund_nav'
    ? '查看基金净值、持仓、行情和估算相关任务日志与未处理异常。'
    : '查看信息流扫描、信息源笔记和笔记汇总相关任务日志与未处理异常。',
)
const currentTaskTypes = computed(() => taskTypeOptions[operationModule.value])

async function loadOperations() {
  loading.value = true
  message.value = ''
  try {
    const [logsResult, errorsResult] = await Promise.all([
      listTaskLogs(operationModule.value, selectedTaskType.value),
      listErrors(operationModule.value),
    ])
    taskLogs.value = logsResult
    errors.value = errorsResult
  } catch (error) {
    message.value = '运行状态加载失败，请确认后端服务是否正常。'
  } finally {
    loading.value = false
  }
}

function applyQueryFilters() {
  selectedTaskType.value = typeof route.query.task_type === 'string' ? route.query.task_type : ''
}

async function applyTaskTypeFilter() {
  await router.replace({
    name: operationModule.value === 'fund_nav' ? 'fund-nav-operations' : 'information-operations',
    query: selectedTaskType.value ? { task_type: selectedTaskType.value } : undefined,
  })
  await loadOperations()
}

function resetTaskType() {
  selectedTaskType.value = ''
  applyTaskTypeFilter()
}

function durationText(durationMs?: number | null) {
  return durationMs == null ? '-' : `${durationMs} ms`
}

function targetRoute(log: TaskLog) {
  if (operationModule.value !== 'information' || !log.target_type || !log.target_id) return null
  if (log.target_type === 'video' && /^\d+$/.test(log.target_id)) {
    return { name: 'information-videos', query: { video_id: log.target_id } }
  }
  return null
}

onMounted(() => {
  applyQueryFilters()
  loadOperations()
})
watch(operationModule, () => {
  selectedTaskType.value = ''
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
    <section class="detail-hero">
      <div>
        <p class="eyebrow">Operations</p>
        <h1>{{ pageTitle }}</h1>
        <p class="subtitle">{{ pageSubtitle }}</p>
      </div>
      <div class="section-actions">
        <button class="ghost" :disabled="loading" @click="loadOperations">
          {{ loading ? '刷新中...' : '刷新状态' }}
        </button>
      </div>
    </section>

    <p v-if="message" class="message">{{ message }}</p>

    <section class="section-title">
      <div>
        <p class="eyebrow">Task Logs</p>
        <h2>任务日志</h2>
      </div>
      <span>{{ taskLogs.length }} 条</span>
    </section>

    <form class="filter-bar compact-filter" @submit.prevent="applyTaskTypeFilter">
      <label>
        任务类型
        <select v-model="selectedTaskType">
          <option value="">全部类型</option>
          <option v-for="taskType in currentTaskTypes" :key="taskType" :value="taskType">
            {{ taskType }}
          </option>
        </select>
      </label>
      <div class="filter-actions">
        <button class="ghost" type="submit" :disabled="loading">应用筛选</button>
        <button class="ghost" type="button" :disabled="loading || !selectedTaskType" @click="resetTaskType">重置</button>
      </div>
    </form>

    <div class="table-card">
      <table class="info-table operations-table">
        <colgroup>
          <col class="col-id" />
          <col class="col-task-name" />
          <col class="col-task-type" />
          <col class="col-target" />
          <col class="col-task" />
          <col class="col-status" />
          <col class="col-time" />
          <col class="col-duration" />
          <col class="col-message" />
          <col class="col-message" />
        </colgroup>
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
            <td class="mono">
              <RouterLink
                :to="{
                  name: operationModule === 'fund_nav' ? 'fund-nav-operations' : 'information-operations',
                  query: { task_type: log.task_type },
                }"
              >
                {{ log.task_type }}
              </RouterLink>
            </td>
            <td class="mono">
              <RouterLink v-if="targetRoute(log)" :to="targetRoute(log)!">
                {{ log.target_type && log.target_id ? `${log.target_type}:${log.target_id}` : '-' }}
              </RouterLink>
              <span v-else>{{ log.target_type && log.target_id ? `${log.target_type}:${log.target_id}` : '-' }}</span>
            </td>
            <td class="mono">{{ log.external_task_id ?? '-' }}</td>
            <td><span class="status-pill" :class="statusClass(log.status)">{{ log.status }}</span></td>
            <td>{{ log.started_at }}</td>
            <td>{{ durationText(log.duration_ms) }}</td>
            <td>{{ log.message ?? '-' }}</td>
            <td>{{ log.error_message ?? '-' }}</td>
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
      <table class="info-table errors-table">
        <colgroup>
          <col class="col-id" />
          <col class="col-source" />
          <col class="col-task-type" />
          <col class="col-target" />
          <col class="col-time" />
          <col class="col-message" />
        </colgroup>
        <thead>
          <tr>
            <th>ID</th>
            <th>来源</th>
            <th>类型</th>
            <th>目标代码</th>
            <th>发生时间</th>
            <th>错误信息</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="errors.length === 0">
            <td colspan="6">暂无未处理数据异常。</td>
          </tr>
          <tr v-for="error in errors" :key="error.id">
            <td class="mono">{{ error.id }}</td>
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
