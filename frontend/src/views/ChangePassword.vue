<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import http from '../api'

const router = useRouter()
const loading = ref(false)
const forced = ref(false)
const form = reactive({ old_password: '', new_password: '', confirm: '' })

onMounted(async () => {
  const { data } = await http.get('/auth/me')
  forced.value = data.must_change_password
})

async function submit() {
  if (form.new_password.length < 6) {
    ElMessage.error('新密码至少 6 位')
    return
  }
  if (form.new_password !== form.confirm) {
    ElMessage.error('两次输入的新密码不一致')
    return
  }
  loading.value = true
  try {
    await http.post('/auth/password', { old_password: form.old_password, new_password: form.new_password })
    ElMessage.success('密码已修改，其他设备上的登录已失效')
    router.push('/items')
  } finally {
    loading.value = false
  }
}

async function logout() {
  await http.post('/auth/logout')
  router.push('/login')
}
</script>

<template>
  <div class="auth-page">
    <div class="auth-card page-card">
      <h1>修改密码</h1>
      <p v-if="forced" class="muted">当前是初始密码，请先修改后再使用。</p>
      <p v-else class="muted">修改后，其他设备上的登录会失效。</p>
      <el-form @submit.prevent="submit">
        <el-form-item label="原密码">
          <el-input v-model="form.old_password" type="password" show-password autocomplete="current-password" />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="form.new_password" type="password" show-password autocomplete="new-password" placeholder="至少 6 位" />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input v-model="form.confirm" type="password" show-password autocomplete="new-password" />
        </el-form-item>
        <el-button type="primary" native-type="submit" :loading="loading" style="width: 100%">保存新密码</el-button>
      </el-form>
      <p v-if="forced"><el-button link type="primary" @click="logout">退出登录</el-button></p>
      <p v-else><router-link to="/items">返回</router-link></p>
    </div>
  </div>
</template>
