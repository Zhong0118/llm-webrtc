<template>
  <div class="stream-manager">
    <div class="stream-manager-header">
      <h3>视频源管理</h3>
      <div class="source-selector">
        <label>
          <input 
            type="radio" 
            value="webrtc" 
            v-model="currentSourceType"
            @change="handleSourceChange"
          />
          WebRTC摄像头
        </label>
        <label>
          <input 
            type="radio" 
            value="vlc" 
            v-model="currentSourceType"
            @change="handleSourceChange"
            :disabled="!isVlcAvailable"
          />
          VLC推流
          <span v-if="!isVlcAvailable" class="unavailable">(不可用)</span>
        </label>
      </div>
    </div>

    <!-- VLC推流控制面板 -->
    <div v-if="currentSourceType === 'vlc'" class="vlc-panel">
      <div class="vlc-status">
        <div class="status-indicator" :class="vlcStatusClass">
          <span class="status-dot"></span>
          <span class="status-text">{{ vlcStatusText }}</span>
        </div>
        <div v-if="vlcError" class="error-message">
          错误: {{ vlcError }}
        </div>
      </div>

      <div class="vlc-config">
        <h4>推流配置</h4>
        <div class="config-grid">
          <div class="config-item">
            <label>输入源:</label>
            <input 
              type="text" 
              v-model="localConfig.input_source"
              placeholder="摄像头名称或文件路径"
              :disabled="isVlcStreaming"
            />
          </div>
          
          <div class="config-item">
            <label>RTSP地址:</label>
            <input 
              type="text" 
              v-model="localConfig.rtsp_url"
              placeholder="rtsp://localhost:8554/live"
              :disabled="isVlcStreaming"
            />
          </div>
          
          <div class="config-item">
            <label>分辨率:</label>
            <select v-model="localConfig.resolution" :disabled="isVlcStreaming">
              <option value="640x480">640x480</option>
              <option value="1280x720">1280x720</option>
              <option value="1920x1080">1920x1080</option>
            </select>
          </div>
          
          <div class="config-item">
            <label>帧率:</label>
            <select v-model="localConfig.fps" :disabled="isVlcStreaming">
              <option :value="15">15 FPS</option>
              <option :value="30">30 FPS</option>
              <option :value="60">60 FPS</option>
            </select>
          </div>
          
          <div class="config-item">
            <label>视频质量 (CRF):</label>
            <input 
              type="range" 
              min="18" 
              max="28" 
              v-model="localConfig.crf"
              :disabled="isVlcStreaming"
            />
            <span>{{ localConfig.crf }}</span>
          </div>
          
          <div class="config-item">
            <label>编码预设:</label>
            <select v-model="localConfig.preset" :disabled="isVlcStreaming">
              <option value="ultrafast">ultrafast</option>
              <option value="superfast">superfast</option>
              <option value="veryfast">veryfast</option>
              <option value="faster">faster</option>
              <option value="fast">fast</option>
              <option value="medium">medium</option>
              <option value="slow">slow</option>
            </select>
          </div>
        </div>
      </div>

      <div class="vlc-controls">
        <button 
          @click="handleStartStream"
          :disabled="isVlcStreaming || vlcStatus === 'starting'"
          class="btn btn-primary"
        >
          {{ vlcStatus === 'starting' ? '启动中...' : '开始推流' }}
        </button>
        
        <button 
          @click="handleStopStream"
          :disabled="!isVlcStreaming || vlcStatus === 'stopping'"
          class="btn btn-secondary"
        >
          {{ vlcStatus === 'stopping' ? '停止中...' : '停止推流' }}
        </button>
        
        <button 
          @click="handleUpdateConfig"
          :disabled="isVlcStreaming"
          class="btn btn-outline"
        >
          更新配置
        </button>
        
        <button 
          @click="handleRefreshStatus"
          class="btn btn-outline"
        >
          刷新状态
        </button>
      </div>

      <!-- 推流日志 -->
      <div v-if="showLogs" class="vlc-logs">
        <div class="logs-header">
          <h4>推流日志</h4>
          <button @click="showLogs = false" class="btn-close">×</button>
        </div>
        <div class="logs-content">
          <div 
            v-for="(log, index) in vlcLogs" 
            :key="index"
            class="log-entry"
          >
            {{ log }}
          </div>
        </div>
      </div>
      
      <div class="vlc-actions">
        <button 
          @click="toggleLogs"
          class="btn btn-outline btn-small"
        >
          {{ showLogs ? '隐藏日志' : '显示日志' }}
        </button>
      </div>
    </div>

    <!-- WebRTC状态显示 -->
    <div v-else class="webrtc-panel">
      <div class="webrtc-status">
        <div class="status-indicator" :class="webrtcStatusClass">
          <span class="status-dot"></span>
          <span class="status-text">{{ webrtcStatusText }}</span>
        </div>
      </div>
      <p class="webrtc-info">
        使用本地摄像头进行WebRTC通信
      </p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useWebRTCStore } from '@/stores/old/webrtc'

const webrtcStore = useWebRTCStore()

// 本地状态
const currentSourceType = ref('webrtc')
const showLogs = ref(false)
const localConfig = ref({
  input_source: 'Integrated Camera',
  rtsp_url: 'rtsp://localhost:8554/mystream',
  resolution: '640x480',
  fps: 30,
  crf: 28,
  preset: 'ultrafast',
  ffmpeg_path: 'ffmpeg'
})

// 从store获取状态
const isVlcAvailable = computed(() => webrtcStore.isVlcAvailable)
const isVlcStreaming = computed(() => webrtcStore.isVlcStreaming)
const vlcStatus = computed(() => webrtcStore.vlcStatus)
const vlcError = computed(() => webrtcStore.vlcError)
const vlcLogs = computed(() => webrtcStore.vlcStreamState.logs)

// WebRTC状态
const isWebRTCConnected = computed(() => webrtcStore.isConnected)
const isWebRTCConnecting = computed(() => webrtcStore.isConnecting)

// 状态显示
const vlcStatusClass = computed(() => {
  switch (vlcStatus.value) {
    case 'streaming': return 'status-success'
    case 'starting': 
    case 'stopping': return 'status-warning'
    case 'error': return 'status-error'
    default: return 'status-inactive'
  }
})

const vlcStatusText = computed(() => {
  switch (vlcStatus.value) {
    case 'streaming': return '推流中'
    case 'starting': return '启动中'
    case 'stopping': return '停止中'
    case 'error': return '错误'
    case 'stopped': return '已停止'
    default: return '未知状态'
  }
})

const webrtcStatusClass = computed(() => {
  if (isWebRTCConnected.value) return 'status-success'
  if (isWebRTCConnecting.value) return 'status-warning'
  return 'status-inactive'
})

const webrtcStatusText = computed(() => {
  if (isWebRTCConnected.value) return '已连接'
  if (isWebRTCConnecting.value) return '连接中'
  return '未连接'
})

// 事件处理
const handleSourceChange = async () => {
  try {
    await webrtcStore.switchVideoSource(currentSourceType.value)
  } catch (error) {
    console.error('切换视频源失败:', error)
    // 恢复到之前的选择
    currentSourceType.value = webrtcStore.videoSourceType
  }
}

const handleStartStream = async () => {
  try {
    await webrtcStore.updateVlcConfig(localConfig.value)
    await webrtcStore.startVlcStream()
  } catch (error) {
    console.error('启动推流失败:', error)
  }
}

const handleStopStream = async () => {
  try {
    await webrtcStore.stopVlcStream()
  } catch (error) {
    console.error('停止推流失败:', error)
  }
}

const handleUpdateConfig = async () => {
  try {
    await webrtcStore.updateVlcConfig(localConfig.value)
  } catch (error) {
    console.error('更新配置失败:', error)
  }
}

const handleRefreshStatus = async () => {
  try {
    await webrtcStore.getVlcStatus()
    if (showLogs.value) {
      await webrtcStore.getVlcLogs()
    }
  } catch (error) {
    console.error('刷新状态失败:', error)
  }
}

const toggleLogs = async () => {
  showLogs.value = !showLogs.value
  if (showLogs.value) {
    await webrtcStore.getVlcLogs()
  }
}

// 监听store中的配置变化
watch(() => webrtcStore.vlcStreamConfig, (newConfig) => {
  localConfig.value = { ...newConfig }
}, { deep: true })

// 监听store中的视频源类型变化
watch(() => webrtcStore.videoSourceType, (newType) => {
  currentSourceType.value = newType
})

// 组件挂载时初始化
onMounted(async () => {
  await webrtcStore.getVlcStatus()
  currentSourceType.value = webrtcStore.videoSourceType
  localConfig.value = { ...webrtcStore.vlcStreamConfig }
})
</script>

<style scoped>
.stream-manager {
  background: white;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  margin-bottom: 20px;
}

.stream-manager-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  padding-bottom: 15px;
  border-bottom: 1px solid #eee;
}

.stream-manager-header h3 {
  margin: 0;
  color: #333;
}

.source-selector {
  display: flex;
  gap: 20px;
}

.source-selector label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-weight: 500;
}

.source-selector input[type="radio"] {
  margin: 0;
}

.unavailable {
  color: #999;
  font-size: 0.9em;
}

.vlc-panel, .webrtc-panel {
  margin-top: 20px;
}

.vlc-status, .webrtc-status {
  margin-bottom: 20px;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.status-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  display: inline-block;
}

.status-success .status-dot {
  background-color: #52c41a;
}

.status-warning .status-dot {
  background-color: #faad14;
}

.status-error .status-dot {
  background-color: #ff4d4f;
}

.status-inactive .status-dot {
  background-color: #d9d9d9;
}

.status-text {
  font-weight: 500;
}

.error-message {
  color: #ff4d4f;
  background-color: #fff2f0;
  padding: 8px 12px;
  border-radius: 4px;
  border: 1px solid #ffccc7;
  font-size: 0.9em;
}

.vlc-config {
  margin-bottom: 20px;
}

.vlc-config h4 {
  margin: 0 0 15px 0;
  color: #333;
}

.config-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 15px;
}

.config-item {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.config-item label {
  font-weight: 500;
  color: #555;
  font-size: 0.9em;
}

.config-item input,
.config-item select {
  padding: 8px 12px;
  border: 1px solid #d9d9d9;
  border-radius: 4px;
  font-size: 0.9em;
}

.config-item input:disabled,
.config-item select:disabled {
  background-color: #f5f5f5;
  color: #999;
}

.config-item input[type="range"] {
  padding: 0;
}

.vlc-controls {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}

.btn {
  padding: 10px 20px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-weight: 500;
  transition: all 0.2s;
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-primary {
  background-color: #1890ff;
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background-color: #40a9ff;
}

.btn-secondary {
  background-color: #52c41a;
  color: white;
}

.btn-secondary:hover:not(:disabled) {
  background-color: #73d13d;
}

.btn-outline {
  background-color: white;
  color: #1890ff;
  border: 1px solid #1890ff;
}

.btn-outline:hover:not(:disabled) {
  background-color: #f0f8ff;
}

.btn-small {
  padding: 6px 12px;
  font-size: 0.9em;
}

.vlc-logs {
  background-color: #f8f9fa;
  border: 1px solid #e9ecef;
  border-radius: 4px;
  margin-bottom: 15px;
}

.logs-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 15px;
  border-bottom: 1px solid #e9ecef;
  background-color: #f1f3f4;
}

.logs-header h4 {
  margin: 0;
  font-size: 0.9em;
  color: #333;
}

.btn-close {
  background: none;
  border: none;
  font-size: 18px;
  cursor: pointer;
  color: #666;
  padding: 0;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.logs-content {
  max-height: 200px;
  overflow-y: auto;
  padding: 10px 15px;
}

.log-entry {
  font-family: 'Courier New', monospace;
  font-size: 0.8em;
  color: #333;
  margin-bottom: 5px;
  word-break: break-all;
}

.vlc-actions {
  display: flex;
  gap: 10px;
}

.webrtc-info {
  color: #666;
  margin: 0;
  font-size: 0.9em;
}
</style>