import { createRouter, createWebHistory } from 'vue-router'
import FundListView from '../views/FundListView.vue'
import FundDetailView from '../views/FundDetailView.vue'
import OperationsView from '../views/OperationsView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'fund-list',
      component: FundListView,
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
  ],
})

export default router
