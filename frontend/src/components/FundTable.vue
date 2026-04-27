<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import type { Fund } from '../api/funds'

const props = defineProps<{
  funds: Fund[]
  loading?: boolean
  selectedFundCodes: string[]
}>()

const emit = defineEmits<{
  delete: [fundCode: string]
  refresh: [fundCode: string]
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

function statusText(fund: Fund) {
  if (!fund.latest_unit_nav) return '缺官方净值'
  if (!fund.latest_estimated_nav) return '待估算'
  if (fund.latest_coverage_ratio && Number(fund.latest_coverage_ratio) < 0.6) return '覆盖率偏低'
  return '正常'
}

function statusClass(fund: Fund) {
  return statusText(fund) === '正常' ? 'status-ok' : 'status-warn'
}
</script>

<template>
  <div class="table-card">
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
          <th>基金代码</th>
          <th>基金名称</th>
          <th>官方净值</th>
          <th>净值日期</th>
          <th>估算净值</th>
          <th>估算涨跌幅</th>
          <th>覆盖率</th>
          <th>估算时间</th>
          <th>数据状态</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="loading">
          <td colspan="11">正在加载基金池...</td>
        </tr>
        <tr v-else-if="funds.length === 0">
          <td colspan="11">还没有自选基金，先添加一只试试。</td>
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
          <td class="mono">{{ fund.fund_code }}</td>
          <td>{{ fund.fund_name }}</td>
          <td>{{ fund.latest_unit_nav ?? '-' }}</td>
          <td>{{ fund.latest_nav_date ?? '-' }}</td>
          <td>{{ fund.latest_estimated_nav ?? '-' }}</td>
          <td>{{ percent(fund.latest_estimated_growth_rate) }}</td>
          <td>{{ percent(fund.latest_coverage_ratio) }}</td>
          <td>{{ fund.latest_estimate_time ?? '-' }}</td>
          <td><span class="status-pill" :class="statusClass(fund)">{{ statusText(fund) }}</span></td>
          <td class="actions">
            <RouterLink class="link-button" :to="`/funds/${fund.fund_code}`">查看详情</RouterLink>
            <button class="ghost" @click="emit('refresh', fund.fund_code)">刷新净值</button>
            <button class="danger" @click="emit('delete', fund.fund_code)">删除</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
