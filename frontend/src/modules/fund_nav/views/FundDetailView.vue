<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AreaSeries,
  ColorType,
  CrosshairMode,
  LineStyle,
  createChart,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type LogicalRange,
  type MouseEventParams,
  type Time,
} from 'lightweight-charts'
import { apiErrorMessage } from '../../../api/client'
import { formatDateTime } from '../../../utils/datetime'
import { routeNames } from '../../../router/routeNames'
import {
  getFund,
  listFundTaskDetailLogs,
  listFundNavHistory,
  listFundHoldings,
  refreshFundNavHistory,
  refreshFundHoldings,
  type Fund,
  type FundHolding,
  type FundNav,
  type FundTaskDetailLog,
} from '../api/funds'

const route = useRoute()
const router = useRouter()
const fundCode = computed(() => String(route.params.fundCode || ''))
const fund = ref<Fund | null>(null)
const holdings = ref<FundHolding[]>([])
const navHistory = ref<FundNav[]>([])
const taskDetailLogs = ref<FundTaskDetailLog[]>([])
const selectedReportPeriod = ref('')
const loading = ref(false)
const refreshingHoldings = ref(false)
const refreshingNavHistory = ref(false)
const message = ref('')
const navChartEl = ref<HTMLElement | null>(null)
const selectedHistoryNav = ref<FundNav | null>(null)
const priceLineMode = ref<'point' | 'mouse'>('point')
let navChart: IChartApi | null = null
let navSeries: ISeriesApi<'Area'> | null = null
let selectedNavPriceLine: IPriceLine | null = null
let navChartResizeObserver: ResizeObserver | null = null
let adjustingNavChartRange = false

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
    return '当前报告期持仓覆盖比例偏低，可能存在持仓缺失；债券等部分持仓会展示但暂不参与实时估算。'
  }
  return ''
})

const chartNavs = computed(() => navHistory.value.filter((item) => Number.isFinite(Number(item.unit_nav))))
const latestHistoryNav = computed(() => chartNavs.value[chartNavs.value.length - 1] ?? null)
const displayedHistoryNav = computed(() => selectedHistoryNav.value ?? latestHistoryNav.value)
const chartRangeText = computed(() => {
  const items = chartNavs.value
  if (items.length === 0) return '-'
  return `${items[0].nav_date} - ${items[items.length - 1].nav_date}`
})

const navChartData = computed(() =>
  chartNavs.value.map((item) => ({
    time: item.nav_date as Time,
    value: Number(item.unit_nav),
  })),
)

function chartDateLabel(time: Time) {
  if (typeof time === 'string') return time
  if (typeof time === 'number') {
    return new Date(time * 1000).toISOString().slice(0, 10)
  }
  const month = String(time.month).padStart(2, '0')
  const day = String(time.day).padStart(2, '0')
  return `${time.year}-${month}-${day}`
}

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

function statusLabel(status?: string | null) {
  if (status === 'success') return '成功'
  if (status === 'skipped') return '跳过'
  if (status === 'failed') return '失败'
  return status || '-'
}

function statusClass(status?: string | null) {
  if (status === 'success') return 'status-ok'
  if (status === 'skipped') return 'status-muted'
  return 'status-warn'
}

function categorySourceLabel(source?: string | null) {
  if (source === 'auto') return '自动识别'
  if (source === 'manual') return '人工维护'
  return '-'
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

function indexQuoteWarning(log: FundTaskDetailLog) {
  const staleAttempt = log.attempts?.find(
    (attempt) => attempt.strategy === 'index_tracking' && attempt.result === 'stale_index_quote',
  )
  if (!staleAttempt) return ''
  return log.status === 'success'
    ? '指数法行情滞后，已回退到其他算法估算。'
    : '指数法行情滞后，未能使用跟踪指数估算。'
}

async function loadDetail() {
  loading.value = true
  message.value = ''
  try {
    const [fundResult, holdingsResult, navHistoryResult, taskDetailLogResult] = await Promise.all([
      getFund(fundCode.value),
      listFundHoldings(fundCode.value),
      listFundNavHistory(fundCode.value),
      listFundTaskDetailLogs(fundCode.value),
    ])
    fund.value = fundResult
    holdings.value = holdingsResult
    navHistory.value = navHistoryResult
    taskDetailLogs.value = taskDetailLogResult
    selectedReportPeriod.value = latestReportPeriod(holdingsResult)
  } catch (error) {
    message.value = apiErrorMessage(error, '基金详情加载失败，请稍后重试。')
  } finally {
    loading.value = false
  }
}

async function refreshNavHistory() {
  refreshingNavHistory.value = true
  message.value = ''
  try {
    navHistory.value = await refreshFundNavHistory(fundCode.value)
    fund.value = await getFund(fundCode.value)
    message.value = `历史净值已更新，共 ${navHistory.value.length} 条。`
  } catch (error) {
    message.value = apiErrorMessage(error, '历史净值更新失败，请稍后重试。')
  } finally {
    refreshingNavHistory.value = false
  }
}

function ensureNavChart() {
  if (!navChartEl.value || navChart) return
  navChart = createChart(navChartEl.value, {
    width: navChartEl.value.clientWidth,
    height: 320,
    autoSize: false,
    layout: {
      background: { type: ColorType.Solid, color: '#ffffff' },
      textColor: '#52645a',
      fontFamily: 'Inter, "Microsoft YaHei", Arial, sans-serif',
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: 'rgba(36, 63, 47, 0.08)' },
      horzLines: { color: 'rgba(36, 63, 47, 0.10)' },
    },
    crosshair: {
      mode: CrosshairMode.Normal,
      horzLine: {
        visible: false,
        labelVisible: false,
      },
    },
    rightPriceScale: {
      borderColor: 'rgba(36, 63, 47, 0.16)',
      minimumWidth: 112,
      entireTextOnly: true,
      scaleMargins: {
        top: 0.12,
        bottom: 0.12,
      },
    },
    timeScale: {
      borderColor: 'rgba(36, 63, 47, 0.16)',
      timeVisible: false,
      secondsVisible: false,
      rightOffset: 0,
      minBarSpacing: 2,
      fixLeftEdge: true,
      fixRightEdge: true,
      tickMarkFormatter: (time: Time) => chartDateLabel(time),
    },
    localization: {
      locale: 'zh-CN',
      dateFormat: 'yyyy-MM-dd',
      priceFormatter: (price: number) => price.toFixed(4),
      timeFormatter: (time: Time) => chartDateLabel(time),
    },
  })
  navSeries = navChart.addSeries(AreaSeries, {
    lineColor: '#287356',
    topColor: 'rgba(40, 115, 86, 0.28)',
    bottomColor: 'rgba(40, 115, 86, 0.02)',
    lineWidth: 2,
    priceLineVisible: false,
    lastValueVisible: false,
  })
  navChartResizeObserver = new ResizeObserver((entries) => {
    const width = entries[0]?.contentRect.width
    if (width && navChart) {
      navChart.applyOptions({ width })
      requestAnimationFrame(fitNavChartToDataEdges)
    }
  })
  navChartResizeObserver.observe(navChartEl.value)
  navChart.subscribeCrosshairMove(handleNavCrosshairMove)
  navChart.timeScale().subscribeVisibleLogicalRangeChange(keepNavChartRangeInsideData)
  applyPriceLineMode()
}

function keepNavChartRangeInsideData(range: LogicalRange | null = navChart?.timeScale().getVisibleLogicalRange() ?? null) {
  if (!navChart || adjustingNavChartRange || !range || navChartData.value.length <= 1) return
  const firstIndex = 0
  const lastIndex = navChartData.value.length - 1
  const span = range.to - range.from
  const maxSpan = lastIndex - firstIndex
  const nextRange =
    span >= maxSpan
      ? { from: firstIndex, to: lastIndex }
      : { from: range.from, to: range.to }

  if (span < maxSpan && nextRange.to > lastIndex) {
    nextRange.from -= nextRange.to - lastIndex
    nextRange.to = lastIndex
  }
  if (span < maxSpan && nextRange.from < firstIndex) {
    nextRange.to += firstIndex - nextRange.from
    nextRange.from = firstIndex
  }
  if (nextRange.from === range.from && nextRange.to === range.to) return

  adjustingNavChartRange = true
  try {
    navChart.timeScale().setVisibleLogicalRange(nextRange)
  } finally {
    adjustingNavChartRange = false
  }
}

function handleNavCrosshairMove(param: MouseEventParams<Time>) {
  if (!param.time) {
    selectedHistoryNav.value = null
    updateSelectedNavPriceLine()
    return
  }
  const navDate = chartDateLabel(param.time)
  selectedHistoryNav.value = chartNavs.value.find((item) => item.nav_date === navDate) ?? null
  updateSelectedNavPriceLine()
}

function updateSelectedNavPriceLine() {
  if (!navSeries) return
  if (priceLineMode.value !== 'point') {
    if (selectedNavPriceLine) {
      navSeries.removePriceLine(selectedNavPriceLine)
      selectedNavPriceLine = null
    }
    return
  }
  if (!selectedHistoryNav.value) {
    if (selectedNavPriceLine) {
      navSeries.removePriceLine(selectedNavPriceLine)
      selectedNavPriceLine = null
    }
    return
  }
  const selectedValue = Number(selectedHistoryNav.value.unit_nav)
  if (!Number.isFinite(selectedValue)) {
    if (selectedNavPriceLine) {
      navSeries.removePriceLine(selectedNavPriceLine)
      selectedNavPriceLine = null
    }
    return
  }
  const priceLineOptions = {
    price: selectedValue,
    color: '#287356',
    lineWidth: 1 as const,
    lineStyle: LineStyle.Dashed,
    lineVisible: true,
    axisLabelVisible: true,
    axisLabelColor: '#17271f',
    axisLabelTextColor: '#ffffff',
    title: '',
  }
  if (selectedNavPriceLine) {
    selectedNavPriceLine.applyOptions(priceLineOptions)
  } else {
    selectedNavPriceLine = navSeries.createPriceLine(priceLineOptions)
  }
}

function disposeNavChart() {
  navChartResizeObserver?.disconnect()
  navChartResizeObserver = null
  selectedNavPriceLine = null
  navChart?.remove()
  navChart = null
  navSeries = null
  selectedHistoryNav.value = null
  adjustingNavChartRange = false
}

function applyPriceLineMode() {
  navChart?.applyOptions({
    crosshair: {
      horzLine: {
        visible: priceLineMode.value === 'mouse',
        labelVisible: priceLineMode.value === 'mouse',
      },
    },
  })
  updateSelectedNavPriceLine()
}

function fitNavChartToDataEdges() {
  if (!navChart || navChartData.value.length <= 1) return
  navChart.timeScale().setVisibleLogicalRange({
    from: 0,
    to: navChartData.value.length - 1,
  })
}

async function renderNavChart() {
  await nextTick()
  if (navChartData.value.length === 0) {
    disposeNavChart()
    return
  }
  ensureNavChart()
  navSeries?.setData(navChartData.value)
  navChart?.timeScale().fitContent()
  fitNavChartToDataEdges()
  keepNavChartRangeInsideData()
}

async function refreshHoldings() {
  refreshingHoldings.value = true
  message.value = ''
  try {
    const result = await refreshFundHoldings(fundCode.value)
    message.value = result.reused
      ? `相同任务已在等待执行，任务 ${result.task_id}。`
      : `任务 ${result.task_id} 已提交，可在运行状态查看进度。`
  } catch (error) {
    message.value = apiErrorMessage(error, '持仓刷新失败，请稍后重试。')
  } finally {
    refreshingHoldings.value = false
  }
}

function goBack() {
  if (window.history.state?.back) {
    router.back()
    return
  }
  router.push({ name: 'fund-list' })
}

watch(navChartData, renderNavChart)
watch(priceLineMode, applyPriceLineMode)

onMounted(async () => {
  await loadDetail()
  await renderNavChart()
})

onBeforeUnmount(disposeNavChart)
</script>

<template>
  <main class="page-shell">
    <RouterLink class="back-link" :to="{ name: routeNames.fundList }">返回基金池</RouterLink>

    <section class="detail-hero">
      <div>
        <p class="eyebrow">Fund Detail</p>
        <h1>{{ fund?.fund_name ?? fundCode }}</h1>
        <p class="subtitle">查看基金基础信息、官方净值和当前已维护的持仓情况。</p>
      </div>
      <div class="section-actions">
        <span class="code-badge">{{ fundCode }}</span>
        <button class="ghost" type="button" @click="goBack">返回</button>
      </div>
    </section>

    <p v-if="message" class="message">{{ message }}</p>
    <p v-if="loading" class="message">正在加载详情...</p>

    <section v-if="fund" class="info-grid">
      <article class="info-card">
        <span>统一分类</span>
        <strong>{{ fund.fund_category_label ?? fund.fund_category ?? '未分类' }}</strong>
        <small class="muted">{{ categorySourceLabel(fund.fund_category_source) }}</small>
      </article>
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
        <span>目标 ETF</span>
        <strong>{{ fund.target_etf_name ?? '-' }}</strong>
        <small v-if="fund.target_etf_code" class="muted mono">{{ fund.target_etf_code }}</small>
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
        <strong>{{ formatDateTime(fund.latest_estimate_time) }}</strong>
      </article>
      <article class="info-card" :class="{ 'warning-card': fund.latest_coverage_ratio && Number(fund.latest_coverage_ratio) < 0.6 }">
        <span>有效覆盖率</span>
        <strong>{{ percent(fund.latest_coverage_ratio) }}</strong>
      </article>
    </section>

    <p v-if="fund && !fund.latest_unit_nav" class="message">缺少官方净值，请先刷新净值。</p>
    <p v-else-if="fund && !fund.latest_estimated_nav" class="message">当前还没有估算结果，可在运行状态页查看估算任务日志。</p>
    <p v-else-if="fund?.latest_coverage_ratio && Number(fund.latest_coverage_ratio) < 0.6" class="message">
      当前估算覆盖率偏低，可能存在持仓、行情缺失，或债券等不可实时估值资产未参与估算。
    </p>

    <section class="section-title">
      <div>
        <p class="eyebrow">Official NAV</p>
        <h2>历史净值走势</h2>
      </div>
      <div class="section-actions">
        <span>{{ navHistory.length }} 条记录</span>
        <button class="ghost" :disabled="refreshingNavHistory" @click="refreshNavHistory">
          {{ refreshingNavHistory ? '更新中...' : '更新历史净值' }}
        </button>
      </div>
    </section>

    <section class="nav-chart-panel">
      <div class="nav-chart-meta">
        <div>
          <span>日期范围</span>
          <strong>{{ chartRangeText }}</strong>
        </div>
        <div>
          <span>{{ selectedHistoryNav ? '当前净值' : '最新净值' }}</span>
          <strong>{{ displayedHistoryNav?.unit_nav ?? '-' }}</strong>
        </div>
        <div>
          <span>{{ selectedHistoryNav ? '当前日期' : '最新日期' }}</span>
          <strong>{{ displayedHistoryNav?.nav_date ?? '-' }}</strong>
        </div>
        <div class="nav-chart-toolbar">
          <span>价格线</span>
          <div class="segmented-control" aria-label="价格线模式">
            <button
              type="button"
              :class="{ active: priceLineMode === 'point' }"
              @click="priceLineMode = 'point'"
            >
              点位
            </button>
            <button
              type="button"
              :class="{ active: priceLineMode === 'mouse' }"
              @click="priceLineMode = 'mouse'"
            >
              鼠标
            </button>
          </div>
        </div>
      </div>
      <div v-if="navChartData.length" ref="navChartEl" class="nav-chart" aria-label="历史净值走势"></div>
      <p v-else class="empty-chart">暂无历史净值数据，点击“更新历史净值”从 akshare 同步。</p>
      <a v-if="navChartData.length" class="nav-chart-attribution" href="https://www.tradingview.com/" target="_blank" rel="noreferrer">
        Charts by TradingView
      </a>
    </section>

    <section class="section-title">
      <div>
        <p class="eyebrow">Estimate Logs</p>
        <h2>估算执行日志</h2>
      </div>
      <span>{{ taskDetailLogs.length }} 条</span>
    </section>

    <div class="table-card">
      <table class="responsive-card-table quality-table">
        <thead>
          <tr>
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
          <tr v-if="taskDetailLogs.length === 0">
            <td colspan="7">暂无基金级估算执行日志。</td>
          </tr>
          <tr v-for="log in taskDetailLogs" :key="log.id">
            <td data-label="执行时间">{{ formatDateTime(log.estimate_time || log.created_at) }}</td>
            <td data-label="状态">
              <span class="status-pill" :class="statusClass(log.status)">{{ log.status_label || statusLabel(log.status) }}</span>
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
      <table class="responsive-card-table holdings-table">
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
            <td data-label="报告期">{{ holding.report_period }}</td>
            <td class="mono" data-label="资产代码">{{ holding.asset_code }}</td>
            <td data-label="资产名称">{{ holding.asset_name }}</td>
            <td data-label="资产类型">{{ holding.asset_type }}</td>
            <td data-label="市场">{{ holding.market ?? '-' }}</td>
            <td data-label="持仓比例">{{ percent(holding.holding_ratio) }}</td>
            <td data-label="持仓市值">{{ holding.holding_value ?? '-' }}</td>
            <td data-label="来源">{{ holding.source }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </main>
</template>
