<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import http from '../api'
import { FORMAT_LABEL, formatDate } from '../format'

const router = useRouter()
const loading = ref(false)
const uploading = ref(false)
const rows = ref([])

async function load() {
  loading.value = true
  try {
    const { data } = await http.get('/projects')
    rows.value = data
  } finally {
    loading.value = false
  }
}

async function upload(option) {
  const body = new FormData()
  body.append('file', option.file)
  uploading.value = true
  try {
    const { data } = await http.post('/projects/import', body)
    ElMessage.success('导入完成，已自动匹配')
    router.push(`/projects/${data.id}`)
  } finally {
    uploading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="stack">
    <div class="page-card">
      <el-upload drag :show-file-list="false" accept=".xls,.xlsx" :http-request="upload" :disabled="uploading">
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div>将 BOM 拖到此处，或点击上传</div>
        <div class="muted">支持立创 EDA 的 .xlsx 和立创商城报价单 .xls</div>
      </el-upload>
    </div>
    <div class="page-card">
      <el-table v-loading="loading" :data="rows">
        <el-table-column prop="name" label="名称" min-width="220" show-overflow-tooltip />
        <el-table-column label="格式" width="150">
          <template #default="{ row }">{{ FORMAT_LABEL[row.format] || row.format }}</template>
        </el-table-column>
        <el-table-column prop="source_filename" label="来源文件" min-width="180" show-overflow-tooltip />
        <el-table-column prop="purchase_sets" label="采购套数" width="100" />
        <el-table-column prop="line_count" label="明细" width="80" />
        <el-table-column label="导入时间" width="170">
          <template #default="{ row }">{{ formatDate(row.imported_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <el-button link type="primary" @click="router.push(`/projects/${row.id}`)">查看</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="还没有导入项目" />
        </template>
      </el-table>
    </div>
  </div>
</template>
