<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { Fund, FundSortBy, SortOrder } from '../api/funds'

const props = defineProps<{
  funds: Fund[]
  loading?: boolean
  selectedFundCodes: string[]
  sortBy?: FundSortBy | null
  sortOrder?: SortOrder
}>()

const emit = defineEmits<{
  delete: [fundCode: string]
  refresh: [fundCode: string]
  sort: [sortBy: FundSortBy]
  'update:selectedFundCodes': [fundCodes: string[]]
}>()

const allSelected = computed(
  () => props.funds.length > 0 && props.funds.every((fund) => props.selectedFundCodes.includes(fund.fund_code)),
)

function toggleFund(fundCode: string, checked: boolean) {
  if (checked) {
    emit('update:selectedFundCodes', Array.from(new Set([...props.selectedFundCodes, fundCode])))
    return
  }
  emit(
    'update:selectedFundCodes',
    props.selectedFundCodes.filter((code) => code !== fundCode),
  )
}

function toggleAll(checked: boolean) {
  emit('update:selectedFundCodes', checked ? props.funds.map((fund) => fund.fund_code) : [])
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

function shortDateTime(value?: string | null) {
  if (!value) return '-'
  return value.replace('T', ' ').slice(0, 16)
}

function statusText(fund: Fund) {
  if (!fund.latest_unit_nav) return '缺官方净值'
  if (!fund.latest_estimated_nav) return '待估算'
  if (fund.latest_coverage_ratio && Number(fund.latest_coverage_ratio) < 0.6) return '覆盖率偏低'
  return '正常'
}

function statusClass(fund: Fund) {
  return statusText(fund) === '正常' ? 'status-ok' : 'status-warn'
}

function sortIndicator(sortBy: FundSortBy) {
  if (props.sortBy !== sortBy) return '↕'
  return props.sortOrder === 'asc' ? '↑' : '↓'
}
</script>

<template>
  <div class="table-card fund-table-card">
    <table>
      <thead>
        <tr>
          <th>
            <input
              class="row-check"
              type="checkbox"
              :checked="allSelected"
              :disabled="loading || funds.length === 0"
              @change="toggleAll(($event.target as HTMLInputElement).checked)"
            />
          </th>
          <th>基金资产</th>
          <th>最新估算数据</th>
          <th>
            <button class="sort-header" type="button" :disabled="loading" @click="emit('sort', 'latest_estimated_growth_rate')">
              涨跌幅 <span aria-hidden="true">{{ sortIndicator('latest_estimated_growth_rate') }}</span>
            </button>
          </th>
          <th>估算状态</th>
          <th>官方净值</th>
          <th>快捷操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="loading">
          <td colspan="7">正在加载基金池...</td>
        </tr>
        <tr v-else-if="funds.length === 0">
          <td colspan="7">还没有自选基金，先添加一只试试。</td>
        </tr>
        <tr v-for="fund in funds" :key="fund.fund_code">
          <td>
            <input
              class="row-check"
              type="checkbox"
              :checked="selectedFundCodes.includes(fund.fund_code)"
              @change="toggleFund(fund.fund_code, ($event.target as HTMLInputElement).checked)"
            />
          </td>
          <td class="fund-cell">
            <RouterLink class="fund-name" :to="`/funds/${fund.fund_code}`">{{ fund.fund_name }}</RouterLink>
            <span class="muted mono">{{ fund.fund_code }}</span>
          </td>
          <td>
            <strong class="metric">{{ fund.latest_estimated_nav ?? '-' }}</strong>
            <span class="muted">{{ shortDateTime(fund.latest_estimate_time) }}</span>
          </td>
          <td>
            <strong class="metric change-rate" :class="growthClass(fund.latest_estimated_growth_rate)">
              {{ growthPercent(fund.latest_estimated_growth_rate) }}
            </strong>
          </td>
          <td class="status-cell">
            <span class="status-pill" :class="statusClass(fund)">{{ statusText(fund) }}</span>
            <span class="muted">覆盖 {{ percent(fund.latest_coverage_ratio) }}</span>
          </td>
          <td>
            <div class="benchmark-cell">
              <div>
                <strong class="metric">{{ fund.latest_unit_nav ?? '-' }}</strong>
                <span class="muted">{{ fund.latest_nav_date ?? '-' }}</span>
              </div>
              <strong class="inline-growth" :class="growthClass(fund.latest_daily_growth_rate)">
                {{ growthPercent(fund.latest_daily_growth_rate) }}
              </strong>
            </div>
          </td>
          <td>
            <div class="quick-actions">
              <RouterLink class="link-button" :to="`/funds/${fund.fund_code}`">详情</RouterLink>
              <button class="ghost" @click="emit('refresh', fund.fund_code)">刷新</button>
              <button class="danger" @click="emit('delete', fund.fund_code)">删除</button>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
