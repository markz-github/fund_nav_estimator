<script setup lang="ts">
import { onMounted, ref } from 'vue'
import FundTable from '../components/FundTable.vue'
import { apiErrorMessage, isRequestTimeout } from '../../../api/client'
import { routeNames } from '../../../router/routeNames'
import { refreshQuotesAndRunEstimates } from '../api/estimates'
import { listTaskLogs, type TaskLog } from '../operations/api/operations'
import {
  createFund,
  deleteFund,
  listFunds,
  refreshFundNav,
  refreshFundNavs,
  type Fund,
  type FundSortBy,
  type SortOrder,
} from '../api/funds'

const SORT_STORAGE_KEY = 'fund-list-sort'

const funds = ref<Fund[]>([])
const selectedFundCodes = ref<string[]>([])
const fundCode = ref('')
const remark = ref('')
const loading = ref(false)
const saving = ref(false)
const estimating = ref(false)
const refreshingNavs = ref(false)
const message = ref('')
const pendingDeleteFund = ref<Fund | null>(null)
const batchActionsOpen = ref(false)
const addFundOpen = ref(false)
const initialSort = readSavedSort()
const sortBy = ref<FundSortBy | null>(initialSort.sortBy)
const sortOrder = ref<SortOrder>(initialSort.sortOrder)

function readSavedSort(): { sortBy: FundSortBy | null; sortOrder: SortOrder } {
  try {
    const rawValue = window.localStorage.getItem(SORT_STORAGE_KEY)
    if (!rawValue) return { sortBy: null, sortOrder: 'desc' }
    const parsed = JSON.parse(rawValue) as { sortBy?: string | null; sortOrder?: string }
    return {
      sortBy: parsed.sortBy === 'latest_estimated_growth_rate' ? parsed.sortBy : null,
      sortOrder: parsed.sortOrder === 'asc' ? 'asc' : 'desc',
    }
  } catch {
    return { sortBy: null, sortOrder: 'desc' }
  }
}

function saveSort() {
  window.localStorage.setItem(
    SORT_STORAGE_KEY,
    JSON.stringify({
      sortBy: sortBy.value,
      sortOrder: sortOrder.value,
    }),
  )
}

async function loadFunds(options?: { keepMessage?: boolean }) {
  loading.value = true
  if (!options?.keepMessage) message.value = ''
  try {
    funds.value = await listFunds({ sortBy: sortBy.value, sortOrder: sortOrder.value })
    const existingCodes = new Set(funds.value.map((fund) => fund.fund_code))
    selectedFundCodes.value = selectedFundCodes.value.filter((code) => existingCodes.has(code))
  } catch (error) {
    message.value = apiErrorMessage(error, '基金列表加载失败，请确认后端服务和 MySQL 配置。')
  } finally {
    loading.value = false
  }
}

async function updateSort(nextSortBy: FundSortBy) {
  if (sortBy.value === nextSortBy) {
    sortOrder.value = sortOrder.value === 'desc' ? 'asc' : 'desc'
  } else {
    sortBy.value = nextSortBy
    sortOrder.value = 'desc'
  }
  saveSort()
  await loadFunds()
}

async function submitFund() {
  if (!fundCode.value.trim()) return
  saving.value = true
  try {
    await createFund(fundCode.value.trim(), remark.value.trim() || undefined)
    message.value = '基金已添加，净值和持仓正在后台同步。'
    fundCode.value = ''
    remark.value = ''
    await loadFunds({ keepMessage: true })
  } catch (error) {
    if (isRequestTimeout(error)) {
      await loadFunds({ keepMessage: true })
      message.value = '新增基金请求超时，已刷新列表；如果基金稍后出现，说明后台已完成写入。'
    } else {
      message.value = apiErrorMessage(error, '新增基金失败，请检查基金代码或后端日志。')
    }
  } finally {
    saving.value = false
  }
}

async function removeFund(code: string) {
  const fund = funds.value.find((item) => item.fund_code === code)
  pendingDeleteFund.value = fund ?? {
    id: 0,
    fund_code: code,
    fund_name: code,
    enabled: 1,
  }
}

async function confirmDeleteFund() {
  if (!pendingDeleteFund.value) return
  const code = pendingDeleteFund.value.fund_code
  try {
    await deleteFund(code)
    pendingDeleteFund.value = null
    await loadFunds()
  } catch (error) {
    message.value = apiErrorMessage(error, '删除基金失败，请稍后重试。')
  }
}

async function refreshNav(code: string) {
  try {
    const result = await refreshFundNav(code)
    message.value = taskSubmitMessage(result)
    const task = await waitForTaskLog(result.task_log_id)
    if (task) {
      message.value = task.status === 'success'
        ? `任务 ${result.task_id} 已完成，列表已更新。`
        : `任务 ${result.task_id} ${task.status_label}，列表已更新。`
      await loadFunds({ keepMessage: true })
    }
  } catch (error) {
    message.value = apiErrorMessage(error, '官方净值刷新失败，请查看运行状态。')
  }
}

async function refreshSelectedNavs() {
  refreshingNavs.value = true
  const targetCodes =
    selectedFundCodes.value.length > 0
      ? selectedFundCodes.value
      : funds.value.map((fund) => fund.fund_code)
  message.value = `正在提交 ${targetCodes.length} 只基金的官方净值更新任务...`
  try {
    const result = await refreshFundNavs(targetCodes)
    message.value = taskSubmitMessage(result)
    const task = await waitForTaskLog(result.task_log_id, 90)
    if (task) {
      message.value = task.status === 'success'
        ? `任务 ${result.task_id} 已完成，列表已更新。`
        : `任务 ${result.task_id} ${task.status_label}，列表已更新。`
      await loadFunds({ keepMessage: true })
    }
  } catch (error) {
    message.value = apiErrorMessage(error, '批量更新官方净值失败，请查看运行状态。')
  } finally {
    refreshingNavs.value = false
  }
}

async function estimateToday() {
  estimating.value = true
  const targetCodes =
    selectedFundCodes.value.length > 0
      ? selectedFundCodes.value
      : funds.value.map((fund) => fund.fund_code)
  message.value = `正在提交 ${targetCodes.length} 只基金的行情刷新和估算任务...`
  try {
    const estimateResult = await refreshQuotesAndRunEstimates(targetCodes)
    message.value = taskSubmitMessage(estimateResult)
  } catch (error) {
    message.value = apiErrorMessage(error, '估算当日净值失败，请查看运行状态。')
  } finally {
    estimating.value = false
  }
}

function taskSubmitMessage(result: { reused: boolean; task_id: number }) {
  return result.reused
    ? `相同任务已在等待执行，任务 ${result.task_id}。`
    : `任务 ${result.task_id} 已提交，可在运行状态查看进度。`
}

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms))
}

async function waitForTaskLog(taskLogId: number, maxAttempts = 30): Promise<TaskLog | null> {
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    const page = await listTaskLogs('fund_nav', { page: 1, pageSize: 20 })
    const task = page.items.find((item) => item.id === taskLogId)
    if (task && ['success', 'failed', 'partial'].includes(task.status)) return task
    await sleep(2000)
  }
  return null
}

onMounted(loadFunds)
</script>

<template>
  <main class="page-shell">
    <section class="dashboard-panel">
      <header class="dashboard-header">
        <div class="brand-heading">
          <h1>基金估值</h1>
        </div>
      </header>

      <div class="toolbar">
        <section class="mobile-collapsible" :class="{ 'is-open': batchActionsOpen }">
          <button
            class="mobile-collapsible-toggle"
            type="button"
            :aria-expanded="batchActionsOpen"
            @click="batchActionsOpen = !batchActionsOpen"
          >
            批量操作
          </button>
          <div class="page-actions mobile-collapsible-content">
            <button class="ghost" :disabled="estimating" @click="estimateToday">
              {{ estimating ? '估算中...' : selectedFundCodes.length ? `估算选中 ${selectedFundCodes.length} 只` : '批量估算全部' }}
            </button>
            <button class="ghost" :disabled="refreshingNavs" @click="refreshSelectedNavs">
              {{
                refreshingNavs
                  ? '更新中...'
                  : selectedFundCodes.length
                    ? `更新选中 ${selectedFundCodes.length} 只官方净值`
                    : '批量更新官方净值'
              }}
            </button>
            <RouterLink class="link-button" :to="{ name: routeNames.operations }">查看运行状态</RouterLink>
          </div>
        </section>
        <section class="mobile-collapsible" :class="{ 'is-open': addFundOpen }">
          <button
            class="mobile-collapsible-toggle"
            type="button"
            :aria-expanded="addFundOpen"
            @click="addFundOpen = !addFundOpen"
          >
            添加基金
          </button>
          <form class="inline-add-form mobile-collapsible-content" @submit.prevent="submitFund">
            <input v-model="fundCode" class="code-input" placeholder="基金代码" />
            <input v-model="remark" class="remark-input" placeholder="备注" />
            <button type="submit" :disabled="saving">{{ saving ? '添加中...' : '添加基金' }}</button>
          </form>
        </section>
      </div>

      <p v-if="message" class="message">{{ message }}</p>
      <FundTable
        v-model:selected-fund-codes="selectedFundCodes"
        :funds="funds"
        :loading="loading"
        :sort-by="sortBy"
        :sort-order="sortOrder"
        @delete="removeFund"
        @refresh="refreshNav"
        @sort="updateSort"
      />
    </section>

    <div v-if="pendingDeleteFund" class="modal-backdrop" @click.self="pendingDeleteFund = null">
      <section class="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-title">
        <p class="eyebrow">Delete Fund</p>
        <h2 id="delete-title">删除自选基金</h2>
        <p class="dialog-copy">
          确认删除 <strong>{{ pendingDeleteFund.fund_name }}</strong>
          <span class="mono">({{ pendingDeleteFund.fund_code }})</span>？
        </p>
        <div class="dialog-actions">
          <button class="ghost" type="button" @click="pendingDeleteFund = null">取消</button>
          <button class="danger" type="button" @click="confirmDeleteFund">删除</button>
        </div>
      </section>
    </div>
  </main>
</template>
