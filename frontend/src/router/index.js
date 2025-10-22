import { createRouter, createWebHistory } from 'vue-router'
import SimpleWebRTC from '../views/SimpleWebRTC.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: SimpleWebRTC
    }
  ],
})

export default router
