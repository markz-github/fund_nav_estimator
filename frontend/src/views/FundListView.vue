<script setup lang="ts">
import { onMounted, ref } from 'vue'
import FundTable from '../components/FundTable.vue'
import { createFund, deleteFund, listFunds, refreshFundNav, type Fund } from '../api/funds'

const funds = ref<Fund[]>([])
const fundCode = ref('')
const remark = ref('')
const loading = ref(false)
const saving = ref(false)
const message = ref('')

async function loadFunds() {
  loading.value = true
  message.value = ''
  try {
    funds.value = await listFunds()
  } catch (error) {
    message.value = '基金列表加载失败，请确认后端服务和 MySQL 配置。'
  } finally {
    loading.value = false
  }
}

async function submitFund() {
  if (!fundCode.value.trim()) return
  saving.value = true
  try {
    await createFund(fundCode.value.trim(), remark.value.trim() || undefined)
    fundCode.value = ''
    remark.value = ''
    await loadFunds()
  } catch (error) {
    message.value = '新增基金失败，请检查基金代码或后端日志。'
  } finally {
    saving.value = false
  }
}

async function removeFund(code: string) {
  await deleteFund(code)
  await loadFunds()
}

async function refreshNav(code: string) {
  await refreshFundNav(code)
  await loadFunds()
}

onMounted(loadFunds)
</script>

<template>
  <main class="page-shell">
    <section class="hero">
      <div>
        <p class="eyebrow">Intraday Fund NAV Lab</p>
        <h1>基金当日净值预测</h1>
        <p class="subtitle">
          维护自选基金池，定时同步持仓与行情，用半小时粒度估算当日基金净值。
        </p>
      </div>
      <form class="add-card" @submit.prevent="submitFund">
        <label>
          基金代码
          <input v-model="fundCode" placeholder="例如 000001" />
        </label>
        <label>
          备注
          <input v-model="remark" placeholder="可选" />
        </label>
        <button type="submit" :disabled="saving">{{ saving ? '添加中...' : '加入自选' }}</button>
      </form>
    </section>

    <p v-if="message" class="message">{{ message }}</p>
    <FundTable :funds="funds" :loading="loading" @delete="removeFund" @refresh="refreshNav" />
  </main>
</template>
