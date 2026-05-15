<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { apiErrorMessage } from '../api/client'
import {
  getFund,
  listFundHoldings,
  refreshFundHoldings,
  type Fund,
  type FundHolding,
} from '../api/funds'

const route = useRoute()
const fundCode = computed(() => String(route.params.fundCode || ''))
const fund = ref<Fund | null>(null)
const holdings = ref<FundHolding[]>([])
const selectedReportPeriod = ref('')
const loading = ref(false)
const refreshingHoldings = ref(false)
const message = ref('')

const reportPeriods = computed(() =>
  Array.from(new Set(holdings.value.map((holding) => holding.report_period))).sort((a, b) =>
    b.localeCompare(a),
  ),
)

const filteredHoldings = computed(() =>
  selectedReportPeriod.value
    ? holdings.value.filter((holding) => holding.report_period === selectedReportPeriod.value)
    : holdings.value,
)

const selectedHoldingRatio = computed(() =>
  filteredHoldings.value.reduce((total, holding) => total + Number(holding.holding_ratio || 0), 0),
)

const holdingCompletenessWarning = computed(() => {
  if (!fund.value || holdings.value.length === 0) return ''
  const fundType = fund.value.fund_type ?? ''
  const fundName = fund.value.fund_name ?? ''
  if (fundType.includes('QDII') || fundName.includes('联接')) {
    return '该基金可能是联接基金或 QDII，公开持仓可能只覆盖部分底层资产，估算结果需结合覆盖率判断。'
  }
  if (selectedHoldingRatio.value > 0 && selectedHoldingRatio.value < 0.6) {
    return '当前报告期持仓覆盖比例偏低，可能存在持仓或行情缺失。'
  }
  return ''
})

function latestReportPeriod(items: FundHolding[]) {
  return Array.from(new Set(items.map((holding) => holding.report_period)))
    .sort((a, b) => b.localeCompare(a))[0] ?? ''
}

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

async function loadDetail() {
  loading.value = true
  message.value = ''
  try {
    const [fundResult, holdingsResult] = await Promise.all([
      getFund(fundCode.value),
      listFundHoldings(fundCode.value),
    ])
    fund.value = fundResult
    holdings.value = holdingsResult
    selectedReportPeriod.value = latestReportPeriod(holdingsResult)
  } catch (error) {
    message.value = apiErrorMessage(error, '基金详情加载失败，请稍后重试。')
  } finally {
    loading.value = false
  }
}

async function refreshHoldings() {
  refreshingHoldings.value = true
  message.value = ''
  try {
    const result = await refreshFundHoldings(fundCode.value)
    holdings.value = await listFundHoldings(fundCode.value)
    selectedReportPeriod.value = latestReportPeriod(holdings.value)
    message.value = result.refreshed ? `持仓已刷新，共 ${result.holding_count} 条。` : '未获取到持仓数据，已记录到运行状态。'
  } catch (error) {
    message.value = apiErrorMessage(error, '持仓刷新失败，请稍后重试。')
  } finally {
    refreshingHoldings.value = false
  }
}

onMounted(loadDetail)
</script>

<template>
  <main class="page-shell">
    <RouterLink class="back-link" to="/">返回基金池</RouterLink>

    <section class="detail-hero">
      <div>
        <p class="eyebrow">Fund Detail</p>
        <h1>{{ fund?.fund_name ?? fundCode }}</h1>
        <p class="subtitle">查看基金基础信息、官方净值和当前已维护的持仓情况。</p>
      </div>
      <div class="code-badge">{{ fundCode }}</div>
    </section>

    <p v-if="message" class="message">{{ message }}</p>
    <p v-if="loading" class="message">正在加载详情...</p>

    <section v-if="fund" class="info-grid">
      <article class="info-card">
        <span>基金类型</span>
        <strong>{{ fund.fund_type ?? '-' }}</strong>
      </article>
      <article class="info-card">
        <span>跟踪指数</span>
        <strong>{{ fund.tracked_index_name ?? '-' }}</strong>
        <small v-if="fund.tracked_index_code" class="muted mono">{{ fund.tracked_index_code }}</small>
      </article>
      <article class="info-card">
        <span>官方净值</span>
        <strong>{{ fund.latest_unit_nav ?? '-' }}</strong>
      </article>
      <article class="info-card">
        <span>净值日期</span>
        <strong>{{ fund.latest_nav_date ?? '-' }}</strong>
      </article>
      <article class="info-card">
        <span>昨日官方涨跌幅</span>
        <strong :class="growthClass(fund.latest_daily_growth_rate)">{{ growthPercent(fund.latest_daily_growth_rate) }}</strong>
      </article>
      <article class="info-card">
        <span>估算净值</span>
        <strong>{{ fund.latest_estimated_nav ?? '-' }}</strong>
      </article>
      <article class="info-card">
        <span>估算涨跌幅</span>
        <strong :class="growthClass(fund.latest_estimated_growth_rate)">{{ growthPercent(fund.latest_estimated_growth_rate) }}</strong>
      </article>
      <article class="info-card">
        <span>估算时间</span>
        <strong>{{ fund.latest_estimate_time ?? '-' }}</strong>
      </article>
      <article class="info-card" :class="{ 'warning-card': fund.latest_coverage_ratio && Number(fund.latest_coverage_ratio) < 0.6 }">
        <span>有效覆盖率</span>
        <strong>{{ percent(fund.latest_coverage_ratio) }}</strong>
      </article>
    </section>

    <p v-if="fund && !fund.latest_unit_nav" class="message">缺少官方净值，请先刷新净值。</p>
    <p v-else-if="fund && !fund.latest_estimated_nav" class="message">当前还没有估算结果，可在运行状态页查看估算任务日志。</p>
    <p v-else-if="fund?.latest_coverage_ratio && Number(fund.latest_coverage_ratio) < 0.6" class="message">
      当前估算覆盖率偏低，可能存在持仓或行情缺失。
    </p>

    <section class="section-title">
      <div>
        <p class="eyebrow">Portfolio</p>
        <h2>持仓情况</h2>
      </div>
      <div class="section-actions">
        <span>{{ filteredHoldings.length }} / {{ holdings.length }} 条记录</span>
        <select v-model="selectedReportPeriod" class="period-select" :disabled="reportPeriods.length === 0">
          <option value="">全部报告期</option>
          <option v-for="period in reportPeriods" :key="period" :value="period">{{ period }}</option>
        </select>
        <button class="ghost" :disabled="refreshingHoldings" @click="refreshHoldings">
          {{ refreshingHoldings ? '刷新中...' : '刷新持仓' }}
        </button>
      </div>
    </section>

    <p v-if="holdingCompletenessWarning" class="message">{{ holdingCompletenessWarning }}</p>

    <div class="table-card">
      <table>
        <thead>
          <tr>
            <th>报告期</th>
            <th>资产代码</th>
            <th>资产名称</th>
            <th>资产类型</th>
            <th>市场</th>
            <th>持仓比例</th>
            <th>持仓市值</th>
            <th>来源</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="holdings.length === 0">
            <td colspan="8">当前还没有持仓数据，可以点击“刷新持仓”从 akshare 同步。</td>
          </tr>
          <tr v-else-if="filteredHoldings.length === 0">
            <td colspan="8">当前报告期没有持仓数据。</td>
          </tr>
          <tr v-for="holding in filteredHoldings" :key="`${holding.report_period}-${holding.asset_code}`">
            <td>{{ holding.report_period }}</td>
            <td class="mono">{{ holding.asset_code }}</td>
            <td>{{ holding.asset_name }}</td>
            <td>{{ holding.asset_type }}</td>
            <td>{{ holding.market ?? '-' }}</td>
            <td>{{ percent(holding.holding_ratio) }}</td>
            <td>{{ holding.holding_value ?? '-' }}</td>
            <td>{{ holding.source }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </main>
</template>
