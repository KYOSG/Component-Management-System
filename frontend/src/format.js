export const MATCH_STATUS = {
  matched: { label: '已匹配', type: 'success' },
  insufficient: { label: '库存不足', type: 'warning' },
  suggested: { label: '建议替换', type: 'primary' },
  not_found: { label: '未找到', type: 'info' },
}

export const FORMAT_LABEL = {
  easyeda_v131: '立创 EDA',
  lcsc_quote: '立创商城报价单',
}

export function formatDate(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const pad = (number) => String(number).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function cellText(row, col) {
  if (!row || !col) return '未入盒'
  return `第${row}行第${col}列`
}

export const SPEC_FIELDS = {
  电阻: [
    { key: 'tolerance', label: '精度' },
    { key: 'power', label: '功率' },
    { key: 'tempco', label: '温度系数' },
  ],
  电容: [
    { key: 'voltage', label: '额定电压' },
    { key: 'tempco', label: '温度系数' },
    { key: 'tolerance', label: '精度' },
  ],
  电感: [
    { key: 'isat', label: '饱和电流' },
    { key: 'tolerance', label: '精度' },
  ],
  二极管: [
    { key: 'vr', label: '反向耐压' },
    { key: 'if', label: '正向电流' },
  ],
  MOS: [
    { key: 'vds', label: '漏源耐压' },
    { key: 'id', label: '连续漏极电流' },
    { key: 'rds', label: '导通电阻' },
  ],
  三极管: [
    { key: 'vceo', label: '集电极-发射极耐压' },
    { key: 'ic', label: '集电极电流' },
  ],
}

export function specFields(category) {
  return SPEC_FIELDS[(category || '').trim()] || []
}

export function filledSpecs(item) {
  if (!item) return []
  const specs = item.specs || {}
  return specFields(item.category)
    .filter((field) => specs[field.key])
    .map((field) => ({ key: field.key, label: field.label, value: specs[field.key] }))
}

export function itemPayload(item, extra = {}) {
  return {
    lcsc_code: item.lcsc_code || '',
    mpn: item.mpn || '',
    name: item.name || '',
    brand: item.brand || '',
    footprint: item.footprint || '',
    category: item.category || '',
    value: item.value || '',
    params: item.params || '',
    specs: { ...(item.specs || {}) },
    quantity: item.quantity || 0,
    box_id: item.box_id ?? null,
    row: item.row ?? null,
    col: item.col ?? null,
    datasheet_url: item.datasheet_url || '',
    image_url: item.image_url || '',
    remark: item.remark || '',
    ...extra,
  }
}
