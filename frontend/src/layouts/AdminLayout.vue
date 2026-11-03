<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import http from '../api'
import BrandMark from '../components/BrandMark.vue'

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
const initial = computed(() => (email.value || '?').slice(0, 1).toUpperCase())

onMounted(async () => {
  const { data } = await http.get('/auth/me')
  email.value = data.email
  isAdmin.value = data.is_admin
})

async function logout() {
  await http.post('/auth/logout')
  router.push('/login')
}

function onUserCommand(command) {
  if (command === 'password') router.push('/password')
  if (command === 'logout') logout()
}
</script>

<template>
  <el-container class="shell">
    <el-aside class="aside" width="232px">
      <BrandMark />
      <el-menu
        :key="isAdmin ? 'admin' : 'user'"
        class="side-menu"
        :default-active="active"
        :default-openeds="['settings']"
        router
      >
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
        <el-dropdown trigger="click" @command="onUserCommand">
          <button type="button" class="user-chip">
            <span class="user-avatar">{{ initial }}</span>
            <span class="user-email">{{ email }}</span>
            <el-icon><ArrowDown /></el-icon>
          </button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="password" icon="Lock">修改密码</el-dropdown-item>
              <el-dropdown-item command="logout" icon="SwitchButton" divided>退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-main class="main">
        <router-view v-slot="{ Component }">
          <transition name="page-fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>
