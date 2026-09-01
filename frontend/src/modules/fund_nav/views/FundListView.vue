<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import FundTable from '../components/FundTable.vue'
import BaseDialog from '../components/BaseDialog.vue'
import { apiErrorMessage, isRequestTimeout } from '../../../api/client'
import { routeNames } from '../../../router/routeNames'
import { formatDateTime } from '../../../utils/datetime'
import { refreshQuotesAndRunEstimates } from '../api/estimates'
import { listTaskLogs, type TaskLog } from '../operations/api/operations'
import {
  createFund,
  deleteFund,
  generateDailySummary,
  getDailySummary,
  listDailySummaryRules,
  listFunds,
  replaceDailySummaryRules,
  refreshFundNavs,
  updateFundFavorite,
  type Fund,
  type FundDailySummary,
  type FundSummaryRule,
  type FundSortBy,
  type SortOrder,
} from '../api/funds'

const SORT_STORAGE_KEY = 'fund-list-sort'

const funds = ref<Fund[]>([])
const summarySnapshot = ref<FundDailySummary>({ items: [] })
type EditableRule = { id?: number; rule_name: string; window_days: number; rise_percent: number; fall_percent: number; enabled: number }
const summaryRules = ref<EditableRule[]>([])
const selectedFundCodes = ref<string[]>([])
const fundCode = ref('')
const remark = ref('')
const searchKeyword = ref('')
const favoritesOnly = ref(false)
const loading = ref(false)
const saving = ref(false)
const favoriteUpdatingCode = ref<string | null>(null)
const estimating = ref(false)
const refreshingNavs = ref(false)
const generatingSummary = ref(false)
const savingRules = ref(false)
const message = ref('')
const pendingDeleteFund = ref<Fund | null>(null)
const batchActionsOpen = ref(false)
const addFundOpen = ref(false)
const ruleSettingsOpen = ref(false)
const initialSort = readSavedSort()
const sortBy = ref<FundSortBy | null>(initialSort.sortBy)
const sortOrder = ref<SortOrder>(initialSort.sortOrder)

const filteredFunds = computed(() => {
  const keyword = searchKeyword.value.trim().toLowerCase()
  return funds.value.filter((fund) => {
    if (favoritesOnly.value && fund.is_favorite !== 1) return false
    return !keyword || fund.fund_code.toLowerCase().includes(keyword) || fund.fund_name.toLowerCase().includes(keyword)
  })
})

const dailySummary = computed(() => {
  const summary = { up: 0, down: 0, flat: 0, noData: 0, continuousUp: 0, continuousDown: 0, ruleAlerts: 0 }
  for (const fund of filteredFunds.value) {
    const item = dailySummaryByFund.value[fund.fund_code]
    const growth = item?.latest_growth_rate == null ? null : Number(item.latest_growth_rate)
    if (growth == null) summary.noData += 1
    else if (growth > 0) summary.up += 1
    else if (growth < 0) summary.down += 1
    else summary.flat += 1
    if (item?.trend_days >= 3 && item.trend_direction === 'up') summary.continuousUp += 1
    if (item?.trend_days >= 3 && item.trend_direction === 'down') summary.continuousDown += 1
    if (item?.rule_matches?.length) summary.ruleAlerts += 1
  }
  return summary
})

const dailySummaryByFund = computed(() => Object.fromEntries(
  summarySnapshot.value.items.map((item) => [item.fund_code, item]),
))

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
    const [fundRows, summary, rules] = await Promise.all([
      listFunds({ sortBy: sortBy.value, sortOrder: sortOrder.value }),
      getDailySummary(),
      listDailySummaryRules(),
    ])
    funds.value = fundRows
    summarySnapshot.value = summary
    summaryRules.value = toEditableRules(rules)
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
    addFundOpen.value = false
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
    is_favorite: 0,
  }
}

function toEditableRules(rules: FundSummaryRule[]): EditableRule[] {
  return rules.map((rule) => ({
    id: rule.id,
    rule_name: rule.rule_name,
    window_days: rule.window_days,
    rise_percent: Number(rule.rise_threshold) * 100,
    fall_percent: Number(rule.fall_threshold) * 100,
    enabled: rule.enabled,
  }))
}

function addSummaryRule() {
  summaryRules.value.push({ rule_name: '自定义涨跌预警', window_days: 30, rise_percent: 10, fall_percent: 10, enabled: 1 })
}

async function saveSummaryRules() {
  savingRules.value = true
  try {
    const saved = await replaceDailySummaryRules(summaryRules.value.map((rule) => ({
      id: rule.id,
      rule_name: rule.rule_name.trim(),
      window_days: Number(rule.window_days),
      rise_threshold: Number(rule.rise_percent) / 100,
      fall_threshold: Number(rule.fall_percent) / 100,
      enabled: rule.enabled,
    })))
    summaryRules.value = toEditableRules(saved)
    ruleSettingsOpen.value = false
    message.value = '总结规则已保存，请立即生成或等待下一次定时任务应用新规则。'
  } catch (error) {
    message.value = apiErrorMessage(error, '总结规则保存失败，请检查输入。')
  } finally {
    savingRules.value = false
  }
}

async function requestDailySummary() {
  generatingSummary.value = true
  try {
    const result = await generateDailySummary()
    message.value = taskSubmitMessage(result)
    const task = await waitForTaskLog(result.task_log_id, 90)
    if (task) {
      summarySnapshot.value = await getDailySummary()
      message.value = task.status === 'success'
        ? `任务 ${result.task_id} 已完成，每日总结已更新。`
        : `任务 ${result.task_id} ${task.status_label}，已加载最近一次总结。`
    }
  } catch (error) {
    message.value = apiErrorMessage(error, '每日总结任务提交失败，请查看运行状态。')
  } finally {
    generatingSummary.value = false
  }
}

async function toggleFavorite(fund: Fund) {
  favoriteUpdatingCode.value = fund.fund_code
  try {
    const updated = await updateFundFavorite(fund.fund_code, fund.is_favorite !== 1)
    const index = funds.value.findIndex((item) => item.fund_code === updated.fund_code)
    if (index !== -1) funds.value[index] = updated
  } catch (error) {
    message.value = apiErrorMessage(error, '更新基金关注状态失败，请稍后重试。')
  } finally {
    favoriteUpdatingCode.value = null
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
    if (task && ['success', 'failed', 'partial', 'no_data', 'completed_with_issues', 'skipped'].includes(task.status)) return task
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

      <div class="toolbar fund-list-toolbar">
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
        <div class="fund-list-filters">
          <label class="fund-search">
            <span class="sr-only">搜索基金</span>
            <input v-model="searchKeyword" type="search" placeholder="搜索基金代码或名称" />
          </label>
          <label class="favorite-filter">
            <input v-model="favoritesOnly" type="checkbox" />
            仅看特别关注
          </label>
        </div>
        <button class="add-fund-button" type="button" @click="addFundOpen = true">添加基金</button>
      </div>

      <section class="daily-summary" aria-labelledby="daily-summary-title">
        <div class="daily-summary-heading">
          <div>
            <p class="eyebrow">Daily Summary</p>
            <h2 id="daily-summary-title">每日总结</h2>
          </div>
          <span class="muted">
            {{ summarySnapshot.summary_date ? `总结日期 ${summarySnapshot.summary_date}` : '暂无定时总结' }}
            · 当前范围 {{ filteredFunds.length }} 只基金
          </span>
        </div>
        <div class="daily-summary-grid">
          <div class="daily-summary-item up"><span>上涨</span><strong>{{ dailySummary.up }}</strong></div>
          <div class="daily-summary-item down"><span>下跌</span><strong>{{ dailySummary.down }}</strong></div>
          <div class="daily-summary-item flat"><span>持平</span><strong>{{ dailySummary.flat }}</strong></div>
          <div class="daily-summary-item muted-item"><span>暂无数据</span><strong>{{ dailySummary.noData }}</strong></div>
        </div>
        <p v-if="dailySummary.continuousUp || dailySummary.continuousDown" class="trend-summary-line">
          <span v-if="dailySummary.continuousUp" class="trend-badge up">持续上涨 {{ dailySummary.continuousUp }} 只</span>
          <span v-if="dailySummary.continuousDown" class="trend-badge down">持续下跌 {{ dailySummary.continuousDown }} 只</span>
          <span class="muted">基金定时调度启用后每天 23:00 生成，连续 3 个交易日起标注。</span>
        </p>
        <p v-else class="trend-summary-line muted">当前范围暂无连续 3 天以上的上涨或下跌基金。</p>
        <p v-if="dailySummary.ruleAlerts" class="trend-summary-line">
          <span class="rule-badge alert">区间规则预警 {{ dailySummary.ruleAlerts }} 只</span>
          <span class="muted">具体命中规则已标注在基金名称下方。</span>
        </p>
        <div class="daily-summary-actions">
          <span v-if="summarySnapshot.generated_at" class="muted">生成时间 {{ formatDateTime(summarySnapshot.generated_at) }}</span>
          <button class="ghost" type="button" :disabled="generatingSummary" @click="requestDailySummary">
            {{ generatingSummary ? '提交中...' : '立即生成' }}
          </button>
          <button class="ghost" type="button" @click="ruleSettingsOpen = true">规则设置</button>
        </div>
      </section>

      <p v-if="message" class="message">{{ message }}</p>
      <FundTable
        v-model:selected-fund-codes="selectedFundCodes"
        :funds="filteredFunds"
        :loading="loading"
        :sort-by="sortBy"
        :sort-order="sortOrder"
        :favorite-updating-code="favoriteUpdatingCode"
        :daily-summary-by-fund="dailySummaryByFund"
        :empty-text="searchKeyword.trim() || favoritesOnly ? '没有匹配的基金。' : undefined"
        @delete="removeFund"
        @favorite="toggleFavorite"
        @sort="updateSort"
      />
    </section>

    <BaseDialog v-if="pendingDeleteFund" :open="true" @close="pendingDeleteFund = null">
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
    </BaseDialog>

    <BaseDialog v-if="ruleSettingsOpen" :open="true" @close="ruleSettingsOpen = false">
      <section class="summary-rule-dialog" role="dialog" aria-modal="true" aria-labelledby="summary-rule-title">
        <h2 id="summary-rule-title">每日总结规则</h2>
        <p class="muted">按自然日窗口复合计算区间涨跌幅。阈值填写百分数，例如 10 表示 10%。</p>
        <div class="summary-rule-list">
          <div v-for="(rule, index) in summaryRules" :key="rule.id ?? `new-${index}`" class="summary-rule-row">
            <input v-model="rule.rule_name" aria-label="规则名称" placeholder="规则名称" />
            <label>天数<input v-model.number="rule.window_days" type="number" min="1" max="3650" /></label>
            <label>上涨 ≥ %<input v-model.number="rule.rise_percent" type="number" min="0.01" step="0.01" /></label>
            <label>下跌 ≥ %<input v-model.number="rule.fall_percent" type="number" min="0.01" step="0.01" /></label>
            <label class="rule-enabled"><input v-model="rule.enabled" type="checkbox" :true-value="1" :false-value="0" />启用</label>
            <button class="danger" type="button" @click="summaryRules.splice(index, 1)">删除</button>
          </div>
        </div>
        <div class="dialog-actions summary-rule-actions">
          <button class="ghost" type="button" @click="addSummaryRule">添加规则</button>
          <span class="dialog-action-spacer"></span>
          <button class="ghost" type="button" :disabled="savingRules" @click="ruleSettingsOpen = false">取消</button>
          <button type="button" :disabled="savingRules || summaryRules.some((rule) => !rule.rule_name.trim())" @click="saveSummaryRules">
            {{ savingRules ? '保存中...' : '保存规则' }}
          </button>
        </div>
      </section>
    </BaseDialog>

    <BaseDialog v-if="addFundOpen" :open="true" @close="addFundOpen = false">
      <section class="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="add-fund-title">
        <p class="eyebrow">Add Fund</p>
        <h2 id="add-fund-title">添加基金</h2>
        <form class="add-fund-form" @submit.prevent="submitFund">
          <label>
            基金代码
            <input v-model="fundCode" class="code-input" placeholder="请输入基金代码" autofocus />
          </label>
          <label>
            备注（可选）
            <input v-model="remark" class="remark-input" placeholder="例如：长期持有" />
          </label>
          <div class="dialog-actions">
            <button class="ghost" type="button" :disabled="saving" @click="addFundOpen = false">取消</button>
            <button type="submit" :disabled="saving || !fundCode.trim()">{{ saving ? '添加中...' : '添加基金' }}</button>
          </div>
        </form>
      </section>
    </BaseDialog>
  </main>
</template>
