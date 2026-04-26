import { createRouter, createWebHistory } from 'vue-router'
import FundListView from '../views/FundListView.vue'
import FundDetailView from '../views/FundDetailView.vue'

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
  ],
})

export default router
