<script setup lang="ts">
/**
 * 文件说明：监测大屏科技风面板容器组件。
 * 提供切角边框、四角亮色装饰与标题栏（含右侧扩展插槽），统一大屏各面板视觉规范。
 */
defineProps<{
  /** 面板标题 */
  title: string
}>();

/** 插槽：default 面板内容；extra 标题栏右侧扩展区（如图例、时间） */
</script>

<template>
  <div class="tech-panel">
    <span class="corner tl" />
    <span class="corner tr" />
    <span class="corner bl" />
    <span class="corner br" />
    <div class="panel-head">
      <span class="head-tick" />
      <span class="head-title">{{ title }}</span>
      <div class="head-extra">
        <slot name="extra" />
      </div>
    </div>
    <div class="panel-body">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.tech-panel {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 0;
  background:
    linear-gradient(180deg, rgba(20, 48, 82, 0.55) 0%, rgba(10, 26, 47, 0.92) 100%);
  border: 1px solid rgba(78, 166, 255, 0.22);
  clip-path: polygon(0 10px, 10px 0, calc(100% - 10px) 0, 100% 10px, 100% calc(100% - 10px), calc(100% - 10px) 100%, 10px 100%, 0 calc(100% - 10px));
}

/* 四角亮色装饰 */
.corner {
  position: absolute;
  width: 12px;
  height: 12px;
  z-index: 2;
}

.corner.tl {
  top: 0;
  left: 0;
  border-top: 2px solid #35d0ba;
  border-left: 2px solid #35d0ba;
}

.corner.tr {
  top: 0;
  right: 0;
  border-top: 2px solid #35d0ba;
  border-right: 2px solid #35d0ba;
}

.corner.bl {
  bottom: 0;
  left: 0;
  border-bottom: 2px solid #35d0ba;
  border-left: 2px solid #35d0ba;
}

.corner.br {
  bottom: 0;
  right: 0;
  border-bottom: 2px solid #35d0ba;
  border-right: 2px solid #35d0ba;
}

.panel-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px 8px;
  border-bottom: 1px solid rgba(78, 166, 255, 0.15);
}

.head-tick {
  width: 4px;
  height: 14px;
  background: #35d0ba;
  box-shadow: 0 0 6px rgba(53, 208, 186, 0.8);
}

.head-title {
  color: #d7ecff;
  font-size: 17px;
  font-weight: 600;
  letter-spacing: 2px;
}

.head-extra {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
}

.panel-body {
  flex: 1;
  min-height: 0;
  padding: 10px 14px 12px;
  display: flex;
  flex-direction: column;
}

/* 深色背景下的骨架与空态适配 */
.tech-panel :deep(.el-skeleton__item) {
  background: rgba(255, 255, 255, 0.08);
}

.tech-panel :deep(.el-empty__description p) {
  color: #6d89a8;
}
</style>
