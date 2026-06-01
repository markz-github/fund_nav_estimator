<script setup lang="ts">
const navItems = [
  { to: '/', label: '基金估值' },
  { to: '/operations', label: '运行状态' },
]
</script>

<template>
  <aside class="app-sidebar">
    <RouterLink class="sidebar-brand" to="/">
      <span>基金净值预测</span>
    </RouterLink>
    <nav class="sidebar-nav" aria-label="主导航">
      <section class="sidebar-group">
        <p class="sidebar-group-title">基金</p>
        <RouterLink
          v-for="item in navItems"
          :key="item.to"
          class="sidebar-link"
          :to="item.to"
        >
          {{ item.label }}
        </RouterLink>
      </section>
    </nav>
  </aside>
</template>
