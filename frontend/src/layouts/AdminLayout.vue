<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import http from '../api'

const route = useRoute()
const router = useRouter()
const email = ref('')
const isAdmin = ref(false)

const active = computed(() => {
  if (route.path.startsWith('/projects')) return '/projects'
  if (route.path.startsWith('/users')) return '/users'
  if (route.path.startsWith('/settings/categories')) return '/settings/categories'
  if (route.path.startsWith('/settings')) return '/settings'
  return route.path
})

const title = computed(() => route.meta.title || '电子元件库')

onMounted(async () => {
  const { data } = await http.get('/auth/me')
  email.value = data.email
  isAdmin.value = data.is_admin
})

async function logout() {
  await http.post('/auth/logout')
  router.push('/login')
}
</script>

<template>
  <el-container class="shell">
    <el-aside class="aside" width="220px">
      <div class="brand">电子元件库</div>
      <el-menu :key="isAdmin ? 'admin' : 'user'" :default-active="active" :default-openeds="['settings']" router>
        <el-menu-item index="/items">
          <el-icon><Goods /></el-icon>
          <span>物料库</span>
        </el-menu-item>
        <el-menu-item index="/map">
          <el-icon><Grid /></el-icon>
          <span>物料盒地图</span>
        </el-menu-item>
        <el-menu-item index="/projects">
          <el-icon><Document /></el-icon>
          <span>项目 BOM</span>
        </el-menu-item>
        <el-menu-item index="/statistics">
          <el-icon><TrendCharts /></el-icon>
          <span>物料统计</span>
        </el-menu-item>
        <el-menu-item v-if="isAdmin" index="/users">
          <el-icon><User /></el-icon>
          <span>账户管理</span>
        </el-menu-item>
        <el-sub-menu index="settings">
          <template #title>
            <el-icon><Setting /></el-icon>
            <span>系统配置</span>
          </template>
          <el-menu-item v-if="isAdmin" index="/settings">基本设置</el-menu-item>
          <el-menu-item index="/settings/categories">参数配置</el-menu-item>
        </el-sub-menu>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <h2>{{ title }}</h2>
        <div>
          <span class="muted">{{ email }}</span>
          <el-button link type="primary" @click="router.push('/password')">修改密码</el-button>
          <el-button link type="primary" @click="logout">退出</el-button>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>
