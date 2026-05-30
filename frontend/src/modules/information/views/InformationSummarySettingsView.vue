<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { apiErrorMessage } from '../../../api/client'
import {
  createSummaryTaskConfig,
  deleteSummaryTaskConfig,
  getInformationSettings,
  listInformationCategories,
  listSummaryTaskConfigs,
  runSummaryTaskConfigNow,
  updateInformationSettings,
  updateSummaryTaskConfig,
  type InformationSettings,
  type SummaryTaskConfig,
} from '../api/videos'

const settings = ref<InformationSettings | null>(null)
const summaryTaskConfigs = ref<SummaryTaskConfig[]>([])
const categories = ref<string[]>(['财经'])
const loading = ref(false)
const saving = ref(false)
const message = ref('')
const dialogMode = ref<'add' | 'edit' | null>(null)
const editingSummaryTaskId = ref<number | null>(null)
const summaryTaskDraft = ref(emptySummaryTask())
const confirmAction = ref<'disable' | 'delete' | 'run' | null>(null)
const confirmSummaryTask = ref<SummaryTaskConfig | null>(null)
const runningConfigId = ref<number | null>(null)
const selectedTemplateCategory = ref('财经')
const defaultTemplateExpanded = ref(false)

function emptySummaryTask() {
  return {
    task_name: '财经汇总',
    platform: 'bilibili',
    category: '财经',
    start_days_before: 1,
    cron_expression: '0 7 * * *',
    title_template: '{start_date:%Y-%m-%d} {platform} {category}汇总',
    summary_instruction: '',
    push_to_wechat: 0,
  }
}

function formatDate(value: Date, pattern = '%Y-%m-%d') {
  const year = String(value.getFullYear())
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return pattern.replace(/%Y/g, year).replace(/%m/g, month).replace(/%d/g, day)
}

function summaryDateRange(task: { start_days_before: number }) {
  const today = new Date()
  const endDate = new Date(today)
  endDate.setDate(today.getDate() - 1)
  const startDate = new Date(today)
  startDate.setDate(today.getDate() - (Number(task.start_days_before) || 1))
  if (startDate > endDate) startDate.setTime(endDate.getTime())
  return { startDate, endDate }
}

function renderSummaryTitleSample(task: {
  task_name: string
  platform: string
  category: string
  start_days_before: number
  cron_expression: string
  title_template: string
}) {
  const { startDate, endDate } = summaryDateRange(task)
  const values: Record<string, string> = {
    platform: task.platform || 'bilibili',
    category: task.category || '财经',
  }
  const template = task.title_template || '{start_date:%Y-%m-%d} {platform} {category}汇总'
  return template.replace(/\{(start_date|end_date)(?::([^}]+))?\}|\{(platform|category)\}/g, (_match, dateKey, dateFormat, valueKey) => {
    if (dateKey === 'start_date') return formatDate(startDate, dateFormat || '%Y-%m-%d')
    if (dateKey === 'end_date') return formatDate(endDate, dateFormat || '%Y-%m-%d')
    return values[valueKey] ?? ''
  })
}

const summaryTaskDialogOpen = computed(() => dialogMode.value !== null)
const summaryTaskDialogTitle = computed(() => (dialogMode.value === 'edit' ? '修改汇总任务' : '添加汇总任务'))
const summaryTaskSample = computed(() => renderSummaryTitleSample(summaryTaskDraft.value))
const templateCategories = computed(() => {
  const storedTemplateCategories = settings.value?.hermes_summary_document_templates.map((item) => item.category) || []
  return Array.from(new Set(['财经', ...categories.value, ...storedTemplateCategories])).filter(Boolean)
})
const currentSummaryDocumentTemplate = computed({
  get() {
    if (!settings.value) return ''
    return templateSettingForCategory(selectedTemplateCategory.value)?.template_text || ''
  },
  set(value: string) {
    if (!settings.value) return
    const existing = settings.value.hermes_summary_document_templates.find((item) => item.category === selectedTemplateCategory.value)
    if (existing) {
      existing.template_text = value
      return
    }
    settings.value.hermes_summary_document_templates.push({
      category: selectedTemplateCategory.value,
      summary_instruction: '',
      template_text: value,
    })
  },
})
const currentSummaryInstruction = computed({
  get() {
    if (!settings.value) return ''
    return templateSettingForCategory(selectedTemplateCategory.value)?.summary_instruction || ''
  },
  set(value: string) {
    if (!settings.value) return
    const existing = templateSettingForCategory(selectedTemplateCategory.value)
    if (existing) {
      existing.summary_instruction = value
      return
    }
    settings.value.hermes_summary_document_templates.push({
      category: selectedTemplateCategory.value,
      summary_instruction: value,
      template_text: '',
    })
  },
})
const confirmDialogOpen = computed(() => confirmAction.value !== null && confirmSummaryTask.value !== null)
const confirmDialogTitle = computed(() => {
  if (confirmAction.value === 'delete') return '删除汇总任务'
  if (confirmAction.value === 'run') return '立即执行汇总'
  return '停用汇总任务'
})
const confirmDialogText = computed(() => {
  const task = confirmSummaryTask.value
  if (!task) return ''
  if (confirmAction.value === 'delete') return `确认删除汇总任务“${task.task_name}”吗？删除后不会再按该配置生成新汇总。`
  if (confirmAction.value === 'run') return `确认立即执行汇总任务“${task.task_name}”吗？确认后会提交一篇新的汇总文档。`
  return `确认停用汇总任务“${task.task_name}”吗？停用后定时汇总将不再执行。`
})

async function loadPage() {
  loading.value = true
  message.value = ''
  try {
    const [settingsResult, configResult, categoryResult] = await Promise.all([
      getInformationSettings(),
      listSummaryTaskConfigs(),
      listInformationCategories(),
    ])
    settings.value = settingsResult
    summaryTaskConfigs.value = configResult
    categories.value = categoryResult
    if (!templateCategories.value.includes(selectedTemplateCategory.value)) selectedTemplateCategory.value = templateCategories.value[0] || '财经'
  } catch (error) {
    message.value = apiErrorMessage(error, '汇总设置加载失败。')
  } finally {
    loading.value = false
  }
}

function openAddDialog() {
  summaryTaskDraft.value = emptySummaryTask()
  editingSummaryTaskId.value = null
  dialogMode.value = 'add'
}

function openEditDialog(config: SummaryTaskConfig) {
  summaryTaskDraft.value = {
    task_name: config.task_name,
    platform: config.platform,
    category: config.category,
    start_days_before: config.start_days_before,
    cron_expression: config.cron_expression,
    title_template: config.title_template,
    summary_instruction: config.summary_instruction,
    push_to_wechat: config.push_to_wechat,
  }
  editingSummaryTaskId.value = config.id
  dialogMode.value = 'edit'
}

function closeAddDialog() {
  if (saving.value) return
  dialogMode.value = null
  editingSummaryTaskId.value = null
}

async function saveDefaultInstruction() {
  if (!settings.value) return
  saving.value = true
  message.value = ''
  try {
    settings.value = await updateInformationSettings({
      hermes_summary_document_templates: settings.value.hermes_summary_document_templates,
    })
    message.value = '默认汇总模板已保存。'
  } catch (error) {
    message.value = apiErrorMessage(error, '保存默认汇总模板失败。')
  } finally {
    saving.value = false
  }
}

function templateForCategory(category: string) {
  return templateSettingForCategory(category)?.template_text || ''
}

function templateSettingForCategory(category: string) {
  return settings.value?.hermes_summary_document_templates.find((item) => item.category === category)
}

async function addSummaryTaskConfig() {
  saving.value = true
  message.value = ''
  try {
    await createSummaryTaskConfig({
      ...summaryTaskDraft.value,
      start_days_before: Number(summaryTaskDraft.value.start_days_before) || 1,
      enabled: 1,
    })
    dialogMode.value = null
    message.value = '汇总任务配置已添加。'
    await loadPage()
  } catch (error) {
    message.value = apiErrorMessage(error, '新增汇总任务配置失败。')
  } finally {
    saving.value = false
  }
}

async function saveSummaryTaskConfig() {
  if (editingSummaryTaskId.value === null) return
  saving.value = true
  message.value = ''
  try {
    await updateSummaryTaskConfig(editingSummaryTaskId.value, {
      task_name: summaryTaskDraft.value.task_name,
      platform: summaryTaskDraft.value.platform,
      category: summaryTaskDraft.value.category,
      start_days_before: Number(summaryTaskDraft.value.start_days_before) || 1,
      cron_expression: summaryTaskDraft.value.cron_expression,
      title_template: summaryTaskDraft.value.title_template,
      summary_instruction: summaryTaskDraft.value.summary_instruction,
      push_to_wechat: summaryTaskDraft.value.push_to_wechat,
    })
    dialogMode.value = null
    editingSummaryTaskId.value = null
    message.value = '汇总任务配置已保存。'
    await loadPage()
  } catch (error) {
    message.value = apiErrorMessage(error, '保存汇总任务配置失败。')
  } finally {
    saving.value = false
  }
}

async function saveSummaryTaskDialog() {
  if (dialogMode.value === 'edit') {
    await saveSummaryTaskConfig()
    return
  }
  await addSummaryTaskConfig()
}

async function toggleSummaryTaskConfig(config: SummaryTaskConfig) {
  if (config.enabled) {
    openConfirmDialog('disable', config)
    return
  }
  await updateSummaryTaskConfig(config.id, { enabled: 1 })
  await loadPage()
}

async function removeSummaryTaskConfig(config: SummaryTaskConfig) {
  openConfirmDialog('delete', config)
}

function openConfirmDialog(action: 'disable' | 'delete' | 'run', config: SummaryTaskConfig) {
  confirmAction.value = action
  confirmSummaryTask.value = config
}

function closeConfirmDialog() {
  if (saving.value) return
  confirmAction.value = null
  confirmSummaryTask.value = null
}

async function confirmDangerAction() {
  const action = confirmAction.value
  const config = confirmSummaryTask.value
  if (!action || !config) return
  saving.value = true
  message.value = ''
  try {
    let successMessage = ''
    if (action === 'delete') {
      await deleteSummaryTaskConfig(config.id)
      successMessage = `汇总任务“${config.task_name}”已删除。`
    } else if (action === 'run') {
      runningConfigId.value = config.id
      const result = await runSummaryTaskConfigNow(config.id)
      successMessage = result.document
        ? `汇总任务“${config.task_name}”已提交，文档 ${result.document.id} 当前状态：${result.document.status_label}。`
        : `汇总任务“${config.task_name}”本次没有生成文档：${result.message}`
    } else {
      await updateSummaryTaskConfig(config.id, { enabled: 0 })
      successMessage = `汇总任务“${config.task_name}”已停用。`
    }
    confirmAction.value = null
    confirmSummaryTask.value = null
    await loadPage()
    message.value = successMessage
  } catch (error) {
    const fallback = action === 'delete' ? '删除汇总任务失败。' : action === 'run' ? `执行汇总任务“${config.task_name}”失败。` : '停用汇总任务失败。'
    message.value = apiErrorMessage(error, fallback)
  } finally {
    saving.value = false
    if (action === 'run') runningConfigId.value = null
  }
}

async function runSummaryTaskNow(config: SummaryTaskConfig) {
  openConfirmDialog('run', config)
}

onMounted(loadPage)
</script>

<template>
  <main class="page-shell">
    <section class="detail-hero">
      <div>
        <p class="eyebrow">Summary Settings</p>
        <h1>汇总设置</h1>
        <p class="subtitle">维护默认汇总说明和按配置执行的汇总任务。</p>
      </div>
      <div class="section-actions">
        <button class="ghost" :disabled="loading" @click="loadPage">{{ loading ? '刷新中...' : '刷新设置' }}</button>
        <button type="button" @click="openAddDialog">添加任务</button>
      </div>
    </section>

    <p v-if="message" class="message">{{ message }}</p>

    <section v-if="settings" class="note-detail">
      <div class="raw-toolbar">
        <h3>默认汇总模板</h3>
        <button class="ghost" type="button" @click="defaultTemplateExpanded = !defaultTemplateExpanded">
          {{ defaultTemplateExpanded ? '收起模板' : '展开模板' }}
        </button>
      </div>
      <div v-if="defaultTemplateExpanded" class="summary-default-template">
        <label>
          汇总说明
          <select v-model="selectedTemplateCategory" class="template-category-select">
            <option v-for="category in templateCategories" :key="category" :value="category">{{ category }}</option>
          </select>
          <textarea v-model="currentSummaryInstruction" rows="6" placeholder="当前分类的默认汇总说明；汇总任务未填写说明时使用这里。" />
        </label>
        <label>
          输出文档模板
          <textarea v-model="currentSummaryDocumentTemplate" rows="10" placeholder="Hermes 汇总输出时会按当前分类的 Markdown 结构组织文档。" />
        </label>
        <div class="page-actions">
          <button type="button" :disabled="saving" @click="saveDefaultInstruction">{{ saving ? '保存中...' : '保存默认模板' }}</button>
        </div>
      </div>
    </section>

    <section class="section-title summary-config-title">
      <div>
        <p class="eyebrow">Summary Jobs</p>
        <h2>汇总任务配置</h2>
      </div>
      <span>{{ summaryTaskConfigs.length }} 个任务</span>
    </section>

    <datalist id="summary-categories">
      <option v-for="category in categories" :key="category" :value="category" />
    </datalist>

    <div class="table-card spaced-title">
      <table class="info-table summary-config-table">
        <colgroup>
          <col class="col-id" />
          <col class="col-task-name" />
          <col class="col-category" />
          <col class="col-duration" />
          <col class="col-title" />
          <col class="col-title" />
          <col class="col-status" />
          <col class="col-platform" />
          <col class="col-status" />
          <col class="col-actions-wide" />
        </colgroup>
        <thead>
          <tr>
            <th>ID</th>
            <th>任务名称</th>
            <th>分类</th>
            <th>范围</th>
            <th>定时</th>
            <th>结果名称模板</th>
            <th>微信推送</th>
            <th>平台</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="summaryTaskConfigs.length === 0">
            <td colspan="10">暂无汇总任务配置。</td>
          </tr>
          <tr v-for="config in summaryTaskConfigs" :key="config.id">
            <td class="mono">{{ config.id }}</td>
            <td>{{ config.task_name }}</td>
            <td>{{ config.category }}</td>
            <td>{{ config.start_days_before }} 天前至昨天</td>
            <td><span class="mono">{{ config.cron_expression }}</span></td>
            <td>
              <span class="mono">{{ config.title_template }}</span>
            </td>
            <td>{{ config.push_to_wechat ? '推送' : '不推送' }}</td>
            <td>{{ config.platform }}</td>
            <td>{{ config.enabled ? '启用' : '停用' }}</td>
            <td>
              <div class="quick-actions">
                <button class="ghost" type="button" :disabled="saving" @click="openEditDialog(config)">修改</button>
                <button class="ghost" type="button" :disabled="saving || runningConfigId === config.id" @click="runSummaryTaskNow(config)">
                  {{ runningConfigId === config.id ? '执行中...' : '立即执行' }}
                </button>
                <button class="ghost" type="button" :disabled="saving" @click="toggleSummaryTaskConfig(config)">{{ config.enabled ? '停用' : '启用' }}</button>
                <button class="danger" type="button" :disabled="saving" @click="removeSummaryTaskConfig(config)">删除</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="summaryTaskDialogOpen" class="modal-backdrop" @click.self="closeAddDialog">
      <section class="confirm-dialog summary-task-dialog" role="dialog" aria-modal="true" aria-labelledby="add-summary-task-title">
        <h2 id="add-summary-task-title">{{ summaryTaskDialogTitle }}</h2>
        <div class="settings-grid">
          <label>任务名称<input v-model="summaryTaskDraft.task_name" /></label>
          <label>分类<input v-model="summaryTaskDraft.category" list="summary-categories" /></label>
          <label>范围<input v-model.number="summaryTaskDraft.start_days_before" type="number" min="1" step="1" /></label>
          <label>平台<input v-model="summaryTaskDraft.platform" /></label>
          <label>定时 Cron<input v-model="summaryTaskDraft.cron_expression" placeholder="0 7 * * *" /></label>
          <label>微信推送
            <select v-model.number="summaryTaskDraft.push_to_wechat">
              <option :value="0">不推送</option>
              <option :value="1">推送</option>
            </select>
          </label>
          <label class="settings-wide">结果名称模板<input v-model="summaryTaskDraft.title_template" /></label>
          <div class="settings-wide template-helper">
            <div class="template-tokens">
              <span class="mono">{start_date:%Y-%m-%d}</span>
              <span class="mono">{end_date:%Y-%m-%d}</span>
              <span class="mono">{category}</span>
              <span class="mono">{platform}</span>
            </div>
            <p>示例：{{ summaryTaskSample }}</p>
          </div>
          <label class="settings-wide">汇总说明<textarea v-model="summaryTaskDraft.summary_instruction" rows="6" /></label>
        </div>
        <div class="dialog-actions">
          <button class="ghost" type="button" :disabled="saving" @click="closeAddDialog">取消</button>
          <button type="button" :disabled="saving" @click="saveSummaryTaskDialog">{{ saving ? '保存中...' : (dialogMode === 'edit' ? '保存修改' : '添加任务') }}</button>
        </div>
      </section>
    </div>

    <div v-if="confirmDialogOpen" class="modal-backdrop" @click.self="closeConfirmDialog">
      <section class="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="summary-task-confirm-title">
        <h2 id="summary-task-confirm-title">{{ confirmDialogTitle }}</h2>
        <p class="dialog-copy">{{ confirmDialogText }}</p>
        <div class="dialog-actions">
          <button class="ghost" type="button" :disabled="saving" @click="closeConfirmDialog">取消</button>
          <button :class="{ danger: confirmAction !== 'run' }" type="button" :disabled="saving" @click="confirmDangerAction">
            {{ saving ? '处理中...' : '确认' }}
          </button>
        </div>
      </section>
    </div>
  </main>
</template>
