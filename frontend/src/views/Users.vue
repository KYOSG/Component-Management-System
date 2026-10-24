<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import http from '../api'
import { formatDate } from '../format'

const loading = ref(false)
const saving = ref(false)
const rows = ref([])
const visible = ref(false)
const editingId = ref(null)
const currentId = ref(null)
const form = reactive({ email: '', password: '', is_admin: false })

async function load() {
  loading.value = true
  try {
    const [me, users] = await Promise.all([http.get('/auth/me'), http.get('/users')])
    currentId.value = me.data.id
    rows.value = users.data
  } finally {
    loading.value = false
  }
}

function resetForm() {
  form.email = ''
  form.password = ''
  form.is_admin = false
}

function create() {
  editingId.value = null
  resetForm()
  visible.value = true
}

function edit(row) {
  editingId.value = row.id
  form.email = row.email
  form.password = ''
  form.is_admin = row.is_admin
  visible.value = true
}

async function save() {
  saving.value = true
  try {
    const payload = { email: form.email, password: form.password, is_admin: form.is_admin }
    if (editingId.value) {
      await http.put(`/users/${editingId.value}`, payload)
    } else {
      await http.post('/users', payload)
    }
    visible.value = false
    await load()
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  await ElMessageBox.confirm(
    `删除账号 ${row.email}？该账号下的物料、物料盒和项目会一起删除。`,
    '删除账号',
    { type: 'warning' },
  )
  await http.delete(`/users/${row.id}`)
  await load()
}

onMounted(load)
</script>

<template>
  <div class="page-card">
    <div class="toolbar">
      <el-button type="primary" @click="create">新增账号</el-button>
    </div>
    <el-table v-loading="loading" :data="rows" stripe>
      <el-table-column prop="email" label="账号" min-width="180" />
      <el-table-column label="身份" width="120">
        <template #default="{ row }">
          <el-tag :type="row.is_admin ? 'danger' : 'info'">{{ row.is_admin ? '管理员' : '普通用户' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="创建时间" min-width="170">
        <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="edit(row)">编辑</el-button>
          <el-button link type="danger" :disabled="row.id === currentId" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="还没有账号" />
      </template>
    </el-table>
    <el-dialog v-model="visible" :title="editingId ? '编辑账号' : '新增账号'" width="420px">
      <el-form label-width="72px" @submit.prevent="save">
        <el-form-item label="账号">
          <el-input v-model="form.email" autocomplete="off" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            autocomplete="new-password"
            :placeholder="editingId ? '留空则不修改' : '至少 6 位'"
          />
        </el-form-item>
        <el-form-item label="管理员">
          <el-switch v-model="form.is_admin" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
