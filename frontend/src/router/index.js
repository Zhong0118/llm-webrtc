import { createRouter, createWebHistory } from 'vue-router'
import WebRTCApp from '../components/WebRTCApp.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: WebRTCApp
    }
  ],
})

export default router
