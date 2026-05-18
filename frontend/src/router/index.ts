import { createRouter, createWebHistory } from 'vue-router'
import FundListView from '../modules/fund_nav/views/FundListView.vue'
import FundDetailView from '../modules/fund_nav/views/FundDetailView.vue'
import OperationsView from '../modules/information/views/OperationsView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'fund-list',
      component: FundListView,
    },
    {
      path: '/index.html',
      redirect: '/',
    },
    {
      path: '/funds/:fundCode',
      name: 'fund-detail',
      component: FundDetailView,
    },
    {
      path: '/operations',
      name: 'operations',
      component: OperationsView,
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/',
    },
  ],
})

export default router
