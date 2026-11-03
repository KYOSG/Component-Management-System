<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http, { reportRequestError } from '../api'
import { loadCatalog } from '../specCatalog'

const categories = ref([])
const selectedId = ref(null)
const saving = ref(false)
const originalName = ref('')
const form = reactive({
  id: null,
  name: '',
  lcsc_keywords: [],
  fields: [],
  sort_order: 0,
})

function splitList(text) {
  const seen = []
  String(text || '')
    .split(/[,，]/)
    .map((part) => part.trim())
    .filter(Boolean)
    .forEach((part) => {
      if (!seen.includes(part)) seen.push(part)
    })
  return seen
}

function editorPayload(sortOrder = form.sort_order) {
  return {
    name: form.name.trim(),
    lcsc_keywords: [...form.lcsc_keywords],
    sort_order: sortOrder,
    fields: form.fields.map((field) => ({
      key: field.key.trim().toLowerCase(),
      label: field.label.trim(),
      type: field.type,
      unit: field.type === 'number' ? field.unit.trim() : '',
      options: field.type === 'select' ? splitList(field.optionsText) : [],
      aliases: splitList(field.aliasesText),
      required: !!field.required,
    })),
  }
}

function storedPayload(row, sortOrder = row.sort_order) {
  return {
    name: row.name,
    lcsc_keywords: [...(row.lcsc_keywords || [])],
    sort_order: sortOrder,
    fields: (row.fields || []).map((field) => ({
      key: field.key,
      label: field.label,
      type: field.type || 'text',
      unit: field.type === 'number' ? field.unit || '' : '',
      options: field.type === 'select' ? [...(field.options || [])] : [],
      aliases: [...(field.aliases || [])],
      required: !!field.required,
    })),
  }
}

function isDirty() {
  const stored = categories.value.find((item) => item.id === form.id)
  if (!stored) return false
  return JSON.stringify(editorPayload(stored.sort_order)) !== JSON.stringify(storedPayload(stored))
}

function toEditor(row) {
  form.id = row.id
  form.name = row.name
  form.lcsc_keywords = [...(row.lcsc_keywords || [])]
  form.sort_order = row.sort_order
  form.fields = (row.fields || []).map((field) => ({
    key: field.key,
    label: field.label,
    type: field.type || 'text',
    unit: field.unit || '',
    optionsText: (field.options || []).join('，'),
    aliasesText: (field.aliases || []).join('，'),
    required: !!field.required,
  }))
  originalName.value = row.name
}

async function load(keepId = selectedId.value) {
  try {
    const { data } = await http.get('/spec-categories')
    categories.value = data
    const found = data.find((item) => item.id === keepId) || data[0]
    if (found) {
      selectedId.value = found.id
      toEditor(found)
    } else {
      selectedId.value = null
      form.id = null
    }
    await loadCatalog(true)
  } catch (error) {
    reportRequestError(error)
  }
}

async function select(row) {
  if (row.id === form.id) return
  if (isDirty()) {
    try {
      await ElMessageBox.confirm('当前类目有未保存的修改，切换后会丢弃。', '切换类目', {
        type: 'warning',
        confirmButtonText: '丢弃并切换',
      })
    } catch {
      return
    }
  }
  selectedId.value = row.id
  toEditor(row)
}

async function createCategory() {
  let value = ''
  try {
    const result = await ElMessageBox.prompt('类目名称', '新增类目', {
      inputPlaceholder: '例如 晶振',
      inputValidator: (text) => (text && text.trim() ? true : '请填写类目名称'),
    })
    value = result.value
  } catch {
    return
  }
  try {
    const { data } = await http.post('/spec-categories', { name: value.trim(), lcsc_keywords: [], fields: [] })
    await load(data.id)
    ElMessage.success('已新增类目')
  } catch (error) {
    reportRequestError(error)
  }
}

async function removeCategory() {
  if (!form.id) return
  try {
    await ElMessageBox.confirm('只删除类目配置，已有物料的类目名称和参数不会删除。', '删除类目', { type: 'warning' })
  } catch {
    return
  }
  try {
    await http.delete(`/spec-categories/${form.id}`)
    await load(null)
    ElMessage.success('已删除类目')
  } catch (error) {
    reportRequestError(error)
  }
}

function validate(body) {
  if (!body.name) {
    ElMessage.warning('请填写类目名称')
    return false
  }
  for (const field of body.fields) {
    if (!field.key) {
      ElMessage.warning('请填写字段键名')
      return false
    }
    if (!field.label) {
      ElMessage.warning('请填写字段显示名')
      return false
    }
    if (field.type === 'select' && !field.options.length) {
      ElMessage.warning('字典字段需要至少一个选项')
      return false
    }
  }
  const keys = body.fields.map((field) => field.key)
  if (new Set(keys).size !== keys.length) {
    ElMessage.warning('同一类目的字段键名不能重复')
    return false
  }
  return true
}

async function save() {
  const body = editorPayload()
  if (!validate(body)) return false
  if (body.name !== originalName.value) {
    try {
      await ElMessageBox.confirm('库中同名物料的类目会一并更新。', '修改类目名称', { type: 'warning' })
    } catch {
      return false
    }
  }
  saving.value = true
  try {
    await http.put(`/spec-categories/${form.id}`, body)
    await load(form.id)
    ElMessage.success('已保存')
    return true
  } catch (error) {
    reportRequestError(error)
    return false
  } finally {
    saving.value = false
  }
}

async function move(index, delta) {
  const next = index + delta
  if (next < 0 || next >= categories.value.length) return
  const movingId = categories.value[index].id
  if (isDirty()) {
    try {
      await ElMessageBox.confirm('当前类目有未保存的修改。调整顺序会先保存它。', '调整顺序', { type: 'warning' })
    } catch {
      return
    }
    const kept = await save()
    if (!kept) return
  }
  const ordered = categories.value.slice()
  const from = ordered.findIndex((item) => item.id === movingId)
  const target = from + delta
  if (from < 0 || target < 0 || target >= ordered.length) return
  const [item] = ordered.splice(from, 1)
  ordered.splice(target, 0, item)
  try {
    await Promise.all(ordered.map((row, order) => http.put(`/spec-categories/${row.id}`, storedPayload(row, order))))
    await load(item.id)
  } catch (error) {
    reportRequestError(error)
  }
}

function addField() {
  form.fields.push({
    key: '',
    label: '',
    type: 'text',
    unit: '',
    optionsText: '',
    aliasesText: '',
    required: false,
  })
}

function removeField(index) {
  form.fields.splice(index, 1)
}

function moveField(index, delta) {
  const next = index + delta
  if (next < 0 || next >= form.fields.length) return
  const [item] = form.fields.splice(index, 1)
  form.fields.splice(next, 0, item)
}

function onKey(field) {
  field.key = field.key.toLowerCase().replace(/[^a-z0-9_]/g, '').slice(0, 32)
}

onMounted(() => load())
</script>

<template>
  <div class="spec-page">
    <section class="spec-help">
      <div class="spec-help-title">说明</div>
      <p><strong>字典。</strong>在参数配置里把类型改成字典，并在「字典选项」里填入用逗号分开的选项，例如 ±1%，±5%，±10%。之后新增或编辑物料时，这个参数会变成一个下拉框，而不是自由输入的文本框。</p>
      <p><strong>立创参数别名。</strong>立创商品和 BOM 里，同一个参数常常有好几种叫法，例如「精度」「阻值精度」「tolerance」。别名就是这些叫法。查询立创或导入时，参数名对上任意一个别名，就会把对应的值填进这个字段。多个别名用逗号分隔；留空则用显示名去匹配。</p>
    </section>
    <div class="spec-layout">
    <aside class="page-card spec-side">
      <div class="toolbar">
        <el-button type="primary" icon="Plus" @click="createCategory">新增类目</el-button>
      </div>
      <div
        v-for="(item, index) in categories"
        :key="item.id"
        class="spec-item"
        :class="{ active: item.id === selectedId }"
        role="button"
        tabindex="0"
        @click="select(item)"
        @keydown.enter.prevent="select(item)"
      >
        <span>{{ item.name }}</span>
        <span class="spec-item-actions">
          <el-button link type="primary" :disabled="index === 0" @click.stop="move(index, -1)">上移</el-button>
          <el-button link type="primary" :disabled="index === categories.length - 1" @click.stop="move(index, 1)">下移</el-button>
        </span>
      </div>
      <el-empty v-if="!categories.length" description="还没有类目" />
    </aside>
    <section v-if="form.id" class="page-card spec-editor">
      <el-form label-width="120px" @submit.prevent>
        <el-form-item label="类目名称">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="立创关键词">
          <el-select
            v-model="form.lcsc_keywords"
            multiple
            filterable
            allow-create
            default-first-option
            placeholder="输入后回车，例如 resistor"
            style="width: 100%"
          />
          <div class="muted">立创查询时，只看最后一级目录名。目录名包含这些词就归入此类目，列表中靠前的类目优先匹配。物料盒格子按下面的字段显示已填写的参数。</div>
        </el-form-item>
      </el-form>
      <div class="toolbar">
        <el-button @click="addField">新增字段</el-button>
        <el-button type="danger" plain @click="removeCategory">删除类目</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </div>
      <el-table :data="form.fields" border size="small">
        <el-table-column label="键名" width="140">
          <template #default="{ row }">
            <el-input v-model="row.key" placeholder="vds" @input="onKey(row)" />
          </template>
        </el-table-column>
        <el-table-column label="显示名" width="160">
          <template #default="{ row }">
            <el-input v-model="row.label" placeholder="漏源耐压" />
          </template>
        </el-table-column>
        <el-table-column label="类型" width="110">
          <template #default="{ row }">
            <el-select v-model="row.type">
              <el-option label="文本" value="text" />
              <el-option label="数字" value="number" />
              <el-option label="字典" value="select" />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="单位" width="120">
          <template #default="{ row }">
            <el-input v-if="row.type === 'number'" :key="`${row.key}-unit`" v-model="row.unit" placeholder="如 V、mW" />
            <span v-else class="muted">数字类型可填</span>
          </template>
        </el-table-column>
        <el-table-column label="字典选项" min-width="160">
          <template #default="{ row }">
            <el-input v-if="row.type === 'select'" :key="`${row.key}-options`" v-model="row.optionsText" placeholder="用逗号分隔，例如 ±1%，±5%，±10%" />
            <span v-else class="muted">字典类型可填</span>
          </template>
        </el-table-column>
        <el-table-column label="立创参数别名" min-width="180">
          <template #default="{ row }">
            <el-input v-model="row.aliasesText" placeholder="用逗号分隔，留空则用显示名" />
          </template>
        </el-table-column>
        <el-table-column label="必填" width="70" align="center">
          <template #default="{ row }">
            <el-checkbox v-model="row.required" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ $index }">
            <el-button link type="primary" :disabled="$index === 0" @click="moveField($index, -1)">上移</el-button>
            <el-button link type="primary" :disabled="$index === form.fields.length - 1" @click="moveField($index, 1)">下移</el-button>
            <el-button link type="danger" @click="removeField($index)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>
    <section v-else class="page-card spec-editor">
      <el-empty description="选择左侧类目，或新增一个类目" />
    </section>
    </div>
  </div>
</template>

<style scoped>
.spec-help {
  margin-bottom: 16px;
  padding: 14px 18px;
  border: 1px solid var(--cms-primary-line);
  border-left: 4px solid var(--cms-primary);
  border-radius: var(--cms-radius);
  background: var(--cms-primary-soft);
}

.spec-help-title {
  margin-bottom: 8px;
  color: var(--cms-primary-strong);
  font-weight: 700;
}

.spec-help p {
  margin: 0;
  color: var(--cms-text-2);
  font-size: 13px;
  line-height: 1.7;
}

.spec-help p + p {
  margin-top: 8px;
}

.spec-layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.spec-side {
  padding: 16px;
}

.spec-side .toolbar {
  margin-bottom: 12px;
}

.spec-item {
  display: flex;
  box-sizing: border-box;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 0;
  padding: 4px 4px 4px 12px;
  border: 0;
  border-radius: var(--cms-radius-sm);
  background: transparent;
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: background-color 0.15s;
}

.spec-item + .spec-item {
  margin-top: 4px;
}

.spec-item:hover {
  background: var(--cms-surface-muted);
}

.spec-item:focus-visible {
  outline: none;
  box-shadow: var(--cms-ring);
}

.spec-item.active {
  background: var(--cms-primary-soft);
  color: var(--cms-primary);
  font-weight: 600;
}

.spec-item-actions {
  display: flex;
  flex: none;
  align-items: center;
}

.spec-item-actions :deep(.el-button) {
  margin: 0;
  padding: 4px 8px;
}

.spec-editor .muted {
  margin-top: 6px;
  line-height: 1.5;
}
</style>
