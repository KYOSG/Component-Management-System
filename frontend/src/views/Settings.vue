<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http, { reportRequestError } from '../api'
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
  } catch (error) {
    reportRequestError(error)
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
  } catch (error) {
    reportRequestError(error)
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
  } catch (error) {
    reportRequestError(error)
  } finally {
    backingUp.value = false
  }
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="settings stack">
    <el-form label-width="120px" class="stack" @submit.prevent="save">
      <section class="page-card">
        <div class="card-head">
          <div>
            <h3>数据库</h3>
            <p>SQLite 数据库文件的目录和文件名。只有这两项变化时才会切换数据库。</p>
          </div>
        </div>
        <el-form-item label="数据库位置">
          <el-input v-model="form.database_location" placeholder="例如 F:\data 或 ./data" />
        </el-form-item>
        <el-form-item label="数据库名字">
          <el-input v-model="form.database_name" placeholder="例如 app.db" />
        </el-form-item>
      </section>

      <section class="page-card">
        <div class="card-head">
          <div>
            <h3>辅助 AI</h3>
            <p>用于 BOM 匹配时的智能建议。API Key 留空时不启用。</p>
          </div>
          <el-tag :type="keySet ? 'success' : 'info'" effect="light" round>{{ keySet ? '已配置' : '未配置' }}</el-tag>
        </div>
        <el-form-item label="API Key">
          <el-input
            v-model="form.deepseek_api_key"
            type="password"
            show-password
            autocomplete="off"
            placeholder="留空则不启用智能建议"
          />
          <div class="form-hint">
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
          <el-input v-model="trialPrompt" type="textarea" :rows="3" placeholder="随便输入一段话，发给当前填写的模型" />
        </el-form-item>
        <el-form-item>
          <el-button icon="Promotion" :loading="testing" @click="testAi">发送测试</el-button>
        </el-form-item>
        <el-form-item v-if="trialOutput" label="模型输出">
          <el-input :model-value="trialOutput" type="textarea" :rows="6" readonly />
        </el-form-item>
      </section>

      <section class="page-card">
        <div class="card-head">
          <div>
            <h3>账号</h3>
            <p>控制登录页是否开放自助注册。</p>
          </div>
        </div>
        <el-form-item label="允许注册">
          <el-switch v-model="form.allow_register" />
          <div class="form-hint">关闭后登录页不再显示注册入口，新账号只能由管理员在账户管理里创建。</div>
        </el-form-item>
      </section>

      <div class="save-bar">
        <span class="muted">以上配置写入当前数据库。</span>
        <el-button type="primary" icon="Check" :loading="saving" @click="save">保存配置</el-button>
      </div>
    </el-form>

    <section class="page-card">
      <div class="card-head">
        <div>
          <h3>备份</h3>
          <p>打包当前 SQLite 数据库和物料图片为 zip，不包含登录密钥。恢复时把数据库文件和图片目录放回原位置即可。</p>
        </div>
        <el-button icon="Download" :loading="backingUp" @click="backup">下载备份</el-button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.settings {
  max-width: 880px;
}

.settings .el-form-item:last-child {
  margin-bottom: 0;
}

.form-hint {
  width: 100%;
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--cms-muted);
}

.save-bar {
  position: sticky;
  bottom: 16px;
  z-index: 5;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 16px 12px 20px;
  background: color-mix(in srgb, var(--cms-surface) 88%, transparent);
  backdrop-filter: blur(8px);
  border: 1px solid var(--cms-border);
  border-radius: var(--cms-radius);
  box-shadow: var(--cms-shadow);
}
</style>
