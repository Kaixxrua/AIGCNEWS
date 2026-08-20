<script setup lang="ts">
/* 顶栏右上角固定标识：无论真实登录态如何，始终显示「未登录 / guest」两行
   报纸刊头式小字（绝对定位，不参与居中 flex 排布，与左侧 MastheadMeta 镜像）。
   这是刻意的视觉/品牌标识，不代表真实会话状态——真实认证操作由 Dock 承担。
   因此对辅助技术隐藏（aria-hidden），避免冒充真实会话信息。 */
</script>

<template>
  <div class="masthead-user" aria-hidden="true">
    <span class="masthead-user__status">未登录</span>
    <span class="masthead-user__identity">guest</span>
  </div>
</template>

<style scoped>
.masthead-user {
  position: absolute;
  right: 24px;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 1px;
  font-size: 10px;
  line-height: 1.25;
  letter-spacing: 0.04em;
  color: var(--ink-muted);
  user-select: none;
  pointer-events: none;
  white-space: nowrap;
  text-align: right;
}

.masthead-user__status {
  font-weight: 800;
  color: var(--ink);
}

/* 窄屏隐藏：避免与居中字标/工具组挤压（与 MastheadMeta 同口径） */
@media (max-width: 767px) {
  .masthead-user {
    display: none;
  }
}
</style>
