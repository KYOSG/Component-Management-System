<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import http, { reportRequestError } from '../api'
import { itemPayload, placeText } from '../format'
import { categoryNames, loadCatalog, specFields, specValueOk } from '../specCatalog'

const props = defineProps({
  modelValue: Boolean,
  item: { type: Object, default: null },
  draft: { type: Object, default: null },
  boxes: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'saved'])

const empty = () => ({
  id: null,
  lcsc_code: '',
  mpn: '',
  name: '',
  brand: '',
  footprint: '',
  category: '',
  value: '',
  params: '',
  specs: {},
  quantity: 0,
  min_stock: 0,
  unit_price: null,
  locations: [],
  box_id: null,
  row: null,
  col: null,
  slot_index: null,
  datasheet_url: '',
  image_url: '',
  remark: '',
  lcsc_sync_status: 'idle',
  lcsc_sync_error: '',
})

const form = reactive(empty())
const querying = ref(false)
const saving = ref(false)
const hint = ref('')
const hydrating = ref(false)

const gridBoxes = computed(() => props.boxes.filter((box) => (box.box_type || 'grid') === 'grid'))
const currentBox = computed(() => gridBoxes.value.find((box) => box.id === form.box_id) || null)
const reelPlaceText = computed(() => {
  if (!form.slot_index) return ''
  const box = props.boxes.find((row) => row.id === form.box_id)
  return `${box?.name || '料卷盒'} 卷${form.slot_index}`
})
const title = computed(() => (form.id ? '编辑物料' : '新增物料'))
const names = computed(() => categoryNames())
const fields = computed(() => specFields(form.category))
const locked = computed(() => form.lcsc_sync_status === 'queued' || form.lcsc_sync_status === 'running')
let lockTimer = 0

function applyItem(source) {
  Object.assign(form, empty(), source || {})
  form.specs = { ...(source?.specs || {}) }
}

function stopLockPoll() {
  if (!lockTimer) return
  window.clearInterval(lockTimer)
  lockTimer = 0
}

async function pullItem() {
  if (!props.modelValue || !form.id) return
  try {
    const { data } = await http.get(`/items/${form.id}`)
    const wasLocked = locked.value
    applyItem(data)
    const busy = data.lcsc_sync_status === 'queued' || data.lcsc_sync_status === 'running'
    if (!busy) {
      if (wasLocked && data.lcsc_sync_status !== 'failed') hint.value = '立创资料已更新'
      stopLockPoll()
    }
  } catch (error) {
    if (error.response?.status === 404) stopLockPoll()
  }
}

function startLockPoll() {
  stopLockPoll()
  pullItem()
  lockTimer = window.setInterval(pullItem, 3000)
}

watch(
  () => props.modelValue,
  async (open) => {
    if (!open) {
      stopLockPoll()
      return
    }
    hydrating.value = true
    try {
      await loadCatalog()
      let source = props.item?.id ? props.item : props.draft || {}
      if (props.item?.id) {
        const { data } = await http.get(`/items/${props.item.id}`)
        source = data
      }
      applyItem(source)
      hint.value = ''
      await nextTick()
      if (locked.value) startLockPoll()
    } catch (error) {
      reportRequestError(error)
    } finally {
      hydrating.value = false
    }
  },
)

watch(
  () => (props.modelValue && props.item?.id === form.id ? props.item?.lcsc_sync_status : ''),
  (status) => {
    if (status !== 'queued' && status !== 'running') return
    form.lcsc_sync_status = status
    form.lcsc_sync_error = props.item?.lcsc_sync_error || ''
    startLockPoll()
  },
)

watch(
  () => form.category,
  (category) => {
    if (hydrating.value) return
    const allowed = new Set(specFields(category).map((field) => field.key))
    const specs = {}
    Object.entries(form.specs || {}).forEach(([key, value]) => {
      if (allowed.has(key)) specs[key] = value
    })
    form.specs = specs
  },
)

function close() {
  emit('update:modelValue', false)
}

async function placeNew(itemId, place) {
  const { data } = await http.get(`/items/${itemId}/locations`)
  const unboxed = data.find((row) => row.location_type === 'unboxed' && row.quantity > 0)
  const reel = !!place.slot_index
  if (unboxed) {
    await http.post('/transfer', {
      from_location_id: unboxed.id,
      to_type: reel ? 'tape_reel' : 'box_cell',
      to_box_id: place.box_id,
      to_row: reel ? null : place.row,
      to_col: reel ? null : place.col,
      to_slot_index: reel ? place.slot_index : null,
      quantity: unboxed.quantity,
    })
    return
  }
  await http.post(`/items/${itemId}/locations`, {
    location_type: reel ? 'tape_reel' : 'box_cell',
    box_id: place.box_id,
    row: reel ? null : place.row,
    col: reel ? null : place.col,
    slot_index: reel ? place.slot_index : null,
    quantity: 0,
  })
}

function onBoxChange() {
  if (!form.box_id) {
    form.row = null
    form.col = null
  }
}

async function queryLcsc() {
  if (locked.value) return
  const code = (form.lcsc_code || '').trim().toUpperCase()
  if (!code) return
  form.lcsc_code = code
  querying.value = true
  try {
    const params = form.id ? { item_id: form.id } : {}
    const { data } = await http.get(`/lcsc/${encodeURIComponent(code)}`, { params })
    const keep = {
      quantity: form.quantity,
      box_id: form.box_id,
      row: form.row,
      col: form.col,
      slot_index: form.slot_index,
      remark: form.remark,
      min_stock: form.min_stock,
      locations: form.locations,
    }
    Object.assign(form, {
      lcsc_code: data.lcsc_code,
      mpn: data.mpn,
      name: data.name,
      brand: data.brand,
      footprint: data.footprint,
      category: data.category,
      value: data.value,
      params: data.params,
      specs: { ...(data.specs || {}) },
      unit_price: data.unit_price ?? null,
      datasheet_url: data.datasheet_url,
      image_url: data.image_url,
    }, keep)
    hint.value = `已填入立创资料。商城库存 ${data.mall_stock ?? '—'}，参考价格 ${data.mall_price || '—'}。`
    ElMessage.success('已填入立创资料')
  } catch (error) {
    reportRequestError(error)
  } finally {
    querying.value = false
  }
}

async function save() {
  if (locked.value) return
  if (!form.slot_index && form.box_id && (!form.row || !form.col)) {
    ElMessage.warning('放入物料盒时需要填写行和列')
    return
  }
  for (const field of fields.value) {
    const value = form.specs[field.key]
    if (field.required && !String(value || '').trim()) {
      ElMessage.warning(`请填写${field.label}`)
      return
    }
    if (String(value || '').trim() && !specValueOk(field, value)) {
      ElMessage.warning(field.type === 'select' ? `${field.label}不在可选项内` : `${field.label}需要是数字`)
      return
    }
  }
  saving.value = true
  try {
    const payload = itemPayload(form)
    const place = !form.id && form.box_id
      ? { box_id: form.box_id, row: form.row, col: form.col, slot_index: form.slot_index }
      : null
    if (form.id) {
      await http.put(`/items/${form.id}`, payload)
    } else {
      const saved = await http.post('/items', payload)
      form.id = saved.data.id
      if (place?.slot_index || (place?.box_id && place.row && place.col)) await placeNew(saved.data.id, place)
    }
    ElMessage.success('已保存')
    emit('saved')
    close()
  } catch (error) {
    reportRequestError(error)
  } finally {
    saving.value = false
  }
}

onBeforeUnmount(stopLockPoll)
</script>

<template>
  <el-drawer :model-value="modelValue" :title="title" size="520px" @close="close">
    <el-alert
      v-if="locked"
      class="lock-alert"
      type="warning"
      show-icon
      :closable="false"
      title="正在从立创更新这条物料，完成前不能查询或编辑"
    />
    <el-alert
      v-else-if="form.lcsc_sync_status === 'failed' && form.lcsc_sync_error"
      class="lock-alert"
      type="error"
      show-icon
      :closable="false"
      :title="form.lcsc_sync_error"
    />
    <el-form label-width="168px" @submit.prevent>
      <el-form-item label="立创编号">
        <el-input
          :model-value="form.lcsc_code"
          :disabled="locked"
          clearable
          placeholder="例如 C105580"
          @update:model-value="(value) => (form.lcsc_code = (value || '').toUpperCase())"
        >
          <template #append>
            <el-button :loading="querying" :disabled="locked" @click="queryLcsc">查询</el-button>
          </template>
        </el-input>
      </el-form-item>
      <el-alert v-if="hint" :title="hint" type="info" show-icon :closable="false" />
      <el-form-item label="厂家型号">
        <el-input v-model="form.mpn" :disabled="locked" />
      </el-form-item>
      <el-form-item label="商品名称">
        <el-input v-model="form.name" :disabled="locked" />
      </el-form-item>
      <el-form-item label="品牌">
        <el-input v-model="form.brand" :disabled="locked" />
      </el-form-item>
      <el-form-item label="封装">
        <el-input v-model="form.footprint" :disabled="locked" />
      </el-form-item>
      <el-form-item label="类目">
        <el-select
          v-model="form.category"
          :disabled="locked"
          filterable
          allow-create
          default-first-option
          clearable
          placeholder="选择或输入类目"
          style="width: 100%"
        >
          <el-option v-for="name in names" :key="name" :label="name" :value="name" />
        </el-select>
      </el-form-item>
      <el-form-item label="标称值">
        <el-input v-model="form.value" :disabled="locked" placeholder="5.1kΩ、4.7uF" />
      </el-form-item>
      <el-form-item v-for="field in fields" :key="field.key" :label="field.label" :required="field.required">
        <el-select
          v-if="field.type === 'select'"
          v-model="form.specs[field.key]"
          :disabled="locked"
          clearable
          filterable
          style="width: 100%"
        >
          <el-option v-for="option in field.options" :key="option" :label="option" :value="option" />
        </el-select>
        <el-input v-else v-model="form.specs[field.key]" :disabled="locked">
          <template v-if="field.type === 'number' && field.unit" #append>{{ field.unit }}</template>
        </el-input>
      </el-form-item>
      <el-form-item label="参数">
        <el-input v-model="form.params" :disabled="locked" type="textarea" :rows="4" />
      </el-form-item>
      <el-form-item label="单价">
        <el-input-number v-model="form.unit_price" :disabled="locked" :min="0" :step="0.0001" :precision="4" :value-on-clear="null" />
        <div class="muted">立创查询会填入最小起订量的单价。物料总价值 = 单价 × 总库存。</div>
      </el-form-item>
      <el-form-item label="自有库存">
        <el-input-number v-model="form.quantity" :disabled="locked" :min="0" :step="1" />
        <div v-if="!form.id && (form.slot_index || (form.box_id && form.row && form.col))" class="muted">这里填写的数量记一次新入库，保存后转入目标位置。</div>
        <div v-else class="muted">改的是总库存。增加的数量记为未入库，不能低于已放入盒子和料卷的数量。</div>
      </el-form-item>
      <el-form-item label="低库存阈值">
        <el-input-number v-model="form.min_stock" :disabled="locked" :min="0" :step="1" :precision="0" :value-on-clear="0" />
        <div class="muted">总库存低于这个数时在物料库里标红提醒。填 0 表示不提醒。</div>
      </el-form-item>
      <el-form-item v-if="form.id" label="存放位置">
        <div v-for="loc in form.locations" :key="loc.id">{{ placeText(loc) }}</div>
        <span v-if="!form.locations?.length" class="muted">还没有分配位置。请到物料盒地图里流转。</span>
      </el-form-item>
      <el-form-item v-if="!form.id && form.slot_index" label="放入位置">
        <span>{{ reelPlaceText }}</span>
        <div class="muted">保存时先按上面的自有库存记一次新入库，再转入这个料卷槽。</div>
      </el-form-item>
      <el-form-item v-if="!form.id && !form.slot_index" label="物料盒">
        <el-select v-model="form.box_id" :disabled="locked" clearable placeholder="先放在未入库" style="width: 100%" @change="onBoxChange">
          <el-option v-for="box in gridBoxes" :key="box.id" :label="`${box.name}（${box.rows} 行 × ${box.cols} 列）`" :value="box.id" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="!form.id && !form.slot_index && currentBox" label="格子">
        <el-input-number v-model="form.row" :disabled="locked" :min="1" :max="currentBox.rows" />
        <span class="muted">行</span>
        <el-input-number v-model="form.col" :disabled="locked" :min="1" :max="currentBox.cols" />
        <span class="muted">列</span>
      </el-form-item>
      <el-form-item label="数据手册">
        <el-input v-model="form.datasheet_url" :disabled="locked" />
      </el-form-item>
      <el-form-item label="图片">
        <el-input v-model="form.image_url" :disabled="locked" />
        <div class="muted">保存后图片放在服务器本机，打开物料盒时不再访问外网。</div>
        <el-image v-if="form.image_url" :src="form.image_url" fit="contain" style="width: 120px; height: 120px; margin-top: 8px" />
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="form.remark" :disabled="locked" type="textarea" :rows="2" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="saving" :disabled="locked" @click="save">保存</el-button>
    </template>
  </el-drawer>
</template>

<style scoped>
.lock-alert {
  margin-bottom: 12px;
}
</style>
