<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { apiErrorMessage } from '../../../api/client'
import { routeNames } from '../../../router/routeNames'
import { getFund, listFundHoldings, type Fund, type FundHolding } from '../api/funds'

const route = useRoute()
const fundCode = computed(() => String(route.params.fundCode || ''))
const reportPeriod = computed(() => String(route.params.reportPeriod || ''))
const fund = ref<Fund | null>(null)
const holdings = ref<FundHolding[]>([])
const loading = ref(false)
const message = ref('')

const reportTitle = computed(() => {
  const value = reportPeriod.value
  if (/^\d{4}Q[1-4]$/.test(value)) return `${value.slice(0, 4)} 年第 ${value.slice(-1)} 季度报告`
  if (/^\d{4}H1$/.test(value)) return `${value.slice(0, 4)} 年中期报告`
  if (/^\d{4}Y$/.test(value)) return `${value.slice(0, 4)} 年年度报告`
  return `${value} 报告`
})

const totalRatio = computed(() => holdings.value.reduce((total, item) => total + Number(item.holding_ratio || 0), 0))
const assetGroups = computed(() => {
  const groups = new Map<string, number>()
  for (const holding of holdings.value) {
    groups.set(holding.asset_type, (groups.get(holding.asset_type) ?? 0) + Number(holding.holding_ratio || 0))
  }
  return [...groups.entries()].map(([type, ratio]) => ({ type, ratio })).sort((a, b) => b.ratio - a.ratio)
})
const marketGroups = computed(() => {
  const groups = new Map<string, number>()
  for (const holding of holdings.value) {
    const market = holding.market || '未识别'
    groups.set(market, (groups.get(market) ?? 0) + Number(holding.holding_ratio || 0))
  }
  return [...groups.entries()].map(([market, ratio]) => ({ market, ratio })).sort((a, b) => b.ratio - a.ratio)
})

function percent(value: number | string | null | undefined) {
  if (value == null || value === '') return '-'
  return `${(Number(value) * 100).toFixed(2)}%`
}

function assetTypeLabel(value: string) {
  return ({ stock: '股票', bond: '债券', etf: 'ETF', fund: '基金' } as Record<string, string>)[value] || value
}

async function load() {
  loading.value = true
  message.value = ''
  try {
    const [fundResult, holdingsResult] = await Promise.all([getFund(fundCode.value), listFundHoldings(fundCode.value)])
    fund.value = fundResult
    holdings.value = holdingsResult
      .filter((item) => item.report_period === reportPeriod.value)
      .sort((a, b) => Number(b.holding_ratio) - Number(a.holding_ratio))
  } catch (error) {
    message.value = apiErrorMessage(error, '报告详情加载失败，请稍后重试。')
  } finally {
    loading.value = false
  }
}

watch([fundCode, reportPeriod], load)
onMounted(load)
</script>

<template>
  <main class="page-shell">
    <RouterLink class="back-link" :to="{ name: routeNames.fundDetail, params: { fundCode } }">返回基金详情</RouterLink>

    <section class="detail-hero">
      <div>
        <p class="eyebrow">Fund Report</p>
        <h1>{{ reportTitle }}</h1>
        <p class="subtitle">{{ fund?.fund_name ?? fundCode }}（{{ fundCode }}）的已结构化报告数据。</p>
      </div>
      <span class="code-badge">{{ reportPeriod }}</span>
    </section>

    <p v-if="message" class="message">{{ message }}</p>
    <p v-if="loading" class="message">正在加载报告详情...</p>

    <section v-if="!loading" class="info-grid">
      <article class="info-card"><span>已入库证券数</span><strong>{{ holdings.length }}</strong></article>
      <article class="info-card"><span>已披露持仓合计</span><strong>{{ percent(totalRatio) }}</strong></article>
      <article class="info-card"><span>未具名/非证券部分</span><strong>{{ percent(Math.max(0, 1 - totalRatio)) }}</strong></article>
    </section>

    <p v-if="!loading && holdings.length === 0" class="message">该报告期暂无已入库的持仓数据。请先在基金详情刷新持仓。</p>
    <p v-else-if="!loading" class="message">
      当前系统保存的是报告中的证券持仓明细；行业配置、现金及其他资产等整份报告字段尚未接入，因此“未具名/非证券部分”不能直接视为遗漏股票。
    </p>

    <template v-if="holdings.length">
      <section class="section-title"><div><p class="eyebrow">Summary</p><h2>已入库配置汇总</h2></div></section>
      <div class="report-summary-grid">
        <article class="table-card report-summary-card"><h3>按资产类型</h3><dl><div v-for="item in assetGroups" :key="item.type"><dt>{{ assetTypeLabel(item.type) }}</dt><dd>{{ percent(item.ratio) }}</dd></div></dl></article>
        <article class="table-card report-summary-card"><h3>按市场</h3><dl><div v-for="item in marketGroups" :key="item.market"><dt>{{ item.market }}</dt><dd>{{ percent(item.ratio) }}</dd></div></dl></article>
      </div>

      <section class="section-title"><div><p class="eyebrow">Holdings</p><h2>证券持仓明细</h2></div></section>
      <div class="table-card">
        <table class="responsive-card-table holdings-table"><thead><tr><th>资产代码</th><th>资产名称</th><th>资产类型</th><th>市场</th><th>持仓比例</th><th>持仓市值</th><th>来源</th></tr></thead>
          <tbody><tr v-for="holding in holdings" :key="holding.asset_code"><td class="mono" data-label="资产代码">{{ holding.asset_code }}</td><td data-label="资产名称">{{ holding.asset_name }}</td><td data-label="资产类型">{{ assetTypeLabel(holding.asset_type) }}</td><td data-label="市场">{{ holding.market ?? '-' }}</td><td data-label="持仓比例">{{ percent(holding.holding_ratio) }}</td><td data-label="持仓市值">{{ holding.holding_value ?? '-' }}</td><td data-label="来源">{{ holding.source }}</td></tr></tbody>
        </table>
      </div>
    </template>
  </main>
</template>
