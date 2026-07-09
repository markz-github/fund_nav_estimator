<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { apiErrorMessage } from '../../../api/client'
import { routeNames } from '../../../router/routeNames'
import { listIndexQuoteSources, updateIndexQuoteSource, type IndexQuoteSourceStatus } from '../api/market'

const sources = ref<IndexQuoteSourceStatus[]>([])
const loading = ref(false)
const message = ref('')
const popover = ref({ text: '', top: 0, left: 0, visible: false })
const activeSourceType = ref<'index' | 'stock' | 'etf'>('index')
const savingSourceKey = ref('')
const ruleForms = ref<Record<string, { source_description: string; exclude_rule_type: string; exclude_rule_value: string }>>({})

const sourceGroups = computed(() => [
  {
    key: 'index',
    title: '指数渠道',
    items: sources.value.filter((item) => item.source_type === 'index'),
  },
  {
    key: 'stock',
    title: '股票渠道',
    items: sources.value.filter((item) => item.source_type === 'stock'),
  },
  {
    key: 'etf',
    title: 'ETF 渠道',
    items: sources.value.filter((item) => item.source_type === 'etf'),
  },
])
const activeGroup = computed(() => sourceGroups.value.find((group) => group.key === activeSourceType.value) ?? sourceGroups.value[0])

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
    resetRuleForms()
  } catch (error) {
    message.value = apiErrorMessage(error, '渠道数据加载失败，请确认后端服务。')
  } finally {
    loading.value = false
  }
}

function resetRuleForms() {
  ruleForms.value = Object.fromEntries(
    sources.value.map((item) => [
      item.source_key,
      {
        source_description: item.source_description || '',
        exclude_rule_type: item.exclude_rule_type || 'none',
        exclude_rule_value: item.exclude_rule_value || '',
      },
    ]),
  )
}

function ruleTypeLabel(type?: string | null) {
  if (type === 'regex') return '正则'
  if (type === 'enum') return '枚举'
  return '无'
}

async function saveRule(item: IndexQuoteSourceStatus) {
  const form = ruleForms.value[item.source_key]
  if (!form) return
  savingSourceKey.value = item.source_key
  message.value = ''
  try {
    const updated = await updateIndexQuoteSource(item.source_key, {
      source_description: form.source_description,
      exclude_rule_type: form.exclude_rule_type,
      exclude_rule_value: form.exclude_rule_value,
    })
    sources.value = sources.value.map((source) => (source.source_key === updated.source_key ? updated : source))
    resetRuleForms()
  } catch (error) {
    message.value = apiErrorMessage(error, '渠道规则保存失败，请检查正则或枚举配置。')
  } finally {
    savingSourceKey.value = ''
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

    <el-tabs v-model="activeSourceType" class="source-tabs">
      <el-tab-pane v-for="group in sourceGroups" :key="group.key" :name="group.key">
        <template #label>
          <span class="source-tab-label">
            <span>{{ group.title }}</span>
            <strong>{{ group.items.length }}</strong>
          </span>
        </template>
      </el-tab-pane>
    </el-tabs>

    <div
      :id="`source-panel-${activeGroup.key}`"
      class="table-card source-group-card"
    >
      <table class="responsive-card-table quote-source-table">
        <thead>
          <tr>
            <th>排序</th>
            <th>渠道</th>
            <th>说明</th>
            <th>排除规则</th>
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
          <tr v-if="activeGroup.items.length === 0">
            <td colspan="14">暂无{{ activeGroup.title }}。</td>
          </tr>
          <tr v-for="(item, index) in activeGroup.items" :key="item.source_key">
            <td data-label="排序">{{ index + 1 }}</td>
            <td data-label="渠道">
              <strong>{{ item.source_name }}</strong>
              <span class="muted code-line">{{ item.source_key }}</span>
            </td>
            <td
              data-label="说明"
              class="log-text-cell source-description-cell"
              tabindex="0"
              @mouseenter="showTextPopover($event, item.source_description)"
              @mouseleave="hideTextPopover"
              @focus="showTextPopover($event, item.source_description)"
              @blur="hideTextPopover"
            >
              <span class="log-text-preview">{{ item.source_description || '-' }}</span>
            </td>
            <td data-label="排除规则" class="rule-cell">
              <div class="rule-editor" v-if="ruleForms[item.source_key]">
                <ElSelect v-model="ruleForms[item.source_key].exclude_rule_type" size="small" class="rule-type-select">
                  <ElOption label="无" value="none" />
                  <ElOption label="正则" value="regex" />
                  <ElOption label="枚举" value="enum" />
                </ElSelect>
                <textarea
                  v-model="ruleForms[item.source_key].exclude_rule_value"
                  :disabled="ruleForms[item.source_key].exclude_rule_type === 'none'"
                  :placeholder="ruleForms[item.source_key].exclude_rule_type === 'regex' ? '^9' : '930875,931027'"
                />
                <button
                  class="ghost rule-save-button"
                  type="button"
                  :disabled="savingSourceKey === item.source_key"
                  @click="saveRule(item)"
                >
                  {{ savingSourceKey === item.source_key ? '保存中' : '保存' }}
                </button>
              </div>
              <span class="muted rule-summary">
                {{ ruleTypeLabel(item.exclude_rule_type) }}{{ item.exclude_rule_value ? `：${item.exclude_rule_value}` : '' }}
              </span>
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
  min-width: 1520px;
}

.code-line {
  display: block;
  margin-top: 4px;
  font-family: ui-monospace, SFMono-Regular, Consolas, 'Liberation Mono', monospace;
  font-size: 12px;
}

.source-tabs {
  margin: 28px 0 12px;
}

.source-tab-label {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 17px;
  font-weight: 800;
}

.source-tab-label strong {
  min-width: 24px;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 12px;
  line-height: 20px;
  text-align: center;
}

.source-group-card {
  margin-bottom: 32px;
}

.source-description-cell {
  max-width: 240px;
}

.rule-cell {
  min-width: 260px;
}

.rule-editor {
  display: grid;
  grid-template-columns: 86px minmax(130px, 1fr) auto;
  gap: 8px;
  align-items: start;
}

.rule-type-select {
  width: 86px;
}

.rule-editor textarea {
  min-height: 34px;
  max-height: 86px;
  resize: vertical;
  border: 1px solid var(--border-subtle);
  border-radius: 6px;
  padding: 7px 9px;
  background: var(--surface);
  color: var(--text-main);
  font: inherit;
  font-size: 13px;
}

.rule-editor textarea:disabled {
  color: var(--text-muted);
  background: var(--surface-muted);
}

.rule-save-button {
  min-height: 32px;
  padding: 0 10px;
}

.rule-summary {
  display: block;
  margin-top: 6px;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

</style>
