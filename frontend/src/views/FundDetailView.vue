<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
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
const loading = ref(false)
const refreshingHoldings = ref(false)
const message = ref('')

function percent(value?: string | null) {
  if (!value) return '-'
  return `${(Number(value) * 100).toFixed(2)}%`
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
  } catch (error) {
    message.value = '基金详情加载失败，请稍后重试。'
  } finally {
    loading.value = false
  }
}

async function refreshHoldings() {
  refreshingHoldings.value = true
  message.value = ''
  try {
    await refreshFundHoldings(fundCode.value)
    holdings.value = await listFundHoldings(fundCode.value)
  } catch (error) {
    message.value = '持仓刷新失败，请稍后重试。'
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
        <span>官方净值</span>
        <strong>{{ fund.latest_unit_nav ?? '-' }}</strong>
      </article>
      <article class="info-card">
        <span>净值日期</span>
        <strong>{{ fund.latest_nav_date ?? '-' }}</strong>
      </article>
      <article class="info-card">
        <span>估算净值</span>
        <strong>{{ fund.latest_estimated_nav ?? '-' }}</strong>
      </article>
      <article class="info-card">
        <span>估算涨跌幅</span>
        <strong>{{ percent(fund.latest_estimated_growth_rate) }}</strong>
      </article>
      <article class="info-card">
        <span>估算时间</span>
        <strong>{{ fund.latest_estimate_time ?? '-' }}</strong>
      </article>
    </section>

    <section class="section-title">
      <div>
        <p class="eyebrow">Portfolio</p>
        <h2>持仓情况</h2>
      </div>
      <div class="section-actions">
        <span>{{ holdings.length }} 条记录</span>
        <button class="ghost" :disabled="refreshingHoldings" @click="refreshHoldings">
          {{ refreshingHoldings ? '刷新中...' : '刷新持仓' }}
        </button>
      </div>
    </section>

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
          <tr v-for="holding in holdings" :key="`${holding.report_period}-${holding.asset_code}`">
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
