<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import http from '../api'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const form = reactive({ email: '', password: '' })
const allowRegister = ref(false)

onMounted(async () => {
  try {
    const { data } = await http.get('/auth/options')
    allowRegister.value = data.allow_register
  } catch {
    allowRegister.value = false
  }
})

async function submit() {
  loading.value = true
  try {
    const { data } = await http.post('/auth/login', form)
    if (data.must_change_password) {
      router.push('/password')
      return
    }
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
      <h1>电子元件库</h1>
      <p class="muted">登录后管理物料库、物料盒和项目 BOM。</p>
      <el-form @submit.prevent="submit">
        <el-form-item label="账号">
          <el-input v-model="form.email" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password autocomplete="current-password" />
        </el-form-item>
        <el-button type="primary" native-type="submit" :loading="loading" style="width: 100%">登录</el-button>
      </el-form>
      <p v-if="allowRegister">还没有账号？<router-link to="/register">注册</router-link></p>
      <p v-else class="muted">需要账号请联系管理员创建。</p>
    </div>
  </div>
</template>
