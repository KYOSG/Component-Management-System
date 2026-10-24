<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import http from '../api'

const router = useRouter()
const loading = ref(false)
const form = reactive({ email: '', password: '' })

async function submit() {
  loading.value = true
  try {
    await http.post('/auth/register', form)
    router.push('/items')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card page-card">
      <h1>注册</h1>
      <p class="muted">使用邮箱和密码创建账号，数据按账号隔离。</p>
      <el-form @submit.prevent="submit">
        <el-form-item label="邮箱">
          <el-input v-model="form.email" autocomplete="username" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" show-password autocomplete="new-password" placeholder="至少 6 位" />
        </el-form-item>
        <el-button type="primary" native-type="submit" :loading="loading" style="width: 100%">注册并进入</el-button>
      </el-form>
      <p>已有账号？<router-link to="/login">登录</router-link></p>
    </div>
  </div>
</template>
