<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import http from '../api'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const form = reactive({ email: '', password: '' })

async function submit() {
  loading.value = true
  try {
    await http.post('/auth/login', form)
    const redirect = typeof route.query.redirect === 'string' && route.query.redirect.startsWith('/')
      ? route.query.redirect
      : '/items'
    router.push(redirect)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card page-card">
      <h1>物品映射</h1>
      <p class="muted">登录后管理物料库、物料盒和项目 BOM。</p>
      <el-form @submit.prevent="submit">
        <el-form-item label="邮箱">
          <el-input v-model="form.email" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password autocomplete="current-password" />
        </el-form-item>
        <el-button type="primary" native-type="submit" :loading="loading" style="width: 100%">登录</el-button>
      </el-form>
      <p>还没有账号？<router-link to="/register">注册</router-link></p>
    </div>
  </div>
</template>
