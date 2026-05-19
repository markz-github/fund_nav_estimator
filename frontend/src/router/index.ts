import { createRouter, createWebHistory } from 'vue-router'
import FundListView from '../modules/fund_nav/views/FundListView.vue'
import FundDetailView from '../modules/fund_nav/views/FundDetailView.vue'
import OperationsView from '../modules/information/views/OperationsView.vue'
import InformationSourcesView from '../modules/information/views/InformationSourcesView.vue'
import InformationVideosView from '../modules/information/views/InformationVideosView.vue'
import InformationNotesView from '../modules/information/views/InformationNotesView.vue'
import InformationNoteDetailView from '../modules/information/views/InformationNoteDetailView.vue'
import InformationSettingsView from '../modules/information/views/InformationSettingsView.vue'
import InformationSummariesView from '../modules/information/views/InformationSummariesView.vue'
import InformationSummaryDetailView from '../modules/information/views/InformationSummaryDetailView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      redirect: '/fund-nav',
    },
    {
      path: '/fund-nav',
      name: 'fund-list',
      component: FundListView,
    },
    {
      path: '/index.html',
      redirect: '/fund-nav',
    },
    {
      path: '/fund-nav/funds/:fundCode',
      name: 'fund-detail',
      component: FundDetailView,
    },
    {
      path: '/information/operations',
      name: 'information-operations',
      component: OperationsView,
    },
    {
      path: '/fund-nav/operations',
      name: 'fund-nav-operations',
      component: OperationsView,
    },
    {
      path: '/information/sources',
      name: 'information-sources',
      component: InformationSourcesView,
    },
    {
      path: '/information/videos',
      name: 'information-videos',
      component: InformationVideosView,
    },
    {
      path: '/information/summaries',
      name: 'information-summaries',
      component: InformationSummariesView,
    },
    {
      path: '/information/summaries/:documentId',
      name: 'information-summary-detail',
      component: InformationSummaryDetailView,
    },
    {
      path: '/information/notes',
      name: 'information-notes',
      component: InformationNotesView,
    },
    {
      path: '/information/notes/:noteId',
      name: 'information-note-detail',
      component: InformationNoteDetailView,
    },
    {
      path: '/information/settings',
      name: 'information-settings',
      component: InformationSettingsView,
    },
    {
      path: '/funds/:fundCode',
      redirect: (to) => `/fund-nav/funds/${to.params.fundCode}`,
    },
    {
      path: '/operations',
      redirect: '/fund-nav/operations',
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/fund-nav',
    },
  ],
})

export default router
