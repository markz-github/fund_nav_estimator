<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'

const props = withDefaults(
  defineProps<{
    open: boolean
    closeOnBackdrop?: boolean
    closeOnEscape?: boolean
  }>(),
  {
    closeOnBackdrop: true,
    closeOnEscape: true,
  },
)

const emit = defineEmits<{
  close: []
}>()

function handleBackdropMouseDown(event: MouseEvent) {
  // 只在按下时已位于遮罩层才关闭。不能依赖 click：它会在弹窗内按下、
  // 移到遮罩层释放时以遮罩层为目标触发，导致误关弹窗。
  if (props.closeOnBackdrop && event.target === event.currentTarget) emit('close')
}

function handleKeyDown(event: KeyboardEvent) {
  if (props.open && props.closeOnEscape && event.key === 'Escape') emit('close')
}

onMounted(() => window.addEventListener('keydown', handleKeyDown))
onBeforeUnmount(() => window.removeEventListener('keydown', handleKeyDown))
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="modal-backdrop" @mousedown="handleBackdropMouseDown">
      <slot />
    </div>
  </Teleport>
</template>
