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
  return route.path
})

const title = computed(() => route.meta.title || '物品映射')

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
      <div class="brand">物品映射</div>
      <el-menu :default-active="active" router>
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
        <el-menu-item v-if="isAdmin" index="/users">
          <el-icon><User /></el-icon>
          <span>账户管理</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <h2>{{ title }}</h2>
        <div>
          <span class="muted">{{ email }}</span>
          <el-button link type="primary" @click="logout">退出</el-button>
        </div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>
