<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from '../api'
import { cellText, money } from '../format'
import { catalogState, filledSpecs, loadCatalog } from '../specCatalog'
import ItemDrawer from '../components/ItemDrawer.vue'
import ReelBoxPanel from '../components/ReelBoxPanel.vue'
import TransferDialog from '../components/TransferDialog.vue'

const route = useRoute()
const loading = ref(false)
const mapData = ref({ stats: { item_count: 0, box_count: 0, quantity_total: 0, total_value: 0, low_stock_count: 0 }, categories: [], boxes: [], unboxed: [], highlights: {} })
const projects = ref([])
const category = ref('')
const projectId = ref(route.query.project ? Number(route.query.project) : null)
const boxVisible = ref(false)
const boxSaving = ref(false)
const boxForm = reactive({ id: null, name: '', box_type: 'grid', rows: 5, cols: 10, slot_count: 8, remark: '' })
const detailVisible = ref(false)
const placeVisible = ref(false)
const transferVisible = ref(false)
const transferSource = ref(null)
const activeBox = ref(null)
const activeCell = ref(null)
const activeSlot = ref(null)
const activePlace = ref(null)
const selectedLocation = ref(null)
const placeQuantity = ref(1)
const drawer = ref(false)
const editing = ref(null)
const draft = ref(null)
const expanded = ref({})

const highlights = computed(() => {
  const output = {}
  Object.entries(mapData.value.highlights || {}).forEach(([key, marks]) => {
    output[Number(key)] = marks
  })
  return output
})

const visibleUnboxed = computed(() => {
  if (!category.value) return mapData.value.unboxed
  return mapData.value.unboxed.filter((item) => item.category === category.value)
})

function itemLabel(item) {
  return item?.lcsc_code || item?.mpn || item?.name || '未命名'
}

const placeableLocations = computed(() => {
  const rows = []
  const match = (item) => !category.value || item.category === category.value
  for (const item of mapData.value.unboxed || []) {
    if (!match(item) || !(item.location_quantity > 0)) continue
    rows.push({
      location_id: item.location_id,
      quantity: item.location_quantity,
      label: `未入库 · ${itemLabel(item)} · 库存 ${item.location_quantity}`,
    })
  }
  for (const box of mapData.value.boxes || []) {
    if (box.box_type === 'reel') {
      for (const slot of box.reel_slots || []) {
        if (!slot.item || !(slot.quantity > 0) || !match(slot.item)) continue
        rows.push({
          location_id: slot.location_id,
          quantity: slot.quantity,
          label: `${box.name} 卷${slot.slot_index} · ${itemLabel(slot.item)} · 库存 ${slot.quantity}`,
        })
      }
      continue
    }
    for (const cell of box.cells || []) {
      if (!cell.item || !(cell.location_quantity > 0) || !match(cell.item)) continue
      rows.push({
        location_id: cell.location_id,
        quantity: cell.location_quantity,
        label: `${box.name} ${cell.row}-${cell.col} · ${itemLabel(cell.item)} · 库存 ${cell.location_quantity}`,
      })
    }
  }
  return rows
})

const selectedPlace = computed(() => placeableLocations.value.find((row) => row.location_id === selectedLocation.value) || null)

const placeTargetText = computed(() => {
  if (!activeBox.value) return ''
  if (activeSlot.value) return `${activeBox.value.name} 卷${activeSlot.value.slot_index}`
  return `${activeBox.value.name} ${cellText(activeCell.value?.row, activeCell.value?.col)}`
})

function gridStyle(box) {
  return { gridTemplateColumns: `repeat(${box.cols}, minmax(128px, 1fr))` }
}

function occupiedCount(box) {
  if (box.box_type === 'reel') return (box.reel_slots || []).filter((slot) => slot.item).length
  return box.cells.filter((cell) => cell.item).length
}

function toggleBox(id) {
  expanded.value = { ...expanded.value, [id]: !expanded.value[id] }
}

function marks(item) {
  if (!item) return []
  return highlights.value[item.id] || []
}

function longLcsc(item) {
  const digits = String(item?.lcsc_code || '').replace(/\D/g, '')
  return digits.length > 6
}

async function loadProjects() {
  const { data } = await http.get('/projects')
  projects.value = data
}

function cellSpecs(item) {
  void catalogState.categories
  return filledSpecs(item)
}

async function load() {
  loading.value = true
  try {
    await loadCatalog(true)
    const params = {}
    if (category.value) params.category = category.value
    if (projectId.value) params.project_id = projectId.value
    const { data } = await http.get('/map', { params })
    mapData.value = data
  } finally {
    loading.value = false
  }
}

function openCreateBox() {
  Object.assign(boxForm, { id: null, name: '', box_type: 'grid', rows: 5, cols: 10, slot_count: 8, remark: '' })
  boxVisible.value = true
}

function openEditBox(box) {
  Object.assign(boxForm, {
    id: box.id,
    name: box.name,
    box_type: box.box_type || 'grid',
    rows: box.rows,
    cols: box.cols,
    slot_count: box.slot_count || 8,
    remark: box.remark || '',
  })
  boxVisible.value = true
}

async function saveBox() {
  boxSaving.value = true
  try {
    const reel = boxForm.box_type === 'reel'
    const payload = {
      name: boxForm.name,
      box_type: boxForm.box_type,
      rows: reel ? 0 : boxForm.rows,
      cols: reel ? 0 : boxForm.cols,
      slot_count: reel ? boxForm.slot_count : 0,
      remark: boxForm.remark,
    }
    if (boxForm.id) await http.put(`/boxes/${boxForm.id}`, payload)
    else await http.post('/boxes', payload)
    boxVisible.value = false
    await load()
  } finally {
    boxSaving.value = false
  }
}

async function removeBox(box) {
  await ElMessageBox.confirm('删除后，盒内物料会变为未入盒，物料本身仍保留。', '删除物料盒', { type: 'warning' })
  await http.delete(`/boxes/${box.id}`)
  await load()
}

function openPlace(box) {
  activeBox.value = box
  selectedLocation.value = null
  placeQuantity.value = 1
  placeVisible.value = true
}

function openCell(box, cell) {
  activeSlot.value = null
  activeCell.value = cell
  if (cell.item) {
    activeBox.value = box
    activePlace.value = {
      item: cell.item,
      locationId: cell.location_id,
      quantity: cell.location_quantity,
      cellValue: cell.cell_value,
      title: `${box.name} ${cell.row}-${cell.col}`,
    }
    detailVisible.value = true
    return
  }
  openPlace(box)
}

function placeFromSlot(box, slot) {
  activePlace.value = {
    item: slot.item,
    locationId: slot.location_id,
    quantity: slot.quantity,
    cellValue: slot.cell_value,
    title: `${box.name} 卷${slot.slot_index}`,
  }
}

function openSlot(box, slot) {
  activeCell.value = null
  activeSlot.value = slot
  if (slot.item) {
    placeFromSlot(box, slot)
    detailVisible.value = true
    return
  }
  openPlace(box)
}

async function checkoutSlot(box, slot) {
  placeFromSlot(box, slot)
  await checkoutPlace()
}

function openTransfer(place) {
  transferSource.value = {
    itemId: place.item?.id || place.id,
    locationId: place.locationId || place.location_id,
  }
  detailVisible.value = false
  transferVisible.value = true
}

function editItem(item) {
  editing.value = { ...item }
  draft.value = null
  detailVisible.value = false
  drawer.value = true
}

function createHere() {
  editing.value = null
  draft.value = {
    box_id: activeBox.value.id,
    row: activeSlot.value ? null : activeCell.value?.row,
    col: activeSlot.value ? null : activeCell.value?.col,
    slot_index: activeSlot.value?.slot_index || null,
    quantity: 0,
  }
  placeVisible.value = false
  drawer.value = true
}

function onPlaceSource(locationId) {
  const source = placeableLocations.value.find((row) => row.location_id === locationId)
  placeQuantity.value = source?.quantity || 1
}

async function placeSelected() {
  const source = selectedPlace.value
  if (!source) return
  const amount = Number(placeQuantity.value)
  if (!Number.isInteger(amount) || amount < 1 || amount > source.quantity) {
    ElMessage.warning('流转数量需要是不超过该位置库存的正整数')
    return
  }
  const payload = {
    from_location_id: source.location_id,
    to_box_id: activeBox.value.id,
    quantity: amount,
  }
  if (activeSlot.value) {
    payload.to_type = 'tape_reel'
    payload.to_slot_index = activeSlot.value.slot_index
  } else {
    payload.to_type = 'box_cell'
    payload.to_row = activeCell.value.row
    payload.to_col = activeCell.value.col
  }
  await http.post('/transfer', payload)
  placeVisible.value = false
  await load()
}

async function clearPlace() {
  const place = activePlace.value
  if (!place?.locationId) return
  if (place.quantity > 0) {
    await http.post('/transfer', {
      from_location_id: place.locationId,
      to_type: 'unboxed',
      quantity: place.quantity,
    })
  } else {
    await http.delete(`/locations/${place.locationId}`)
  }
  detailVisible.value = false
  await load()
}

async function checkoutPlace() {
  const place = activePlace.value
  if (!place?.locationId) return
  let amount = place.quantity
  try {
    const result = await ElMessageBox.prompt(`该位置库存 ${place.quantity}，填写出库数量`, '出库', {
      inputValue: String(place.quantity || ''),
      inputPattern: /^[1-9]\d*$/,
      inputErrorMessage: '请输入正整数',
    })
    amount = Number(result.value)
  } catch {
    return
  }
  if (amount > place.quantity) {
    ElMessage.warning('出库数量超过该位置的库存')
    return
  }
  await http.post(`/items/${place.item.id}/checkout`, { location_id: place.locationId, quantity: amount })
  ElMessage.success('已出库')
  detailVisible.value = false
  await load()
}

async function removeItem(item) {
  await ElMessageBox.confirm(
    '它的所有出入库流水会一起删除，统计页里的用量也会随之减少，删除后无法恢复。',
    '删除物料',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
  )
  await http.delete(`/items/${item.id}`)
  detailVisible.value = false
  await load()
}

watch(() => route.query.project, (value) => {
  projectId.value = value ? Number(value) : null
  load()
})

onMounted(async () => {
  await loadProjects()
  await load()
})
</script>

<template>
  <div v-loading="loading">
    <div class="stats">
      <div class="stat">
        <span class="stat-icon"><el-icon><Collection /></el-icon></span>
        <div><span class="stat-label">物料种类</span><b class="stat-value">{{ mapData.stats.item_count }}</b></div>
      </div>
      <div class="stat">
        <span class="stat-icon"><el-icon><Box /></el-icon></span>
        <div><span class="stat-label">盒子数量</span><b class="stat-value">{{ mapData.stats.box_count }}</b></div>
      </div>
      <div class="stat">
        <span class="stat-icon"><el-icon><Histogram /></el-icon></span>
        <div><span class="stat-label">库存总数</span><b class="stat-value">{{ mapData.stats.quantity_total }}</b></div>
      </div>
      <div class="stat">
        <span class="stat-icon"><el-icon><Money /></el-icon></span>
        <div><span class="stat-label">库存总价值</span><b class="stat-value">{{ money(mapData.stats.total_value) }}</b></div>
      </div>
      <router-link
        class="stat stat-link"
        :class="{ 'stat-warn': mapData.stats.low_stock_count }"
        :to="{ path: '/items', query: { low_stock: '1' } }"
      >
        <span class="stat-icon"><el-icon><Warning /></el-icon></span>
        <div><span class="stat-label">低库存物料</span><b class="stat-value">{{ mapData.stats.low_stock_count }}</b></div>
      </router-link>
    </div>
    <div class="page-card" style="margin-bottom: 16px">
      <div class="toolbar">
        <el-select v-model="category" clearable placeholder="按类目筛选" style="width: 180px" @change="load">
          <el-option v-for="name in mapData.categories" :key="name" :label="name" :value="name" />
        </el-select>
        <el-select v-model="projectId" clearable placeholder="按项目高亮位号" style="width: 260px" @change="load">
          <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
        </el-select>
        <span class="spacer" />
        <el-button type="primary" icon="Plus" @click="openCreateBox">新建物料盒</el-button>
      </div>
      <el-empty v-if="!mapData.boxes.length" description="还没有物料盒，先新建一个" />
    </div>
    <div class="stack">
      <section v-for="box in mapData.boxes" :key="box.id" class="page-card">
        <div class="box-title" @click="toggleBox(box.id)">
          <div class="box-heading">
            <span class="box-caret" :class="{ open: expanded[box.id] }"></span>
            <span class="box-icon">
              <el-icon><Coin v-if="box.box_type === 'reel'" /><Grid v-else /></el-icon>
            </span>
            <div>
              <strong>{{ box.name }}</strong>
              <span v-if="box.box_type === 'reel'" class="muted"> · 料卷盒 · {{ occupiedCount(box) }}/{{ box.slot_count }} 卷</span>
              <span v-else class="muted"> · {{ box.rows }} 行 × {{ box.cols }} 列 · {{ occupiedCount(box) }}/{{ box.rows * box.cols }}</span>
              <div v-if="box.remark" class="muted">{{ box.remark }}</div>
            </div>
          </div>
          <div @click.stop>
            <el-button link type="primary" icon="Edit" @click="openEditBox(box)">编辑</el-button>
            <el-button link type="danger" icon="Delete" @click="removeBox(box)">删除</el-button>
          </div>
        </div>
        <div class="box-collapse" :class="{ open: expanded[box.id] }">
          <div class="box-collapse-inner">
            <ReelBoxPanel
              v-if="box.box_type === 'reel'"
              :box="box"
              :highlights="highlights"
              @select="openSlot(box, $event)"
              @transfer="openTransfer({ item: $event.item, locationId: $event.location_id })"
              @checkout="checkoutSlot(box, $event)"
            />
            <div v-else class="box-grid" :style="gridStyle(box)" style="margin-top: 12px">
              <div
                v-for="cell in box.cells"
                :key="`${cell.row}-${cell.col}`"
                class="box-cell"
                :class="{ occupied: !!cell.item, dimmed: cell.dimmed, hit: marks(cell.item).length }"
                role="button"
                tabindex="0"
                @click="openCell(box, cell)"
                @keydown.enter.prevent="openCell(box, cell)"
                @keydown.space.prevent="openCell(box, cell)"
              >
                <div class="cell-head">
                  <span v-if="cell.item && !cell.dimmed" class="cell-type">{{ cell.item.category || '—' }}</span>
                  <span class="cell-pos">{{ cell.row }}-{{ cell.col }}</span>
                </div>
                <div class="cell-main">
                  <div class="cell-copy">
                    <div v-if="cell.item && !cell.dimmed" class="cell-body">
                      <span class="meta">{{ cell.item.footprint || '—' }}</span>
                      <span class="meta">{{ cell.item.value || '—' }}</span>
                      <span v-for="field in cellSpecs(cell.item)" :key="field.key" class="meta">{{ field.label }} {{ field.value }}</span>
                      <span v-if="marks(cell.item).length" class="mark">{{ marks(cell.item).join(' ') }}</span>
                    </div>
                    <div v-else class="cell-body">
                      <span class="meta">{{ cell.item ? '其他类目' : '空' }}</span>
                    </div>
                    <div v-if="cell.item" class="cell-foot" :class="{ stacked: longLcsc(cell.item) }">
                      <span class="code">{{ cell.item.lcsc_code || '—' }}</span>
                      <span class="stock">库存 {{ cell.location_quantity }}</span>
                      <span v-if="cell.cell_value != null" class="worth">{{ money(cell.cell_value) }}</span>
                    </div>
                  </div>
                  <div v-if="cell.item?.image_url" class="cell-photo" @click.stop>
                    <el-image
                      :src="cell.item.image_url"
                      fit="contain"
                      lazy
                      :preview-src-list="[cell.item.image_url]"
                      preview-teleported
                      hide-on-click-modal
                    >
                      <template #error>
                        <div class="cell-photo-fallback">
                          <el-icon><Picture /></el-icon>
                        </div>
                      </template>
                    </el-image>
                  </div>
                </div>
              </div>
            </div>
            <div v-if="box.invalid_items.length" style="margin-top: 12px">
              <div class="muted">坐标不合法，请移出或重新放入：</div>
              <el-tag v-for="item in box.invalid_items" :key="item.id" style="margin: 6px 6px 0 0">
                {{ item.lcsc_code || item.mpn || item.name }}
              </el-tag>
            </div>
          </div>
        </div>
      </section>
      <section class="page-card">
        <div class="card-head">
          <div>
            <h3>未入库</h3>
            <p>还没放进物料盒的物料，点「流转」放进盒子。</p>
          </div>
        </div>
        <el-table :data="visibleUnboxed" size="small">
          <el-table-column label="编号" width="120">
            <template #default="{ row }"><span class="mono">{{ row.lcsc_code || '—' }}</span></template>
          </el-table-column>
          <el-table-column prop="mpn" label="型号" min-width="160" />
          <el-table-column prop="name" label="名称" min-width="160" />
          <el-table-column prop="footprint" label="封装" width="120" />
          <el-table-column prop="category" label="类目" width="100" />
          <el-table-column label="参数" min-width="180">
            <template #default="{ row }">
              <template v-if="cellSpecs(row).length">
                <div v-for="field in cellSpecs(row)" :key="field.key">{{ field.label }} {{ field.value }}</div>
              </template>
              <span v-else>—</span>
            </template>
          </el-table-column>
          <el-table-column label="库存" width="80">
            <template #default="{ row }">{{ row.location_quantity }}</template>
          </el-table-column>
          <el-table-column label="总价" width="120">
            <template #default="{ row }">{{ money(row.cell_value) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="90">
            <template #default="{ row }">
              <el-button link type="primary" @click="openTransfer(row)">流转</el-button>
            </template>
          </el-table-column>
          <template #empty>
            <el-empty description="没有未入库物料" />
          </template>
        </el-table>
      </section>
    </div>

    <el-dialog v-model="boxVisible" :title="boxForm.id ? '编辑物料盒' : '新建物料盒'" width="420px">
      <el-form label-width="72px">
        <el-form-item label="名称"><el-input v-model="boxForm.name" /></el-form-item>
        <el-form-item label="类型">
          <el-radio-group v-model="boxForm.box_type">
            <el-radio value="grid">格子盒</el-radio>
            <el-radio value="reel">料卷盒</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="boxForm.box_type !== 'reel'" label="行数"><el-input-number v-model="boxForm.rows" :min="1" :max="100" /></el-form-item>
        <el-form-item v-if="boxForm.box_type !== 'reel'" label="列数"><el-input-number v-model="boxForm.cols" :min="1" :max="100" /></el-form-item>
        <el-form-item v-else label="最大卷数"><el-input-number v-model="boxForm.slot_count" :min="1" :max="100" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="boxForm.remark" type="textarea" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="boxVisible = false">取消</el-button>
        <el-button type="primary" :loading="boxSaving" @click="saveBox">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" :title="activePlace?.title || '位置详情'" width="520px">
      <template v-if="activePlace?.item">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="位置">{{ activePlace.title }}</el-descriptions-item>
          <el-descriptions-item label="立创编号">{{ activePlace.item.lcsc_code || '—' }}</el-descriptions-item>
          <el-descriptions-item label="型号">{{ activePlace.item.mpn || '—' }}</el-descriptions-item>
          <el-descriptions-item label="名称">{{ activePlace.item.name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="封装">{{ activePlace.item.footprint || '—' }}</el-descriptions-item>
          <el-descriptions-item label="类目">{{ activePlace.item.category || '—' }}</el-descriptions-item>
          <el-descriptions-item label="标称值">{{ activePlace.item.value || '—' }}</el-descriptions-item>
          <el-descriptions-item v-for="field in cellSpecs(activePlace.item)" :key="field.key" :label="field.label">{{ field.value }}</el-descriptions-item>
          <el-descriptions-item label="此处库存">{{ activePlace.quantity }}</el-descriptions-item>
          <el-descriptions-item label="此处总价">{{ money(activePlace.cellValue) }}</el-descriptions-item>
          <el-descriptions-item label="物料总库存">{{ activePlace.item.quantity }}</el-descriptions-item>
          <el-descriptions-item label="单价">{{ money(activePlace.item.unit_price) }}</el-descriptions-item>
          <el-descriptions-item v-if="marks(activePlace.item).length" label="位号">{{ marks(activePlace.item).join('、') }}</el-descriptions-item>
        </el-descriptions>
      </template>
      <template #footer>
        <el-button type="danger" plain @click="removeItem(activePlace.item)">删除</el-button>
        <el-button @click="clearPlace">移出</el-button>
        <el-button :disabled="!activePlace?.quantity" @click="openTransfer(activePlace)">流转</el-button>
        <el-button type="warning" plain :disabled="!activePlace?.quantity" @click="checkoutPlace">出库</el-button>
        <el-button type="primary" @click="editItem(activePlace.item)">编辑</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="placeVisible" title="放入物料" width="520px">
      <p>{{ placeTargetText }} 目前是空的。</p>
      <el-form label-width="72px">
        <el-form-item label="来源">
          <el-select v-model="selectedLocation" filterable placeholder="选择已有存放位置" style="width: 100%" @change="onPlaceSource">
            <el-option v-for="item in placeableLocations" :key="item.location_id" :label="item.label" :value="item.location_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="placeQuantity" :min="1" :max="selectedPlace?.quantity || 1" :step="1" />
        </el-form-item>
      </el-form>
      <p class="muted">从已有位置放入是流转，不计入新入库。新建并放入会按抽屉里的库存记一次入库。</p>
      <template #footer>
        <el-button @click="createHere">新建并放入</el-button>
        <el-button type="primary" :disabled="!selectedLocation" @click="placeSelected">{{ activeSlot ? '放入此槽' : '放入此格' }}</el-button>
      </template>
    </el-dialog>

    <ItemDrawer v-model="drawer" :item="editing" :draft="draft" :boxes="mapData.boxes" @saved="load" />
    <TransferDialog v-model="transferVisible" :source="transferSource" :boxes="mapData.boxes" @saved="load" />
  </div>
</template>
