import { reactive } from 'vue'
import http from './api'

export const catalogState = reactive({
  categories: [],
  loaded: false,
})

let pending = null

export async function loadCatalog(force = false) {
  if (catalogState.loaded && !force) return catalogState.categories
  if (pending && !force) return pending
  pending = http
    .get('/spec-categories')
    .then(({ data }) => {
      catalogState.categories = data
      catalogState.loaded = true
      pending = null
      return data
    })
    .catch((error) => {
      pending = null
      throw error
    })
  return pending
}

export function specFields(category) {
  const name = (category || '').trim()
  const found = catalogState.categories.find((item) => item.name === name)
  return found ? found.fields : []
}

export function categoryNames() {
  return catalogState.categories.map((item) => item.name)
}

export function filledSpecs(item) {
  if (!item) return []
  const specs = item.specs || {}
  return specFields(item.category)
    .filter((field) => specs[field.key])
    .map((field) => ({
      key: field.key,
      label: field.label,
      value: displaySpec(field, specs[field.key]),
    }))
}

function displaySpec(field, value) {
  const text = String(value)
  if (field.type === 'number' && field.unit && !text.endsWith(field.unit)) {
    return `${text}${field.unit}`
  }
  return text
}

export function specValueOk(field, value) {
  const text = String(value || '').trim()
  if (!text) return !field.required
  if (field.type === 'number') return numericText(text, field.unit)
  if (field.type === 'select') return (field.options || []).includes(text)
  return true
}

export function numericText(value, unit) {
  let text = String(value || '').trim()
  const suffix = String(unit || '').trim()
  if (suffix && text.endsWith(suffix)) text = text.slice(0, -suffix.length).trim()
  return /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(text)
}
