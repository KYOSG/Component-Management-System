<script setup>
import { money } from '../format'
import { catalogState, filledSpecs } from '../specCatalog'

const props = defineProps({
  box: { type: Object, required: true },
  highlights: { type: Object, default: () => ({}) },
})
defineEmits(['select', 'transfer', 'checkout'])

function marks(slot) {
  return props.highlights[slot.item?.id] || []
}

function specs(slot) {
  void catalogState.categories
  return filledSpecs(slot.item)
}

function longLcsc(item) {
  const digits = String(item?.lcsc_code || '').replace(/\D/g, '')
  return digits.length > 6
}

/* Sprocket hole positions at r=32, center=(40,40) */
const HOLES = [
  [40, 8],
  [68, 24],
  [68, 56],
  [40, 72],
  [12, 56],
  [12, 24],
]
</script>

<template>
  <div class="reels">
    <p v-if="!box.reel_slots?.length" class="reel-note">
      这个料卷盒还没有槽位，编辑物料盒并填写最大卷数。
    </p>

    <article
      v-for="slot in box.reel_slots"
      :key="slot.slot_index"
      class="reel-card"
      :class="{
        'reel-card--empty': !slot.item,
        'reel-card--dimmed': slot.dimmed,
        'reel-card--hit': marks(slot).length,
      }"
    >
      <!-- ── Clickable face ── -->
      <button type="button" class="reel-face" @click="$emit('select', slot)">

        <!-- Reel disc (SVG, always 80×80 px) -->
        <div class="reel-disc" :class="{ 'reel-disc--occupied': slot.item && !slot.dimmed }">
          <svg class="reel-svg" viewBox="0 0 80 80" xmlns="http://www.w3.org/2000/svg">
            <!-- 1. Outer disc flange -->
            <circle
              cx="40" cy="40" r="38"
              :fill="slot.item && !slot.dimmed ? '#e8eaf6' : '#f2f4fb'"
              :stroke="slot.item && !slot.dimmed ? '#7986cb' : '#c5ccdf'"
              :stroke-width="slot.item ? '2.5' : '2'"
              :stroke-dasharray="slot.item ? null : '5 3'"
            />

            <!-- 2. Tape winding fill (solid circle r=28 → covered by hub later) -->
            <circle
              cx="40" cy="40" r="28"
              :fill="slot.item && !slot.dimmed ? '#c5cae9' : '#dde1ef'"
            />

            <!-- 3. Cross spokes -->
            <line x1="40" y1="4" x2="40" y2="76"
              :stroke="slot.item && !slot.dimmed ? '#7986cb' : '#c5ccdf'"
              stroke-width="3" stroke-linecap="round"
            />
            <line x1="4" y1="40" x2="76" y2="40"
              :stroke="slot.item && !slot.dimmed ? '#7986cb' : '#c5ccdf'"
              stroke-width="3" stroke-linecap="round"
            />

            <!-- 4. Hub circle (covers center of spokes; shows tape annulus between r17-r28) -->
            <circle
              cx="40" cy="40" r="17"
              :fill="slot.item && !slot.dimmed ? '#e8eaf6' : '#f2f4fb'"
              :stroke="slot.item && !slot.dimmed ? '#9fa8da' : '#d0d5e4'"
              stroke-width="1.5"
            />

            <!-- 5. Sprocket holes (six dots at r=32) -->
            <circle
              v-for="([hx, hy], i) in HOLES" :key="i"
              :cx="hx" :cy="hy" r="3.5"
              :fill="slot.item && !slot.dimmed ? '#5c6bc0' : '#bbbdcf'"
            />

            <!-- 6. Centre spindle -->
            <circle cx="40" cy="40" r="9"
              fill="white"
              :stroke="slot.item && !slot.dimmed ? '#9fa8da' : '#c5ccdf'"
              stroke-width="1.5"
            />
            <circle cx="40" cy="40" r="4.5"
              :fill="slot.item && !slot.dimmed ? '#9fa8da' : '#d0d5e4'"
            />

          </svg>
          <!-- Slot number badge below disc -->
          <div class="reel-slot-no">卷{{ slot.slot_index }}</div>
        </div>

        <!-- Info panel -->
        <div class="reel-info">

          <!-- Occupied reel -->
          <template v-if="slot.item && !slot.dimmed">
            <div class="reel-row reel-row--head">
              <span class="reel-cat">{{ slot.item.category || '—' }}</span>
            </div>
            <div class="reel-val">{{ slot.item.value || slot.item.mpn || '—' }}</div>
            <div class="reel-fp">{{ slot.item.footprint || '—' }}</div>
            <span
              v-for="field in specs(slot)" :key="field.key"
              class="reel-spec"
            >{{ field.label }} {{ field.value }}</span>
            <span v-if="marks(slot).length" class="reel-mark">
              {{ marks(slot).join(' ') }}
            </span>
            <div class="reel-foot" :class="{ stacked: longLcsc(slot.item) }">
              <span class="reel-code">{{ slot.item.lcsc_code || '—' }}</span>
              <span class="reel-stock">库存 {{ slot.quantity }}</span>
              <span v-if="slot.cell_value != null" class="reel-worth">
                {{ money(slot.cell_value) }}
              </span>
            </div>
            <div v-if="slot.item.image_url" class="reel-photo" @click.stop>
              <el-image
                :src="slot.item.image_url"
                fit="contain"
                lazy
                :preview-src-list="[slot.item.image_url]"
                preview-teleported
                hide-on-click-modal
              >
                <template #error>
                  <div class="reel-photo-err"><el-icon><Picture /></el-icon></div>
                </template>
              </el-image>
            </div>
          </template>

          <!-- Dimmed / filtered-out reel -->
          <template v-else-if="slot.item && slot.dimmed">
            <div class="reel-dim">其他类目</div>
          </template>

          <!-- Empty slot -->
          <template v-else>
            <div class="reel-empty">
              <el-icon class="reel-plus-icon"><Plus /></el-icon>
              <span class="reel-empty-label">空槽位</span>
              <span class="reel-empty-hint">点击放入物料</span>
            </div>
          </template>

        </div>
      </button>

      <!-- Action buttons (only for occupied slots) -->
      <div v-if="slot.item" class="reel-actions">
        <button type="button" class="reel-btn reel-btn--transfer" @click="$emit('transfer', slot)">
          流转
        </button>
        <button type="button" class="reel-btn reel-btn--out" @click="$emit('checkout', slot)">
          出库
        </button>
      </div>
    </article>
  </div>
</template>

<style scoped>
/* ── Grid container ── */
.reels {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(270px, 1fr));
  gap: 10px;
  margin-top: 12px;
}

.reel-note {
  grid-column: 1 / -1;
  margin: 4px 0 0;
  font-size: 13px;
  color: #8b93a7;
}

/* ── Card ── */
.reel-card {
  display: flex;
  flex-direction: column;
  border: 1px solid #d5daf0;
  border-radius: 14px;
  background: #fff;
  overflow: hidden;
  transition: box-shadow 0.15s, border-color 0.15s;
}

.reel-card:hover {
  border-color: #9fa8da;
  box-shadow: 0 2px 10px rgba(63, 81, 181, 0.1);
}

.reel-card--empty {
  background: #fafbff;
  border-color: #dde2f0;
  border-style: dashed;
}

.reel-card--empty:hover {
  border-color: #9fa8da;
  border-style: dashed;
  box-shadow: 0 2px 8px rgba(63, 81, 181, 0.08);
}

.reel-card--dimmed {
  opacity: 0.4;
  pointer-events: none;
}

.reel-card--hit {
  border-color: #3f51b5;
  box-shadow: 0 0 0 2px #c5cae9;
}

/* ── Clickable face ── */
.reel-face {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  width: 100%;
  padding: 12px 12px 10px;
  border: 0;
  background: transparent;
  cursor: pointer;
  text-align: left;
  color: inherit;
  font: inherit;
}

.reel-face:focus-visible {
  outline: 2px solid #3f51b5;
  outline-offset: -2px;
  border-radius: 14px;
}

/* ── SVG disc ── */
.reel-disc {
  flex: 0 0 80px;
  width: 80px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}

.reel-svg {
  width: 80px;
  height: 80px;
  display: block;
}

.reel-slot-no {
  font-size: 11px;
  font-weight: 700;
  color: #9fa8c5;
  line-height: 1;
}

.reel-disc--occupied .reel-slot-no {
  color: #5c6bc0;
}

/* ── Info panel ── */
.reel-info {
  flex: 1;
  min-width: 0;
}

/* Category + slot-number row */
.reel-row--head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 4px;
  margin-bottom: 3px;
}

.reel-cat {
  font-size: 11px;
  font-weight: 700;
  color: #5c6bc0;
  line-height: 1.3;
}

/* Main value */
.reel-val {
  font-size: 15px;
  font-weight: 700;
  color: #1a1f3c;
  line-height: 1.35;
  margin-bottom: 1px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Footprint */
.reel-fp {
  font-size: 12px;
  color: #6679b8;
  margin-bottom: 2px;
}

/* Spec lines */
.reel-spec {
  display: block;
  font-size: 12px;
  color: #4b556c;
  line-height: 1.4;
}

/* Marks / BOM highlight */
.reel-mark {
  display: block;
  font-size: 12px;
  font-weight: 650;
  color: #303f9f;
  margin-top: 3px;
}

/* Footer: LCSC + stock + price */
.reel-foot {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-top: 6px;
  flex-wrap: wrap;
}

.reel-foot.stacked {
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
}

.reel-code {
  font-size: 11px;
  font-weight: 650;
  color: #667085;
  word-break: break-all;
  flex: 1 1 auto;
}

.reel-stock {
  flex: 0 0 auto;
  font-size: 11px;
  font-weight: 600;
  color: #8b93a7;
}

.reel-worth {
  flex: 0 0 auto;
  font-size: 11px;
  font-weight: 700;
  color: #303f9f;
}

/* Thumbnail */
.reel-photo {
  width: 56px;
  height: 56px;
  margin-top: 6px;
  border-radius: 8px;
  overflow: hidden;
  background: #f4f5fb;
}

.reel-photo .el-image {
  width: 56px;
  height: 56px;
}

.reel-photo-err {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
  color: #b0bbd6;
  font-size: 18px;
}

/* Dimmed placeholder text */
.reel-dim {
  padding-top: 24px;
  font-size: 12px;
  color: #9fa8c5;
  text-align: center;
}

/* Empty slot hint */
.reel-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 80px;
  gap: 3px;
}

.reel-plus-icon {
  font-size: 22px;
  color: #c5cce0;
}

.reel-empty-label {
  font-size: 12px;
  color: #9fa8c5;
}

.reel-empty-hint {
  font-size: 11px;
  color: #c5cce0;
}

/* ── Action buttons ── */
.reel-actions {
  display: flex;
  gap: 0;
  border-top: 1px solid #eef0fa;
}

.reel-btn {
  flex: 1;
  border: 0;
  background: transparent;
  padding: 7px 0;
  font-size: 12px;
  cursor: pointer;
  transition: background 0.12s;
  color: #5c6bc0;
}

.reel-btn:first-child {
  border-right: 1px solid #eef0fa;
}

.reel-btn--transfer:hover {
  background: #eef0fb;
}

.reel-btn--out:hover {
  background: #fef3f2;
  color: #e53935;
}
</style>
