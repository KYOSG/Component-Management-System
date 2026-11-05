<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http, { reportRequestError } from '../api'
import { downloadFile, money, placeText } from '../format'
import { filledSpecs, loadCatalog } from '../specCatalog'
import ItemDrawer from '../components/ItemDrawer.vue'
import OrderImportDialog from '../components/OrderImportDialog.vue'

const route = useRoute()
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const boxes = ref([])
const drawer = ref(false)
const editing = ref(null)
const hints = ref([])
const lowCount = ref(0)
const exporting = ref(false)
const orderVisible = ref(false)
const tableRef = ref(null)
const selected = ref([])
const startingRefresh = ref(false)
const refreshState = ref({ queued: 0, running: 0, failed: 0 })
let pollTimer = 0
const filters = reactive({
  page: 1,
  page_size: 20,
  q: '',
  low_stock: false,
  lcsc_code: '',
  mpn: '',
  name: '',
  footprint: '',
  category: '',
  remark: '',
})

async function loadBoxes() {
  try {
    const { data } = await http.get('/boxes')
    boxes.value = data
  } catch (error) {
    reportRequestError(error)
  }
}

function isSyncing(row) {
  return row?.lcsc_sync_status === 'queued' || row?.lcsc_sync_status === 'running'
}

function describeRefresh(data) {
  const parts = []
  if (data.queued) parts.push(`已加入后台更新 ${data.queued} 条`)
  if (data.skipped_busy) parts.push(`${data.skipped_busy} 条正在更新，已跳过`)
  if (data.skipped_no_code) parts.push(`${data.skipped_no_code} 条没有立创编号`)
  if (!parts.length) return '没有可更新的物料'
  if (data.queued) parts.push('大约每分钟不超过 30 条，完成前不能编辑或再次查询')
  return parts.join('，')
}

async function load(options) {
  const silent = Boolean(options && typeof options === 'object' && options.silent)
  if (!silent) loading.value = true
  let ok = false
  try {
    if (!silent) await loadCatalog(true)
    const { data } = await http.get('/items', { params: filters })
    rows.value = data.items
    total.value = data.total
    hints.value = data.hints || []
    lowCount.value = data.low_stock_count || 0
    const status = await http.get('/items/lcsc-refresh/status')
    refreshState.value = status.data
    syncEditing()
    ok = true
  } catch (error) {
    reportRequestError(error)
  } finally {
    if (!silent) loading.value = false
    if (ok) schedulePoll()
    else window.clearTimeout(pollTimer)
  }
}

function syncEditing() {
  if (!editing.value?.id) return
  const fresh = rows.value.find((row) => row.id === editing.value.id)
  if (!fresh) return
  const was = editing.value.lcsc_sync_status
  if (isSyncing(editing.value) || isSyncing(fresh) || was !== fresh.lcsc_sync_status) {
    editing.value = { ...fresh }
  }
}

function schedulePoll() {
  window.clearTimeout(pollTimer)
  const active = (refreshState.value.queued || 0) + (refreshState.value.running || 0)
  if (active > 0) pollTimer = window.setTimeout(() => load({ silent: true }), 3000)
}

function search() {
  filters.page = 1
  tableRef.value?.clearSelection()
  load()
}

function reset() {
  Object.assign(filters, {
    page: 1,
    page_size: 20,
    q: '',
    low_stock: false,
    lcsc_code: '',
    mpn: '',
    name: '',
    footprint: '',
    category: '',
    remark: '',
  })
  tableRef.value?.clearSelection()
  load()
}

function onSelect(rows) {
  selected.value = rows
}

async function refreshSelected() {
  const chosen = selected.value.filter((row) => String(row.lcsc_code || '').trim())
  if (!selected.value.length) return
  if (!chosen.length) {
    ElMessage.warning('选中的物料没有立创编号')
    return
  }
  const skipped = selected.value.length - chosen.length
  const extra = skipped ? `另外 ${skipped} 条没有立创编号，会跳过。` : ''
  try {
    await ElMessageBox.confirm(
      `将按立创编号更新选中的 ${chosen.length} 条物料：型号、名称、品牌、封装、类目、标称值、参数、规格、数据手册和图片。已有单价、库存、存放位置、备注和低库存阈值会保留；还没有单价的，会填入立创参考价。${extra}查询在后台进行，大约每分钟不超过 30 条，两次查询之间随机间隔。每条物料更新结束前，不能再次查询或编辑它的字段。`,
      '更新选中物料',
      { type: 'warning', confirmButtonText: '开始更新', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await startRefresh({ item_ids: chosen.map((row) => row.id) })
}

async function refreshAll() {
  try {
    await ElMessageBox.confirm(
      '将按立创编号更新物料库中全部有编号的物料，不限当前筛选和分页。已有单价、库存、存放位置、备注和低库存阈值会保留；还没有单价的，会填入立创参考价。查询在后台进行，大约每分钟不超过 30 条，两次查询之间随机间隔。每条物料更新结束前，不能再次查询或编辑它的字段。',
      '更新整库资料',
      { type: 'warning', confirmButtonText: '开始更新', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await startRefresh({ all: true })
}

async function startRefresh(body) {
  startingRefresh.value = true
  try {
    const { data } = await http.post('/items/lcsc-refresh', body)
    const text = describeRefresh(data)
    if (data.queued) ElMessage.success(text)
    else ElMessage.warning(text)
    await load()
  } catch (error) {
    reportRequestError(error)
  } finally {
    startingRefresh.value = false
  }
}

const fieldKeys = ['lcsc_code', 'mpn', 'name', 'footprint', 'category', 'remark']
const moreOpen = ref(false)
const fieldCount = computed(() => fieldKeys.filter((key) => String(filters[key] || '').trim()).length)
const filtering = computed(() => Boolean(String(filters.q || '').trim() || fieldCount.value || filters.low_stock))

function showLow() {
  filters.low_stock = true
  search()
}

function imported() {
  filters.page = 1
  load()
}

async function exportExcel() {
  const { page, page_size, ...params } = filters
  exporting.value = true
  try {
    await downloadFile(http, '/items/export', params, 'items.xlsx')
  } catch (error) {
    reportRequestError(error)
  } finally {
    exporting.value = false
  }
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
  try {
    await http.post(`/items/${row.id}/unbox`)
    await load()
  } catch (error) {
    reportRequestError(error)
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(
      `删除 ${row.mpn || row.lcsc_code || '这条物料'}？它的所有出入库流水会一起删除，统计页里的用量也会随之减少，删除后无法恢复。`,
      '删除物料',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  try {
    await http.delete(`/items/${row.id}`)
    await load()
  } catch (error) {
    reportRequestError(error)
  }
}

onMounted(async () => {
  if (route.query.low_stock) filters.low_stock = true
  await loadBoxes()
  await load()
})

onBeforeUnmount(() => window.clearTimeout(pollTimer))
</script>

<template>
  <div class="stack">
    <div class="page-card">
      <el-form label-position="top" @submit.prevent="search">
        <div class="search-row">
          <el-input
            v-model="filters.q"
            size="large"
            clearable
            prefix-icon="Search"
            placeholder="搜索物料，例如 10k 0603、100nF 50V、C25804"
          />
          <el-button size="large" type="primary" native-type="submit">搜索</el-button>
          <el-button size="large" icon="Filter" @click="moreOpen = !moreOpen">
            更多筛选<template v-if="fieldCount"> · {{ fieldCount }}</template>
          </el-button>
          <el-button size="large" text @click="reset">重置</el-button>
        </div>
        <el-collapse-transition>
          <div v-show="moreOpen" class="field-filters">
            <el-form-item label="立创编号"><el-input v-model="filters.lcsc_code" clearable /></el-form-item>
            <el-form-item label="厂家型号"><el-input v-model="filters.mpn" clearable /></el-form-item>
            <el-form-item label="商品名称"><el-input v-model="filters.name" clearable /></el-form-item>
            <el-form-item label="封装"><el-input v-model="filters.footprint" clearable /></el-form-item>
            <el-form-item label="类目"><el-input v-model="filters.category" clearable /></el-form-item>
            <el-form-item label="备注"><el-input v-model="filters.remark" clearable /></el-form-item>
          </div>
        </el-collapse-transition>
      </el-form>
      <div v-if="hints.length" class="search-hints">
        <span class="muted">识别为</span>
        <el-tag v-for="hint in hints" :key="`${hint.kind}-${hint.label}`" size="small" effect="light" round>
          {{ hint.label }}
        </el-tag>
      </div>
    </div>

    <div class="page-card">
      <el-alert
        v-if="lowCount && !filters.low_stock"
        class="low-alert"
        type="warning"
        show-icon
        :closable="false"
        :title="`有 ${lowCount} 种物料低于低库存阈值`"
      >
        <el-button link type="primary" @click="showLow">只看这些</el-button>
      </el-alert>
      <el-alert
        v-if="refreshState.queued || refreshState.running"
        class="low-alert"
        type="info"
        show-icon
        :closable="false"
        :title="`正在后台更新立创资料：排队 ${refreshState.queued} 条，进行中 ${refreshState.running} 条`"
        description="大约每分钟不超过 30 条，间隔随机。这些物料在更新完成前不能查询或编辑。可以继续入库或做别的操作。"
      />
      <el-alert
        v-if="refreshState.failed"
        class="low-alert"
        type="warning"
        show-icon
        :closable="false"
        :title="`有 ${refreshState.failed} 条立创资料更新失败，表格里标出了原因，可以重新更新`"
      />
      <div class="toolbar">
        <span class="muted">共 {{ total }} 种物料</span>
        <el-checkbox v-model="filters.low_stock" @change="search">只看低库存</el-checkbox>
        <span class="spacer" />
        <el-button icon="Refresh" :loading="startingRefresh" :disabled="!selected.length" @click="refreshSelected">
          更新选中<template v-if="selected.length"> · {{ selected.length }}</template>
        </el-button>
        <el-button icon="Refresh" :loading="startingRefresh" @click="refreshAll">更新整库</el-button>
        <el-button icon="Download" :loading="exporting" @click="exportExcel">导出 Excel</el-button>
        <el-button type="primary" plain icon="Upload" @click="orderVisible = true">订单入库</el-button>
        <el-button type="primary" icon="Plus" @click="create">新增物料</el-button>
      </div>
      <el-table
        ref="tableRef"
        v-loading="loading"
        class="items-table"
        :data="rows"
        row-key="id"
        table-layout="auto"
        @selection-change="onSelect"
      >
        <el-table-column type="selection" width="42" reserve-selection align="center" />
        <el-table-column prop="lcsc_code" label="编号" align="center" header-align="center">
          <template #default="{ row }">
            <div class="code-cell">
              <span class="mono">{{ row.lcsc_code || '—' }}</span>
              <el-tag v-if="row.lcsc_sync_status === 'queued'" size="small" type="info" effect="plain">等待更新</el-tag>
              <el-tag v-else-if="row.lcsc_sync_status === 'running'" size="small" type="warning" effect="plain">正在更新</el-tag>
              <el-tooltip v-else-if="row.lcsc_sync_status === 'failed'" :content="row.lcsc_sync_error || '更新失败'" placement="top">
                <el-tag size="small" type="danger" effect="plain">更新失败</el-tag>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="category" label="类目" align="center" header-align="center">
          <template #default="{ row }">{{ row.category || '—' }}</template>
        </el-table-column>
        <el-table-column prop="footprint" label="封装" align="center" header-align="center">
          <template #default="{ row }">{{ row.footprint || '—' }}</template>
        </el-table-column>
        <el-table-column prop="value" label="标称值" align="center" header-align="center">
          <template #default="{ row }"><strong v-if="row.value">{{ row.value }}</strong><span v-else>—</span></template>
        </el-table-column>
        <el-table-column label="参数(仅显示指定字段)" align="center" header-align="center">
          <template #default="{ row }">
            <template v-if="filledSpecs(row).length">
              <div v-for="field in filledSpecs(row)" :key="field.key" class="spec-line">
                <span class="muted">{{ field.label }}</span> {{ field.value }}
              </div>
            </template>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column prop="quantity" label="库存" align="center" header-align="center">
          <template #default="{ row }">
            <span class="qty" :class="{ 'low-qty': row.low_stock }">{{ row.quantity }}</span>
            <el-tag v-if="row.low_stock" size="small" type="danger" effect="light" class="low-tag">低库存</el-tag>
            <div v-if="row.min_stock" class="muted small">阈值 {{ row.min_stock }}</div>
          </template>
        </el-table-column>
        <el-table-column label="单价" align="center" header-align="center">
          <template #default="{ row }">{{ money(row.unit_price) }}</template>
        </el-table-column>
        <el-table-column label="总价值" align="center" header-align="center">
          <template #default="{ row }">{{ money(row.total_value) }}</template>
        </el-table-column>
        <el-table-column label="存放位置" align="center" header-align="center" min-width="180">
          <template #default="{ row }">
            <div v-for="loc in row.locations" :key="loc.id">{{ placeText(loc) }}</div>
            <span v-if="!row.locations?.length" class="muted">未分配</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" align="center" header-align="center">
          <template #default="{ row }">
            <div class="row-actions">
              <el-tooltip :disabled="!isSyncing(row)" content="立创资料更新完成前不能编辑" placement="top">
                <span>
                  <el-button link type="primary" :disabled="isSyncing(row)" @click="edit(row)">编辑</el-button>
                </span>
              </el-tooltip>
              <el-button link type="primary" :disabled="!placed(row)" @click="unbox(row)">移出</el-button>
              <el-button link type="danger" @click="remove(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty :description="filtering ? '没有符合条件的物料' : '物料库还是空的'" />
        </template>
      </el-table>
      <div v-if="total > filters.page_size" class="table-pager">
        <el-pagination
          v-model:current-page="filters.page"
          v-model:page-size="filters.page_size"
          background
          layout="prev, pager, next"
          :total="total"
          @current-change="load"
        />
      </div>
    </div>
    <ItemDrawer v-model="drawer" :item="editing" :boxes="boxes" @saved="load" />
    <OrderImportDialog v-model="orderVisible" @done="imported" />
  </div>
</template>

<style scoped>
.search-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}

.search-row .el-input {
  flex: 1 1 320px;
}

.search-row :deep(.el-button) {
  margin-left: 0;
}

.field-filters {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 0 16px;
  padding-top: 16px;
}

.field-filters :deep(.el-form-item) {
  margin-bottom: 0;
}

.search-hints {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 14px;
  font-size: 13px;
}

.low-alert {
  margin-bottom: 16px;
}

.code-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.row-actions {
  display: inline-flex;
  gap: 12px;
  white-space: nowrap;
}

.row-actions :deep(.el-button) {
  margin-left: 0;
}

.spec-line {
  line-height: 1.6;
}

.qty {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.low-qty {
  color: var(--cms-danger);
}

.low-tag {
  margin-left: 6px;
}

.small {
  font-size: 12px;
}

.table-pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
