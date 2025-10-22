<template>
  <div class="video-stream">
    <div class="video-container">
      <!-- 本地视频 -->
      <div class="local-video-wrapper">
        <video
          ref="localVideoRef"
          class="local-video"
          autoplay
          muted
          playsinline
        ></video>
        <!-- 隐藏的处理画布：用于分析前帧预处理 -->
        <canvas ref="procCanvasRef" class="processing-canvas"></canvas>
        <div class="video-overlay">
          <el-tag v-if="isStreaming" type="success" size="small">
            <el-icon><VideoCamera /></el-icon>
            本地视频
          </el-tag>
          <el-tag v-else type="info" size="small">
            <el-icon><VideoCameraFilled /></el-icon>
            未连接
          </el-tag>
        </div>
        <!-- 手语翻译叠加（轻量方案） -->
        <div class="sl-overlay" v-if="latestSL">
          <el-tag :type="(latestSL.confidence||0) > 0.6 ? 'success' : 'info'" effect="dark">
            {{ latestSL.text }}
            <span v-if="latestSL.confidence"> ({{ (latestSL.confidence*100).toFixed(0) }}%)</span>
          </el-tag>
        </div>
      </div>

      <!-- 远程视频 -->
      <div class="remote-video-wrapper" v-if="mode === 'live'">
        <video
          ref="remoteVideoRef"
          class="remote-video"
          autoplay
          playsinline
        ></video>
        <div class="video-overlay">
          <el-tag v-if="store.remoteStream" type="success" size="small">
            <el-icon><Monitor /></el-icon>
            远程视频
          </el-tag>
          <el-tag v-else type="warning" size="small">
            <el-icon><Monitor /></el-icon>
            等待连接
          </el-tag>
        </div>
      </div>
    </div>

    <!-- 控制面板 -->
    <div class="control-panel">
      <div class="control-buttons">
        <!-- 模式切换 -->
        <el-radio-group v-model="mode" size="large" style="margin-right:10px;">
          <el-radio-button label="live">直播</el-radio-button>
          <el-radio-button label="upload">上传视频</el-radio-button>
        </el-radio-group>

        <!-- 上传视频控件（美化：拖拽上传） -->
        <el-upload
          v-if="mode === 'upload'"
          class="upload-area"
          drag
          :show-file-list="false"
          :auto-upload="false"
          accept="video/*"
          :on-change="onUploadChange"
        >
          <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
          <div class="el-upload__text">拖拽或<em>点击上传</em> 视频文件</div>
        </el-upload>

        <el-button
          v-if="mode === 'live' && !isStreaming"
          type="primary"
          size="large"
          :loading="store.connectionState === 'connecting'"
          @click="startStream"
        >
          <el-icon><VideoPlay /></el-icon>
          开始视频通话
        </el-button>
        
        <el-button
          v-else-if="mode === 'live'"
          type="danger"
          size="large"
          @click="stopStream"
        >
          <el-icon><VideoPause /></el-icon>
          停止通话
        </el-button>

        <el-button
          v-if="(mode === 'live' && isStreaming) || mode === 'upload'"
          :type="analysisEnabled ? 'success' : 'info'"
          size="large"
          @click="toggleAnalysis"
        >
          <el-icon><View /></el-icon>
          {{ analysisEnabled ? '停止分析' : '开始AI分析' }}
        </el-button>

        <el-button
          v-if="(mode === 'live' && isStreaming) || mode === 'upload'"
          :type="frameFilterEnabled ? 'success' : 'info'"
          size="large"
          @click="toggleFrameFilter"
        >
          <el-icon><Filter /></el-icon>
          {{ frameFilterEnabled ? '关闭帧过滤' : '开启帧过滤' }}
        </el-button>

        <!-- 关键点采样FPS选择 -->
        <el-select v-model="keypointFps" placeholder="采样FPS" size="large" style="width:140px;">
          <el-option :value="2" label="2 FPS" />
          <el-option :value="5" label="5 FPS" />
          <el-option :value="10" label="10 FPS" />
        </el-select>

        <!-- 帧过滤模式选择（仅在开启过滤时生效） -->
        <el-select v-model="filterMode" placeholder="滤镜模式" size="large" style="width:160px;">
          <el-option value="enhance" label="增强(亮度/对比/饱和)" />
          <el-option value="bright" label="提亮" />
          <el-option value="contrast" label="对比增强" />
          <el-option value="gray" label="轻度灰度" />
          <el-option value="none" label="无" />
        </el-select>
      </div>

      <!-- 状态信息 -->
      <div class="status-info">
        <el-descriptions :column="4" size="small" border>
          <el-descriptions-item label="连接状态">
            <el-tag :type="getConnectionStatusType(store.connectionState)">
              {{ getConnectionStatusText(store.connectionState) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="视频编码">
            {{ store.statistics.video.codec || 'N/A' }}
          </el-descriptions-item>
          <el-descriptions-item label="分辨率">
            {{ store.statistics.video.resolution || 'N/A' }}
          </el-descriptions-item>
          <el-descriptions-item label="帧率">
            {{ store.statistics.video.frameRate || 0 }} FPS
          </el-descriptions-item>
          <el-descriptions-item label="视频码率">
            {{ formatBitrate(store.statistics.video.bitrate) }}
          </el-descriptions-item>
          <el-descriptions-item label="音频编码">
            {{ store.statistics.audio.codec || 'N/A' }}
          </el-descriptions-item>
          <el-descriptions-item label="延迟">
            {{ store.statistics.connection.latency || 0 }} ms
          </el-descriptions-item>
          <el-descriptions-item label="丢包率">
            {{ (store.statistics.connection.packetLoss * 100).toFixed(2) }}%
          </el-descriptions-item>
        </el-descriptions>
      </div>
    </div>

    <!-- 错误提示 -->
    <el-alert
      v-if="lastError"
      :title="lastError.message"
      type="error"
      :description="lastError.error"
      show-icon
      closable
      @close="clearErrors"
    />
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted, computed } from 'vue'
import { useWebRTCStore } from '@/stores/old/webrtc'
import {
  VideoCamera,
  VideoCameraFilled,
  Monitor,
  VideoPlay,
  VideoPause,
  View,
  Filter,
  UploadFilled
} from '@element-plus/icons-vue'
import { loadHandposeModel, toPlainHandData } from '@/utils/keypointsLoader'

const store = useWebRTCStore()

const localVideoRef = ref(null)
const remoteVideoRef = ref(null)
const procCanvasRef = ref(null)
const handposeModel = ref(null)
const keypointTimer = ref(null)
const latestSL = computed(() => store.latestSignLanguage)
const mode = ref('live')
const keypointFps = ref(5)
const filterMode = ref('enhance')

// 计算属性
const isStreaming = computed(() => store.isStreamingState)
const analysisEnabled = computed(() => store.isAnalysisEnabled)
const frameFilterEnabled = computed(() => store.isFrameFilterEnabled)
const lastError = computed(() => store.errors && Array.isArray(store.errors) && store.errors.length > 0 ? store.errors[store.errors.length - 1] : null)

// 监听本地流变化
watch(() => store.localStream, (newStream) => {
  if (newStream && localVideoRef.value) {
    localVideoRef.value.srcObject = newStream
  }
})

// 监听远程流变化
watch(() => store.remoteStream, (newStream) => {
  if (newStream && remoteVideoRef.value) {
    remoteVideoRef.value.srcObject = newStream
  }
})

// 开始视频流
const startStream = async () => {
  try {
    await store.startCall()
    if (analysisEnabled.value) await startKeypointCapture()
  } catch (error) {
    console.error('启动视频流失败:', error)
  }
}

// 停止视频流
const stopStream = () => {
  store.stopCall()
  stopKeypointCapture()
}

// 切换AI分析
const toggleAnalysis = () => {
  const enabled = !analysisEnabled.value
  // 修正：Pinia ref 赋值需使用 .value
  store.isAnalysisEnabled.value = enabled
  if (enabled) {
    startKeypointCapture()
  } else {
    stopKeypointCapture()
  }
}

// 切换帧过滤
const toggleFrameFilter = () => {
  // 修正：Pinia ref 赋值需使用 .value
  store.isFrameFilterEnabled.value = !frameFilterEnabled.value
}

// 获取连接状态类型
const getConnectionStatusType = (state) => {
  const types = {
    'disconnected': 'info',
    'connecting': 'warning',
    'connected': 'success',
    'failed': 'danger'
  }
  return types[state] || 'info'
}

// 获取连接状态文本
const getConnectionStatusText = (state) => {
  const texts = {
    'disconnected': '未连接',
    'connecting': '连接中',
    'connected': '已连接',
    'failed': '连接失败'
  }
  return texts[state] || '未知'
}

// 格式化码率
const formatBitrate = (bitrate) => {
  if (!bitrate) return '0 kbps'
  if (bitrate < 1000) return `${bitrate} kbps`
  return `${(bitrate / 1000).toFixed(1)} Mbps`
}

// 清除错误
const clearErrors = () => {
  // 清空错误数组
  store.clearErrors()
}

onMounted(() => {
  // 初始化设备列表
  store.updateDevices()
  // 恢复持久化设置
  try {
    const m = localStorage.getItem('vs-mode')
    if (m) mode.value = m
    const fps = Number(localStorage.getItem('vs-keypoint-fps'))
    if (fps) keypointFps.value = fps
    const fm = localStorage.getItem('vs-filter-mode')
    if (fm) filterMode.value = fm
  } catch {}
})

onUnmounted(() => {
  // 清理资源
  stopStream()
  stopKeypointCapture()
})

// 持久化：模式、采样FPS、滤镜模式
watch(mode, (v) => {
  try { localStorage.setItem('vs-mode', v) } catch {}
})
watch(keypointFps, (v) => {
  try { localStorage.setItem('vs-keypoint-fps', String(v)) } catch {}
})
watch(filterMode, (v) => {
  try { localStorage.setItem('vs-filter-mode', v) } catch {}
})

// 关键点采集与发送（轻量方案）
const startKeypointCapture = async () => {
  try {
    if (!localVideoRef.value) return
    if (!handposeModel.value) {
      handposeModel.value = await loadHandposeModel()
    }
    // 准备处理画布尺寸（降采样以提升性能）
    const video = localVideoRef.value
    const canvas = procCanvasRef.value
    const aspect = video.videoHeight ? (video.videoWidth / video.videoHeight) : (16/9)
    const targetWidth = 320
    canvas.width = targetWidth
    canvas.height = Math.max(1, Math.round(targetWidth / aspect))
    const ctx = canvas.getContext('2d')

    const targetFps = keypointFps.value
    const intervalMs = Math.max(50, Math.floor(1000 / targetFps))
    stopKeypointCapture()
    // 序列缓冲与简单切割参数
    let seqBuffer = []
    let lastHand = null
    let inactiveCount = 0
    const sequenceMaxMs = 2000 // 最长序列窗口（毫秒）
    const inactivityFrames = 3 // 连续静止帧触发切割
    const motionThreshold = 0.005 // 平均关键点位移阈值（归一化坐标）

    const computeMotion = (prev, curr) => {
      if (!prev || !curr) return 1
      const p = prev.landmarks || []
      const c = curr.landmarks || []
      if (!p.length || !c.length) return 1
      const n = Math.min(p.length, c.length)
      let sum = 0
      for (let i = 0; i < n; i++) {
        const dx = (c[i][0] - p[i][0])
        const dy = (c[i][1] - p[i][1])
        sum += Math.sqrt(dx*dx + dy*dy)
      }
      return sum / n
    }

    keypointTimer.value = setInterval(async () => {
      try {
        if (!video.videoWidth || !video.videoHeight) return
        // 根据开关与模式应用预处理滤镜到Canvas
        const filterMap = {
          enhance: 'brightness(1.05) contrast(1.1) saturate(1.1)',
          bright: 'brightness(1.15)',
          contrast: 'contrast(1.25)',
          gray: 'grayscale(0.15)',
          none: 'none'
        }
        const activeFilter = frameFilterEnabled.value ? (filterMap[filterMode.value] || filterMap.enhance) : 'none'
        ctx.filter = activeFilter
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
        const source = canvas
        const preds = await handposeModel.value.estimateHands(source, true)
        const hands = toPlainHandData(preds)
        const now = Date.now()

        // 只取第一只手做简单时序度量
        const currentHand = (hands && hands.length) ? hands[0] : null
        const motion = computeMotion(lastHand, currentHand)
        if (currentHand && motion < motionThreshold) {
          inactiveCount++
        } else if (!currentHand) {
          inactiveCount++
        } else {
          inactiveCount = 0
        }

        // 追加到缓冲序列
        seqBuffer.push({ hands, timestamp: now })

        // 判断是否切割并发送序列：达到最大时长或静止若干帧
        const duration = now - (seqBuffer[0]?.timestamp || now)
        const shouldCut = (duration >= sequenceMaxMs) || (inactiveCount >= inactivityFrames)
        if (shouldCut && seqBuffer.length >= 2) {
          if (store.socket) {
            store.socket.emit('analysis_keypoints_sequence', {
              source: 'local',
              fps: targetFps,
              frames: seqBuffer,
              started_at: seqBuffer[0].timestamp,
              ended_at: now
            })
          }
          // 重置序列缓冲
          seqBuffer = []
          inactiveCount = 0
          lastHand = null
        } else {
          // 更新上一帧手数据
          lastHand = currentHand
        }
      } catch {}
    }, intervalMs)
  } catch (e) {
    console.error('关键点采集启动失败:', e)
  }
}

const stopKeypointCapture = () => {
  if (keypointTimer.value) {
    clearInterval(keypointTimer.value)
    keypointTimer.value = null
  }
}

// 上传视频切换
const onVideoFileChange = (e) => {
  const file = e.target.files && e.target.files[0]
  if (!file || !localVideoRef.value) return
  stopStream()
  const url = URL.createObjectURL(file)
  localVideoRef.value.srcObject = null
  localVideoRef.value.src = url
  localVideoRef.value.play()
  if (analysisEnabled.value) startKeypointCapture()
}

// Element Plus 上传组件回调
const onUploadChange = (file) => {
  const raw = file && file.raw
  if (!raw || !localVideoRef.value) return
  stopStream()
  const url = URL.createObjectURL(raw)
  localVideoRef.value.srcObject = null
  localVideoRef.value.src = url
  localVideoRef.value.play()
  if (analysisEnabled.value) startKeypointCapture()
}

// 本地流就绪时自动开启采集
watch(() => store.localStream, (newStream) => {
  if (newStream && localVideoRef.value && analysisEnabled.value) {
    startKeypointCapture()
  }
})
</script>

<style scoped>
.video-stream {
  padding: 20px;
}

.video-container {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
  margin-bottom: 20px;
}

.local-video-wrapper,
.remote-video-wrapper {
  position: relative;
  background: #000;
  border-radius: 8px;
  overflow: hidden;
  aspect-ratio: 16/9;
}

.local-video,
.remote-video {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

/* 隐藏的分析处理画布 */
.processing-canvas {
  display: none;
}

.upload-area {
  width: 240px;
}

.video-overlay {
  position: absolute;
  top: 10px;
  left: 10px;
  z-index: 10;
}

.control-panel {
  background: #f5f5f5;
  padding: 20px;
  border-radius: 8px;
  margin-bottom: 20px;
}

.control-buttons {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

.status-info {
  margin-top: 20px;
}

@media (max-width: 768px) {
  .video-container {
    grid-template-columns: 1fr;
  }
  
  .control-buttons {
    flex-direction: column;
  }
}
</style>