<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { apiErrorMessage } from '../../../api/client'
import { routeNames } from '../../../router/routeNames'
import { formatDateTime } from '../../../utils/datetime'
import {
  deleteManualIndexMapping,
  listManualIndexMappings,
  saveManualIndexMapping,
  type ManualFundIndexMapping,
  type ManualFundIndexMappingPayload,
} from '../api/manualIndexMappings'

const mappings = ref<ManualFundIndexMapping[]>([])
const loading = ref(false)
const saving = ref(false)
const message = ref('')
const editingFundCode = ref<string | null>(null)
const form = ref<ManualFundIndexMappingPayload>({
  fund_code: '',
  fund_name: '',
  index_code: '',
  index_name: '',
  benchmark_text: '',
  remark: '',
})

async function loadMappings() {
  loading.value = true
  message.value = ''
  try {
    mappings.value = await listManualIndexMappings()
  } catch (error) {
    message.value = apiErrorMessage(error, '人工指数映射加载失败，请确认后端服务。')
  } finally {
    loading.value = false
  }
}

function editMapping(mapping: ManualFundIndexMapping) {
  editingFundCode.value = mapping.fund_code
  form.value = {
    fund_code: mapping.fund_code,
    fund_name: mapping.fund_name ?? '',
    index_code: mapping.index_code,
    index_name: mapping.index_name,
    benchmark_text: mapping.benchmark_text ?? '',
    remark: mapping.remark ?? '',
  }
}

function resetForm() {
  editingFundCode.value = null
  form.value = {
    fund_code: '',
    fund_name: '',
    index_code: '',
    index_name: '',
    benchmark_text: '',
    remark: '',
  }
}

async function submitMapping() {
  if (!form.value.fund_code.trim() || !form.value.index_code.trim() || !form.value.index_name.trim()) return
  saving.value = true
  message.value = ''
  try {
    await saveManualIndexMapping({
      fund_code: form.value.fund_code.trim(),
      fund_name: form.value.fund_name?.trim() || null,
      index_code: form.value.index_code.trim(),
      index_name: form.value.index_name.trim(),
      benchmark_text: form.value.benchmark_text?.trim() || null,
      remark: form.value.remark?.trim() || null,
    })
    message.value = '人工映射已保存，刷新该基金指数映射后生效。'
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
    await deleteManualIndexMapping(mapping.fund_code)
    if (editingFundCode.value === mapping.fund_code) resetForm()
    message.value = '人工映射已删除。'
    await loadMappings()
  } catch (error) {
    message.value = apiErrorMessage(error, '人工映射删除失败。')
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
        <h1>人工指数映射</h1>
        <p class="subtitle">维护自动解析无法稳定识别的基金跟踪指数映射。</p>
      </div>
      <button class="ghost" type="button" :disabled="loading" @click="loadMappings">
        {{ loading ? '刷新中...' : '刷新列表' }}
      </button>
    </section>

    <p v-if="message" class="message">{{ message }}</p>

    <form class="filter-bar compact-filter" @submit.prevent="submitMapping">
      <label>
        基金代码
        <input v-model="form.fund_code" placeholder="160218" />
      </label>
      <label>
        基金名称
        <input v-model="form.fund_name" placeholder="可选" />
      </label>
      <label>
        指数代码
        <input v-model="form.index_code" placeholder="399393" />
      </label>
      <label>
        指数名称
        <input v-model="form.index_name" placeholder="国证地产" />
      </label>
      <label>
        备注
        <input v-model="form.remark" placeholder="可选" />
      </label>
      <div class="filter-actions">
        <button type="submit" :disabled="saving">
          {{ saving ? '保存中...' : editingFundCode ? '更新映射' : '新增映射' }}
        </button>
        <button class="ghost" type="button" :disabled="saving" @click="resetForm">清空</button>
      </div>
    </form>

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
            <th>指数</th>
            <th>备注</th>
            <th>更新时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="mappings.length === 0">
            <td colspan="5">暂无人工指数映射。</td>
          </tr>
          <tr v-for="mapping in mappings" :key="mapping.fund_code">
            <td data-label="基金">
              <RouterLink class="fund-name" :to="{ name: routeNames.fundDetail, params: { fundCode: mapping.fund_code } }">
                {{ mapping.fund_code }}
              </RouterLink>
              <span class="muted">{{ mapping.fund_name ?? '-' }}</span>
            </td>
            <td data-label="指数">
              <span class="mono">{{ mapping.index_code }}</span>
              <span>{{ mapping.index_name }}</span>
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
  </main>
</template>
