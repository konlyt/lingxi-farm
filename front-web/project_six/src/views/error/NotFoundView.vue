<script setup lang="ts">
/**
 * 文件说明：404 页面。
 * 访问不存在的路由时展示明确提示，提供返回总览入口。
 */
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <div class="not-found">
    <div class="code">404</div>
    <p class="text">页面不存在或已被移除</p>
    <el-button type="primary" @click="router.push('/dashboard')">返回总览</el-button>
  </div>
</template>

<style scoped>
.not-found {
  height: 60vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
}

.code {
  font-size: 72px;
  font-weight: 700;
  color: #409eff;
  line-height: 1;
}

.text {
  color: #909399;
  font-size: 14px;
  margin: 0 0 8px;
}
</style>
