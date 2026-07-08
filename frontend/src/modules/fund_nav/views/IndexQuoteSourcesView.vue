<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { apiErrorMessage } from '../../../api/client'
import { routeNames } from '../../../router/routeNames'
import { listIndexQuoteSources, type IndexQuoteSourceStatus } from '../api/market'

const sources = ref<IndexQuoteSourceStatus[]>([])
const loading = ref(false)
const message = ref('')
const popover = ref({ text: '', top: 0, left: 0, visible: false })

const sourceGroups = computed(() => [
  {
    key: 'index',
    eyebrow: 'Index',
    title: '指数渠道',
    subtitle: '指数估值使用的实时行情源。',
    items: sources.value.filter((item) => item.source_type === 'index'),
  },
  {
    key: 'stock',
    eyebrow: 'Stock',
    title: '股票渠道',
    subtitle: '持仓股票估值使用的行情源。',
    items: sources.value.filter((item) => item.source_type === 'stock'),
  },
  {
    key: 'etf',
    eyebrow: 'ETF',
    title: 'ETF 渠道',
    subtitle: 'ETF 持仓和 ETF 净值估算使用的行情源。',
    items: sources.value.filter((item) => item.source_type === 'etf'),
  },
])

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

function percentText(value?: string | null) {
  if (value == null) return '-'
  return `${(Number(value) * 100).toFixed(2)}%`
}

function statusClass(item: IndexQuoteSourceStatus) {
  if (!item.enabled) return 'status-danger'
  if (item.status_label === '冷却中') return 'status-warn'
  return 'status-ok'
}

function showTextPopover(event: MouseEvent | FocusEvent, text?: string | null) {
  if (!text) return
  const element = event.currentTarget as HTMLElement
  const rect = element.getBoundingClientRect()
  const width = Math.min(720, window.innerWidth - 48)
  const pointerLeft = event instanceof MouseEvent ? event.clientX + 10 : rect.left
  const pointerTop = event instanceof MouseEvent ? event.clientY + 10 : rect.bottom + 6
  popover.value = {
    text,
    top: pointerTop,
    left: Math.min(Math.max(12, pointerLeft), window.innerWidth - width - 12),
    visible: true,
  }
}

function hideTextPopover() {
  popover.value.visible = false
}

async function loadSources() {
  loading.value = true
  message.value = ''
  try {
    sources.value = await listIndexQuoteSources()
  } catch (error) {
    message.value = apiErrorMessage(error, '渠道数据加载失败，请确认后端服务。')
  } finally {
    loading.value = false
  }
}

onMounted(loadSources)
</script>

<template>
  <main class="page-shell">
    <RouterLink class="back-link" :to="{ name: routeNames.fundList }">返回基金池</RouterLink>

    <section class="detail-hero">
      <div>
        <p class="eyebrow">Source Management</p>
        <h1>渠道管理</h1>
        <p class="subtitle">按指数、股票、ETF 分类查看行情渠道，当前 {{ sources.length }} 个。</p>
      </div>
      <button class="ghost" :disabled="loading" @click="loadSources">
        {{ loading ? '刷新中...' : '刷新' }}
      </button>
    </section>

    <p v-if="message" class="message">{{ message }}</p>

    <template v-for="group in sourceGroups" :key="group.key">
      <section class="section-title">
        <div>
          <p class="eyebrow">{{ group.eyebrow }}</p>
          <h2>{{ group.title }}</h2>
          <p class="group-subtitle">{{ group.subtitle }}</p>
        </div>
        <span>{{ group.items.length }} 个</span>
      </section>
      <div class="table-card source-group-card">
      <table class="responsive-card-table quote-source-table">
        <thead>
          <tr>
            <th>排序</th>
            <th>渠道</th>
            <th>状态</th>
            <th>优先级</th>
            <th>排序分</th>
            <th>成功率</th>
            <th>成功/失败</th>
            <th>连续失败</th>
            <th>冷却至</th>
            <th>最近成功</th>
            <th>最近失败</th>
            <th>最近错误</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="group.items.length === 0">
            <td colspan="12">暂无{{ group.title }}。</td>
          </tr>
          <tr v-for="(item, index) in group.items" :key="item.source_key">
            <td data-label="排序">{{ index + 1 }}</td>
            <td data-label="渠道">
              <strong>{{ item.source_name }}</strong>
              <span class="muted code-line">{{ item.source_key }}</span>
            </td>
            <td data-label="状态">
              <span class="status-pill" :class="statusClass(item)">{{ item.status_label }}</span>
            </td>
            <td data-label="优先级">{{ item.priority }}</td>
            <td data-label="排序分">{{ item.effective_priority }}</td>
            <td data-label="成功率">{{ percentText(item.success_rate) }}</td>
            <td data-label="成功/失败">{{ item.success_count }} / {{ item.failure_count }}</td>
            <td data-label="连续失败">{{ item.consecutive_failures }}</td>
            <td data-label="冷却至">{{ formatDateTime(item.auto_disabled_until) }}</td>
            <td data-label="最近成功">{{ formatDateTime(item.last_success_at) }}</td>
            <td data-label="最近失败">{{ formatDateTime(item.last_failure_at) }}</td>
            <td
              data-label="最近错误"
              class="log-text-cell"
              tabindex="0"
              @mouseenter="showTextPopover($event, item.last_error)"
              @mouseleave="hideTextPopover"
              @focus="showTextPopover($event, item.last_error)"
              @blur="hideTextPopover"
            >
              <span class="log-text-preview">{{ item.last_error || '-' }}</span>
            </td>
          </tr>
        </tbody>
      </table>
      </div>
    </template>
    <div
      v-if="popover.visible"
      class="log-text-popover"
      :style="{ top: `${popover.top}px`, left: `${popover.left}px` }"
      @mouseenter="popover.visible = true"
      @mouseleave="hideTextPopover"
    >
      {{ popover.text }}
    </div>
  </main>
</template>

<style scoped>
.quote-source-table {
  min-width: 1180px;
}

.code-line {
  display: block;
  margin-top: 4px;
  font-family: ui-monospace, SFMono-Regular, Consolas, 'Liberation Mono', monospace;
  font-size: 12px;
}

.group-subtitle {
  margin: 4px 0 0;
  color: var(--text-muted);
}

.source-group-card {
  margin-bottom: 32px;
}

</style>
