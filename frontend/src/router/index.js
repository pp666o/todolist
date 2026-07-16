import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: () => import('../views/Home.vue')
  },
  {
    path: '/matches',
    name: 'UserMatches',
    component: () => import('../views/UserMatches.vue')
  },
  {
    path: '/match-details/:userId1/:userId2',
    name: 'MatchDetails',
    component: () => import('../views/MatchDetails.vue'),
    props: true
  },
  {
    path: '/recommendations/:userId1/:userId2',
    name: 'PairRecommendations',
    component: () => import('../views/PairRecommendations.vue'),
    props: true
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router 