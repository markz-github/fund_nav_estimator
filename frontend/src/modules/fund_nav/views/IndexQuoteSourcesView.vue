<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { apiErrorMessage } from '../../../api/client'
import { routeNames } from '../../../router/routeNames'
import {
  listIndexQuoteSources,
  listIndexQuoteSymbols,
  updateIndexQuoteSource,
  upsertIndexQuoteSymbol,
  type IndexQuoteSourceStatus,
  type IndexQuoteSymbol,
} from '../api/market'

const sources = ref<IndexQuoteSourceStatus[]>([])
const loading = ref(false)
const message = ref('')
const popover = ref({ text: '', top: 0, left: 0, visible: false })
const activeSourceType = ref<'index' | 'stock' | 'etf'>('index')
const savingSourceKey = ref('')
const symbols = ref<IndexQuoteSymbol[]>([])
const symbolsLoading = ref(false)
const symbolTotal = ref(0)
const symbolPage = ref(1)
const symbolPageSize = ref(20)
const savingSymbol = ref(false)
const viewingSource = ref<IndexQuoteSourceStatus | null>(null)
const editingSource = ref<IndexQuoteSourceStatus | null>(null)
const editingSymbol = ref<IndexQuoteSymbol | null>(null)
const symbolDialogOpen = ref(false)
const ruleForm = ref({ source_description: '', exclude_rule_type: 'none', exclude_rule_value: '' })
const symbolForm = ref({ index_code: '', source_key: '', quote_symbol: '', supported: 1, description: '' })
const symbolQuery = ref({ index_code: '', source_key: '' })

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
const indexSources = computed(() => sources.value.filter((item) => item.source_type === 'index'))

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
    const [sourceRows, symbolPageData] = await Promise.all([
      listIndexQuoteSources(),
      listIndexQuoteSymbols({ limit: symbolPageSize.value, offset: 0 }),
    ])
    sources.value = sourceRows
    symbols.value = symbolPageData.items
    symbolTotal.value = symbolPageData.total
    symbolPage.value = 1
  } catch (error) {
    message.value = apiErrorMessage(error, '渠道数据加载失败，请确认后端服务。')
  } finally {
    loading.value = false
  }
}

async function loadSymbols() {
  symbolsLoading.value = true
  message.value = ''
  try {
    const pageData = await listIndexQuoteSymbols({
      index_code: symbolQuery.value.index_code || undefined,
      source_key: symbolQuery.value.source_key || undefined,
      limit: symbolPageSize.value,
      offset: (symbolPage.value - 1) * symbolPageSize.value,
    })
    symbols.value = pageData.items
    symbolTotal.value = pageData.total
  } catch (error) {
    message.value = apiErrorMessage(error, '指数映射加载失败，请确认筛选条件。')
  } finally {
    symbolsLoading.value = false
  }
}

function querySymbols() {
  symbolPage.value = 1
  loadSymbols()
}

function handleSymbolPageChange(page: number) {
  symbolPage.value = page
  loadSymbols()
}

function sourceName(sourceKey: string) {
  return sources.value.find((source) => source.source_key === sourceKey)?.source_name || sourceKey
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

function openSymbolDialog(item?: IndexQuoteSymbol) {
  editingSymbol.value = item || null
  symbolDialogOpen.value = true
  symbolForm.value = {
    index_code: item?.index_code || '',
    source_key: item?.source_key || indexSources.value[0]?.source_key || '',
    quote_symbol: item?.quote_symbol || '',
    supported: item?.supported ?? 1,
    description: item?.description || '',
  }
}

function closeSymbolDialog() {
  if (savingSymbol.value) return
  symbolDialogOpen.value = false
  editingSymbol.value = null
  symbolForm.value = { index_code: '', source_key: '', quote_symbol: '', supported: 1, description: '' }
}

async function saveSymbol() {
  savingSymbol.value = true
  message.value = ''
  try {
    const updated = await upsertIndexQuoteSymbol({
      index_code: symbolForm.value.index_code,
      source_key: symbolForm.value.source_key,
      quote_symbol: symbolForm.value.supported ? symbolForm.value.quote_symbol : null,
      supported: Number(symbolForm.value.supported),
      description: symbolForm.value.description,
    })
    closeSymbolDialog()
    await loadSymbols()
  } catch (error) {
    message.value = apiErrorMessage(error, '指数映射保存失败，请检查代码和 symbol。')
  } finally {
    savingSymbol.value = false
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
              <div class="quick-actions">
                <button class="ghost" type="button" @click="openViewDialog(item)">查看</button>
                <button class="ghost" type="button" @click="openRuleDialog(item)">编辑</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <section class="mapping-section">
      <div class="section-toolbar">
        <div>
          <p class="eyebrow">Index Symbols</p>
          <h2>指数代码映射</h2>
        </div>
        <div class="mapping-actions">
          <input v-model.trim="symbolQuery.index_code" class="compact-input" placeholder="指数代码" @keyup.enter="querySymbols" />
          <ElSelect v-model="symbolQuery.source_key" class="compact-select" clearable placeholder="渠道">
            <ElOption
              v-for="source in indexSources"
              :key="source.source_key"
              :label="source.source_name"
              :value="source.source_key"
            />
          </ElSelect>
          <button class="ghost" type="button" :disabled="symbolsLoading" @click="querySymbols">
            {{ symbolsLoading ? '查询中...' : '查询' }}
          </button>
          <button class="ghost" type="button" @click="openSymbolDialog()">新增映射</button>
        </div>
      </div>
      <p class="table-hint">共 {{ symbolTotal }} 条，每页 {{ symbolPageSize }} 条；维护指定指数时可输入指数代码查询。</p>
      <div class="table-card">
        <table class="responsive-card-table quote-symbol-table">
          <thead>
            <tr>
              <th>指数代码</th>
              <th>渠道</th>
              <th>请求 Symbol</th>
              <th>状态</th>
              <th>说明</th>
              <th>更新时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="symbols.length === 0">
              <td colspan="7">暂无指数代码映射。</td>
            </tr>
            <tr v-for="item in symbols" :key="`${item.index_code}-${item.source_key}`">
              <td data-label="指数代码">
                <strong>{{ item.index_code }}</strong>
              </td>
              <td data-label="渠道">
                <strong>{{ sourceName(item.source_key) }}</strong>
                <span class="muted code-line">{{ item.source_key }}</span>
              </td>
              <td data-label="请求 Symbol">
                <code>{{ item.quote_symbol || '-' }}</code>
              </td>
              <td data-label="状态">
                <span class="status-pill" :class="item.supported ? 'status-ok' : 'status-danger'">
                  {{ item.supported ? '支持' : '不支持' }}
                </span>
              </td>
              <td
                data-label="说明"
                class="log-text-cell"
                tabindex="0"
                @mouseenter="showTextPopover($event, item.description)"
                @mouseleave="hideTextPopover"
                @focus="showTextPopover($event, item.description)"
                @blur="hideTextPopover"
              >
                <span class="log-text-preview">{{ item.description || '-' }}</span>
              </td>
              <td data-label="更新时间">{{ formatDateTime(item.updated_at) }}</td>
              <td data-label="操作" class="operation-cell">
                <div class="quick-actions">
                  <button class="ghost" type="button" @click="openSymbolDialog(item)">编辑</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="pagination-bar" v-if="symbolTotal > symbolPageSize">
        <ElPagination
          layout="prev, pager, next, total"
          :current-page="symbolPage"
          :page-size="symbolPageSize"
          :total="symbolTotal"
          :disabled="symbolsLoading"
          @current-change="handleSymbolPageChange"
        />
      </div>
    </section>
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

    <div v-if="symbolDialogOpen" class="modal-backdrop" @click.self="closeSymbolDialog">
      <section class="form-dialog source-rule-dialog" role="dialog" aria-modal="true" aria-labelledby="symbol-rule-title">
        <div class="dialog-header">
          <div>
            <p class="eyebrow">Index Symbol</p>
            <h2 id="symbol-rule-title">编辑指数代码映射</h2>
          </div>
          <button class="ghost" type="button" :disabled="savingSymbol" @click="closeSymbolDialog">关闭</button>
        </div>
        <form class="dialog-form" @submit.prevent="saveSymbol">
          <label>
            指数代码
            <input v-model.trim="symbolForm.index_code" placeholder="930875" :disabled="!!editingSymbol" />
          </label>
          <label>
            渠道
            <ElSelect v-model="symbolForm.source_key" :disabled="!!editingSymbol">
              <ElOption
                v-for="source in indexSources"
                :key="source.source_key"
                :label="`${source.source_name}（${source.source_key}）`"
                :value="source.source_key"
              />
            </ElSelect>
          </label>
          <label>
            状态
            <ElSelect v-model="symbolForm.supported">
              <ElOption label="支持" :value="1" />
              <ElOption label="不支持" :value="0" />
            </ElSelect>
          </label>
          <label>
            请求 Symbol
            <input
              v-model.trim="symbolForm.quote_symbol"
              :disabled="Number(symbolForm.supported) === 0"
              placeholder="CSI930875 / 2.930875 / s_sz399967"
            />
          </label>
          <label>
            说明
            <textarea v-model="symbolForm.description" rows="4" placeholder="说明该渠道的代码规则或不支持原因" />
          </label>
          <p class="dialog-copy">
            支持状态为“不支持”时，调度会跳过该渠道和指数组合，不计入失败次数；支持状态为“支持”时必须填写请求 Symbol。
          </p>
          <div class="dialog-actions">
            <button class="ghost" type="button" :disabled="savingSymbol" @click="closeSymbolDialog">取消</button>
            <button class="primary" type="submit" :disabled="savingSymbol">
              {{ savingSymbol ? '保存中...' : '保存' }}
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

.quote-symbol-table {
  min-width: 980px;
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

.mapping-section {
  margin-top: 32px;
}

.section-toolbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.section-toolbar h2 {
  margin: 0;
  font-size: 28px;
}

.mapping-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.compact-input {
  width: 150px;
  height: 48px;
  border: 1px solid rgba(36, 63, 47, 0.2);
  border-radius: 8px;
  padding: 0 14px;
  background: #fff;
  color: #17271d;
  font-size: 0.95rem;
  font-weight: 700;
}

.compact-input::placeholder {
  color: #7f8d87;
  font-weight: 700;
}

.compact-input:focus {
  border-color: rgba(36, 63, 47, 0.42);
  box-shadow: 0 0 0 3px rgba(31, 63, 53, 0.1);
  outline: none;
}

.compact-select {
  width: 210px;
}

.compact-select :deep(.el-select__wrapper) {
  min-height: 48px;
  border: 1px solid rgba(36, 63, 47, 0.2);
  border-radius: 8px;
  background: #fff;
  box-shadow: none;
  color: #17271d;
  font-family: inherit;
  font-size: 0.95rem;
  font-weight: 700;
}

.compact-select :deep(.el-select__wrapper.is-focused) {
  border-color: rgba(36, 63, 47, 0.42);
  box-shadow: 0 0 0 3px rgba(31, 63, 53, 0.1);
}

.compact-select :deep(.el-select__placeholder),
.compact-select :deep(.el-select__selected-item) {
  color: #17271d;
  font-size: 0.95rem;
  font-weight: 700;
}

.compact-select :deep(.el-select__placeholder.is-transparent),
.compact-select :deep(.el-select__caret) {
  color: #7f8d87;
}

.mapping-actions button {
  min-height: 48px;
  padding: 0 20px;
  font-weight: 800;
}

.table-hint {
  margin: -4px 0 12px;
  color: var(--text-muted);
}

.pagination-bar {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.operation-cell {
  min-width: 150px;
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
