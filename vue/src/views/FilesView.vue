<template>
  <section class="page">
    <header class="page-header">
      <h1>文件管理器</h1>
      <p>浏览本地文件夹，直接执行下载、修改、复制、移动和播放。</p>
    </header>

    <FileBrowser />
  </section>
</template>

<script setup>
import FileBrowser from '../components/FileBrowser.vue'
</script>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.page-header h1 {
  margin: 0;
  font-size: 30px;
  color: #111827;
}

.page-header p {
  margin: 8px 0 0;
  color: #4b5563;
}
</style>
