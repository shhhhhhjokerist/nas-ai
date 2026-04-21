<template>
  <div class="chat-shell">
    <div class="chat-log" ref="logRef">
      <div v-if="messages.length === 0" class="empty-chat">
        直接输入自然语言，例如：
        <div class="hint">我想要在线看星际穿越</div>
        <div class="hint">把下载好的文件移动到电影文件夹</div>
        <div class="hint">返回某个文件夹的信息</div>
      </div>

      <div v-for="(message, index) in messages" :key="index" class="chat-item" :class="message.role">
        <div class="bubble">
          <div class="role">{{ message.role === 'user' ? '你' : '助手' }}</div>
          <div class="text">{{ message.text }}</div>

          <div v-if="resolveFolderTarget(message)" class="quick-actions">
            <button
              type="button"
              class="action-btn browse-btn"
              @click="openInFileManager(message)"
            >
              打开对应文件夹
            </button>
          </div>

          <div v-if="message.data?.urls" class="url-list">
            <button
              v-if="message.data.urls.play_url"
              type="button"
              class="action-btn"
              @click="openPlayModal(message)"
            >
              播放
            </button>
            <button
              v-if="message.data.urls.info_url"
              type="button"
              class="action-btn"
              @click="openInfoByMessage(message)"
            >
              信息弹窗
            </button>
            <a
              v-if="message.data.urls.download_url"
              :href="message.data.urls.download_url"
              target="_blank"
              rel="noreferrer"
            >
              下载文件
            </a>
          </div>

          <div v-if="message.data?.file" class="meta-box">
            <div>名称: {{ message.data.file.name }}</div>
            <div>路径: {{ message.data.file.path }}</div>
            <div v-if="message.data.file.mime_type">MIME: {{ message.data.file.mime_type }}</div>
          </div>

          <div v-if="message.data?.results" class="result-list">
            <div v-for="result in message.data.results" :key="result.id" class="result-item">
              <span>{{ result.is_directory ? '📁' : '📄' }} {{ result.name }}</span>
              <div class="result-actions">
                <button
                  v-if="result.urls?.play_url"
                  type="button"
                  class="action-btn"
                  @click="openPlayModal({ data: { file: result, urls: result.urls } })"
                >
                  播放
                </button>
                <button
                  type="button"
                  class="action-btn"
                  @click="openInfoPopupFor(result)"
                >
                  信息弹窗
                </button>
                <a v-if="result.urls?.download_url" :href="result.urls.download_url" target="_blank" rel="noreferrer">下载</a>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <form class="chat-input" @submit.prevent="sendMessage">
      <textarea
        v-model="draft"
        rows="3"
        placeholder="输入文件操作需求"
        @keydown.enter.exact.prevent="sendMessage"
      />
      <div class="input-actions">
        <button type="button" class="ghost" @click="clearChat">清空</button>
        <button type="submit" class="primary" :disabled="sending || !draft.trim()">
          {{ sending ? '发送中...' : '发送' }}
        </button>
      </div>
    </form>

    <div v-if="notice" class="notice">{{ notice }}</div>

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
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { postJson } from '../services/api'

const router = useRouter()
const threadId = `thread-${Date.now().toString(36)}`
const draft = ref('')
const sending = ref(false)
const notice = ref('')
const messages = ref([])
const logRef = ref(null)
const showVideoModal = ref(false)
const videoUrl = ref('')
const videoTitle = ref('')
const videoRef = ref(null)
const showInfoModal = ref(false)
const infoTitle = ref('文件信息')
const infoContent = ref('')

function scrollToBottom() {
  nextTick(() => {
    const el = logRef.value
    if (el) {
      el.scrollTop = el.scrollHeight
    }
  })
}

function addMessage(role, text, payload = {}) {
  messages.value.push({
    role,
    text,
    action: payload.action || '',
    data: payload.data || null
  })
  scrollToBottom()
}

function resolveFolderTarget(message) {
  if (message?.data?.folder?.id) {
    return { parentId: Number(message.data.folder.id), focusId: Number(message.data.folder.id) }
  }

  if (message?.data?.file) {
    const file = message.data.file
    if (file.is_directory) {
      return { parentId: Number(file.id), focusId: Number(file.id) }
    }
    if (file.parent_id) {
      return { parentId: Number(file.parent_id), focusId: Number(file.id) }
    }
  }

  const results = message?.data?.results
  if (!Array.isArray(results) || results.length === 0) {
    return null
  }

  const parentCounter = new Map()
  for (const result of results) {
    if (result.is_directory) {
      parentCounter.set(Number(result.id), (parentCounter.get(Number(result.id)) || 0) + 10)
      continue
    }
    if (result.parent_id) {
      parentCounter.set(Number(result.parent_id), (parentCounter.get(Number(result.parent_id)) || 0) + 1)
    }
  }

  if (parentCounter.size === 0) {
    return null
  }

  let bestParentId = null
  let bestScore = -1
  for (const [parentId, score] of parentCounter.entries()) {
    if (score > bestScore) {
      bestParentId = parentId
      bestScore = score
    }
  }

  if (!bestParentId) {
    return null
  }
  return { parentId: bestParentId, focusId: null }
}

function openPlayModal(message) {
  const url = message?.data?.urls?.play_url
  if (!url) {
    notice.value = '没有可播放的视频链接'
    return
  }
  videoTitle.value = message?.data?.file?.name || '视频播放'
  videoUrl.value = url
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

function openInfoPopupFor(file) {
  infoTitle.value = `${file?.name || '文件'} 信息`
  infoContent.value = JSON.stringify(file || {}, null, 2)
  showInfoModal.value = true
}

function closeInfoModal() {
  showInfoModal.value = false
  infoTitle.value = '文件信息'
  infoContent.value = ''
}

async function openInfoByMessage(message) {
  const infoUrl = message?.data?.urls?.info_url
  const file = message?.data?.file
  if (file) {
    openInfoPopupFor(file)
    return
  }

  if (!infoUrl) {
    notice.value = '没有可用的信息链接'
    return
  }

  try {
    const response = await fetch(infoUrl)
    if (!response.ok) {
      throw new Error('获取文件信息失败')
    }
    const data = await response.json()
    infoTitle.value = `${data?.name || '文件'} 信息`
    infoContent.value = JSON.stringify(data || {}, null, 2)
    showInfoModal.value = true
  } catch (error) {
    notice.value = error?.message || '获取文件信息失败'
  }
}

function openInFileManager(message) {
  const target = resolveFolderTarget(message)
  if (!target?.parentId) {
    notice.value = '没有可定位的文件夹'
    return
  }

  const query = {
    parent_id: String(target.parentId)
  }
  if (target.focusId) {
    query.focus_id = String(target.focusId)
  }
  router.push({ path: '/files', query })
}

async function sendMessage() {
  const text = draft.value.trim()
  if (!text || sending.value) {
    return
  }

  addMessage('user', text)
  draft.value = ''
  sending.value = true
  notice.value = ''

  try {
    const response = await postJson('/agent/chat', {
      message: text,
      thread_id: threadId
    })

    addMessage('assistant', response.response || '已完成', {
      action: response.action,
      data: response.data
    })
  } catch (error) {
    notice.value = error?.response?.data?.detail || error.message || '发送失败'
    addMessage('assistant', notice.value)
  } finally {
    sending.value = false
  }
}

function clearChat() {
  messages.value = []
  notice.value = ''
}

onMounted(() => {
  addMessage('assistant', '请用自然语言告诉我你要对文件做什么。')
})
</script>

<style scoped>
.chat-shell {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 70vh;
}

.chat-log {
  flex: 1;
  min-height: 420px;
  max-height: 70vh;
  overflow: auto;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.chat-item {
  display: flex;
}

.chat-item.user {
  justify-content: flex-end;
}

.bubble {
  max-width: min(760px, 88%);
  border-radius: 18px;
  padding: 14px 16px;
  background: #f3f4f6;
  border: 1px solid #e5e7eb;
}

.chat-item.user .bubble {
  background: #111827;
  color: #fff;
  border-color: #111827;
}

.role {
  font-size: 12px;
  opacity: 0.7;
  margin-bottom: 8px;
}

.text {
  white-space: pre-wrap;
  line-height: 1.6;
}

.url-list,
.result-list,
.meta-box {
  margin-top: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.quick-actions {
  margin-top: 10px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.browse-btn {
  background: #111827;
  color: #fff;
  border-color: #111827;
}

.url-list a,
.result-item a {
  display: inline-flex;
  padding: 6px 10px;
  border-radius: 999px;
  background: #fff;
  color: #0f172a;
  text-decoration: none;
  border: 1px solid #d1d5db;
}

.result-list {
  flex-direction: column;
}

.result-item {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
  padding: 8px 10px;
  border-radius: 12px;
  background: #fff;
  border: 1px solid #e5e7eb;
}

.result-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.action-btn {
  display: inline-flex;
  padding: 6px 10px;
  border-radius: 999px;
  background: #fff;
  color: #0f172a;
  text-decoration: none;
  border: 1px solid #d1d5db;
  cursor: pointer;
}

.meta-box {
  flex-direction: column;
  color: inherit;
  font-size: 13px;
  opacity: 0.9;
}

.empty-chat {
  padding: 24px;
  border-radius: 18px;
  border: 1px dashed #d1d5db;
  background: #fafafa;
  color: #4b5563;
}

.hint {
  margin-top: 8px;
  font-weight: 700;
  color: #111827;
}

.chat-input {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

textarea {
  width: 100%;
  resize: vertical;
  border-radius: 16px;
  border: 1px solid #d1d5db;
  padding: 14px;
  font-family: inherit;
  font-size: 15px;
  outline: none;
}

textarea:focus {
  border-color: #111827;
}

.input-actions {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

button {
  border: 1px solid #d1d5db;
  background: #fff;
  color: #111827;
  border-radius: 12px;
  padding: 10px 14px;
  cursor: pointer;
}

button.primary {
  background: #111827;
  color: #fff;
  border-color: #111827;
}

button.ghost {
  background: #f9fafb;
}

button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.notice {
  padding: 12px 14px;
  border-radius: 14px;
  background: #fef2f2;
  color: #b91c1c;
  border: 1px solid #fecaca;
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
</style>
