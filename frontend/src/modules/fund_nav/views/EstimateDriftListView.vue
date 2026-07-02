<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { apiErrorMessage } from '../../../api/client'
import { routeNames } from '../../../router/routeNames'
import { listEstimateDriftFunds, type EstimateDriftFundSummary } from '../api/quality'

const router = useRouter()
const summaries = ref<EstimateDriftFundSummary[]>([])
const loading = ref(false)
const message = ref('')
const endDate = ref(todayText())
const startDate = ref(daysAgoText(59))
const thresholdPercent = ref('')

const abnormalCount = computed(() =>
  thresholdDecimal.value
    ? summaries.value.filter((item) => item.threshold_exceeded_count > 0).length
    : 0,
)
const comparableFundCount = computed(() => summaries.value.filter((item) => item.comparable_count > 0).length)
const thresholdDecimal = computed(() => percentInputToDecimal(thresholdPercent.value))

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

function driftLevelClass(value?: string | null) {
  if (value == null) return 'status-muted'
  const percentValue = Number(value) * 100
  if (!Number.isFinite(percentValue)) return 'status-muted'
  if (percentValue >= 3) return 'status-deep-danger'
  if (percentValue >= 2) return 'status-danger'
  if (percentValue >= 1) return 'status-warn'
  return 'status-ok'
}

function thresholdText() {
  return thresholdPercent.value.trim() ? `${thresholdPercent.value.trim()}%` : '未设置'
}

function detailQuery() {
  return {
    start_date: startDate.value || undefined,
    end_date: endDate.value || undefined,
    threshold: thresholdPercent.value.trim() || undefined,
  }
}

async function loadSummaries() {
  loading.value = true
  message.value = ''
  try {
    summaries.value = await listEstimateDriftFunds({
      startDate: startDate.value,
      endDate: endDate.value,
      threshold: thresholdDecimal.value,
    })
  } catch (error) {
    message.value = apiErrorMessage(error, '估算偏差列表加载失败，请确认后端服务是否正常。')
  } finally {
    loading.value = false
  }
}

function openDetail(fundCode: string) {
  router.push({
    name: routeNames.estimateDriftDetail,
    params: { fundCode },
    query: detailQuery(),
  })
}

onMounted(loadSummaries)
</script>

<template>
  <main class="page-shell">
    <RouterLink class="back-link" :to="{ name: routeNames.fundNavQuality }">返回净值巡检</RouterLink>

    <section class="detail-hero">
      <div>
        <p class="eyebrow">Estimate Drift</p>
        <h1>估算偏差</h1>
        <p class="subtitle">按基金汇总已披露官方净值日期上的估算偏差，点击基金查看走势。</p>
      </div>
      <button class="ghost" :disabled="loading" @click="loadSummaries">
        {{ loading ? '刷新中...' : '刷新列表' }}
      </button>
    </section>

    <p v-if="message" class="message">{{ message }}</p>

    <form class="filter-bar compact-filter" @submit.prevent="loadSummaries">
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
        <button class="ghost" type="button" :disabled="loading" @click="thresholdPercent = ''; loadSummaries()">清空阈值</button>
      </div>
    </form>

    <section class="info-grid quality-summary-grid">
      <article class="info-card">
        <span>有可比较数据的基金</span>
        <strong>{{ comparableFundCount }}</strong>
      </article>
      <article class="info-card">
        <span>阈值</span>
        <strong>{{ thresholdText() }}</strong>
      </article>
      <article class="info-card">
        <span>超阈值基金</span>
        <strong>{{ thresholdDecimal ? abnormalCount : '-' }}</strong>
      </article>
    </section>

    <div class="table-card">
      <table class="quality-table responsive-card-table">
        <thead>
          <tr>
            <th>基金</th>
            <th>可比较天数</th>
            <th>最大偏差率</th>
            <th>平均偏差率</th>
            <th>近7个交易日偏差率</th>
            <th>最近偏差率</th>
            <th>最近日期</th>
            <th>超阈值次数</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="summaries.length === 0">
            <td colspan="9">暂无估算偏差数据。</td>
          </tr>
          <tr v-for="item in summaries" :key="item.fund_code">
            <td data-label="基金">
              <button class="table-link-button" type="button" @click="openDetail(item.fund_code)">
                {{ item.fund_name }}
              </button>
              <span class="muted mono">{{ item.fund_code }}</span>
            </td>
            <td data-label="可比较天数">{{ item.comparable_count }}</td>
            <td data-label="最大偏差率">
              <span class="status-pill" :class="driftLevelClass(item.max_difference_rate)">
                {{ percent(item.max_difference_rate) }}
              </span>
            </td>
            <td data-label="平均偏差率">
              <span class="status-pill" :class="driftLevelClass(item.avg_difference_rate)">
                {{ percent(item.avg_difference_rate) }}
              </span>
            </td>
            <td data-label="近7个交易日偏差率">
              <span class="status-pill" :class="driftLevelClass(item.recent_7_trading_day_difference_rate)">
                {{ percent(item.recent_7_trading_day_difference_rate) }}
              </span>
            </td>
            <td data-label="最近偏差率">
              <span class="status-pill" :class="driftLevelClass(item.latest_difference_rate)">
                {{ percent(item.latest_difference_rate) }}
              </span>
            </td>
            <td class="mono" data-label="最近日期">{{ item.latest_date || '-' }}</td>
            <td data-label="超阈值次数">
              <span v-if="thresholdDecimal" class="status-pill" :class="item.threshold_exceeded_count ? 'status-warn' : 'status-ok'">
                {{ item.threshold_exceeded_count }}
              </span>
              <span v-else>-</span>
            </td>
            <td data-label="操作">
              <button class="ghost" type="button" @click="openDetail(item.fund_code)">查看走势</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </main>
</template>
