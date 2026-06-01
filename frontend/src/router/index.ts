import { createRouter, createWebHistory } from 'vue-router'
import FundListView from '../modules/fund_nav/views/FundListView.vue'
import FundDetailView from '../modules/fund_nav/views/FundDetailView.vue'
import OperationsView from '../modules/fund_nav/views/OperationsView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', redirect: '/fund-nav' },
    { path: '/fund-nav', name: 'fund-list', component: FundListView },
    { path: '/index.html', redirect: '/fund-nav' },
    { path: '/fund-nav/funds/:fundCode', name: 'fund-detail', component: FundDetailView },
    { path: '/fund-nav/operations', name: 'fund-nav-operations', component: OperationsView },
    { path: '/funds/:fundCode', redirect: (to) => `/fund-nav/funds/${to.params.fundCode}` },
    { path: '/operations', redirect: '/fund-nav/operations' },
    { path: '/:pathMatch(.*)*', redirect: '/fund-nav' },
  ],
})

export default router
