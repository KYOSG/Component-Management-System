<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import http from '../api'
import { cellText } from '../format'
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
    <el-table v-loading="loading" :data="rows" stripe>
      <el-table-column prop="lcsc_code" label="编号" min-width="110">
        <template #default="{ row }">{{ row.lcsc_code || '—' }}</template>
      </el-table-column>
      <el-table-column prop="mpn" label="型号" min-width="160" />
      <el-table-column prop="name" label="名称" min-width="180" show-overflow-tooltip />
      <el-table-column prop="footprint" label="封装" min-width="120" />
      <el-table-column prop="category" label="类目" width="100" />
      <el-table-column prop="quantity" label="库存" width="80" />
      <el-table-column label="物料盒" min-width="120">
        <template #default="{ row }">{{ row.box_name || '未入盒' }}</template>
      </el-table-column>
      <el-table-column label="格子" width="130">
        <template #default="{ row }">{{ cellText(row.row, row.col) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="edit(row)">编辑</el-button>
          <el-button link type="primary" :disabled="!row.box_id" @click="unbox(row)">移出</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty description="物料库还是空的" />
      </template>
    </el-table>
    <div class="toolbar" style="justify-content: flex-end">
      <el-pagination
        v-model:current-page="filters.page"
        v-model:page-size="filters.page_size"
        layout="total, sizes, prev, pager, next"
        :total="total"
        :page-sizes="[10, 20, 50]"
        @current-change="load"
        @size-change="search"
      />
    </div>
    <ItemDrawer v-model="drawer" :item="editing" :boxes="boxes" @saved="load" />
  </div>
</template>
