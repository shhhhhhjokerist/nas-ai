<template>
  <div class="app-shell">
    <header class="topbar">
      <div class="brand">
        <div class="brand-mark">NA</div>
        <div>
          <div class="brand-title">NAS AI</div>
          <div class="brand-subtitle">文件浏览 + Chatbot 控制台</div>
        </div>
      </div>

      <nav class="nav-links">
        <router-link to="/files">文件管理器</router-link>
        <router-link to="/chat">Chatbot</router-link>
      </nav>
    </header>

    <main class="main-area">
      <router-view />
    </main>
  </div>
</template>

<script>
export default {
  name: 'App'
}
</script>

<style>
html,
body,
#app {
  margin: 0;
  min-height: 100%;
}

body {
  font-family: Inter, "Segoe UI", Arial, sans-serif;
  background:
    radial-gradient(circle at top left, rgba(59, 130, 246, 0.10), transparent 28%),
    radial-gradient(circle at top right, rgba(16, 185, 129, 0.10), transparent 24%),
    #f3f4f6;
  color: #111827;
}

.app-shell {
  min-height: 100vh;
}

.topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 18px 24px;
  background: rgba(255, 255, 255, 0.8);
  backdrop-filter: blur(14px);
  border-bottom: 1px solid rgba(229, 231, 235, 0.9);
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-mark {
  width: 42px;
  height: 42px;
  border-radius: 14px;
  display: grid;
  place-items: center;
  background: #111827;
  color: #fff;
  font-weight: 800;
}

.brand-title {
  font-size: 16px;
  font-weight: 800;
}

.brand-subtitle {
  font-size: 12px;
  color: #6b7280;
}

.nav-links {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.nav-links a {
  text-decoration: none;
  color: #111827;
  border: 1px solid #d1d5db;
  padding: 9px 14px;
  border-radius: 999px;
  background: #fff;
}

.nav-links a.router-link-active {
  background: #111827;
  color: #fff;
  border-color: #111827;
}

.main-area {
  padding: 24px;
}
</style>