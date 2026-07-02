<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { apiErrorMessage } from '../../../api/client'
import { routeNames } from '../../../router/routeNames'
import { getFundNavQualityReport, type FundNavQualityReport } from '../api/quality'

const report = ref<FundNavQualityReport | null>(null)
const loading = ref(false)
const message = ref('')

const latestTask = computed(() => report.value?.latest_task ?? null)
const issues = computed(() => report.value?.issues ?? [])
const issueCount = computed(() => report.value?.issue_count ?? 0)

function formatDateTime(value?: string | null) {
  if (!value) return '-'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date(value))
}

function statusClass(status?: string | null) {
  if (status === 'success') return 'status-ok'
  if (status === 'failed') return 'status-danger'
  if (status === 'partial') return 'status-warn'
  return 'status-muted'
}

function statusLabel(status?: string | null) {
  if (status === 'success') return '正常'
  if (status === 'partial') return '发现问题'
  if (status === 'failed') return '执行失败'
  if (status === 'running') return '运行中'
  if (status === 'pending') return '待执行'
  return '未巡检'
}

function reasonLabel(reason?: string | null) {
  if (reason === 'missing_nav') return '缺少净值'
  if (reason === 'stale_nav') return '净值滞后'
  if (reason === 'missing_index_mapping') return '缺少跟踪指数'
  if (reason === 'missing_target_etf_mapping') return '缺少目标 ETF'
  return reason || '-'
}

function issueTypeLabel(type?: string | null) {
  if (type === 'fund_mapping') return '映射维护'
  return '净值巡检'
}

function navRuleLabel(rule?: string | null) {
  if (rule === 'qdii_delayed') return 'QDII 延迟规则'
  if (rule === 'standard') return '普通规则'
  return '-'
}

function mappingTypeLabel(type?: string | null) {
  if (type === 'index') return '跟踪指数'
  if (type === 'target_etf') return '目标 ETF'
  return '-'
}

async function loadReport() {
  loading.value = true
  message.value = ''
  try {
    report.value = await getFundNavQualityReport()
  } catch (error) {
    message.value = apiErrorMessage(error, '净值巡检结果加载失败，请确认后端服务是否正常。')
  } finally {
    loading.value = false
  }
}

onMounted(loadReport)
</script>

<template>
  <main class="page-shell">
    <RouterLink class="back-link" :to="{ name: routeNames.fundList }">返回基金池</RouterLink>

    <section class="detail-hero">
      <div>
        <p class="eyebrow">Quality Check</p>
        <h1>净值巡检</h1>
        <p class="subtitle">查看官方净值缺失、日期滞后，以及需要人工维护映射的基金。</p>
      </div>
      <button class="ghost" :disabled="loading" @click="loadReport">
        {{ loading ? '刷新中...' : '刷新结果' }}
      </button>
    </section>

    <p v-if="message" class="message">{{ message }}</p>

    <section class="info-grid quality-summary-grid">
      <article class="info-card">
        <span>最近巡检状态</span>
        <strong>
          <span class="status-pill" :class="statusClass(latestTask?.status)">
            {{ statusLabel(latestTask?.status) }}
          </span>
        </strong>
      </article>
      <article class="info-card">
        <span>当前问题数</span>
        <strong>{{ issueCount }}</strong>
      </article>
      <article class="info-card">
        <span>最近巡检时间</span>
        <strong>{{ formatDateTime(latestTask?.finished_at || latestTask?.started_at) }}</strong>
      </article>
    </section>

    <section class="section-title">
      <div>
        <p class="eyebrow">Issues</p>
        <h2>巡检问题清单</h2>
      </div>
      <div class="section-actions">
        <RouterLink class="link-button" :to="{ name: routeNames.estimateDriftList }">查看估算偏差</RouterLink>
        <RouterLink class="link-button" :to="{ name: routeNames.operations, query: { task_type: 'check_nav_quality' } }">
          查看巡检任务
        </RouterLink>
      </div>
    </section>

    <div class="table-card">
      <table class="quality-table responsive-card-table">
        <thead>
          <tr>
            <th>基金</th>
            <th>类型</th>
            <th>原因</th>
            <th>最新净值日期</th>
            <th>预期净值日期</th>
            <th>发现时间</th>
            <th>详情</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="issues.length === 0">
            <td colspan="7">暂无未解决巡检问题。</td>
          </tr>
          <tr v-for="issue in issues" :key="issue.id">
            <td data-label="基金">
              <RouterLink class="fund-name" :to="{ name: routeNames.fundDetail, params: { fundCode: issue.fund_code } }">
                {{ issue.fund_name || issue.fund_code }}
              </RouterLink>
              <span class="muted mono">{{ issue.fund_code }}</span>
            </td>
            <td data-label="类型">
              <span class="status-pill" :class="issue.issue_type === 'fund_mapping' ? 'status-danger' : 'status-warn'">
                {{ issueTypeLabel(issue.issue_type) }}
              </span>
              <span v-if="issue.issue_type === 'fund_mapping'" class="muted">{{ mappingTypeLabel(issue.mapping_type) }}</span>
            </td>
            <td data-label="原因">
              <span class="status-pill status-warn">{{ reasonLabel(issue.reason) }}</span>
              <span v-if="issue.issue_type !== 'fund_mapping'" class="muted">{{ navRuleLabel(issue.nav_rule) }}</span>
              <RouterLink
                v-else
                class="muted"
                :to="{ name: routeNames.manualIndexMappings }"
              >
                去维护
              </RouterLink>
            </td>
            <td class="mono" data-label="最新净值日期">{{ issue.latest_nav_date || '-' }}</td>
            <td class="mono" data-label="预期净值日期">{{ issue.expected_nav_date || '-' }}</td>
            <td data-label="发现时间">{{ formatDateTime(issue.occurred_at) }}</td>
            <td class="quality-message" data-label="详情">{{ issue.message }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </main>
</template>
