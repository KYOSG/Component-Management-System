<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import http, { reportRequestError } from '../api'
import BrandMark from '../components/BrandMark.vue'

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
      await router.push('/password')
      return
    }
    const redirect = typeof route.query.redirect === 'string' && route.query.redirect.startsWith('/')
      ? route.query.redirect
      : '/items'
    await router.push(redirect)
  } catch (error) {
    reportRequestError(error)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-panel">
      <BrandMark />
      <div class="auth-card page-card">
        <h1>登录</h1>
        <p class="muted">登录后管理物料库、物料盒和项目 BOM。</p>
        <el-form label-position="top" size="large" @submit.prevent="submit">
          <el-form-item label="账号">
            <el-input v-model="form.email" autocomplete="username" prefix-icon="User" placeholder="账号或邮箱" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input
              v-model="form.password"
              type="password"
              show-password
              autocomplete="current-password"
              prefix-icon="Lock"
            />
          </el-form-item>
          <el-button class="auth-submit" type="primary" size="large" native-type="submit" :loading="loading">登录</el-button>
        </el-form>
        <p v-if="allowRegister" class="auth-foot">还没有账号？<router-link to="/register">注册</router-link></p>
        <p v-else class="auth-foot">需要账号请联系管理员创建。</p>
      </div>
    </div>
  </div>
</template>
