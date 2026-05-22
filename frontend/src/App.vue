<script setup lang="ts">
const navGroups = [
  {
    label: '基金',
    items: [
      { to: '/fund-nav', label: '基金估值' },
      { to: '/fund-nav/operations', label: '运行状态' },
    ],
  },
  {
    label: '信息流',
    items: [
      { to: '/information/sources', label: '信息源管理' },
      { to: '/information/videos', label: '信息管理' },
      { to: '/information/notes', label: '笔记管理' },
      { to: '/information/summaries', label: '笔记汇总' },
      { to: '/information/operations', label: '运行状态' },
      { to: '/information/settings', label: '接口设置' },
    ],
  },
]
</script>

<template>
  <div class="app-layout">
    <aside class="app-sidebar">
      <RouterLink class="sidebar-brand" to="/fund-nav">
        <span>基金净值预测</span>
      </RouterLink>
      <nav class="sidebar-nav" aria-label="主导航">
        <section v-for="group in navGroups" :key="group.label" class="sidebar-group">
          <p class="sidebar-group-title">{{ group.label }}</p>
          <RouterLink
            v-for="item in group.items"
            :key="item.to"
            class="sidebar-link"
            :to="item.to"
          >
            {{ item.label }}
          </RouterLink>
        </section>
      </nav>
    </aside>
    <RouterView />
  </div>
</template>
