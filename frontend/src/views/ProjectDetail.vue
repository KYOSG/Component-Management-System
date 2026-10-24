<script setup>
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import http from '../api'
import { FORMAT_LABEL, MATCH_STATUS, formatDate } from '../format'
import ItemDrawer from '../components/ItemDrawer.vue'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const matching = ref(false)
const savingSets = ref(false)
const committedSets = ref(null)
const project = ref(null)
const boxes = ref([])
const drawer = ref(false)
const draft = ref(null)

async function load() {
  loading.value = true
  try {
    const [{ data }, boxRes] = await Promise.all([
      http.get(`/projects/${route.params.id}`),
      http.get('/boxes'),
    ])
    committedSets.value = data.purchase_sets
    project.value = data
    boxes.value = boxRes.data
  } finally {
    loading.value = false
  }
}

async function rematch() {
  matching.value = true
  try {
    const { data } = await http.post(`/projects/${route.params.id}/match`)
    committedSets.value = data.purchase_sets
    project.value = data
    ElMessage.success('已重新匹配')
  } finally {
    matching.value = false
  }
}

async function saveSets(value) {
  if (!project.value || value == null || value < 1 || value === committedSets.value) return
  savingSets.value = true
  try {
    const { data } = await http.put(`/projects/${route.params.id}`, { purchase_sets: value })
    committedSets.value = data.purchase_sets
    project.value = data
    ElMessage.success('已更新采购套数')
  } catch {
    await load()
  } finally {
    savingSets.value = false
  }
}

async function adopt(row) {
  const { data } = await http.post(`/projects/${route.params.id}/lines/${row.id}/adopt`)
  if (data.warning) ElMessage.warning(data.warning)
  else ElMessage.info(`商城库存 ${data.mall_stock ?? '—'}，参考价格 ${data.mall_price || '—'}，请填写自有库存和物料盒后再保存`)
  draft.value = data
  drawer.value = true
}

function canAdopt(row) {
  return row.lcsc_code && (row.match_status === 'not_found' || row.match_status === 'suggested')
}

onMounted(load)
</script>

<template>
  <div v-loading="loading" class="stack">
    <div v-if="project" class="page-card">
      <div class="toolbar">
        <el-button @click="router.push('/projects')">返回列表</el-button>
        <el-button type="primary" :loading="matching" @click="rematch">重新匹配</el-button>
        <el-button @click="router.push({ path: '/map', query: { project: project.id } })">在物料盒地图中查看</el-button>
      </div>
      <el-alert
        v-if="!project.ai_enabled"
        title="未配置辅助Ai，未启用智能建议"
        type="info"
        show-icon
        :closable="false"
        style="margin-bottom: 16px"
      />
      <el-descriptions :column="3" border>
        <el-descriptions-item label="名称">{{ project.name }}</el-descriptions-item>
        <el-descriptions-item label="格式">{{ FORMAT_LABEL[project.format] || project.format }}</el-descriptions-item>
        <el-descriptions-item label="来源文件">{{ project.source_filename }}</el-descriptions-item>
        <el-descriptions-item label="采购套数">
          <el-input-number
            v-model="project.purchase_sets"
            :min="1"
            :step="1"
            :precision="0"
            :disabled="savingSets"
            @change="saveSets"
          />
        </el-descriptions-item>
        <el-descriptions-item label="配单编号">{{ project.order_no || '—' }}</el-descriptions-item>
        <el-descriptions-item label="导入时间">{{ formatDate(project.imported_at) }}</el-descriptions-item>
      </el-descriptions>
    </div>
    <div v-if="project" class="page-card">
      <el-table :data="project.lines" stripe>
        <el-table-column label="位号" min-width="120">
          <template #default="{ row }">{{ row.designators || '—' }}</template>
        </el-table-column>
        <el-table-column label="用量" min-width="150">
          <template #default="{ row }">单板 {{ row.quantity_per_board }} / 需求 {{ row.quantity_required }}</template>
        </el-table-column>
        <el-table-column label="立创编号" width="120">
          <template #default="{ row }">{{ row.lcsc_code || '—' }}</template>
        </el-table-column>
        <el-table-column label="型号" min-width="160">
          <template #default="{ row }">{{ row.mpn || row.product_name || '—' }}</template>
        </el-table-column>
        <el-table-column prop="footprint" label="封装" min-width="140" show-overflow-tooltip />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag v-if="MATCH_STATUS[row.match_status]" :type="MATCH_STATUS[row.match_status].type">
              {{ MATCH_STATUS[row.match_status].label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="库中位置" min-width="240">
          <template #default="{ row }">
            <div v-for="place in row.locations" :key="place">{{ place }}</div>
            <span v-if="!row.locations.length" class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="库存/需求" width="120">
          <template #default="{ row }">{{ row.stock ?? '—' }} / {{ row.quantity_required }}</template>
        </el-table-column>
        <el-table-column label="替换理由" min-width="220">
          <template #default="{ row }">
            <div>{{ row.reason || '—' }}</div>
            <el-tag v-for="risk in row.risks" :key="risk" size="small" type="warning" style="margin: 4px 4px 0 0">{{ risk }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button v-if="canAdopt(row)" link type="primary" @click="adopt(row)">按编号加入物料库</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <ItemDrawer v-model="drawer" :draft="draft" :boxes="boxes" @saved="rematch" />
  </div>
</template>
