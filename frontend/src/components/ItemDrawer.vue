<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import http from '../api'
import { itemPayload } from '../format'

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
  quantity: 0,
  box_id: null,
  row: null,
  col: null,
  datasheet_url: '',
  image_url: '',
  remark: '',
})

const form = reactive(empty())
const querying = ref(false)
const saving = ref(false)
const hint = ref('')

const currentBox = computed(() => props.boxes.find((box) => box.id === form.box_id) || null)
const title = computed(() => (form.id ? '编辑物料' : '新增物料'))

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    Object.assign(form, empty(), props.item?.id ? props.item : props.draft || {})
    hint.value = ''
  },
)

function close() {
  emit('update:modelValue', false)
}

function onBoxChange() {
  if (!form.box_id) {
    form.row = null
    form.col = null
  }
}

async function queryLcsc() {
  const code = (form.lcsc_code || '').trim()
  if (!code) return
  querying.value = true
  try {
    const { data } = await http.get(`/lcsc/${encodeURIComponent(code)}`)
    const keep = {
      quantity: form.quantity,
      box_id: form.box_id,
      row: form.row,
      col: form.col,
      remark: form.remark,
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
      datasheet_url: data.datasheet_url,
      image_url: data.image_url,
    }, keep)
    hint.value = `已填入立创资料。商城库存 ${data.mall_stock ?? '—'}，参考价格 ${data.mall_price || '—'}，不会写入自有库存。`
    ElMessage.success('已填入立创资料')
  } finally {
    querying.value = false
  }
}

async function save() {
  if (form.box_id && (!form.row || !form.col)) {
    ElMessage.warning('放入物料盒时需要填写行和列')
    return
  }
  saving.value = true
  try {
    const payload = itemPayload(form)
    if (form.id) {
      await http.put(`/items/${form.id}`, payload)
    } else {
      await http.post('/items', payload)
    }
    ElMessage.success('已保存')
    emit('saved')
    close()
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-drawer :model-value="modelValue" :title="title" size="480px" @close="close">
    <el-form label-width="96px" @submit.prevent>
      <el-form-item label="立创编号">
        <el-input v-model="form.lcsc_code" clearable placeholder="例如 C105580">
          <template #append>
            <el-button :loading="querying" @click="queryLcsc">查询</el-button>
          </template>
        </el-input>
      </el-form-item>
      <el-alert v-if="hint" :title="hint" type="info" show-icon :closable="false" />
      <el-form-item label="厂家型号">
        <el-input v-model="form.mpn" />
      </el-form-item>
      <el-form-item label="商品名称">
        <el-input v-model="form.name" />
      </el-form-item>
      <el-form-item label="品牌">
        <el-input v-model="form.brand" />
      </el-form-item>
      <el-form-item label="封装">
        <el-input v-model="form.footprint" />
      </el-form-item>
      <el-form-item label="类目">
        <el-input v-model="form.category" placeholder="电阻、电容" />
      </el-form-item>
      <el-form-item label="标称值">
        <el-input v-model="form.value" placeholder="5.1kΩ、4.7uF" />
      </el-form-item>
      <el-form-item label="参数">
        <el-input v-model="form.params" type="textarea" :rows="4" />
      </el-form-item>
      <el-form-item label="自有库存">
        <el-input-number v-model="form.quantity" :min="0" :step="1" />
      </el-form-item>
      <el-form-item label="物料盒">
        <el-select v-model="form.box_id" clearable placeholder="未入盒" style="width: 100%" @change="onBoxChange">
          <el-option v-for="box in boxes" :key="box.id" :label="`${box.name}（${box.rows} 行 × ${box.cols} 列）`" :value="box.id" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="currentBox" label="格子">
        <el-input-number v-model="form.row" :min="1" :max="currentBox.rows" />
        <span class="muted">行</span>
        <el-input-number v-model="form.col" :min="1" :max="currentBox.cols" />
        <span class="muted">列</span>
      </el-form-item>
      <el-form-item label="数据手册">
        <el-input v-model="form.datasheet_url" />
      </el-form-item>
      <el-form-item label="图片">
        <el-input v-model="form.image_url" />
        <el-image v-if="form.image_url" :src="form.image_url" fit="contain" style="width: 120px; height: 120px; margin-top: 8px" />
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="form.remark" type="textarea" :rows="2" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-drawer>
</template>
