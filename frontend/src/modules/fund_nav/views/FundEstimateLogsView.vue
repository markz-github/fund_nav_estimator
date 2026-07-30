<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { apiErrorMessage } from '../../../api/client'
import { dateInputValue, formatDateTime } from '../../../utils/datetime'
import { routeNames } from '../../../router/routeNames'
import {
  listAllFundTaskDetailLogs,
  listFunds,
  type Fund,
  type FundTaskDetailLog,
} from '../api/funds'

const route = useRoute()
const funds = ref<Fund[]>([])
const logs = ref<FundTaskDetailLog[]>([])
const loading = ref(false)
const message = ref('')
const selectedFundCode = ref(String(route.query.fund_code || ''))
const selectedDate = ref(String(route.query.estimate_date || ''))
const currentPage = ref(1)
const pageSize = 30
const totalLogs = ref(0)
const totalPages = computed(() => Math.max(1, Math.ceil(totalLogs.value / pageSize)))

const selectedFund = computed(() =>
  funds.value.find((fund) => fund.fund_code === selectedFundCode.value) ?? null,
)

function percent(value?: string | null) {
  if (!value) return '-'
  return `${(Number(value) * 100).toFixed(2)}%`
}

function growthPercent(value?: string | null) {
  if (!value) return '-'
  const percentValue = Number(value) * 100
  const sign = percentValue > 0 ? '+' : ''
  return `${sign}${percentValue.toFixed(2)}%`
}

function growthClass(value?: string | null) {
  if (!value) return ''
  return Number(value) >= 0 ? 'up' : 'down'
}

function statusClass(status?: string | null) {
  if (status === 'success') return 'status-ok'
  if (status === 'skipped') return 'status-muted'
  return 'status-warn'
}

function strategyLabel(strategy?: string | null) {
  if (strategy === 'index_tracking') return '指数法'
  if (strategy === 'holding_weighted') return '持仓法'
  if (strategy === 'etf_quote') return 'ETF实时价格'
  if (strategy === 'etf_iopv') return 'ETF IOPV'
  return strategy || '-'
}

function resultClass(result?: string | null) {
  if (result === 'success') return 'status-ok'
  if (result === 'stale_index_quote') return 'status-warn'
  return 'status-muted'
}

function originLabel(origin?: string | null) {
  if (origin === 'scheduled') return '定时任务'
  if (origin === 'manual') return '手动操作'
  if (origin === 'new_fund') return '新增基金同步'
  return '未知来源'
}

function indexQuoteWarning(log: FundTaskDetailLog) {
  const staleAttempt = log.attempts?.find(
    (attempt) => attempt.strategy === 'index_tracking' && attempt.result === 'stale_index_quote',
  )
  if (!staleAttempt) return ''
  return log.status === 'success'
    ? '指数法行情滞后，已回退到其他算法估算。'
    : '指数法行情滞后，未能使用跟踪指数估算。'
}

async function loadFunds() {
  funds.value = await listFunds()
}

async function loadLogs() {
  loading.value = true
  message.value = ''
  try {
    const result = await listAllFundTaskDetailLogs({
      fundCode: selectedFundCode.value,
      estimateDate: selectedDate.value,
      page: currentPage.value,
      pageSize,
    })
    logs.value = result.items
    totalLogs.value = result.total
    currentPage.value = result.page
  } catch (error) {
    message.value = apiErrorMessage(error, '估算执行日志加载失败，请稍后重试。')
  } finally {
    loading.value = false
  }
}

function clearFilters() {
  selectedFundCode.value = ''
  selectedDate.value = ''
  currentPage.value = 1
  void loadLogs()
}

function useToday() {
  selectedDate.value = dateInputValue()
  currentPage.value = 1
  void loadLogs()
}

function clearDate() {
  selectedDate.value = ''
  currentPage.value = 1
  void loadLogs()
}

function applyFilters() {
  currentPage.value = 1
  void loadLogs()
}

function goToPage(page: number) {
  currentPage.value = Math.min(Math.max(1, page), totalPages.value)
  void loadLogs()
}

onMounted(async () => {
  try {
    await loadFunds()
    await loadLogs()
  } catch (error) {
    message.value = apiErrorMessage(error, '页面初始化失败，请稍后重试。')
  }
})
</script>

<template>
  <main class="page-shell">
    <RouterLink class="back-link" :to="{ name: routeNames.fundList }">返回基金池</RouterLink>

    <section class="detail-hero">
      <div>
        <p class="eyebrow">Estimate Logs</p>
        <h1>估算执行日志</h1>
        <p class="subtitle">按基金和估算日期查看基金级估算过程、最终算法和回退原因。</p>
      </div>
      <button class="ghost" :disabled="loading" @click="loadLogs">
        {{ loading ? '刷新中...' : '刷新日志' }}
      </button>
    </section>

    <p v-if="message" class="message">{{ message }}</p>

    <form class="filter-bar compact-filter" @submit.prevent="applyFilters">
      <label>
        基金
        <ElSelect v-model="selectedFundCode" filterable clearable placeholder="全部基金">
          <ElOption label="全部基金" value="" />
          <ElOption
            v-for="fund in funds"
            :key="fund.fund_code"
            :label="`${fund.fund_code} ${fund.fund_name}`"
            :value="fund.fund_code"
          />
        </ElSelect>
      </label>
      <label>
        估算日期
        <ElDatePicker
          v-model="selectedDate"
          type="date"
          value-format="YYYY-MM-DD"
          format="YYYY-MM-DD"
          placeholder="全部日期"
          clearable
        />
      </label>
      <div class="filter-actions">
        <button class="ghost" type="submit" :disabled="loading">应用</button>
        <button class="ghost" type="button" :disabled="loading" @click="useToday">今天</button>
        <button class="ghost" type="button" :disabled="loading || !selectedDate" @click="clearDate">清空日期</button>
        <button class="ghost" type="button" :disabled="loading" @click="clearFilters">重置</button>
      </div>
    </form>

    <section class="info-grid quality-summary-grid">
      <article class="info-card">
        <span>当前基金</span>
        <strong>{{ selectedFund?.fund_name || selectedFundCode || '全部基金' }}</strong>
        <small v-if="selectedFundCode" class="muted mono">{{ selectedFundCode }}</small>
      </article>
      <article class="info-card">
        <span>估算日期</span>
        <strong>{{ selectedDate || '全部日期' }}</strong>
      </article>
      <article class="info-card">
        <span>日志数量</span>
        <strong>{{ totalLogs }}</strong>
      </article>
    </section>

    <div class="table-card">
      <table class="responsive-card-table quality-table">
        <thead>
          <tr>
            <th>基金</th>
            <th>来源</th>
            <th>执行时间</th>
            <th>状态</th>
            <th>算法</th>
            <th>估算涨跌幅</th>
            <th>估算净值</th>
            <th>覆盖率</th>
            <th>原因/过程</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="logs.length === 0">
            <td colspan="9">暂无估算执行日志。</td>
          </tr>
          <tr v-for="log in logs" :key="log.id">
            <td data-label="基金">
              <RouterLink class="fund-name" :to="{ name: routeNames.fundDetail, params: { fundCode: log.fund_code } }">
                {{ log.fund_name || log.fund_code }}
              </RouterLink>
              <span class="muted mono">{{ log.fund_code }}</span>
            </td>
            <td data-label="来源">{{ originLabel(log.origin) }}</td>
            <td data-label="执行时间">{{ formatDateTime(log.estimate_time || log.created_at) }}</td>
            <td data-label="状态">
              <span class="status-pill" :class="statusClass(log.status)">{{ log.status_label || log.status }}</span>
            </td>
            <td data-label="算法">{{ log.strategy_label || strategyLabel(log.strategy) }}</td>
            <td :class="growthClass(log.estimated_growth_rate)" data-label="估算涨跌幅">
              {{ growthPercent(log.estimated_growth_rate) }}
            </td>
            <td data-label="估算净值">{{ log.estimated_nav ?? '-' }}</td>
            <td data-label="覆盖率">{{ percent(log.coverage_ratio) }}</td>
            <td class="quality-message task-log-message" data-label="原因/过程">
              <div v-if="log.reason_label && log.status !== 'success'" class="task-log-final-reason">
                最终原因：{{ log.reason_label }}
              </div>
              <div v-if="indexQuoteWarning(log)" class="task-log-warning">
                {{ indexQuoteWarning(log) }}
              </div>
              <div v-if="log.attempts?.length" class="task-log-attempts">
                <span
                  v-for="attempt in log.attempts"
                  :key="`${log.id}-${attempt.strategy}`"
                  class="status-pill task-log-attempt"
                  :class="resultClass(attempt.result)"
                >
                  {{ attempt.strategy_label }}：{{ attempt.result_label }}
                </span>
              </div>
              <span v-else>{{ log.reason_label || '-' }}</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <nav class="pagination-bar" aria-label="估算日志分页">
      <button class="ghost" type="button" :disabled="loading || currentPage <= 1" @click="goToPage(currentPage - 1)">
        上一页
      </button>
      <span>第 {{ currentPage }} / {{ totalPages }} 页，共 {{ totalLogs }} 条</span>
      <button class="ghost" type="button" :disabled="loading || currentPage >= totalPages" @click="goToPage(currentPage + 1)">
        下一页
      </button>
    </nav>
  </main>
</template>
