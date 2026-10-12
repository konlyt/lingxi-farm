<script setup lang="ts">
/**
 * 文件说明：知识问答页（15）。
 * 对话流（用户右侧/AI 左侧卡片）、文字输入 + 语音按钮（Web Speech API，不支持则禁用提示）、
 * 播报开关（speechSynthesis 朗读 AI 回复）、新会话示例问题点击即问、历史会话侧栏。
 */
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import MarkdownIt from 'markdown-it'
import { askQuestion, createChatSession, listChatMessages, listChatSessions } from '@/api/chat'
import { formatDateTime } from '@/utils/format'
import type { ChatMessage, ChatSession } from '@/types/farm'

/**
 * Markdown 渲染器（AI 回复含加粗/列表等语法）。
 * html:false 时 markdown-it 默认转义内嵌 HTML，具备基础 XSS 防护。
 */
const md = new MarkdownIt({ breaks: true, linkify: false, html: false })

/**
 * 将 AI 回复的 Markdown 文本渲染为 HTML。
 * @param content 原始文本
 * @returns 渲染后的 HTML 字符串
 */
function renderMarkdown(content: string): string {
  return md.render(content ?? '')
}

/** 语音识别结果事件最小结构 */
interface SpeechEvent {
  /** 识别结果集合 */
  results: ArrayLike<ArrayLike<{ transcript: string }>>
}

/** 浏览器语音识别器最小接口 */
interface SpeechRecognizer {
  /** 识别语言 */
  lang: string
  /** 是否返回中间结果 */
  interimResults: boolean
  /** 是否连续识别 */
  continuous: boolean
  /** 结果回调 */
  onresult: ((event: SpeechEvent) => void) | null
  /** 错误回调 */
  onerror: (() => void) | null
  /** 结束回调 */
  onend: (() => void) | null
  /** 开始识别 */
  start(): void
  /** 停止识别 */
  stop(): void
}

/** 语音识别器构造类型 */
type SpeechRecognizerCtor = new () => SpeechRecognizer

/** 新会话示例问题 */
const sampleQuestions = ['番茄早疫病怎么防治？', '黄瓜霜霉病用什么药？', '大棚湿度太高如何降湿？']

/** 会话列表 */
const sessions = ref<ChatSession[]>([])
/** 当前会话 ID */
const activeSessionId = ref<number | null>(null)
/** 消息列表 */
const messages = ref<ChatMessage[]>([])
/** 输入内容 */
const inputText = ref('')
/** AI 回复加载中 */
const sending = ref(false)
/** 会话列表加载中 */
const sessionsLoading = ref(false)

/** 消息滚动容器引用 */
const messageBoxRef = ref<HTMLDivElement | null>(null)

/** 播报开关 */
const ttsEnabled = ref(false)

/** 语音录制中 */
const recording = ref(false)
/** 语音识别器实例 */
let recognizer: SpeechRecognizer | null = null

/** 浏览器是否支持语音识别 */
const speechSupported = computed(() => {
  const w = window as unknown as { SpeechRecognition?: SpeechRecognizerCtor; webkitSpeechRecognition?: SpeechRecognizerCtor }
  return typeof w.SpeechRecognition === 'function' || typeof w.webkitSpeechRecognition === 'function'
})

/**
 * 加载会话列表。
 */
async function loadSessions(): Promise<void> {
  sessionsLoading.value = true
  try {
    sessions.value = await listChatSessions()
  } catch {
    /* 会话列表加载失败不阻塞页面 */
  } finally {
    sessionsLoading.value = false
  }
}

/**
 * 滚动消息区到底部。
 */
async function scrollToBottom(): Promise<void> {
  await nextTick()
  if (messageBoxRef.value) {
    messageBoxRef.value.scrollTop = messageBoxRef.value.scrollHeight
  }
}

/**
 * 切换会话并加载消息历史。
 * @param sessionId 会话 ID
 */
async function selectSession(sessionId: number): Promise<void> {
  activeSessionId.value = sessionId
  sending.value = true
  try {
    messages.value = await listChatMessages(sessionId)
    await scrollToBottom()
  } catch {
    messages.value = []
  } finally {
    sending.value = false
  }
}

/**
 * 新建会话。
 * @throws 请求失败时提示
 */
async function handleNewSession(): Promise<void> {
  try {
    const session = await createChatSession()
    activeSessionId.value = session.id
    messages.value = []
    await loadSessions()
  } catch {
    /* 拦截器已提示 */
  }
}

/**
 * 使用 speechSynthesis 朗读 AI 回复。
 * @param text 朗读文本
 */
function speak(text: string): void {
  if (!ttsEnabled.value || !('speechSynthesis' in window)) return
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = 'zh-CN'
  window.speechSynthesis.speak(utterance)
}

/**
 * 发送提问（无会话时自动创建）。
 * @param text 问题文本
 * @throws 空问题或接口失败时提示
 */
async function sendQuestion(text: string): Promise<void> {
  const question = text.trim()
  if (question === '' || sending.value) return
  if (!activeSessionId.value) {
    const session = await createChatSession()
    activeSessionId.value = session.id
    await loadSessions()
  }
  const sessionId = activeSessionId.value
  messages.value.push({ role: 'user', content: question, created_at: new Date().toISOString() })
  inputText.value = ''
  sending.value = true
  await scrollToBottom()
  try {
    const res = await askQuestion(sessionId, question)
    messages.value.push({
      role: 'assistant',
      content: res.answer,
      created_at: new Date().toISOString(),
      low_confidence: res.low_confidence,
    })
    speak(res.answer)
    await scrollToBottom()
  } catch {
    ElMessage.error('回答生成失败，请稍后重试')
  } finally {
    sending.value = false
    await scrollToBottom()
  }
}

/**
 * 点击示例问题立即提问。
 * @param question 示例问题
 */
function askSample(question: string): void {
  void sendQuestion(question)
}

/**
 * 开始/停止语音识别（按住说话简化为点击切换）。
 * @throws 浏览器不支持或识别失败时提示
 */
function toggleRecording(): void {
  if (recording.value) {
    recognizer?.stop()
    return
  }
  const w = window as unknown as { SpeechRecognition?: SpeechRecognizerCtor; webkitSpeechRecognition?: SpeechRecognizerCtor }
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition
  if (!Ctor) {
    ElMessage.warning('当前浏览器不支持语音识别，请使用文字输入')
    return
  }
  recognizer = new Ctor()
  recognizer.lang = 'zh-CN'
  recognizer.interimResults = false
  recognizer.continuous = false
  recognizer.onresult = (event) => {
    const transcript = event.results[0]?.[0]?.transcript ?? ''
    if (transcript) {
      inputText.value = transcript
      ElMessage.success('语音已转为文字，可编辑后发送')
    }
  }
  recognizer.onerror = () => {
    ElMessage.error('语音识别失败，请改用文字输入')
    recording.value = false
  }
  recognizer.onend = () => {
    recording.value = false
  }
  recording.value = true
  recognizer.start()
}

/**
 * 会话标题展示（缺省用「会话 N」）。
 * @param session 会话
 * @returns 标题文本
 */
function sessionTitle(session: ChatSession): string {
  return session.title && session.title !== '' ? session.title : `会话 ${session.id}`
}

onMounted(() => {
  void loadSessions()
})
</script>

<template>
  <div class="page chat-page">
    <!-- 历史会话侧栏 -->
    <div class="page-card session-panel">
      <el-button type="primary" class="new-session-btn" @click="handleNewSession">新会话</el-button>
      <div v-loading="sessionsLoading" class="session-list">
        <div
          v-for="s in sessions"
          :key="s.id"
          class="session-item"
          :class="{ active: s.id === activeSessionId }"
          @click="selectSession(s.id)"
        >
          {{ sessionTitle(s) }}
        </div>
        <div v-if="sessions.length === 0 && !sessionsLoading" class="text-muted" style="text-align: center; padding: 12px 0">
          暂无历史会话
        </div>
      </div>
    </div>

    <!-- 对话区 -->
    <div class="page-card chat-panel">
      <div ref="messageBoxRef" class="message-box">
        <!-- 新会话示例问题 -->
        <div v-if="messages.length === 0" class="sample-zone">
          <p class="sample-title">你好，我是农场智能问答助手，可以试试：</p>
          <div
            v-for="q in sampleQuestions"
            :key="q"
            class="sample-item"
            @click="askSample(q)"
          >
            {{ q }}
          </div>
        </div>

        <!-- 消息流 -->
        <div v-for="(msg, idx) in messages" :key="idx" class="msg-row" :class="msg.role === 'user' ? 'right' : 'left'">
          <div class="bubble" :class="msg.role">
            <!-- AI 回复经 Markdown 渲染；用户消息保持纯文本展示 -->
            <div v-if="msg.role === 'assistant'" class="msg-content md-body" v-html="renderMarkdown(msg.content)" />
            <div v-else class="msg-content">{{ msg.content }}</div>
            <el-tag v-if="msg.low_confidence" size="small" type="warning" class="low-tag">
              置信度不足，建议咨询农技专家
            </el-tag>
            <div class="msg-time text-muted">{{ formatDateTime(msg.created_at) }}</div>
          </div>
        </div>

        <!-- 打字机加载态 -->
        <div v-if="sending && messages.length > 0" class="msg-row left">
          <div class="bubble assistant typing">AI 正在思考…</div>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="input-zone">
        <el-switch v-model="ttsEnabled" active-text="语音播报" class="tts-switch" />
        <el-input
          v-model="inputText"
          type="textarea"
          :rows="2"
          placeholder="输入问题，如：番茄早疫病怎么防治？"
          @keydown.enter.exact.prevent="sendQuestion(inputText)"
        />
        <div class="input-actions">
          <el-tooltip :content="speechSupported ? '点击说话' : '当前浏览器不支持语音识别'" :disabled="speechSupported">
            <span>
              <el-button :type="recording ? 'danger' : 'default'" :disabled="!speechSupported" circle @click="toggleRecording">
                <el-icon><Microphone /></el-icon>
              </el-button>
            </span>
          </el-tooltip>
          <el-button type="primary" :loading="sending" :disabled="inputText.trim() === ''" @click="sendQuestion(inputText)">
            发送
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-page {
  display: flex;
  gap: 16px;
  align-items: stretch;
}

.session-panel {
  width: 220px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
}

.new-session-btn {
  width: 100%;
  margin-bottom: 10px;
}

.session-list {
  flex: 1;
  overflow-y: auto;
}

.session-item {
  padding: 10px;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-item:hover {
  background: #f5f7fa;
}

.session-item.active {
  background: #ecf5ff;
  color: #409eff;
}

.chat-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: calc(100vh - 140px);
  max-width: 900px;
}

.message-box {
  flex: 1;
  overflow-y: auto;
  padding: 10px 4px;
}

.sample-zone {
  text-align: center;
  padding: 30px 0;
}

.sample-title {
  color: #606266;
  font-size: 14px;
}

.sample-item {
  display: inline-block;
  margin: 6px;
  padding: 8px 16px;
  border: 1px solid #dcdfe6;
  border-radius: 18px;
  font-size: 13px;
  cursor: pointer;
  color: #409eff;
}

.sample-item:hover {
  background: #ecf5ff;
}

.msg-row {
  display: flex;
  margin-bottom: 12px;
}

.msg-row.right {
  justify-content: flex-end;
}

.msg-row.left {
  justify-content: flex-start;
}

.bubble {
  max-width: 72%;
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 14px;
  line-height: 1.6;
}

.bubble.user {
  background: #409eff;
  color: #fff;
}

.bubble.assistant {
  background: #f4f4f5;
  color: #303133;
}

.bubble.typing {
  color: #909399;
}

/* AI 回复 Markdown 正文样式（加粗/列表/段落间距） */
.md-body :deep(p) {
  margin: 0 0 6px;
}

.md-body :deep(p:last-child) {
  margin-bottom: 0;
}

.md-body :deep(ul),
.md-body :deep(ol) {
  margin: 4px 0;
  padding-left: 18px;
}

.md-body :deep(strong) {
  font-weight: 600;
}

.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3),
.md-body :deep(h4) {
  font-size: 14px;
  margin: 8px 0 4px;
}

.low-tag {
  margin-top: 6px;
}

.msg-time {
  margin-top: 4px;
  font-size: 11px;
}

.bubble.user .msg-time {
  color: rgba(255, 255, 255, 0.7);
}

.input-zone {
  border-top: 1px solid #e4e7ed;
  padding-top: 10px;
}

.tts-switch {
  margin-bottom: 8px;
}

.input-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 8px;
}

@media (max-width: 767px) {
  .chat-page {
    flex-direction: column;
  }

  .session-panel {
    width: 100%;
  }

  .session-list {
    max-height: 140px;
  }
}
</style>
