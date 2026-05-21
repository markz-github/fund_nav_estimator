<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { apiErrorMessage } from '../../../api/client'
import {
  getInformationSettings,
  updateInformationSettings,
  type InformationSettings,
} from '../api/videos'

const settings = ref<InformationSettings | null>(null)
const loading = ref(false)
const saving = ref(false)
const message = ref('')

async function loadSettings() {
  loading.value = true
  message.value = ''
  try {
    settings.value = await getInformationSettings()
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
      video_note_recent_days: String(settings.value.video_note_recent_days ?? '3'),
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
        <h1>信息流设置</h1>
        <p class="subtitle">维护 B站 Cookie、Bilinote、Hermes 接口参数和各类汇总说明。</p>
      </div>
      <div class="section-actions">
        <button class="ghost" :disabled="loading" @click="loadSettings">{{ loading ? '刷新中...' : '刷新设置' }}</button>
        <button :disabled="saving || !settings" @click="saveSettings">{{ saving ? '保存中...' : '保存设置' }}</button>
      </div>
    </section>

    <p v-if="message" class="message">{{ message }}</p>

    <div v-if="settings" class="settings-grid">
      <label class="settings-wide">B站 Cookie<textarea v-model="settings.bilibili_cookie" rows="3" autocomplete="off" spellcheck="false" /></label>
      <label class="settings-wide">图文投稿过滤关键词<textarea v-model="settings.article_filter_keywords" rows="3" placeholder="可选。多个关键词可用换行、逗号或分号分隔；命中标题或正文的图文投稿不会入库。" /></label>
      <label>Bilinote 地址<input v-model="settings.bilinote_base_url" /></label>
      <label>Provider ID<input v-model="settings.bilinote_provider_id" /></label>
      <label>Model Name<input v-model="settings.bilinote_model_name" /></label>
      <label>Quality<input v-model="settings.bilinote_quality" /></label>
      <label>总结任务视频范围（天）<input v-model="settings.video_note_recent_days" type="number" min="0" step="1" /></label>
      <label>Hermes 地址<input v-model="settings.hermes_base_url" /></label>
      <label>Hermes 鉴权头名<input v-model="settings.hermes_auth_header_name" placeholder="Authorization 或 X-API-Key" /></label>
      <label>Hermes Token<input v-model="settings.hermes_api_key" type="password" autocomplete="off" spellcheck="false" placeholder="可选，作为鉴权头值" /></label>
      <label>Hermes Model<input v-model="settings.hermes_model" placeholder="hermes-agent" /></label>
      <label>Runs 路径<input v-model="settings.hermes_run_path" /></label>
      <label>轮询路径<input v-model="settings.hermes_status_path_template" /></label>
      <label class="settings-wide">微信推送接口<input v-model="settings.wechat_push_webhook_url" placeholder="每日汇总 8 点推送使用" /></label>
      <label>微信推送 Token<input v-model="settings.wechat_push_token" type="password" autocomplete="off" spellcheck="false" placeholder="可选" /></label>
      <label class="settings-wide">Hermes 手动汇总说明<textarea v-model="settings.hermes_summary_instruction" rows="5" placeholder="可选。仅用于在笔记管理中手动选择笔记生成的汇总。" /></label>
      <label class="settings-wide">Hermes 日汇总说明<textarea v-model="settings.hermes_daily_summary_instruction" rows="5" placeholder="可选。仅用于每日定时汇总和手动生成每日汇总。" /></label>
      <label class="settings-wide">Hermes 周汇总说明<textarea v-model="settings.hermes_weekly_summary_instruction" rows="5" placeholder="可选。仅用于每周定时汇总上周一至上周日发布内容。" /></label>
    </div>
  </main>
</template>
