<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import http, { reportRequestError } from '../api'
import { placeText } from '../format'

const props = defineProps({
  modelValue: Boolean,
  source: { type: Object, default: null },
  boxes: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'saved'])

const locations = ref([])
const saving = ref(false)
const form = reactive({
  from_location_id: null,
  quantity: 1,
  to_type: 'unboxed',
  to_box_id: null,
  to_row: 1,
  to_col: 1,
  to_slot_index: 1,
})

const gridBoxes = computed(() => props.boxes.filter((box) => (box.box_type || 'grid') === 'grid'))
const reelBoxes = computed(() => props.boxes.filter((box) => box.box_type === 'reel'))
const sourceLocation = computed(() => locations.value.find((row) => row.id === form.from_location_id) || null)
const targetBox = computed(() => {
  const pool = form.to_type === 'tape_reel' ? reelBoxes.value : gridBoxes.value
  return pool.find((box) => box.id === form.to_box_id) || null
})

watch(
  () => props.modelValue,
  async (open) => {
    if (!open || !props.source?.itemId) return
    try {
      const { data } = await http.get(`/items/${props.source.itemId}/locations`)
      locations.value = data.filter((row) => row.quantity > 0)
      form.from_location_id = props.source.locationId || locations.value[0]?.id || null
      form.quantity = sourceLocation.value?.quantity || 1
      form.to_type = 'unboxed'
      form.to_box_id = null
      form.to_row = 1
      form.to_col = 1
      form.to_slot_index = 1
    } catch (error) {
      reportRequestError(error)
    }
  },
)

function close() {
  emit('update:modelValue', false)
}

async function submit() {
  if (!form.from_location_id) {
    ElMessage.warning('请选择来源位置')
    return
  }
  if (!form.quantity || form.quantity > (sourceLocation.value?.quantity || 0)) {
    ElMessage.warning('流转数量超过该位置的库存')
    return
  }
  saving.value = true
  try {
    await http.post('/transfer', {
      from_location_id: form.from_location_id,
      to_type: form.to_type,
      to_box_id: form.to_type === 'unboxed' ? null : form.to_box_id,
      to_row: form.to_type === 'box_cell' ? form.to_row : null,
      to_col: form.to_type === 'box_cell' ? form.to_col : null,
      to_slot_index: form.to_type === 'tape_reel' ? form.to_slot_index : null,
      quantity: form.quantity,
    })
    ElMessage.success('已流转')
    emit('saved')
    close()
  } catch (error) {
    reportRequestError(error)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog :model-value="modelValue" title="物料流转" width="480px" @close="close">
    <el-form label-width="88px">
      <el-form-item label="来源">
        <el-select v-model="form.from_location_id" style="width: 100%" @change="form.quantity = sourceLocation?.quantity || 1">
          <el-option v-for="loc in locations" :key="loc.id" :label="placeText(loc)" :value="loc.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="数量">
        <el-input-number v-model="form.quantity" :min="1" :max="sourceLocation?.quantity || 1" :step="1" />
      </el-form-item>
      <el-form-item label="目标">
        <el-radio-group v-model="form.to_type">
          <el-radio value="unboxed">未入库</el-radio>
          <el-radio value="box_cell">格子</el-radio>
          <el-radio value="tape_reel">料卷</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item v-if="form.to_type === 'box_cell'" label="格子盒">
        <el-select v-model="form.to_box_id" placeholder="选择格子盒" style="width: 100%">
          <el-option v-for="box in gridBoxes" :key="box.id" :label="box.name" :value="box.id" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="form.to_type === 'box_cell' && targetBox" label="行列">
        <el-input-number v-model="form.to_row" :min="1" :max="targetBox.rows" />
        <span class="muted">行</span>
        <el-input-number v-model="form.to_col" :min="1" :max="targetBox.cols" />
        <span class="muted">列</span>
      </el-form-item>
      <el-form-item v-if="form.to_type === 'tape_reel'" label="料卷盒">
        <el-select v-model="form.to_box_id" placeholder="选择料卷盒" style="width: 100%">
          <el-option v-for="box in reelBoxes" :key="box.id" :label="box.name" :value="box.id" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="form.to_type === 'tape_reel' && targetBox" label="槽位">
        <el-input-number v-model="form.to_slot_index" :min="1" :max="targetBox.slot_count || 1" />
      </el-form-item>
    </el-form>
    <p class="muted">流转只改变存放位置，不计入消耗，也不算新入库。</p>
    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="saving" @click="submit">确认流转</el-button>
    </template>
  </el-dialog>
</template>
