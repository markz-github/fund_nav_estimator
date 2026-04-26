<script setup lang="ts">
import { RouterLink } from 'vue-router'
import type { Fund } from '../api/funds'

defineProps<{
  funds: Fund[]
  loading?: boolean
}>()

const emit = defineEmits<{
  delete: [fundCode: string]
  refresh: [fundCode: string]
}>()

function percent(value?: string | null) {
  if (!value) return '-'
  return `${(Number(value) * 100).toFixed(2)}%`
}
</script>

<template>
  <div class="table-card">
    <table>
      <thead>
        <tr>
          <th>基金代码</th>
          <th>基金名称</th>
          <th>官方净值</th>
          <th>净值日期</th>
          <th>估算净值</th>
          <th>估算涨跌幅</th>
          <th>估算时间</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="loading">
          <td colspan="8">正在加载基金池...</td>
        </tr>
        <tr v-else-if="funds.length === 0">
          <td colspan="8">还没有自选基金，先添加一只试试。</td>
        </tr>
        <tr v-for="fund in funds" :key="fund.fund_code">
          <td class="mono">{{ fund.fund_code }}</td>
          <td>{{ fund.fund_name }}</td>
          <td>{{ fund.latest_unit_nav ?? '-' }}</td>
          <td>{{ fund.latest_nav_date ?? '-' }}</td>
          <td>{{ fund.latest_estimated_nav ?? '-' }}</td>
          <td>{{ percent(fund.latest_estimated_growth_rate) }}</td>
          <td>{{ fund.latest_estimate_time ?? '-' }}</td>
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
