<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import http, { reportRequestError } from '../api'

const props = defineProps({
  modelValue: Boolean,
})
const emit = defineEmits(['update:modelValue', 'done'])

const parsing = ref(false)
const committing = ref(false)
const preview = ref(null)

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})
const busy = computed(() => parsing.value || committing.value)
const shippable = computed(() => (preview.value?.create_count || 0) + (preview.value?.stock_count || 0))

watch(
  () => props.modelValue,
  (shown) => {
    if (shown) preview.value = null
  },
)

function beforeClose(done) {
  if (!committing.value) done()
}

function priceText(value) {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  if (Number.isNaN(number)) return '—'
  return `¥${number.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 6 })}`
}

function rowClass({ row }) {
  return row.action === 'skip' ? 'is-skip' : ''
}

async function upload(option) {
  if (option.file.size > 10 * 1024 * 1024) {
    ElMessage.error('文件不能超过 10MB')
    return
  }
  const body = new FormData()
  body.append('file', option.file)
  parsing.value = true
  preview.value = null
  try {
    const { data } = await http.post('/items/order-preview', body)
    preview.value = data
  } catch (error) {
    reportRequestError(error)
  } finally {
    parsing.value = false
  }
}

async function commit() {
  if (!preview.value || !shippable.value) return
  committing.value = true
  try {
    const { data } = await http.post('/items/order-commit', {
      order_no: preview.value.order_no,
      lines: preview.value.lines.map((row) => ({
        lcsc_code: row.lcsc_code,
        mpn: row.mpn,
        name: row.name,
        brand: row.brand,
        footprint: row.footprint,
        ship_qty: row.ship_qty,
        unit_price: row.unit_price,
        skip: row.action === 'skip',
      })),
    })
    const parts = []
    if (data.created) parts.push(`新建 ${data.created} 种`)
    if (data.stocked) parts.push(`追加 ${data.stocked} 种`)
    ElMessage.success(`已入库 ${data.ship_total} 件${parts.length ? `，${parts.join('，')}` : ''}`)
    open.value = false
    emit('done')
  } catch (error) {
    reportRequestError(error)
  } finally {
    committing.value = false
  }
}

function close() {
  if (committing.value) return
  open.value = false
}
</script>

<template>
  <el-dialog
    v-model="open"
    :title="preview ? '确认订单入库' : '订单入库'"
    width="92%"
    top="6vh"
    :close-on-click-modal="!preview && !busy"
    :close-on-press-escape="!busy"
    :show-close="!committing"
    :before-close="beforeClose"
  >
    <div v-loading="busy" :element-loading-text="committing ? '正在入库' : '正在解析订单'">
      <el-upload
        v-if="!preview"
        drag
        :show-file-list="false"
        accept=".xls,.xlsx"
        :http-request="upload"
        :disabled="parsing"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">将立创商城订单详情拖到此处，或<em>点击上传</em></div>
        <div class="el-upload__tip">支持 .xls / .xlsx。确认后按发货数量入库，库里没有的物料会新建。</div>
      </el-upload>

      <template v-else>
        <el-alert
          v-if="preview.already_imported"
          class="order-alert"
          type="warning"
          show-icon
          :closable="false"
          title="这个订单之前已经入过库，再次确认会再次增加库存"
        />
        <div class="order-meta">
          <span>订单编号 <strong>{{ preview.order_no || '—' }}</strong></span>
          <span>下单日期 <strong>{{ preview.ordered_at || '—' }}</strong></span>
          <span>发货合计 <strong>{{ preview.ship_total }}</strong></span>
          <span>新建 {{ preview.create_count }} · 追加 {{ preview.stock_count }} · 跳过 {{ preview.skip_count }}</span>
        </div>
        <p class="order-note">已有物料只按发货数量增加库存。新建物料会写入订单里的型号、封装和单价，标称值和类目按商品名称识别。数量先记在未入库，之后可以再放入物料盒。发货数量和订购数量不一致时会标出。</p>
        <el-table :data="preview.lines" :row-class-name="rowClass" height="460" table-layout="auto">
          <el-table-column prop="line_no" label="序号" width="64" align="center" />
          <el-table-column label="商品编号" min-width="120" align="center">
            <template #default="{ row }"><span class="mono">{{ row.lcsc_code || '—' }}</span></template>
          </el-table-column>
          <el-table-column prop="mpn" label="厂家型号" min-width="160" show-overflow-tooltip>
            <template #default="{ row }">{{ row.mpn || '—' }}</template>
          </el-table-column>
          <el-table-column prop="name" label="商品名称" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">{{ row.name || '—' }}</template>
          </el-table-column>
          <el-table-column prop="footprint" label="封装" width="120" align="center" show-overflow-tooltip>
            <template #default="{ row }">{{ row.footprint || '—' }}</template>
          </el-table-column>
          <el-table-column label="类目" width="90" align="center">
            <template #default="{ row }">{{ row.category || '—' }}</template>
          </el-table-column>
          <el-table-column label="标称值" width="100" align="center">
            <template #default="{ row }"><strong v-if="row.value">{{ row.value }}</strong><span v-else>—</span></template>
          </el-table-column>
          <el-table-column prop="ordered_qty" label="订购" width="72" align="center" />
          <el-table-column label="发货" width="72" align="center">
            <template #default="{ row }">
              <strong :class="{ 'ship-diff': row.ordered_qty !== row.ship_qty }">{{ row.ship_qty }}</strong>
            </template>
          </el-table-column>
          <el-table-column label="单价" width="110" align="center">
            <template #default="{ row }">{{ priceText(row.unit_price) }}</template>
          </el-table-column>
          <el-table-column label="处理" width="168" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.action === 'create'" type="success" effect="light">新建并入库</el-tag>
              <el-tag v-else-if="row.action === 'stock'" type="primary" effect="light">追加，现有 {{ row.current_quantity }}</el-tag>
              <el-tag v-else type="info" effect="light">{{ row.skip_reason || '跳过' }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </div>
    <template #footer>
      <div class="order-footer">
        <el-upload
          v-if="preview"
          :show-file-list="false"
          accept=".xls,.xlsx"
          :http-request="upload"
          :disabled="busy"
        >
          <el-button :disabled="busy">重新选择</el-button>
        </el-upload>
        <span class="spacer" />
        <el-button :disabled="committing" @click="close">取消</el-button>
        <el-button v-if="preview" type="primary" :loading="committing" :disabled="!shippable || parsing" @click="commit">
          确认入库
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.order-alert {
  margin-bottom: 12px;
}

.order-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  margin-bottom: 8px;
  color: var(--cms-text-2);
}

.order-note {
  margin: 0 0 12px;
  color: var(--cms-muted);
  font-size: 13px;
}

.order-footer {
  display: flex;
  align-items: center;
  gap: 12px;
}

.order-footer :deep(.el-button) {
  margin-left: 0;
}

.ship-diff {
  color: var(--cms-warning-text);
}

:deep(.is-skip) {
  color: var(--cms-muted);
}
</style>
