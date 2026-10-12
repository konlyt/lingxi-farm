<script setup lang="ts">
/**
 * 文件说明：三态包装组件。
 * 统一实现「加载中骨架屏 / 异常重试 / 正常内容插槽」状态规范，供各页面区块复用。
 */
withDefaults(
  defineProps<{
    /** 是否加载中（显示骨架屏） */
    loading?: boolean
    /** 是否加载失败（显示错误提示与重试按钮） */
    failed?: boolean
    /** 骨架屏占位行数 */
    rows?: number
    /** 最小高度（如 '300px'） */
    minHeight?: string
  }>(),
  { loading: false, failed: false, rows: 5, minHeight: '' },
)

/** 事件：点击重试按钮 */
defineEmits<{ (e: 'retry'): void }>()
</script>

<template>
  <div class="state-wrap" :style="minHeight ? { minHeight } : undefined">
    <el-skeleton v-if="loading" :rows="rows" animated />
    <div v-else-if="failed" class="state-failed">
      <el-alert title="数据加载失败，请检查网络或稍后再试" type="error" show-icon :closable="false" />
      <el-button type="primary" plain size="small" @click="$emit('retry')">重试</el-button>
    </div>
    <slot v-else />
  </div>
</template>

<style scoped>
.state-wrap {
  min-height: 60px;
}
</style>
