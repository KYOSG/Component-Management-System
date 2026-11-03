<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import http from '../api'
import BrandMark from '../components/BrandMark.vue'

const router = useRouter()
const loading = ref(false)
const form = reactive({ email: '', password: '' })
const allowRegister = ref(true)

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
    await http.post('/auth/register', form)
    router.push('/items')
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
        <h1>注册</h1>
        <p class="muted">使用邮箱和密码创建账号，数据按账号隔离。</p>
        <el-alert v-if="!allowRegister" type="info" :closable="false" title="管理员未开放注册，请联系管理员创建账号。" />
        <el-form v-else label-position="top" size="large" @submit.prevent="submit">
          <el-form-item label="邮箱">
            <el-input v-model="form.email" autocomplete="username" prefix-icon="Message" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input
              v-model="form.password"
              type="password"
              show-password
              autocomplete="new-password"
              prefix-icon="Lock"
              placeholder="至少 6 位"
            />
          </el-form-item>
          <el-button class="auth-submit" type="primary" size="large" native-type="submit" :loading="loading">注册并进入</el-button>
        </el-form>
        <p class="auth-foot">已有账号？<router-link to="/login">登录</router-link></p>
      </div>
    </div>
  </div>
</template>
