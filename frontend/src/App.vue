<script setup lang="ts">
import { routeNames } from './router/routeNames'

const navItems = [
  { routeName: routeNames.fundList, label: '基金估值' },
  { routeName: routeNames.fundNavHistory, label: '历史净值' },
  { routeName: routeNames.operations, label: '运行状态' },
]

const marketItems = [
  { routeName: routeNames.aStockHistory, label: '历史行情' },
]
</script>

<template>
  <div class="app-layout">
    <aside class="app-sidebar">
      <RouterLink class="sidebar-brand" :to="{ name: routeNames.fundList }">
        <span>基金净值预测</span>
      </RouterLink>
      <nav class="sidebar-nav" aria-label="主导航">
        <section class="sidebar-group">
          <p class="sidebar-group-title">基金</p>
          <RouterLink
            v-for="item in navItems"
            :key="item.routeName"
            class="sidebar-link"
            :to="{ name: item.routeName }"
          >
            {{ item.label }}
          </RouterLink>
        </section>
        <section class="sidebar-group">
          <p class="sidebar-group-title">行情</p>
          <RouterLink
            v-for="item in marketItems"
            :key="item.routeName"
            class="sidebar-link"
            :to="{ name: item.routeName }"
          >
            {{ item.label }}
          </RouterLink>
        </section>
      </nav>
    </aside>
    <RouterView />
  </div>
</template>
