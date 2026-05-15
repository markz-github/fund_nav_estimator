import { createRouter, createWebHistory } from 'vue-router'
import FundListView from '../views/FundListView.vue'
import FundDetailView from '../views/FundDetailView.vue'
import OperationsView from '../views/OperationsView.vue'

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
