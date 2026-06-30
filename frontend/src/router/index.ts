import { createRouter, createWebHistory } from 'vue-router'
import FundListView from '../modules/fund_nav/views/FundListView.vue'
import FundDetailView from '../modules/fund_nav/views/FundDetailView.vue'
import EstimateDriftDetailView from '../modules/fund_nav/views/EstimateDriftDetailView.vue'
import EstimateDriftListView from '../modules/fund_nav/views/EstimateDriftListView.vue'
import FundNavQualityView from '../modules/fund_nav/views/FundNavQualityView.vue'
import ManualIndexMappingsView from '../modules/fund_nav/views/ManualIndexMappingsView.vue'
import OperationsView from '../modules/fund_nav/operations/views/OperationsView.vue'
import AStockHistoryView from '../modules/a_stock/views/AStockHistoryView.vue'
import AStockHistoryTaskView from '../modules/a_stock/views/AStockHistoryTaskView.vue'
import { routeNames } from './routeNames'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      redirect: { name: routeNames.fundList },
    },
    {
      path: '/fund-nav',
      name: routeNames.fundList,
      component: FundListView,
    },
    {
      path: '/index.html',
      redirect: { name: routeNames.fundList },
    },
    {
      path: '/fund-nav/funds/:fundCode',
      name: routeNames.fundDetail,
      component: FundDetailView,
    },
    {
      path: '/fund-nav/quality/nav',
      name: routeNames.fundNavQuality,
      component: FundNavQualityView,
    },
    {
      path: '/fund-nav/quality/estimate-drift',
      name: routeNames.estimateDriftList,
      component: EstimateDriftListView,
    },
    {
      path: '/fund-nav/quality/estimate-drift/:fundCode',
      name: routeNames.estimateDriftDetail,
      component: EstimateDriftDetailView,
    },
    {
      path: '/fund-nav/index-mappings/manual',
      name: routeNames.manualIndexMappings,
      component: ManualIndexMappingsView,
    },
    {
      path: '/fund-nav/operations',
      name: routeNames.operations,
      component: OperationsView,
    },
    {
      path: '/fund-nav/history',
      name: routeNames.fundNavHistory,
      redirect: { name: routeNames.fundList },
    },
    {
      path: '/fund-nav/history/tasks/:taskId',
      name: routeNames.fundNavHistoryTask,
      redirect: { name: routeNames.fundList },
    },
    {
      path: '/a-stocks/history',
      name: routeNames.aStockHistory,
      component: AStockHistoryView,
    },
    {
      path: '/a-stocks/history/tasks/:taskId',
      name: routeNames.aStockHistoryTask,
      component: AStockHistoryTaskView,
    },
    {
      path: '/funds/:fundCode',
      redirect: (to) => ({ name: routeNames.fundDetail, params: { fundCode: to.params.fundCode } }),
    },
    {
      path: '/operations',
      redirect: { name: routeNames.operations },
    },
    {
      path: '/a-stocks',
      redirect: { name: routeNames.aStockHistory },
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: { name: routeNames.fundList },
    },
  ],
})

export default router
