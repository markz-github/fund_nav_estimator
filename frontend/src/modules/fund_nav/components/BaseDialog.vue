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

function close() {
  emit('close')
}

function handleBackdropMouseDown(event: MouseEvent) {
  if (props.closeOnBackdrop && event.target === event.currentTarget) close()
}

function handleKeyDown(event: KeyboardEvent) {
  if (props.open && props.closeOnEscape && event.key === 'Escape') close()
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
