<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { extractMarkdownHeadings, renderMarkdown } from '../utils/markdown'

const props = defineProps<{
  content?: string | null
  showToc?: boolean
}>()

const renderedContent = computed(() => renderMarkdown(props.content || ''))
const headings = computed(() => extractMarkdownHeadings(props.content || ''))
const tocRef = ref<HTMLElement | null>(null)
const activeHeadingId = ref('')

function scrollToHeading(headingId: string) {
  window.document.getElementById(headingId)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function syncActiveHeading() {
  if (!props.showToc || headings.value.length === 0) {
    activeHeadingId.value = ''
    return
  }
  let currentId = headings.value[0].id
  for (const heading of headings.value) {
    const element = window.document.getElementById(heading.id)
    if (!element) continue
    if (element.getBoundingClientRect().top <= 120) {
      currentId = heading.id
    } else {
      break
    }
  }
  if (activeHeadingId.value === currentId) return
  activeHeadingId.value = currentId
  nextTick(() => {
    const toc = tocRef.value
    const activeItem = toc?.querySelector<HTMLElement>(`[data-heading-id="${currentId}"]`)
    if (!toc || !activeItem) return
    toc.scrollTo({ top: Math.max(0, activeItem.offsetTop - 10), behavior: 'smooth' })
  })
}

onMounted(() => {
  window.addEventListener('scroll', syncActiveHeading, { passive: true })
  nextTick(syncActiveHeading)
})

onUnmounted(() => {
  window.removeEventListener('scroll', syncActiveHeading)
})

watch(headings, () => nextTick(syncActiveHeading))
</script>

<template>
  <div :class="showToc ? 'markdown-with-toc' : 'markdown-without-toc'">
    <aside v-if="showToc" ref="tocRef" class="markdown-toc">
      <h3>目录</h3>
      <nav v-if="headings.length > 0" aria-label="正文目录">
        <button
          v-for="heading in headings"
          :key="heading.id"
          type="button"
          :data-heading-id="heading.id"
          :class="[`toc-level-${heading.level}`, { active: activeHeadingId === heading.id }]"
          @click="scrollToHeading(heading.id)"
        >
          {{ heading.text }}
        </button>
      </nav>
      <p v-else class="muted">暂无目录。</p>
    </aside>

    <article class="markdown-body" v-html="renderedContent"></article>
  </div>
</template>
