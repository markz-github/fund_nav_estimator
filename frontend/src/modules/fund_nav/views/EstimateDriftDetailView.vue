<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import {
  ColorType,
  CrosshairMode,
  LineSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type Time,
} from 'lightweight-charts'
import { apiErrorMessage } from '../../../api/client'
import { formatDateTime } from '../../../utils/datetime'
import { routeNames } from '../../../router/routeNames'
import { getEstimateDriftDetail, type EstimateDriftDetail, type EstimateDriftPoint } from '../api/quality'

const route = useRoute()
const fundCode = computed(() => String(route.params.fundCode || ''))
const detail = ref<EstimateDriftDetail | null>(null)
const loading = ref(false)
const message = ref('')
const endDate = ref(queryText('end_date') || todayText())
const startDate = ref(queryText('start_date') || daysAgoText(59))
const thresholdPercent = ref(queryText('threshold') || '')
const chartEl = ref<HTMLElement | null>(null)
let chart: IChartApi | null = null
let driftSeries: ISeriesApi<'Line'> | null = null
let thresholdLine: IPriceLine | null = null
let resizeObserver: ResizeObserver | null = null

const points = computed(() => detail.value?.points ?? [])
const chartData = computed(() =>
  points.value.map((point) => ({
    time: point.estimate_date as Time,
    value: Number(point.difference_rate) * 100,
    color: driftLevelColor(point.difference_rate),
  })),
)
const thresholdDecimal = computed(() => percentInputToDecimal(thresholdPercent.value))

function queryText(key: string) {
  const value = route.query[key]
  return typeof value === 'string' ? value : ''
}

function todayText() {
  return new Date().toISOString().slice(0, 10)
}

function daysAgoText(days: number) {
  const value = new Date()
  value.setDate(value.getDate() - days)
  return value.toISOString().slice(0, 10)
}

function percentInputToDecimal(value: string) {
  const numericValue = Number(value)
  if (!Number.isFinite(numericValue) || numericValue <= 0) return ''
  return String(numericValue / 100)
}

function percent(value?: string | null) {
  if (value == null) return '-'
  return `${(Number(value) * 100).toFixed(2)}%`
}

function signedNav(value?: string | null) {
  if (value == null) return '-'
  const numericValue = Number(value)
  const sign = numericValue > 0 ? '+' : ''
  return `${sign}${numericValue.toFixed(6)}`
}

function driftLevelClass(value?: string | null) {
  if (value == null) return 'status-muted'
  const percentValue = Number(value) * 100
  if (!Number.isFinite(percentValue)) return 'status-muted'
  if (percentValue >= 3) return 'status-deep-danger'
  if (percentValue >= 2) return 'status-danger'
  if (percentValue >= 1) return 'status-warn'
  return 'status-ok'
}

function driftLevelColor(value?: string | null) {
  const className = driftLevelClass(value)
  if (className === 'status-deep-danger') return '#651b16'
  if (className === 'status-danger') return '#a43f35'
  if (className === 'status-warn') return '#b66a00'
  return '#287356'
}

function driftRowClass(point: EstimateDriftPoint) {
  const className = driftLevelClass(point.difference_rate)
  return {
    'drift-row-warn': className === 'status-warn',
    'drift-row-danger': className === 'status-danger',
    'drift-row-deep-danger': className === 'status-deep-danger',
  }
}

function chartDateLabel(time: Time) {
  if (typeof time === 'string') return time
  if (typeof time === 'number') return new Date(time * 1000).toISOString().slice(0, 10)
  return `${time.year}-${String(time.month).padStart(2, '0')}-${String(time.day).padStart(2, '0')}`
}

async function loadDetail() {
  loading.value = true
  message.value = ''
  try {
    detail.value = await getEstimateDriftDetail(fundCode.value, {
      startDate: startDate.value,
      endDate: endDate.value,
      threshold: thresholdDecimal.value,
    })
    await renderChart()
  } catch (error) {
    message.value = apiErrorMessage(error, '估算偏差走势加载失败，请确认后端服务是否正常。')
  } finally {
    loading.value = false
  }
}

function ensureChart() {
  if (!chartEl.value || chart) return
  chart = createChart(chartEl.value, {
    width: chartEl.value.clientWidth,
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
    crosshair: { mode: CrosshairMode.Normal },
    rightPriceScale: {
      borderColor: 'rgba(36, 63, 47, 0.16)',
      minimumWidth: 96,
      entireTextOnly: true,
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
      priceFormatter: (price: number) => `${price.toFixed(2)}%`,
      timeFormatter: (time: Time) => chartDateLabel(time),
    },
  })
  driftSeries = chart.addSeries(LineSeries, {
    color: '#287356',
    lineWidth: 2,
    priceLineVisible: false,
    lastValueVisible: false,
  })
  resizeObserver = new ResizeObserver((entries) => {
    const width = entries[0]?.contentRect.width
    if (width && chart) chart.applyOptions({ width })
  })
  resizeObserver.observe(chartEl.value)
}

function updateThresholdLine() {
  if (!driftSeries) return
  if (thresholdLine) {
    driftSeries.removePriceLine(thresholdLine)
    thresholdLine = null
  }
  const thresholdValue = Number(thresholdPercent.value)
  if (!Number.isFinite(thresholdValue) || thresholdValue <= 0) return
  thresholdLine = driftSeries.createPriceLine({
    price: thresholdValue,
    color: '#a43f35',
    lineWidth: 1,
    lineStyle: LineStyle.Dashed,
    lineVisible: true,
    axisLabelVisible: true,
    axisLabelColor: '#a43f35',
    axisLabelTextColor: '#ffffff',
    title: '阈值',
  })
}

async function renderChart() {
  await nextTick()
  if (chartData.value.length === 0) {
    disposeChart()
    return
  }
  ensureChart()
  driftSeries?.setData(chartData.value)
  updateThresholdLine()
  chart?.timeScale().fitContent()
}

function disposeChart() {
  resizeObserver?.disconnect()
  resizeObserver = null
  thresholdLine = null
  chart?.remove()
  chart = null
  driftSeries = null
}

watch(chartData, renderChart)
onMounted(loadDetail)
onBeforeUnmount(disposeChart)
</script>

<template>
  <main class="page-shell">
    <RouterLink class="back-link" :to="{ name: routeNames.estimateDriftList }">返回估算偏差</RouterLink>

    <section class="detail-hero">
      <div>
        <p class="eyebrow">Estimate Drift</p>
        <h1>{{ detail?.fund_name || fundCode }}</h1>
        <p class="subtitle">查看单只基金在已有官方净值日期上的估算偏差走势。</p>
      </div>
      <span class="code-badge">{{ fundCode }}</span>
    </section>

    <p v-if="message" class="message">{{ message }}</p>

    <form class="filter-bar compact-filter" @submit.prevent="loadDetail">
      <label>
        开始日期
        <input v-model="startDate" type="date" />
      </label>
      <label>
        结束日期
        <input v-model="endDate" type="date" />
      </label>
      <label>
        阈值 %
        <input v-model="thresholdPercent" inputmode="decimal" placeholder="不填则只看趋势" />
      </label>
      <div class="filter-actions">
        <button class="ghost" type="submit" :disabled="loading">应用</button>
        <button class="ghost" type="button" :disabled="loading" @click="thresholdPercent = ''; loadDetail()">清空阈值</button>
      </div>
    </form>

    <section class="info-grid quality-summary-grid">
      <article class="info-card">
        <span>可比较天数</span>
        <strong>{{ detail?.comparable_count ?? 0 }}</strong>
      </article>
      <article class="info-card">
        <span>最大偏差率</span>
        <strong>{{ percent(detail?.max_difference_rate) }}</strong>
      </article>
      <article class="info-card">
        <span>平均偏差率</span>
        <strong>{{ percent(detail?.avg_difference_rate) }}</strong>
      </article>
      <article class="info-card">
        <span>超阈值次数</span>
        <strong>{{ thresholdDecimal ? detail?.threshold_exceeded_count ?? 0 : '-' }}</strong>
      </article>
    </section>

    <section class="nav-chart-panel">
      <div class="nav-chart-meta">
        <div>
          <span>日期范围</span>
          <strong>{{ detail?.start_date ?? startDate }} - {{ detail?.end_date ?? endDate }}</strong>
        </div>
        <div>
          <span>阈值</span>
          <strong>{{ thresholdPercent || '未设置' }}{{ thresholdPercent ? '%' : '' }}</strong>
        </div>
        <div>
          <span>数据点</span>
          <strong>{{ points.length }}</strong>
        </div>
        <div>
          <span>最近估算时间</span>
          <strong>{{ points.length ? formatDateTime(points[points.length - 1].estimate_time) : '-' }}</strong>
        </div>
      </div>
      <div v-if="chartData.length" ref="chartEl" class="nav-chart" aria-label="估算偏差走势"></div>
      <p v-else class="empty-chart">该日期范围内暂无可比较的官方净值和估算数据。</p>
    </section>

    <div class="table-card">
      <table class="quality-table responsive-card-table">
        <thead>
          <tr>
            <th>日期</th>
            <th>预估净值</th>
            <th>官方净值</th>
            <th>差值</th>
            <th>偏差率</th>
            <th>估算时间</th>
            <th>覆盖率</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="points.length === 0">
            <td colspan="7">暂无明细。</td>
          </tr>
          <tr v-for="point in points" :key="point.estimate_date" :class="driftRowClass(point)">
            <td class="mono" data-label="日期">{{ point.estimate_date }}</td>
            <td class="mono" data-label="预估净值">{{ point.estimated_nav }}</td>
            <td class="mono" data-label="官方净值">{{ point.official_nav }}</td>
            <td class="mono" data-label="差值">{{ signedNav(point.absolute_difference) }}</td>
            <td data-label="偏差率">
              <span class="status-pill" :class="driftLevelClass(point.difference_rate)">
                {{ percent(point.difference_rate) }}
              </span>
            </td>
            <td data-label="估算时间">{{ formatDateTime(point.estimate_time) }}</td>
            <td data-label="覆盖率">{{ percent(point.coverage_ratio) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </main>
</template>
