<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import http from '../api'
import { money, placeText } from '../format'
import { filledSpecs, loadCatalog } from '../specCatalog'
import ItemDrawer from '../components/ItemDrawer.vue'

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const boxes = ref([])
const drawer = ref(false)
const editing = ref(null)
const filters = reactive({
  page: 1,
  page_size: 20,
  lcsc_code: '',
  mpn: '',
  name: '',
  footprint: '',
  category: '',
  remark: '',
})

async function loadBoxes() {
  const { data } = await http.get('/boxes')
  boxes.value = data
}

async function load() {
  loading.value = true
  try {
    await loadCatalog(true)
    const { data } = await http.get('/items', { params: filters })
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function search() {
  filters.page = 1
  load()
}

function reset() {
  Object.assign(filters, {
    page: 1,
    page_size: 20,
    lcsc_code: '',
    mpn: '',
    name: '',
    footprint: '',
    category: '',
    remark: '',
  })
  load()
}

function placed(row) {
  return (row.locations || []).some((loc) => loc.location_type !== 'unboxed')
}

function create() {
  editing.value = null
  drawer.value = true
}

function edit(row) {
  editing.value = { ...row }
  drawer.value = true
}

async function unbox(row) {
  await http.post(`/items/${row.id}/unbox`)
  await load()
}

async function remove(row) {
  await ElMessageBox.confirm(`删除 ${row.mpn || row.lcsc_code || '这条物料'}？`, '删除物料', { type: 'warning' })
  await http.delete(`/items/${row.id}`)
  await load()
}

onMounted(async () => {
  await loadBoxes()
  await load()
})
</script>

<template>
  <div class="page-card">
    <el-form inline @submit.prevent="search">
      <el-form-item label="立创编号"><el-input v-model="filters.lcsc_code" clearable /></el-form-item>
      <el-form-item label="厂家型号"><el-input v-model="filters.mpn" clearable /></el-form-item>
      <el-form-item label="商品名称"><el-input v-model="filters.name" clearable /></el-form-item>
      <el-form-item label="封装"><el-input v-model="filters.footprint" clearable /></el-form-item>
      <el-form-item label="类目"><el-input v-model="filters.category" clearable /></el-form-item>
      <el-form-item label="备注"><el-input v-model="filters.remark" clearable /></el-form-item>
      <el-form-item>
        <el-button type="primary" native-type="submit">筛选</el-button>
        <el-button @click="reset">重置</el-button>
      </el-form-item>
    </el-form>
    <div class="toolbar">
      <el-button type="primary" @click="create">新增物料</el-button>
    </div>
    <el-table v-loading="loading" class="items-table" :data="rows" stripe table-layout="auto">
      <el-table-column prop="lcsc_code" label="编号" align="center" header-align="center">
        <template #default="{ row }">{{ row.lcsc_code || '—' }}</template>
      </el-table-column>
      <el-table-column prop="category" label="类目" align="center" header-align="center">
        <template #default="{ row }">{{ row.category || '—' }}</template>
      </el-table-column>
      <el-table-column prop="footprint" label="封装" align="center" header-align="center">
        <template #default="{ row }">{{ row.footprint || '—' }}</template>
      </el-table-column>
      <el-table-column prop="value" label="标称值" align="center" header-align="center">
        <template #default="{ row }">{{ row.value || '—' }}</template>
      </el-table-column>
      <el-table-column label="参数" align="center" header-align="center">
        <template #default="{ row }">
          <template v-if="filledSpecs(row).length">
            <div v-for="field in filledSpecs(row)" :key="field.key">{{ field.label }} {{ field.value }}</div>
          </template>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column prop="quantity" label="库存" align="center" header-align="center" />
      <el-table-column label="单价" align="center" header-align="center">
        <template #default="{ row }">{{ money(row.unit_price) }}</template>
      </el-table-column>
      <el-table-column label="总价值" align="center" header-align="center">
        <template #default="{ row }">{{ money(row.total_value) }}</template>
      </el-table-column>
      <el-table-column label="存放位置" align="center" header-align="center" min-width="180">
        <template #default="{ row }">
          <div v-for="loc in row.locations" :key="loc.id">{{ placeText(loc) }}</div>
          <span v-if="!row.locations?.length">未分配</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" align="center" header-align="center">
        <template #default="{ row }">
          <div class="row-actions">
            <el-button size="small" plain type="primary" @click="edit(row)">编辑</el-button>
            <el-button size="small" plain type="primary" :disabled="!placed(row)" @click="unbox(row)">移出</el-button>
            <el-button size="small" plain type="danger" @click="remove(row)">删除</el-button>
          </div>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="物料库还是空的" />
      </template>
    </el-table>
    <div class="table-pager">
      <el-pagination
        v-model:current-page="filters.page"
        v-model:page-size="filters.page_size"
        background
        layout="prev, pager, next"
        :total="total"
        @current-change="load"
      />
    </div>
    <ItemDrawer v-model="drawer" :item="editing" :boxes="boxes" @saved="load" />
  </div>
</template>

<style scoped>
.row-actions {
  display: inline-flex;
  gap: 8px;
  white-space: nowrap;
}

.row-actions :deep(.el-button) {
  margin-left: 0;
}

.table-pager {
  display: flex;
  justify-content: center;
  margin-top: 16px;
}
</style>
