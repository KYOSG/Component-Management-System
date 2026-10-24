import { createRouter, createWebHistory } from 'vue-router'

import http from '../api'
import AdminLayout from '../layouts/AdminLayout.vue'
import Login from '../views/Login.vue'
import Register from '../views/Register.vue'
import Items from '../views/Items.vue'
import MapView from '../views/Map.vue'
import Projects from '../views/Projects.vue'
import ProjectDetail from '../views/ProjectDetail.vue'
import Users from '../views/Users.vue'
import Settings from '../views/Settings.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: Login, meta: { public: true, title: '登录' } },
    { path: '/register', component: Register, meta: { public: true, title: '注册' } },
    {
      path: '/',
      component: AdminLayout,
      children: [
        { path: '', redirect: '/items' },
        { path: 'items', component: Items, meta: { title: '物料库' } },
        { path: 'map', component: MapView, meta: { title: '物料盒地图' } },
        { path: 'projects', component: Projects, meta: { title: '项目 BOM' } },
        { path: 'projects/:id', component: ProjectDetail, meta: { title: '匹配结果' } },
        { path: 'users', component: Users, meta: { title: '账户管理', admin: true } },
        { path: 'settings', component: Settings, meta: { title: '系统配置', admin: true } },
      ],
    },
  ],
})

router.beforeEach(async (to) => {
  if (to.meta.public) return true
  try {
    const { data } = await http.get('/auth/me')
    if (to.matched.some((record) => record.meta.admin) && !data.is_admin) return '/items'
    return true
  } catch {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
})

export default router
