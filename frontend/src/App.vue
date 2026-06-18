<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppLogo from './modules/fund_nav/components/AppLogo.vue'
import { routeNames } from './router/routeNames'

const route = useRoute()
const mobileMenuOpen = ref(false)

const navItems = [
  { routeName: routeNames.fundList, label: '基金估值' },
  { routeName: routeNames.operations, label: '运行状态' },
]

const marketItems = [
  { routeName: routeNames.aStockHistory, label: '历史行情' },
]

watch(
  () => route.fullPath,
  () => {
    mobileMenuOpen.value = false
  },
)
</script>

<template>
  <div class="app-layout">
    <aside class="app-sidebar" :class="{ 'is-open': mobileMenuOpen }">
      <div class="sidebar-top">
        <RouterLink class="sidebar-brand" :to="{ name: routeNames.fundList }">
          <AppLogo />
          <span>基金净值预测</span>
        </RouterLink>
        <button
          class="sidebar-toggle"
          type="button"
          :aria-expanded="mobileMenuOpen"
          aria-controls="primary-navigation"
          aria-label="展开或收起导航菜单"
          @click="mobileMenuOpen = !mobileMenuOpen"
        >
          <span></span>
          <span></span>
          <span></span>
        </button>
      </div>
      <nav id="primary-navigation" class="sidebar-nav" aria-label="主导航">
        <section class="sidebar-group">
          <p class="sidebar-group-title">基金</p>
          <RouterLink
            v-for="item in navItems"
            :key="item.routeName"
            class="sidebar-link"
            :to="{ name: item.routeName }"
            @click="mobileMenuOpen = false"
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
            @click="mobileMenuOpen = false"
          >
            {{ item.label }}
          </RouterLink>
        </section>
      </nav>
    </aside>
    <RouterView />
  </div>
</template>
