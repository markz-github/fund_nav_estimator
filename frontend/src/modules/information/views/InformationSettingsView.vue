<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { apiErrorMessage } from '../../../api/client'
import {
  getInformationSettings,
  listInformationCategories,
  updateInformationSettings,
  type InformationSettings,
} from '../api/videos'

const settings = ref<InformationSettings | null>(null)
const categories = ref<string[]>(['财经'])
const loading = ref(false)
const saving = ref(false)
const message = ref('')
const selectedBilinoteExtraCategory = ref('财经')

const bilinoteExtraCategories = computed(() => {
  const storedCategories = settings.value?.bilinote_extra_templates.map((item) => item.category) || []
  return Array.from(new Set(['财经', ...categories.value, ...storedCategories])).filter(Boolean)
})

const currentBilinoteExtras = computed({
  get() {
    if (!settings.value) return ''
    return settings.value.bilinote_extra_templates.find((item) => item.category === selectedBilinoteExtraCategory.value)?.extras || ''
  },
  set(value: string) {
    if (!settings.value) return
    const existing = settings.value.bilinote_extra_templates.find((item) => item.category === selectedBilinoteExtraCategory.value)
    if (existing) {
      existing.extras = value
      return
    }
    settings.value.bilinote_extra_templates.push({
      category: selectedBilinoteExtraCategory.value,
      extras: value,
    })
  },
})

async function loadSettings() {
  loading.value = true
  message.value = ''
  try {
    const [settingsResult, categoryResult] = await Promise.all([
      getInformationSettings(),
      listInformationCategories(),
    ])
    settings.value = settingsResult
    categories.value = categoryResult
    if (!bilinoteExtraCategories.value.includes(selectedBilinoteExtraCategory.value)) {
      selectedBilinoteExtraCategory.value = bilinoteExtraCategories.value[0] || '财经'
    }
  } catch (error) {
    message.value = apiErrorMessage(error, '设置加载失败。')
  } finally {
    loading.value = false
  }
}

async function saveSettings() {
  if (!settings.value) return
  saving.value = true
  message.value = ''
  try {
    settings.value = await updateInformationSettings({
      ...settings.value,
      article_min_content_chars: String(settings.value.article_min_content_chars ?? '0'),
      video_note_recent_days: String(settings.value.video_note_recent_days ?? '3'),
      video_source_scan_jitter_min_seconds: String(settings.value.video_source_scan_jitter_min_seconds ?? '1'),
      video_source_scan_jitter_max_seconds: String(settings.value.video_source_scan_jitter_max_seconds ?? '3'),
    })
    message.value = '设置已保存。'
  } catch (error) {
    message.value = apiErrorMessage(error, '保存设置失败。')
  } finally {
    saving.value = false
  }
}

onMounted(loadSettings)
</script>

<template>
  <main class="page-shell">
    <section class="detail-hero">
      <div>
        <p class="eyebrow">Settings</p>
        <h1>系统设置</h1>
        <p class="subtitle">维护 B站 Cookie、Bilinote、Hermes 和微信推送接口参数。</p>
      </div>
      <div class="section-actions">
        <button class="ghost" :disabled="loading" @click="loadSettings">{{ loading ? '刷新中...' : '刷新设置' }}</button>
        <button :disabled="saving || !settings" @click="saveSettings">{{ saving ? '保存中...' : '保存设置' }}</button>
      </div>
    </section>

    <p v-if="message" class="message">{{ message }}</p>

    <div v-if="settings" class="settings-sections information-settings-layout">
      <section class="settings-section settings-panel settings-panel-wide">
        <div class="settings-section-header">
          <div>
            <p>Bilibili</p>
            <h2>B站采集</h2>
          </div>
        </div>
        <div class="settings-grid">
          <label class="settings-wide">B站 Cookie<textarea v-model="settings.bilibili_cookie" rows="3" autocomplete="off" spellcheck="false" /></label>
          <label class="settings-wide">图文投稿过滤关键词<textarea v-model="settings.article_filter_keywords" rows="3" placeholder="可选。多个关键词可用换行、逗号或分号分隔；命中标题或正文的图文投稿不会入库。" /></label>
          <label>图文投稿最少字数<input v-model="settings.article_min_content_chars" type="number" min="0" step="1" /></label>
          <label>扫描抖动最小秒数<input v-model="settings.video_source_scan_jitter_min_seconds" type="number" min="0" step="0.1" /></label>
          <label>扫描抖动最大秒数<input v-model="settings.video_source_scan_jitter_max_seconds" type="number" min="0" step="0.1" /></label>
        </div>
      </section>

      <section class="settings-section settings-panel">
        <div class="settings-section-header">
          <div>
            <p>Notes</p>
            <h2>Bilinote 笔记</h2>
          </div>
        </div>
        <div class="settings-grid">
          <label>Bilinote 地址<input v-model="settings.bilinote_base_url" /></label>
          <label>Provider ID<input v-model="settings.bilinote_provider_id" /></label>
          <label>Model Name<input v-model="settings.bilinote_model_name" /></label>
          <label>Quality
            <el-select v-model="settings.bilinote_quality" class="settings-select" fit-input-width>
              <el-option label="fast" value="fast" />
              <el-option label="medium" value="medium" />
              <el-option label="slow" value="slow" />
            </el-select>
          </label>
          <label>自动笔记候选范围（天）<input v-model="settings.video_note_recent_days" type="number" min="0" step="1" /></label>
          <label class="settings-wide">分类附加说明
            <el-select v-model="selectedBilinoteExtraCategory" class="settings-select template-category-select" fit-input-width>
              <el-option v-for="category in bilinoteExtraCategories" :key="category" :label="category" :value="category" />
            </el-select>
            <textarea v-model="currentBilinoteExtras" rows="6" placeholder="会作为 extras 传给 Bilinote，并追加到生成 prompt 后面。可按分类约定单篇视频总结的输出结构。" />
          </label>
        </div>
      </section>

      <section class="settings-section settings-panel">
        <div class="settings-section-header">
          <div>
            <p>Summary</p>
            <h2>Hermes 汇总</h2>
          </div>
        </div>
        <div class="settings-grid">
          <label>Hermes 地址<input v-model="settings.hermes_base_url" /></label>
          <label>Hermes 鉴权头名<input v-model="settings.hermes_auth_header_name" placeholder="Authorization 或 X-API-Key" /></label>
          <label>Hermes Token<input v-model="settings.hermes_api_key" type="password" autocomplete="off" spellcheck="false" placeholder="可选，作为鉴权头值" /></label>
          <label>Hermes Model<input v-model="settings.hermes_model" placeholder="hermes-agent" /></label>
          <label>Runs 路径<input v-model="settings.hermes_run_path" /></label>
          <label>轮询路径<input v-model="settings.hermes_status_path_template" /></label>
        </div>
      </section>

      <section class="settings-section settings-panel settings-panel-wide">
        <div class="settings-section-header">
          <div>
            <p>Push</p>
            <h2>微信推送</h2>
          </div>
        </div>
        <div class="settings-grid">
          <label class="settings-wide">微信推送接口<input v-model="settings.wechat_push_webhook_url" placeholder="汇总任务推送使用" /></label>
          <label>微信推送 Token<input v-model="settings.wechat_push_token" type="password" autocomplete="off" spellcheck="false" placeholder="可选" /></label>
        </div>
      </section>
    </div>
  </main>
</template>
