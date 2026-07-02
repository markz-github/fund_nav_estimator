<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { apiErrorMessage } from '../../../api/client'
import { routeNames } from '../../../router/routeNames'
import { formatDateTime } from '../../../utils/datetime'
import {
  deletePendingManualIndexMapping,
  deleteManualIndexMapping,
  listManualIndexMappings,
  listPendingManualIndexMappings,
  saveManualIndexMapping,
  type ManualFundIndexMapping,
  type ManualFundIndexMappingPayload,
  type PendingManualFundMapping,
} from '../api/manualIndexMappings'

const mappings = ref<ManualFundIndexMapping[]>([])
const pendingMappings = ref<PendingManualFundMapping[]>([])
const loading = ref(false)
const saving = ref(false)
const message = ref('')
const editingFundCode = ref<string | null>(null)
const mappingDialogOpen = ref(false)
const form = ref<ManualFundIndexMappingPayload>({
  fund_code: '',
  fund_name: '',
  mapping_type: 'index',
  target_code: '',
  target_name: '',
  target_market: '',
  holding_ratio: null,
  holding_value: null,
  report_period: '',
  benchmark_text: '',
  remark: '',
})

const targetCodeLabel = computed(() => (form.value.mapping_type === 'target_etf' ? 'ETF代码' : '指数代码'))
const targetNameLabel = computed(() => (form.value.mapping_type === 'target_etf' ? 'ETF名称' : '指数名称'))
const pendingCount = computed(() => pendingMappings.value.length)
const dialogTitle = computed(() => (editingFundCode.value ? '编辑人工映射' : '新增人工映射'))

async function loadMappings() {
  loading.value = true
  message.value = ''
  try {
    const [manualRows, pendingRows] = await Promise.all([
      listManualIndexMappings(),
      listPendingManualIndexMappings(),
    ])
    mappings.value = manualRows
    pendingMappings.value = pendingRows
  } catch (error) {
    message.value = apiErrorMessage(error, '人工映射加载失败，请确认后端服务。')
  } finally {
    loading.value = false
  }
}

function editMapping(mapping: ManualFundIndexMapping) {
  editingFundCode.value = mapping.fund_code
  form.value = {
    fund_code: mapping.fund_code,
    fund_name: mapping.fund_name ?? '',
    mapping_type: mapping.mapping_type,
    target_code: mapping.target_code,
    target_name: mapping.target_name,
    target_market: mapping.target_market ?? '',
    holding_ratio: mapping.holding_ratio ?? null,
    holding_value: mapping.holding_value ?? null,
    report_period: mapping.report_period ?? '',
    benchmark_text: mapping.benchmark_text ?? '',
    remark: mapping.remark ?? '',
  }
  mappingDialogOpen.value = true
}

function resetForm() {
  editingFundCode.value = null
  form.value = {
    fund_code: '',
    fund_name: '',
    mapping_type: 'index',
    target_code: '',
    target_name: '',
    target_market: '',
    holding_ratio: null,
    holding_value: null,
    report_period: '',
    benchmark_text: '',
    remark: '',
  }
}

function openCreateDialog() {
  resetForm()
  mappingDialogOpen.value = true
}

function closeMappingDialog() {
  if (saving.value) return
  mappingDialogOpen.value = false
  resetForm()
}

function maintainPending(issue: PendingManualFundMapping) {
  editingFundCode.value = issue.fund_code
  form.value = {
    fund_code: issue.fund_code,
    fund_name: issue.fund_name ?? '',
    mapping_type: issue.mapping_type,
    target_code: '',
    target_name: '',
    target_market: issue.mapping_type === 'target_etf' ? 'CN' : '',
    holding_ratio: issue.mapping_type === 'target_etf' ? '1' : null,
    holding_value: null,
    report_period: '',
    benchmark_text: '',
    remark: issue.mapping_type === 'target_etf' ? '巡检提示补充目标 ETF' : '巡检提示补充跟踪指数',
  }
  mappingDialogOpen.value = true
}

function reasonLabel(reason?: string | null) {
  if (reason === 'missing_index_mapping') return '缺少跟踪指数'
  if (reason === 'missing_target_etf_mapping') return '缺少目标 ETF'
  return reason || '-'
}

async function submitMapping() {
  if (!form.value.fund_code.trim() || !form.value.target_code.trim() || !form.value.target_name.trim()) return
  saving.value = true
  message.value = ''
  try {
    await saveManualIndexMapping({
      fund_code: form.value.fund_code.trim(),
      fund_name: form.value.fund_name?.trim() || null,
      mapping_type: form.value.mapping_type,
      target_code: form.value.target_code.trim(),
      target_name: form.value.target_name.trim(),
      target_market: form.value.target_market?.trim() || null,
      holding_ratio: form.value.mapping_type === 'target_etf' ? form.value.holding_ratio || null : null,
      holding_value: form.value.mapping_type === 'target_etf' ? form.value.holding_value || null : null,
      report_period: form.value.mapping_type === 'target_etf' ? form.value.report_period?.trim() || null : null,
      benchmark_text: form.value.mapping_type === 'index' ? form.value.benchmark_text?.trim() || null : null,
      remark: form.value.remark?.trim() || null,
    })
    message.value = form.value.mapping_type === 'target_etf'
      ? '人工目标 ETF 映射已保存，刷新该基金持仓后生效。'
      : '人工指数映射已保存，刷新该基金指数映射后生效。'
    mappingDialogOpen.value = false
    resetForm()
    await loadMappings()
  } catch (error) {
    message.value = apiErrorMessage(error, '人工映射保存失败，请检查输入。')
  } finally {
    saving.value = false
  }
}

async function removeMapping(mapping: ManualFundIndexMapping) {
  message.value = ''
  try {
    await deleteManualIndexMapping(mapping.fund_code, mapping.mapping_type)
    if (editingFundCode.value === mapping.fund_code) resetForm()
    message.value = '人工映射已删除。'
    await loadMappings()
  } catch (error) {
    message.value = apiErrorMessage(error, '人工映射删除失败。')
  }
}

async function removePending(issue: PendingManualFundMapping) {
  message.value = ''
  try {
    await deletePendingManualIndexMapping(issue.id)
    message.value = '待维护提示已删除。'
    await loadMappings()
  } catch (error) {
    message.value = apiErrorMessage(error, '待维护提示删除失败。')
  }
}

onMounted(loadMappings)
</script>

<template>
  <main class="page-shell">
    <RouterLink class="back-link" :to="{ name: routeNames.fundList }">返回基金池</RouterLink>

    <section class="detail-hero">
      <div>
        <p class="eyebrow">Index Mapping</p>
        <h1>人工基金映射</h1>
        <p class="subtitle">维护自动解析无法稳定识别的跟踪指数和目标 ETF 映射。</p>
      </div>
      <div class="section-actions">
        <span class="status-pill" :class="pendingCount > 0 ? 'status-danger' : 'status-ok'">
          待维护 {{ pendingCount }} 条
        </span>
        <button type="button" @click="openCreateDialog">新增映射</button>
        <button class="ghost" type="button" :disabled="loading" @click="loadMappings">
          {{ loading ? '刷新中...' : '刷新列表' }}
        </button>
      </div>
    </section>

    <p v-if="message" class="message">{{ message }}</p>

    <section class="section-title">
      <div>
        <p class="eyebrow">Pending</p>
        <h2>待维护映射</h2>
      </div>
      <span>{{ pendingCount }} 条</span>
    </section>

    <div class="table-card">
      <table class="responsive-card-table quality-table">
        <thead>
          <tr>
            <th>基金</th>
            <th>缺失类型</th>
            <th>发现时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="pendingMappings.length === 0">
            <td colspan="4">暂无待维护映射。</td>
          </tr>
          <tr v-for="issue in pendingMappings" :key="issue.id">
            <td data-label="基金">
              <RouterLink class="fund-name" :to="{ name: routeNames.fundDetail, params: { fundCode: issue.fund_code } }">
                {{ issue.fund_code }}
              </RouterLink>
              <span class="muted">{{ issue.fund_name ?? '-' }}</span>
            </td>
            <td data-label="缺失类型">
              <span class="status-pill status-danger">{{ reasonLabel(issue.reason) }}</span>
              <span class="muted">{{ issue.mapping_type === 'target_etf' ? '目标 ETF' : '跟踪指数' }}</span>
            </td>
            <td data-label="发现时间">{{ formatDateTime(issue.occurred_at) }}</td>
            <td data-label="操作">
              <div class="quick-actions">
                <button class="ghost" type="button" @click="maintainPending(issue)">维护</button>
                <button class="danger" type="button" @click="removePending(issue)">删除</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <section class="section-title">
      <div>
        <p class="eyebrow">Manual Records</p>
        <h2>映射记录</h2>
      </div>
      <span>{{ mappings.length }} 条</span>
    </section>

    <div class="table-card">
      <table class="responsive-card-table quality-table">
        <thead>
          <tr>
            <th>基金</th>
            <th>类型</th>
            <th>目标</th>
            <th>持仓信息</th>
            <th>备注</th>
            <th>更新时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="mappings.length === 0">
            <td colspan="7">暂无人工映射。</td>
          </tr>
          <tr v-for="mapping in mappings" :key="`${mapping.mapping_type}:${mapping.fund_code}`">
            <td data-label="基金">
              <RouterLink class="fund-name" :to="{ name: routeNames.fundDetail, params: { fundCode: mapping.fund_code } }">
                {{ mapping.fund_code }}
              </RouterLink>
              <span class="muted">{{ mapping.fund_name ?? '-' }}</span>
            </td>
            <td data-label="类型">{{ mapping.mapping_type === 'target_etf' ? '目标 ETF' : '跟踪指数' }}</td>
            <td data-label="目标">
              <span class="mono">{{ mapping.target_code }}</span>
              <span>{{ mapping.target_name }}</span>
            </td>
            <td data-label="持仓信息">
              <span v-if="mapping.mapping_type === 'target_etf'">
                {{ mapping.holding_ratio ?? '-' }}
                <small class="muted">{{ mapping.report_period ?? '-' }}</small>
              </span>
              <span v-else>-</span>
            </td>
            <td data-label="备注">{{ mapping.remark ?? '-' }}</td>
            <td data-label="更新时间">{{ formatDateTime(mapping.updated_at) }}</td>
            <td data-label="操作">
              <div class="quick-actions">
                <button class="ghost" type="button" @click="editMapping(mapping)">编辑</button>
                <button class="danger" type="button" @click="removeMapping(mapping)">删除</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="mappingDialogOpen" class="modal-backdrop" @click.self="closeMappingDialog">
      <section class="form-dialog" role="dialog" aria-modal="true" aria-labelledby="mapping-dialog-title">
        <div class="dialog-header">
          <div>
            <p class="eyebrow">Manual Mapping</p>
            <h2 id="mapping-dialog-title">{{ dialogTitle }}</h2>
          </div>
          <button class="ghost" type="button" :disabled="saving" @click="closeMappingDialog">关闭</button>
        </div>

        <form class="dialog-form" @submit.prevent="submitMapping">
          <label>
            类型
            <select v-model="form.mapping_type">
              <option value="index">跟踪指数</option>
              <option value="target_etf">目标 ETF</option>
            </select>
          </label>
          <label>
            基金代码
            <input v-model="form.fund_code" placeholder="160218" />
          </label>
          <label>
            基金名称
            <input v-model="form.fund_name" placeholder="可选" />
          </label>
          <label>
            {{ targetCodeLabel }}
            <input v-model="form.target_code" :placeholder="form.mapping_type === 'target_etf' ? '513380' : '399393'" />
          </label>
          <label>
            {{ targetNameLabel }}
            <input v-model="form.target_name" :placeholder="form.mapping_type === 'target_etf' ? '广发恒生科技(QDII-ETF)' : '国证地产'" />
          </label>
          <label v-if="form.mapping_type === 'target_etf'">
            持仓占比
            <input v-model="form.holding_ratio" placeholder="0.9308" />
          </label>
          <label v-if="form.mapping_type === 'target_etf'">
            报告期
            <input v-model="form.report_period" placeholder="2024Q4" />
          </label>
          <label>
            备注
            <input v-model="form.remark" placeholder="可选" />
          </label>
          <div class="dialog-actions">
            <button type="submit" :disabled="saving">
              {{ saving ? '保存中...' : editingFundCode ? '更新映射' : '新增映射' }}
            </button>
            <button class="ghost" type="button" :disabled="saving" @click="closeMappingDialog">取消</button>
          </div>
        </form>
      </section>
    </div>
  </main>
</template>
