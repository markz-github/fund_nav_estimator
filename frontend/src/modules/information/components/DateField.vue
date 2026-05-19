<script setup lang="ts">
import { computed } from 'vue'
import { VueDatePicker } from '@vuepic/vue-datepicker'
import '@vuepic/vue-datepicker/dist/main.css'
import { zhCN } from 'date-fns/locale/zh-CN'

const model = defineModel<string>({ default: '' })

defineProps<{
  placeholder?: string
}>()

function normalizeDateValue(value: unknown) {
  if (value instanceof Date && !Number.isNaN(value.getTime())) {
    const year = value.getFullYear()
    const month = String(value.getMonth() + 1).padStart(2, '0')
    const day = String(value.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
  }
  if (typeof value !== 'string') return ''
  const match = value.match(/(\d{4})[-/](\d{1,2})[-/](\d{1,2})/)
  if (!match) return ''
  const [, year, month, day] = match
  return `${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`
}

const pickerValue = computed(() => normalizeDateValue(model.value) || null)

function updateValue(value: string | Date | null) {
  model.value = normalizeDateValue(value)
}
</script>

<template>
  <VueDatePicker
    :model-value="pickerValue"
    model-type="yyyy-MM-dd"
    :formats="{ input: 'yyyy-MM-dd', preview: 'yyyy-MM-dd' }"
    :time-config="{ enableTimePicker: false, enableMinutes: false, enableSeconds: false }"
    :hide-navigation="['time', 'hours', 'minutes', 'seconds']"
    :action-row="{ showNow: false }"
    :locale="zhCN"
    auto-apply
    :clearable="true"
    :teleport="true"
    :placeholder="placeholder || '选择日期'"
    input-class-name="app-date-input"
    menu-class-name="app-date-menu"
    @update:model-value="updateValue"
  />
</template>
