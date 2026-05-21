<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { listErrors, listTaskLogs, type DataFetchError, type OperationModule, type TaskLog } from '../api/operations'
import { getInformationStatusOptions, type StatusOption } from '../api/videos'
import { statusClass } from '../utils/status'

const route = useRoute()
const router = useRouter()
const taskLogs = ref<TaskLog[]>([])
const errors = ref<DataFetchError[]>([])
const loading = ref(false)
const message = ref('')
const selectedTaskType = ref('')
const selectedStatus = ref('')
const fundNavTaskTypes = ref<StatusOption[]>([])
const informationTaskTypes = ref<StatusOption[]>([])
const taskStatuses = ref<StatusOption[]>([])

const operationModule = computed<OperationModule>(() =>
  route.path.startsWith('/fund-nav') ? 'fund_nav' : 'information',
)
const pageTitle = computed(() => (operationModule.value === 'fund_nav' ? '基金运行状态' : '信息流运行状态'))
const pageSubtitle = computed(() =>
  operationModule.value === 'fund_nav'
    ? '查看基金净值、持仓、行情和估算相关任务日志与未处理异常。'
    : '查看信息流扫描、信息源笔记和笔记汇总相关任务日志与未处理异常。',
)
const currentTaskTypes = computed(() =>
  operationModule.value === 'fund_nav' ? fundNavTaskTypes.value : informationTaskTypes.value,
)

function taskTypeLabel(taskType: string) {
  return currentTaskTypes.value.find((option) => option.value === taskType)?.label ?? taskType
}

function filterQuery() {
  return {
    ...(selectedTaskType.value ? { task_type: selectedTaskType.value } : {}),
    ...(selectedStatus.value ? { status: selectedStatus.value } : {}),
  }
}

async function loadOperations() {
  loading.value = true
  message.value = ''
  try {
    const [logsResult, errorsResult] = await Promise.all([
      listTaskLogs(operationModule.value, {
        taskType: selectedTaskType.value,
        status: selectedStatus.value,
      }),
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

async function loadOptions() {
  try {
    const options = await getInformationStatusOptions()
    fundNavTaskTypes.value = options.fund_nav_task_types
    informationTaskTypes.value = options.information_task_types
    taskStatuses.value = options.task_statuses
  } catch {
    message.value = '枚举选项加载失败，请确认后端服务是否正常。'
  }
}

function applyQueryFilters() {
  selectedTaskType.value = typeof route.query.task_type === 'string' ? route.query.task_type : ''
  selectedStatus.value = typeof route.query.status === 'string' ? route.query.status : ''
}

async function applyFilters() {
  await router.replace({
    name: operationModule.value === 'fund_nav' ? 'fund-nav-operations' : 'information-operations',
    query: filterQuery(),
  })
  await loadOperations()
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
  if (operationModule.value !== 'information' || !log.target_type || !log.target_id) return null
  if (log.target_type === 'video' && /^\d+$/.test(log.target_id)) {
    return { name: 'information-videos', query: { video_id: log.target_id } }
  }
  return null
}

onMounted(() => {
  applyQueryFilters()
  loadOptions()
  loadOperations()
})
watch(operationModule, () => {
  selectedTaskType.value = ''
  selectedStatus.value = ''
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

    <form class="filter-bar compact-filter" @submit.prevent="applyFilters">
      <label>
        任务类型
        <select v-model="selectedTaskType">
          <option value="">全部类型</option>
          <option v-for="taskType in currentTaskTypes" :key="taskType.value" :value="taskType.value">
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
                  query: { ...filterQuery(), task_type: log.task_type },
                }"
              >
                {{ taskTypeLabel(log.task_type) }}
              </RouterLink>
            </td>
            <td class="mono">
              <RouterLink v-if="targetRoute(log)" :to="targetRoute(log)!">
                {{ log.target_type && log.target_id ? `${log.target_type}:${log.target_id}` : '-' }}
              </RouterLink>
              <span v-else>{{ log.target_type && log.target_id ? `${log.target_type}:${log.target_id}` : '-' }}</span>
            </td>
            <td class="mono">{{ log.external_task_id ?? '-' }}</td>
            <td><span class="status-pill" :class="statusClass(log.status)">{{ log.status_label }}</span></td>
            <td>{{ log.started_at }}</td>
            <td>{{ durationText(log.duration_ms) }}</td>
            <td class="log-text-cell">
              <span class="log-text-preview">{{ log.message ?? '-' }}</span>
              <span v-if="log.message" class="log-text-popover" tabindex="0">{{ log.message }}</span>
            </td>
            <td class="log-text-cell">
              <span class="log-text-preview">{{ log.error_message ?? '-' }}</span>
              <span v-if="log.error_message" class="log-text-popover" tabindex="0">{{ log.error_message }}</span>
            </td>
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
            <td class="log-text-cell">
              <span class="log-text-preview">{{ error.error_message }}</span>
              <span class="log-text-popover" tabindex="0">{{ error.error_message }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </main>
</template>
