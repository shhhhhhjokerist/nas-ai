<template>
  <section class="page">
    <header class="page-header">
      <h1>Chatbot</h1>
      <p>输入自然语言，直接让后端去定位、下载、播放、移动或复制文件。</p>
    </header>

    <ChatPanel />
  </section>
</template>

<script setup>
import ChatPanel from '../components/ChatPanel.vue'
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
