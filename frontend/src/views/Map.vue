<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import http from '../api'
import { cellText, filledSpecs, itemPayload } from '../format'
import ItemDrawer from '../components/ItemDrawer.vue'

const route = useRoute()
const loading = ref(false)
const mapData = ref({ stats: { item_count: 0, box_count: 0, quantity_total: 0 }, categories: [], boxes: [], unboxed: [], highlights: {} })
const projects = ref([])
const category = ref('')
const projectId = ref(route.query.project ? Number(route.query.project) : null)
const boxVisible = ref(false)
const boxSaving = ref(false)
const boxForm = reactive({ id: null, name: '', rows: 5, cols: 10, remark: '' })
const detailVisible = ref(false)
const placeVisible = ref(false)
const activeBox = ref(null)
const activeCell = ref(null)
const selectedUnboxed = ref(null)
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

function gridStyle(box) {
  return { gridTemplateColumns: `repeat(${box.cols}, minmax(128px, 1fr))` }
}

function occupiedCount(box) {
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

async function load() {
  loading.value = true
  try {
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
  Object.assign(boxForm, { id: null, name: '', rows: 5, cols: 10, remark: '' })
  boxVisible.value = true
}

function openEditBox(box) {
  Object.assign(boxForm, { id: box.id, name: box.name, rows: box.rows, cols: box.cols, remark: box.remark || '' })
  boxVisible.value = true
}

async function saveBox() {
  boxSaving.value = true
  try {
    const payload = { name: boxForm.name, rows: boxForm.rows, cols: boxForm.cols, remark: boxForm.remark }
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

function openCell(box, cell) {
  activeBox.value = box
  activeCell.value = cell
  if (cell.item) {
    detailVisible.value = true
    return
  }
  selectedUnboxed.value = null
  placeVisible.value = true
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
    row: activeCell.value.row,
    col: activeCell.value.col,
    quantity: 0,
  }
  placeVisible.value = false
  drawer.value = true
}

async function placeSelected() {
  const item = visibleUnboxed.value.find((row) => row.id === selectedUnboxed.value)
  if (!item) return
  await http.put(`/items/${item.id}`, itemPayload(item, {
    box_id: activeBox.value.id,
    row: activeCell.value.row,
    col: activeCell.value.col,
  }))
  placeVisible.value = false
  await load()
}

async function unbox(item) {
  await http.post(`/items/${item.id}/unbox`)
  detailVisible.value = false
  await load()
}

async function removeItem(item) {
  await ElMessageBox.confirm('删除后无法恢复。', '删除物料', { type: 'warning' })
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
      <div class="stat"><span>物料种类</span><b>{{ mapData.stats.item_count }}</b></div>
      <div class="stat"><span>盒子数量</span><b>{{ mapData.stats.box_count }}</b></div>
      <div class="stat"><span>库存总数</span><b>{{ mapData.stats.quantity_total }}</b></div>
    </div>
    <div class="page-card" style="margin-bottom: 16px">
      <div class="toolbar">
        <el-button type="primary" @click="openCreateBox">新建物料盒</el-button>
        <el-select v-model="category" clearable placeholder="按类目筛选" style="width: 180px" @change="load">
          <el-option v-for="name in mapData.categories" :key="name" :label="name" :value="name" />
        </el-select>
        <el-select v-model="projectId" clearable placeholder="按项目高亮位号" style="width: 260px" @change="load">
          <el-option v-for="project in projects" :key="project.id" :label="project.name" :value="project.id" />
        </el-select>
      </div>
      <el-empty v-if="!mapData.boxes.length" description="还没有物料盒，先新建一个" />
    </div>
    <div class="stack">
      <section v-for="box in mapData.boxes" :key="box.id" class="page-card">
        <div class="box-title" @click="toggleBox(box.id)">
          <div class="box-heading">
            <span class="box-caret" :class="{ open: expanded[box.id] }"></span>
            <div>
              <strong>{{ box.name }}</strong>
              <span class="muted"> · {{ box.rows }} 行 × {{ box.cols }} 列 · {{ occupiedCount(box) }}/{{ box.rows * box.cols }}</span>
              <div v-if="box.remark" class="muted">{{ box.remark }}</div>
            </div>
          </div>
          <div @click.stop>
            <el-button link type="primary" @click="openEditBox(box)">编辑</el-button>
            <el-button link type="danger" @click="removeBox(box)">删除</el-button>
          </div>
        </div>
        <div class="box-collapse" :class="{ open: expanded[box.id] }">
          <div class="box-collapse-inner">
            <div class="box-grid" :style="gridStyle(box)" style="margin-top: 12px">
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
                      <span v-for="field in filledSpecs(cell.item)" :key="field.key" class="meta">{{ field.label }} {{ field.value }}</span>
                      <span v-if="marks(cell.item).length" class="mark">{{ marks(cell.item).join(' ') }}</span>
                    </div>
                    <div v-else class="cell-body">
                      <span class="meta">{{ cell.item ? '其他类目' : '空' }}</span>
                    </div>
                    <div v-if="cell.item" class="cell-foot" :class="{ stacked: longLcsc(cell.item) }">
                      <span class="code">{{ cell.item.lcsc_code || '—' }}</span>
                      <span class="stock">库存 {{ cell.item.quantity }}</span>
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
        <h3>未入盒</h3>
        <el-table :data="visibleUnboxed" size="small">
          <el-table-column label="编号" width="120">
            <template #default="{ row }">{{ row.lcsc_code || '—' }}</template>
          </el-table-column>
          <el-table-column prop="mpn" label="型号" min-width="160" />
          <el-table-column prop="name" label="名称" min-width="160" />
          <el-table-column prop="footprint" label="封装" width="120" />
          <el-table-column prop="category" label="类目" width="100" />
          <el-table-column prop="quantity" label="库存" width="80" />
          <template #empty>
            <el-empty description="没有未入盒物料" />
          </template>
        </el-table>
      </section>
    </div>

    <el-dialog v-model="boxVisible" :title="boxForm.id ? '编辑物料盒' : '新建物料盒'" width="420px">
      <el-form label-width="72px">
        <el-form-item label="名称"><el-input v-model="boxForm.name" /></el-form-item>
        <el-form-item label="行数"><el-input-number v-model="boxForm.rows" :min="1" :max="100" /></el-form-item>
        <el-form-item label="列数"><el-input-number v-model="boxForm.cols" :min="1" :max="100" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="boxForm.remark" type="textarea" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="boxVisible = false">取消</el-button>
        <el-button type="primary" :loading="boxSaving" @click="saveBox">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" title="格子详情" width="520px">
      <template v-if="activeCell?.item">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="位置">{{ activeBox.name }} {{ cellText(activeCell.row, activeCell.col) }}</el-descriptions-item>
          <el-descriptions-item label="立创编号">{{ activeCell.item.lcsc_code || '—' }}</el-descriptions-item>
          <el-descriptions-item label="型号">{{ activeCell.item.mpn || '—' }}</el-descriptions-item>
          <el-descriptions-item label="名称">{{ activeCell.item.name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="封装">{{ activeCell.item.footprint || '—' }}</el-descriptions-item>
          <el-descriptions-item label="类目">{{ activeCell.item.category || '—' }}</el-descriptions-item>
          <el-descriptions-item label="标称值">{{ activeCell.item.value || '—' }}</el-descriptions-item>
          <el-descriptions-item v-for="field in filledSpecs(activeCell.item)" :key="field.key" :label="field.label">{{ field.value }}</el-descriptions-item>
          <el-descriptions-item label="库存">{{ activeCell.item.quantity }}</el-descriptions-item>
          <el-descriptions-item v-if="marks(activeCell.item).length" label="位号">{{ marks(activeCell.item).join('、') }}</el-descriptions-item>
        </el-descriptions>
      </template>
      <template #footer>
        <el-button @click="unbox(activeCell.item)">移出</el-button>
        <el-button type="danger" @click="removeItem(activeCell.item)">删除</el-button>
        <el-button type="primary" @click="editItem(activeCell.item)">编辑</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="placeVisible" title="放入物料" width="480px">
      <p>{{ activeBox?.name }} {{ cellText(activeCell?.row, activeCell?.col) }} 目前是空的。</p>
      <el-select v-model="selectedUnboxed" filterable placeholder="选择未入盒物料" style="width: 100%">
        <el-option
          v-for="item in visibleUnboxed"
          :key="item.id"
          :label="`${item.lcsc_code || item.mpn || item.name || '未命名'} · 库存 ${item.quantity}`"
          :value="item.id"
        />
      </el-select>
      <template #footer>
        <el-button @click="createHere">新建并放入</el-button>
        <el-button type="primary" :disabled="!selectedUnboxed" @click="placeSelected">放入此格</el-button>
      </template>
    </el-dialog>

    <ItemDrawer v-model="drawer" :item="editing" :draft="draft" :boxes="mapData.boxes" @saved="load" />
  </div>
</template>
