<template>
  <div class="browser-shell">
    <div class="toolbar">
      <div class="nav-group">
        <button class="ghost" @click="goRoot">根目录</button>
        <button class="ghost" @click="goBack" :disabled="!canGoBack">上一级</button>
        <button class="ghost" @click="refresh">刷新</button>
        <span class="path">{{ currentPath }}</span>
      </div>

      <div class="search-group">
        <input
          v-model="searchText"
          class="search-input"
          type="text"
          placeholder="搜索文件或文件夹"
          @keyup.enter="search"
        />
        <button class="primary" @click="search">搜索</button>
        <button v-if="searchMode" class="ghost" @click="exitSearch">返回浏览</button>
      </div>
    </div>

    <div class="status-row">
      <span>{{ loading ? '加载中...' : message }}</span>
      <span v-if="searchMode" class="badge">搜索结果</span>
    </div>

    <div class="content-grid">
      <section class="list-panel">
        <div class="section-title">文件与文件夹</div>
        <div class="list-head">
          <span>名称</span>
          <span>类型</span>
          <span>大小</span>
          <span>操作</span>
        </div>

        <div v-if="!loading && items.length === 0" class="empty-state">
          当前目录没有内容
        </div>

        <div
          v-for="item in items"
          :key="`${item.is_directory}-${item.id}`"
          class="list-row"
          :class="{ selected: selectedItem && selectedItem.id === item.id && selectedItem.is_directory === item.is_directory }"
          @click="selectItem(item)"
        >
          <div class="name-cell">
            <div class="icon">{{ item.is_directory ? '📁' : iconFor(item) }}</div>
            <div class="name-block">
              <button
                class="name-link"
                @click.stop="item.is_directory ? openFolder(item) : previewFile(item)"
              >
                {{ item.name }}
              </button>
              <small>{{ item.path }}</small>
            </div>
          </div>
          <div>{{ item.is_directory ? '文件夹' : typeLabel(item) }}</div>
          <div>{{ item.is_directory ? '-' : formatSize(item.size) }}</div>
          <div class="actions">
            <button v-if="item.is_directory" @click.stop="openFolder(item)">打开</button>
            <button v-else @click.stop="previewFile(item)">播放</button>
            <button v-if="!item.is_directory" @click.stop="downloadItem(item)">下载</button>
            <button @click.stop="showInfo(item)">信息</button>
            <button @click.stop="renameItem(item)">修改</button>
            <button @click.stop="moveItem(item)">移动</button>
            <button @click.stop="copyItem(item)">复制</button>
            <button class="danger" @click.stop="deleteItem(item)">删除</button>
          </div>
        </div>
      </section>

      <aside class="detail-panel">
        <div class="section-title">详情</div>
        <div v-if="selectedItem" class="detail-card">
          <div class="detail-name">{{ selectedItem.name }}</div>
          <div class="detail-line">ID: {{ selectedItem.id }}</div>
          <div class="detail-line">路径: {{ selectedItem.path }}</div>
          <div class="detail-line">类型: {{ selectedItem.is_directory ? '文件夹' : typeLabel(selectedItem) }}</div>
          <div class="detail-line" v-if="!selectedItem.is_directory">大小: {{ formatSize(selectedItem.size) }}</div>
          <div class="detail-line" v-if="selectedItem.mime_type">MIME: {{ selectedItem.mime_type }}</div>

          <div class="detail-actions" v-if="!selectedItem.is_directory">
            <button @click="downloadItem(selectedItem)">下载</button>
            <button @click="previewFile(selectedItem)">播放</button>
          </div>

          <div v-if="selectedItemUrls" class="url-box">
            <a v-for="(url, key) in selectedItemUrls" :key="key" :href="url" target="_blank" rel="noreferrer">
              {{ key }}
            </a>
          </div>
        </div>
        <div v-else class="empty-state small">选择一个文件或文件夹查看详情</div>

      </aside>
    </div>

    <div v-if="showVideoModal" class="modal-mask" @click.self="closeVideoModal">
      <div class="modal-card">
        <div class="modal-head">
          <strong>{{ videoTitle || '视频播放' }}</strong>
          <button type="button" class="ghost" @click="closeVideoModal">关闭</button>
        </div>
        <video
          ref="videoRef"
          class="modal-video"
          :src="videoUrl"
          controls
          autoplay
          playsinline
        ></video>
      </div>
    </div>

    <div v-if="showInfoModal" class="modal-mask" @click.self="closeInfoModal">
      <div class="modal-card info-card">
        <div class="modal-head">
          <strong>{{ infoTitle }}</strong>
          <button type="button" class="ghost" @click="closeInfoModal">关闭</button>
        </div>
        <pre class="modal-info">{{ infoContent }}</pre>
      </div>
    </div>

    <div v-if="notice" class="notice">{{ notice }}</div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { deleteJson, getJson, postJson, putJson } from '../services/api'

const route = useRoute()
const currentFolder = ref(null)
const historyStack = ref([])
const folders = ref([])
const files = ref([])
const searchText = ref('')
const searchMode = ref(false)
const searchResults = ref([])
const loading = ref(false)
const message = ref('就绪')
const notice = ref('')
const selectedItem = ref(null)
const selectedItemUrls = ref(null)
const showVideoModal = ref(false)
const videoUrl = ref('')
const videoTitle = ref('')
const videoRef = ref(null)
const showInfoModal = ref(false)
const infoTitle = ref('文件信息')
const infoContent = ref('')

const currentPath = computed(() => {
  if (!currentFolder.value) {
    return '/'
  }
  return currentFolder.value.path || currentFolder.value.name || '/'
})

const canGoBack = computed(() => historyStack.value.length > 0)
const items = computed(() => {
  if (searchMode.value) {
    return searchResults.value
  }
  return [...folders.value, ...files.value]
})

function iconFor(item) {
  const type = (item.file_type || '').toLowerCase()
  if (item.mime_type && item.mime_type.startsWith('video')) return '🎬'
  if (['pdf'].includes(type)) return '📕'
  if (['txt', 'md', 'log'].includes(type)) return '📄'
  if (['jpg', 'jpeg', 'png', 'gif', 'webp'].includes(type)) return '🖼️'
  return '📄'
}

function typeLabel(item) {
  if (item.mime_type) return item.mime_type
  if (item.file_type) return item.file_type
  return '文件'
}

function formatSize(size) {
  const value = Number(size || 0)
  if (!value) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let index = 0
  let current = value
  while (current >= 1024 && index < units.length - 1) {
    current /= 1024
    index += 1
  }
  return `${current.toFixed(current >= 10 || index === 0 ? 0 : 1)} ${units[index]}`
}

function setNotice(text) {
  notice.value = text
  window.clearTimeout(setNotice.timer)
  setNotice.timer = window.setTimeout(() => {
    notice.value = ''
  }, 2500)
}

async function loadFolder(parentId = null, folder = null) {
  loading.value = true
  message.value = '正在加载目录...'
  try {
    const params = {}
    if (parentId) {
      params.parent_id = parentId
    }
    const data = await getJson('/media/browse', params)
    folders.value = data.folders || []
    files.value = data.files || []
    currentFolder.value = folder ? { ...folder, path: data.current_path || folder.path } : null
    selectedItem.value = currentFolder.value || null
    selectedItemUrls.value = currentFolder.value ? buildUrls(currentFolder.value) : null
    searchMode.value = false
    searchResults.value = []
    message.value = data.current_path || '已加载'
  } catch (error) {
    message.value = '加载失败'
    setNotice(error?.response?.data?.detail || error.message || '加载目录失败')
  } finally {
    loading.value = false
  }
}

function buildUrls(item) {
  const urls = {
    info_url: `/media/info?id=${item.id}`
  }
  if (item.is_directory) {
    urls.browse_url = `/media/browse?parent_id=${item.id}`
  } else {
    urls.download_url = `/media/download/${item.id}`
    if ((item.mime_type || '').startsWith('video') || ['mp4', 'mkv', 'avi', 'mov', 'webm', 'm4v'].includes((item.file_type || '').toLowerCase())) {
      urls.play_url = `/media/play/${item.id}`
    }
  }
  return urls
}

function selectItem(item) {
  selectedItem.value = item
  selectedItemUrls.value = buildUrls(item)
}

function parseQueryId(value) {
  if (value === undefined || value === null || value === '') {
    return null
  }
  const parsed = Number(value)
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return null
  }
  return parsed
}

async function refresh() {
  if (searchMode.value) {
    await search()
    return
  }
  await loadFolder(currentFolder.value ? currentFolder.value.id : null, currentFolder.value)
}

async function openFolder(folder) {
  // Keep navigation history even when current level is root (null).
  historyStack.value.push(currentFolder.value)
  await loadFolder(folder.id, folder)
}

async function goBack() {
  const previous = historyStack.value.pop()
  if (!previous) {
    await goRoot()
    return
  }
  await loadFolder(previous.id, previous)
}

async function goRoot() {
  historyStack.value = []
  await loadFolder(null, null)
}

async function search() {
  const keyword = searchText.value.trim()
  if (!keyword) {
    setNotice('请输入搜索内容')
    return
  }
  loading.value = true
  message.value = '正在搜索...'
  try {
    const data = await getJson('/media/search', { q: keyword, limit: 50 })
    searchMode.value = true
    folders.value = []
    files.value = []
    searchResults.value = (data.results || []).map((item) => ({
      ...item,
      urls: buildUrls(item)
    }))
    selectedItem.value = null
    selectedItemUrls.value = null
    message.value = `找到 ${data.count || searchResults.value.length} 项`
  } catch (error) {
    setNotice(error?.response?.data?.detail || error.message || '搜索失败')
    message.value = '搜索失败'
  } finally {
    loading.value = false
  }
}

async function exitSearch() {
  searchMode.value = false
  await refresh()
}

async function showInfo(item) {
  try {
    const data = await getJson('/media/info', item.is_directory ? { id: item.id } : { id: item.id })
    selectedItem.value = data
    selectedItemUrls.value = buildUrls(data)
    infoTitle.value = `${data.name || item.name} 信息`
    infoContent.value = JSON.stringify(data || {}, null, 2)
    showInfoModal.value = true
    setNotice('已刷新详情')
  } catch (error) {
    setNotice(error?.response?.data?.detail || error.message || '获取信息失败')
  }
}

function downloadItem(item) {
  window.open(`/media/download/${item.id}`, '_blank', 'noreferrer')
}

function previewFile(item) {
  if (item.is_directory) {
    openFolder(item)
    return
  }
  selectedItem.value = item
  selectedItemUrls.value = buildUrls(item)
  videoTitle.value = item.name || '视频播放'
  videoUrl.value = `/media/play/${item.id}`
  showVideoModal.value = true
}

function closeVideoModal() {
  showVideoModal.value = false
  if (videoRef.value) {
    try {
      videoRef.value.pause()
      videoRef.value.removeAttribute('src')
      videoRef.value.load()
    } catch (e) {
      // no-op
    }
  }
  videoUrl.value = ''
  videoTitle.value = ''
}

function closeInfoModal() {
  showInfoModal.value = false
  infoTitle.value = '文件信息'
  infoContent.value = ''
}

async function renameItem(item) {
  const newName = window.prompt('请输入新的名称', item.name)
  if (!newName || newName.trim() === item.name) {
    return
  }
  try {
    await putJson('/media/rename', { id: item.id, new_name: newName.trim() })
    setNotice('修改成功')
    await refresh()
  } catch (error) {
    setNotice(error?.response?.data?.detail || error.message || '修改失败')
  }
}

async function moveItem(item) {
  const destinationId = window.prompt('请输入目标文件夹 ID')
  if (!destinationId) {
    return
  }
  try {
    await postJson('/media/move', { id: item.id, destination_id: Number(destinationId) })
    setNotice('移动成功')
    await refresh()
  } catch (error) {
    setNotice(error?.response?.data?.detail || error.message || '移动失败')
  }
}

async function copyItem(item) {
  const destinationId = window.prompt('请输入目标文件夹 ID')
  if (!destinationId) {
    return
  }
  const newName = window.prompt('如需重命名副本可输入新名称，留空则保持原名', item.name)
  try {
    await postJson('/media/copy', {
      id: item.id,
      destination_id: Number(destinationId),
      new_name: newName && newName.trim() ? newName.trim() : null
    })
    setNotice('复制成功')
    await refresh()
  } catch (error) {
    setNotice(error?.response?.data?.detail || error.message || '复制失败')
  }
}

async function deleteItem(item) {
  const confirmed = window.confirm(`确定删除 ${item.name} 吗？`)
  if (!confirmed) {
    return
  }
  try {
    await deleteJson('/media/delete', { id: item.id, permanent: true })
    setNotice('删除成功')
    await refresh()
  } catch (error) {
    setNotice(error?.response?.data?.detail || error.message || '删除失败')
  }
}

async function locateByRouteQuery() {
  const parentId = parseQueryId(route.query.parent_id)
  const focusId = parseQueryId(route.query.focus_id)

  if (!parentId) {
    await loadFolder(null, null)
    return
  }

  historyStack.value = [null]
  await loadFolder(parentId, { id: parentId, path: `/${parentId}` })

  if (focusId) {
    const match = [...folders.value, ...files.value].find((item) => item.id === focusId)
    if (match) {
      selectItem(match)
    }
  }
}

onMounted(() => {
  locateByRouteQuery()
})

watch(
  () => [route.query.parent_id, route.query.focus_id],
  () => {
    locateByRouteQuery()
  }
)
</script>

<style scoped>
.browser-shell {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.toolbar,
.status-row,
.list-head,
.list-row,
.detail-line,
.detail-actions,
.actions,
.nav-group,
.search-group,
.url-box {
  display: flex;
  align-items: center;
}

.toolbar,
.status-row {
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.nav-group,
.search-group,
.actions,
.detail-actions,
.url-box {
  gap: 8px;
  flex-wrap: wrap;
}

.path {
  padding: 8px 12px;
  border-radius: 999px;
  background: #eef2ff;
  color: #3730a3;
  font-size: 13px;
}

.search-input {
  min-width: 240px;
  padding: 10px 12px;
  border: 1px solid #d1d5db;
  border-radius: 10px;
  outline: none;
}

button {
  border: 1px solid #d1d5db;
  background: #fff;
  color: #111827;
  border-radius: 10px;
  padding: 9px 12px;
  cursor: pointer;
}

button:hover {
  border-color: #9ca3af;
}

button.primary {
  background: #111827;
  color: #fff;
  border-color: #111827;
}

button.ghost {
  background: #f9fafb;
}

button.danger {
  color: #b91c1c;
}

button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.badge {
  padding: 6px 10px;
  border-radius: 999px;
  background: #ecfeff;
  color: #0f766e;
  font-size: 12px;
}

.content-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.8fr) minmax(280px, 0.85fr);
  gap: 16px;
}

.list-panel,
.detail-panel {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 18px;
  padding: 16px;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.05);
}

.section-title {
  font-size: 14px;
  font-weight: 700;
  margin-bottom: 12px;
  color: #111827;
}

.section-title.compact {
  margin-bottom: 8px;
}

.list-head,
.list-row {
  display: grid;
  grid-template-columns: 2.3fr 1fr 0.8fr 2fr;
  gap: 10px;
  align-items: center;
}

.list-head {
  padding: 10px 12px;
  font-size: 12px;
  color: #6b7280;
  border-bottom: 1px solid #e5e7eb;
}

.list-row {
  padding: 12px;
  border-bottom: 1px solid #f3f4f6;
  cursor: pointer;
}

.list-row:hover,
.list-row.selected {
  background: #f8fafc;
}

.name-cell {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.icon {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  background: #f3f4f6;
  flex: 0 0 auto;
}

.name-block {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.name-link {
  border: 0;
  padding: 0;
  background: transparent;
  text-align: left;
  font-weight: 700;
  color: #111827;
}

.name-block small {
  color: #6b7280;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.actions button,
.detail-actions button {
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 12px;
}

.empty-state {
  padding: 24px 12px;
  text-align: center;
  color: #6b7280;
}

.empty-state.small {
  padding: 16px 0;
}

.detail-card {
  background: #f9fafb;
  border-radius: 16px;
  padding: 14px;
  margin-bottom: 14px;
}

.detail-name {
  font-size: 18px;
  font-weight: 800;
  margin-bottom: 8px;
  color: #111827;
}

.detail-line {
  gap: 8px;
  font-size: 13px;
  margin-bottom: 6px;
  color: #374151;
  word-break: break-all;
}

.url-box {
  margin-top: 12px;
}

.url-box a {
  display: inline-flex;
  padding: 6px 10px;
  border-radius: 999px;
  background: #e0f2fe;
  color: #075985;
  text-decoration: none;
  font-size: 12px;
}

.notice {
  padding: 12px 14px;
  border-radius: 14px;
  background: #eff6ff;
  color: #1d4ed8;
  border: 1px solid #bfdbfe;
}

.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(2, 6, 23, 0.72);
  display: grid;
  place-items: center;
  z-index: 1000;
  padding: 16px;
}

.modal-card {
  width: min(960px, 96vw);
  background: #0b1220;
  border: 1px solid rgba(148, 163, 184, 0.25);
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 20px 50px rgba(2, 6, 23, 0.45);
}

.modal-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  color: #e2e8f0;
  background: #111827;
  padding: 10px 14px;
}

.modal-video {
  display: block;
  width: 100%;
  height: min(72vh, 620px);
  background: #000;
}

.info-card {
  background: #f8fafc;
}

.info-card .modal-head {
  color: #0f172a;
  background: #fff;
  border-bottom: 1px solid #e2e8f0;
}

.modal-info {
  margin: 0;
  padding: 14px;
  box-sizing: border-box;
  width: 100%;
  height: min(72vh, 620px);
  overflow: auto;
  font: 13px/1.6 Consolas, "Courier New", monospace;
  white-space: pre-wrap;
  word-break: break-word;
  color: #0f172a;
  background: #f8fafc;
}

@media (max-width: 1100px) {
  .content-grid {
    grid-template-columns: 1fr;
  }

  .list-head,
  .list-row {
    grid-template-columns: 1.7fr 1fr 0.8fr 1.8fr;
  }
}

@media (max-width: 720px) {
  .list-head {
    display: none;
  }

  .list-row {
    grid-template-columns: 1fr;
    gap: 10px;
  }

  .actions {
    justify-content: flex-start;
  }
}
</style>
