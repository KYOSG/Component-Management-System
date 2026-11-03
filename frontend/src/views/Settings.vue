<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '../api'
import { downloadFile } from '../format'

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const backingUp = ref(false)
const keySet = ref(false)
const trialPrompt = ref('')
const trialOutput = ref('')
const loaded = ref({ database_location: '', database_name: '' })
const form = reactive({
  database_location: '',
  database_name: '',
  deepseek_api_key: '',
  deepseek_base_url: '',
  deepseek_model: '',
  allow_register: false,
})

function apply(data) {
  form.database_location = data.database_location
  form.database_name = data.database_name
  form.deepseek_api_key = data.deepseek_api_key
  form.deepseek_base_url = data.deepseek_base_url
  form.deepseek_model = data.deepseek_model
  form.allow_register = data.allow_register
  keySet.value = data.deepseek_api_key_set
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
        '切换后将使用目标数据库里的数据，当前库的数据不会被复制过去。保存后需要重新登录。如果目标库还不存在，会初始化为空库，管理员账号是 admin / admin，首次登录后必须修改密码。',
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
    if (data.database_switched || databaseChanged) {
      ElMessage.success('已切换数据库，请重新登录')
      window.location.assign('/login')
      return
    }
    ElMessage.success('已保存系统配置')
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

async function backup() {
  backingUp.value = true
  try {
    await downloadFile(http, '/settings/backup', {}, 'component-backup.zip')
  } finally {
    backingUp.value = false
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
        <div class="muted">
          {{ keySet ? '已保存 Key，这里只显示首尾几位。不改动就保持原 Key，清空后保存表示停用。' : '还没有保存 Key。' }}
        </div>
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
      <h3>账号</h3>
      <el-form-item label="允许注册">
        <el-switch v-model="form.allow_register" />
        <div class="muted">关闭后登录页不再显示注册入口，新账号只能由管理员在用户管理里创建。</div>
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </el-form-item>
      <h3>备份</h3>
      <el-form-item label="下载备份">
        <el-button :loading="backingUp" @click="backup">下载备份</el-button>
        <div class="muted">打包当前 SQLite 数据库和物料图片为 zip，不包含登录密钥。恢复时把数据库文件和图片目录放回原位置即可。MySQL 请用数据库自带工具备份。</div>
      </el-form-item>
    </el-form>
    <p class="muted">这些配置写入当前数据库。API Key 留空时不启用智能建议。只有数据库位置或名字变化时才会切换数据库。</p>
  </div>
</template>
