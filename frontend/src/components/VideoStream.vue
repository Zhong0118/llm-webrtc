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
      </div>

      <!-- 远程视频 -->
      <div class="remote-video-wrapper">
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
        <el-button
          v-if="!isStreaming"
          type="primary"
          size="large"
          :loading="store.connectionState === 'connecting'"
          @click="startStream"
        >
          <el-icon><VideoPlay /></el-icon>
          开始视频通话
        </el-button>
        
        <el-button
          v-else
          type="danger"
          size="large"
          @click="stopStream"
        >
          <el-icon><VideoPause /></el-icon>
          停止通话
        </el-button>

        <el-button
          v-if="isStreaming"
          :type="analysisEnabled ? 'success' : 'info'"
          size="large"
          @click="toggleAnalysis"
        >
          <el-icon><View /></el-icon>
          {{ analysisEnabled ? '停止分析' : '开始AI分析' }}
        </el-button>

        <el-button
          v-if="isStreaming"
          :type="frameFilterEnabled ? 'success' : 'info'"
          size="large"
          @click="toggleFrameFilter"
        >
          <el-icon><Filter /></el-icon>
          {{ frameFilterEnabled ? '关闭帧过滤' : '开启帧过滤' }}
        </el-button>
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
import { useWebRTCStore } from '@/stores/webrtc'
import {
  VideoCamera,
  VideoCameraFilled,
  Monitor,
  VideoPlay,
  VideoPause,
  View,
  Filter
} from '@element-plus/icons-vue'

const store = useWebRTCStore()

const localVideoRef = ref(null)
const remoteVideoRef = ref(null)

// 计算属性
const isStreaming = computed(() => store.isStreamingState)
const analysisEnabled = computed(() => store.analysisSettings.enabled)
const frameFilterEnabled = computed(() => store.analysisSettings.frameFilter)
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
  } catch (error) {
    console.error('启动视频流失败:', error)
  }
}

// 停止视频流
const stopStream = () => {
  store.stopCall()
}

// 切换AI分析
const toggleAnalysis = () => {
  const newSettings = {
    ...store.analysisSettings,
    enabled: !store.analysisSettings.enabled
  }
  store.updateAnalysisSettings(newSettings)
}

// 切换帧过滤
const toggleFrameFilter = () => {
  const newSettings = {
    ...store.analysisSettings,
    frameFilter: !store.analysisSettings.frameFilter
  }
  store.updateAnalysisSettings(newSettings)
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
})

onUnmounted(() => {
  // 清理资源
  stopStream()
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