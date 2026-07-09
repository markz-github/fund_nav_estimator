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
const viewingSource = ref<IndexQuoteSourceStatus | null>(null)
const editingSource = ref<IndexQuoteSourceStatus | null>(null)
const ruleForm = ref({ source_description: '', exclude_rule_type: 'none', exclude_rule_value: '' })

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
  } catch (error) {
    message.value = apiErrorMessage(error, '渠道数据加载失败，请确认后端服务。')
  } finally {
    loading.value = false
  }
}

function ruleTypeLabel(type?: string | null) {
  if (type === 'regex') return '正则'
  if (type === 'enum') return '枚举'
  return '无'
}

function ruleSummary(item: IndexQuoteSourceStatus) {
  const label = ruleTypeLabel(item.exclude_rule_type)
  return item.exclude_rule_value ? `${label}：${item.exclude_rule_value}` : label
}

function openViewDialog(item: IndexQuoteSourceStatus) {
  viewingSource.value = item
}

function closeViewDialog() {
  viewingSource.value = null
}

function openRuleDialog(item: IndexQuoteSourceStatus) {
  editingSource.value = item
  ruleForm.value = {
    source_description: item.source_description || '',
    exclude_rule_type: item.exclude_rule_type || 'none',
    exclude_rule_value: item.exclude_rule_value || '',
  }
}

function closeRuleDialog() {
  if (savingSourceKey.value) return
  editingSource.value = null
}

async function saveRule() {
  const item = editingSource.value
  if (!item) return
  savingSourceKey.value = item.source_key
  message.value = ''
  try {
    const updated = await updateIndexQuoteSource(item.source_key, {
      source_description: ruleForm.value.source_description,
      exclude_rule_type: ruleForm.value.exclude_rule_type,
      exclude_rule_value: ruleForm.value.exclude_rule_value,
    })
    sources.value = sources.value.map((source) => (source.source_key === updated.source_key ? updated : source))
    editingSource.value = null
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
            <th>状态</th>
            <th>优先级</th>
            <th>成功率</th>
            <th>成功/失败</th>
            <th>连续失败</th>
            <th>冷却至</th>
            <th>最近成功</th>
            <th>最近失败</th>
            <th>最近错误</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="activeGroup.items.length === 0">
            <td colspan="12">暂无{{ activeGroup.title }}。</td>
          </tr>
          <tr v-for="(item, index) in activeGroup.items" :key="item.source_key">
            <td data-label="排序">{{ index + 1 }}</td>
            <td data-label="渠道">
              <strong>{{ item.source_name }}</strong>
              <span class="muted code-line">{{ item.source_key }}</span>
            </td>
            <td data-label="状态">
              <span class="status-pill" :class="statusClass(item)">{{ item.status_label }}</span>
            </td>
            <td data-label="优先级">{{ item.priority }}</td>
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
            <td data-label="操作" class="operation-cell">
              <button class="table-link-button" type="button" @click="openViewDialog(item)">查看</button>
              <button class="table-link-button" type="button" @click="openRuleDialog(item)">编辑</button>
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

    <div v-if="viewingSource" class="modal-backdrop" @click.self="closeViewDialog">
      <section class="form-dialog source-rule-dialog" role="dialog" aria-modal="true" aria-labelledby="source-rule-view-title">
        <div class="dialog-header">
          <div>
            <p class="eyebrow">Source Detail</p>
            <h2 id="source-rule-view-title">渠道详情</h2>
          </div>
          <button class="ghost" type="button" @click="closeViewDialog">关闭</button>
        </div>
        <div class="source-detail-list">
          <div>
            <span>渠道</span>
            <strong>{{ viewingSource.source_name }}</strong>
            <code>{{ viewingSource.source_key }}</code>
          </div>
          <div>
            <span>说明</span>
            <p>{{ viewingSource.source_description || '-' }}</p>
          </div>
          <div>
            <span>排除规则</span>
            <p>{{ ruleSummary(viewingSource) }}</p>
          </div>
        </div>
        <div class="dialog-actions">
          <button class="ghost" type="button" @click="closeViewDialog">关闭</button>
          <button class="primary" type="button" @click="openRuleDialog(viewingSource); closeViewDialog()">编辑</button>
        </div>
      </section>
    </div>

    <div v-if="editingSource" class="modal-backdrop" @click.self="closeRuleDialog">
      <section class="form-dialog source-rule-dialog" role="dialog" aria-modal="true" aria-labelledby="source-rule-title">
        <div class="dialog-header">
          <div>
            <p class="eyebrow">Source Rule</p>
            <h2 id="source-rule-title">编辑渠道规则</h2>
          </div>
          <button class="ghost" type="button" :disabled="!!savingSourceKey" @click="closeRuleDialog">关闭</button>
        </div>
        <form class="dialog-form" @submit.prevent="saveRule">
          <label>
            渠道
            <input :value="`${editingSource.source_name}（${editingSource.source_key}）`" disabled />
          </label>
          <label>
            说明
            <textarea v-model="ruleForm.source_description" rows="4" placeholder="说明渠道覆盖范围和适用场景" />
          </label>
          <label>
            排除规则类型
            <ElSelect v-model="ruleForm.exclude_rule_type">
              <ElOption label="无" value="none" />
              <ElOption label="正则" value="regex" />
              <ElOption label="枚举" value="enum" />
            </ElSelect>
          </label>
          <label>
            排除规则内容
            <textarea
              v-model="ruleForm.exclude_rule_value"
              rows="5"
              :disabled="ruleForm.exclude_rule_type === 'none'"
              :placeholder="ruleForm.exclude_rule_type === 'regex' ? '^9' : '930875,931027 或每行一个代码'"
            />
          </label>
          <p class="dialog-copy">
            正则规则会匹配指数代码；枚举规则支持逗号或换行分隔。命中的代码会在调度前跳过，不计入失败次数。
          </p>
          <div class="dialog-actions">
            <button class="ghost" type="button" :disabled="!!savingSourceKey" @click="closeRuleDialog">取消</button>
            <button class="primary" type="submit" :disabled="!!savingSourceKey">
              {{ savingSourceKey ? '保存中...' : '保存' }}
            </button>
          </div>
        </form>
      </section>
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

.operation-cell {
  min-width: 96px;
  white-space: nowrap;
}

.operation-cell button + button {
  margin-left: 10px;
}

.source-rule-dialog {
  max-width: 680px;
}

.source-rule-dialog textarea {
  width: 100%;
  resize: vertical;
  border: 1px solid var(--border-subtle);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--surface);
  color: var(--text-main);
  font: inherit;
}

.source-rule-dialog textarea:disabled,
.source-rule-dialog input:disabled {
  color: var(--text-muted);
  background: var(--surface-muted);
}

.source-detail-list {
  display: grid;
  gap: 18px;
}

.source-detail-list div {
  display: grid;
  gap: 6px;
}

.source-detail-list span {
  color: var(--text-muted);
  font-weight: 700;
}

.source-detail-list strong {
  font-size: 18px;
}

.source-detail-list code {
  color: var(--text-muted);
}

.source-detail-list p {
  margin: 0;
  line-height: 1.7;
  white-space: pre-wrap;
}

</style>
