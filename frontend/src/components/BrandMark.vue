<template>
  <div class="brand-mark">
    <span class="brand-logo"><el-icon><Cpu /></el-icon></span>
    <span class="brand-copy">
      <strong>电子元件库</strong>
      <small>物料 · 物料盒 · BOM</small>
    </span>
  </div>
</template>

<style scoped>
.brand-mark {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-logo {
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  width: 38px;
  height: 38px;
  border-radius: var(--cms-radius);
  background: linear-gradient(135deg, var(--cms-primary), var(--cms-accent));
  box-shadow: 0 6px 16px color-mix(in srgb, var(--cms-primary) 32%, transparent);
  color: #fff;
  font-size: 20px;
}

.brand-copy {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}

.brand-copy strong {
  font-size: 16px;
  font-weight: 700;
  color: var(--cms-text);
  letter-spacing: 0.02em;
}

.brand-copy small {
  font-size: 12px;
  color: var(--cms-muted);
}
</style>
