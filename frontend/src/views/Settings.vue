<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '../api'

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const trialPrompt = ref('')
const trialOutput = ref('')
const loaded = ref({ database_location: '', database_name: '' })
const form = reactive({
  database_location: '',
  database_name: '',
  deepseek_api_key: '',
  deepseek_base_url: '',
  deepseek_model: '',
})

function apply(data) {
  form.database_location = data.database_location
  form.database_name = data.database_name
  form.deepseek_api_key = data.deepseek_api_key
  form.deepseek_base_url = data.deepseek_base_url
  form.deepseek_model = data.deepseek_model
  loaded.value = {
    database_location: data.database_location,
    database_name: data.database_name,
  }
}

async function load() {
  loading.value = true
  try {
    const { data } = await http.get('/settings')
    apply(data)
  } finally {
    loading.value = false
  }
}

async function save() {
  const databaseChanged =
    form.database_location !== loaded.value.database_location || form.database_name !== loaded.value.database_name
  if (databaseChanged) {
    try {
      await ElMessageBox.confirm(
        '切换后将使用目标数据库里的数据。如果文件还不存在，会初始化为空库，管理员账号是 admin / admin。当前库的数据不会被复制过去。',
        '切换数据库',
        { type: 'warning', confirmButtonText: '保存并切换', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
  }
  saving.value = true
  try {
    const { data } = await http.put('/settings', { ...form })
    ElMessage.success('已保存系统配置')
    if (databaseChanged) {
      window.location.assign('/settings')
      return
    }
    apply(data)
  } finally {
    saving.value = false
  }
}

async function testAi() {
  testing.value = true
  trialOutput.value = ''
  try {
    const { data } = await http.post(
      '/settings/ai-test',
      {
        prompt: trialPrompt.value,
        deepseek_api_key: form.deepseek_api_key,
        deepseek_base_url: form.deepseek_base_url,
        deepseek_model: form.deepseek_model,
      },
      { timeout: 70000 },
    )
    trialOutput.value = data.output
  } catch {
    trialOutput.value = ''
  } finally {
    testing.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="page-card">
    <el-form label-width="140px" style="max-width: 720px" @submit.prevent="save">
      <h3>数据库</h3>
      <el-form-item label="数据库位置">
        <el-input v-model="form.database_location" placeholder="例如 F:\data 或 ./data" />
      </el-form-item>
      <el-form-item label="数据库名字">
        <el-input v-model="form.database_name" placeholder="例如 app.db" />
      </el-form-item>
      <h3>辅助 AI</h3>
      <el-form-item label="API Key">
        <el-input
          v-model="form.deepseek_api_key"
          type="password"
          show-password
          autocomplete="off"
          placeholder="留空则不启用智能建议"
        />
      </el-form-item>
      <el-form-item label="接口地址">
        <el-input v-model="form.deepseek_base_url" placeholder="https://api.deepseek.com" />
      </el-form-item>
      <el-form-item label="模型">
        <el-input v-model="form.deepseek_model" placeholder="deepseek-chat" />
      </el-form-item>
      <el-form-item label="测试内容">
        <el-input v-model="trialPrompt" type="textarea" :rows="4" placeholder="随便输入一段话，发给当前填写的模型" />
      </el-form-item>
      <el-form-item>
        <el-button :loading="testing" @click="testAi">测试</el-button>
      </el-form-item>
      <el-form-item v-if="trialOutput" label="模型输出">
        <el-input :model-value="trialOutput" type="textarea" :rows="6" readonly />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </el-form-item>
    </el-form>
    <p class="muted">这些配置写入当前数据库。API Key 留空时不启用智能建议。只有数据库位置或名字变化时才会切换数据库。</p>
  </div>
</template>
