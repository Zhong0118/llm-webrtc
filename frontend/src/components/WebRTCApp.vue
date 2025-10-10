<template>
  <div class="webrtc-app">
    <!-- 顶部导航 -->
    <el-header class="app-header">
      <div class="header-content">
        <div class="logo">
          <el-icon size="24"><VideoCamera /></el-icon>
          <span class="title">WebRTC AI 视频分析</span>
        </div>
        <div class="header-actions">
          <el-badge :value="store.signLanguageResults.length" class="item">
            <el-button type="primary" @click="toggleAnalysisPanel">
              <el-icon><DataAnalysis /></el-icon>
              分析结果
            </el-button>
          </el-badge>
          <el-button @click="showSettings = true">
            <el-icon><Setting /></el-icon>
            设置
          </el-button>
        </div>
      </div>
    </el-header>

    <!-- 主内容区域 -->
    <el-container class="main-container">
      <!-- 左侧视频区域 -->
      <el-main class="video-section">
        <VideoStream />
      </el-main>

      <!-- 右侧分析结果面板 -->
      <el-aside 
        v-show="showAnalysisPanel" 
        class="analysis-panel"
        width="400px"
      >
        <AnalysisResults />
      </el-aside>
    </el-container>

    <!-- 设置对话框 -->
    <el-dialog
      v-model="showSettings"
      title="系统设置"
      width="600px"
      :before-close="handleSettingsClose"
    >
      <el-form :model="settings" label-width="120px">
        <!-- WebRTC设置 -->
        <el-divider content-position="left">WebRTC 设置</el-divider>
        
        <el-form-item label="视频质量">
          <el-select v-model="settings.videoQuality" placeholder="选择视频质量">
            <el-option label="高清 (720p)" value="720p" />
            <el-option label="标清 (480p)" value="480p" />
            <el-option label="低清 (360p)" value="360p" />
          </el-select>
        </el-form-item>

        <el-form-item label="帧率">
          <el-slider
            v-model="settings.frameRate"
            :min="15"
            :max="60"
            :step="5"
            show-stops
            show-tooltip
          />
        </el-form-item>

        <el-form-item label="音频">
          <el-switch
            v-model="settings.audioEnabled"
            active-text="启用"
            inactive-text="禁用"
          />
        </el-form-item>

        <!-- 已移除通用AI分析设置，保留视频质量与性能设置 -->

        <!-- 性能设置 -->
        <el-divider content-position="left">性能设置</el-divider>

        <el-form-item label="GPU加速">
          <el-switch
            v-model="settings.gpuAcceleration"
            active-text="启用"
            inactive-text="禁用"
          />
        </el-form-item>

        <el-form-item label="批处理大小">
          <el-input-number
            v-model="settings.batchSize"
            :min="1"
            :max="10"
            controls-position="right"
          />
        </el-form-item>

        <el-form-item label="最大结果数">
          <el-input-number
            v-model="settings.maxResults"
            :min="50"
            :max="200"
            :step="10"
            controls-position="right"
          />
        </el-form-item>
      </el-form>

      <template #footer>
        <span class="dialog-footer">
          <el-button @click="resetSettings">重置</el-button>
          <el-button @click="showSettings = false">取消</el-button>
          <el-button type="primary" @click="saveSettings">保存</el-button>
        </span>
      </template>
    </el-dialog>

    <!-- 连接状态指示器 -->
    <div class="connection-status">
      <el-tag
        :type="getConnectionStatusType()"
        size="small"
        effect="dark"
      >
        <el-icon><Connection /></el-icon>
        {{ getConnectionStatusText() }}
      </el-tag>
    </div>

    <!-- 全局加载遮罩 -->
    <div
      v-loading="store.isInitializing"
      element-loading-text="正在初始化..."
      element-loading-background="rgba(0, 0, 0, 0.8)"
      style="position: fixed; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none;"
      v-if="store.isInitializing"
    ></div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useWebRTCStore } from '@/stores/webrtc'
import VideoStream from './VideoStream.vue'
import AnalysisResults from './AnalysisResults.vue'
import {
  VideoCamera,
  DataAnalysis,
  Setting,
  Connection
} from '@element-plus/icons-vue'

const store = useWebRTCStore()
const showSettings = ref(false)
const showAnalysisPanel = ref(true)

// 设置数据
const settings = reactive({
  // WebRTC设置
  videoQuality: '720p',
  frameRate: 30,
  audioEnabled: true,
  
  // 性能设置
  gpuAcceleration: true,
  batchSize: 1,
  maxResults: 200
})

// 生命周期
onMounted(async () => {
  try {
    // 加载保存的设置
    loadSettings()
    
    // 初始化WebRTC
    await store.initializeWebRTC()
    
    ElMessage.success('系统初始化完成')
  } catch (error) {
    console.error('初始化失败:', error)
    ElMessage.error('系统初始化失败: ' + error.message)
  }
})

onUnmounted(() => {
  // 清理资源
  store.cleanup()
})

// 方法
const toggleAnalysisPanel = () => {
  showAnalysisPanel.value = !showAnalysisPanel.value
}

const handleSettingsClose = (done) => {
  ElMessageBox.confirm('确定要关闭设置吗？未保存的更改将丢失。')
    .then(() => {
      done()
    })
    .catch(() => {
      // 取消关闭
    })
}

const saveSettings = async () => {
  try {
    // 保存到localStorage
    localStorage.setItem('webrtc-settings', JSON.stringify(settings))
    
    // 应用设置到store
    await applySettings()
    
    ElMessage.success('设置已保存')
    showSettings.value = false
  } catch (error) {
    console.error('保存设置失败:', error)
    ElMessage.error('保存设置失败')
  }
}

const loadSettings = () => {
  try {
    const saved = localStorage.getItem('webrtc-settings')
    if (saved) {
      Object.assign(settings, JSON.parse(saved))
    }
  } catch (error) {
    console.error('加载设置失败:', error)
  }
}

const resetSettings = () => {
  ElMessageBox.confirm('确定要重置所有设置吗？')
    .then(() => {
      // 重置为默认值
      Object.assign(settings, {
        videoQuality: '720p',
        frameRate: 30,
        audioEnabled: true,
        gpuAcceleration: true,
        batchSize: 1,
        maxResults: 200
      })
      
      ElMessage.success('设置已重置')
    })
    .catch(() => {
      // 取消重置
    })
}

const applySettings = async () => {
  // 计算视频约束
  const constraints = getVideoConstraints()

  // 1) 持久化到 store，用于后续 getUserMedia
  if (store.streamSettings && store.streamSettings.value) {
    store.streamSettings.value.video.width = constraints.width
    store.streamSettings.value.video.height = constraints.height
    store.streamSettings.value.video.frameRate = constraints.frameRate
    store.streamSettings.value.audio.enabled = settings.audioEnabled
  }

  // 同步分析最大结果数量（仅影响前端历史长度）
  if (store.updateAnalysisSettings) {
    store.updateAnalysisSettings({ maxResults: settings.maxResults })
  }

  // 2) 若正在采集，实时应用到当前视频轨道
  const ls = store.localStream
  if (ls) {
    const vt = ls.getVideoTracks && ls.getVideoTracks()[0]
    if (vt) {
      try {
        await vt.applyConstraints(constraints)
      } catch (e) {
        console.warn('应用视频约束失败，将在下次启动时生效:', e)
      }
    }
  }
}

const getVideoConstraints = () => {
  const qualityMap = {
    '720p': { width: 1280, height: 720 },
    '480p': { width: 854, height: 480 },
    '360p': { width: 640, height: 360 }
  }
  
  return {
    ...qualityMap[settings.videoQuality],
    frameRate: settings.frameRate
  }
}

const getConnectionStatusType = () => {
  switch (store.connectionState) {
    case 'connected': return 'success'
    case 'connecting': return 'warning'
    case 'disconnected': return 'danger'
    default: return 'info'
  }
}

const getConnectionStatusText = () => {
  switch (store.connectionState) {
    case 'connected': return '已连接'
    case 'connecting': return '连接中'
    case 'disconnected': return '已断开'
    default: return '未知状态'
  }
}
</script>

<style scoped>
.webrtc-app {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #f5f7fa;
}

.app-header {
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.header-content {
  display: flex;
  justify-content: space-between;
  align-items: center;
  height: 100%;
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 20px;
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
  color: #409eff;
}

.title {
  font-size: 20px;
  font-weight: 600;
}

.header-actions {
  display: flex;
  gap: 15px;
  align-items: center;
}

.main-container {
  flex: 1;
  overflow: hidden;
}

.video-section {
  padding: 20px;
  background: #fff;
  margin: 20px;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.analysis-panel {
  background: #fff;
  margin: 20px 20px 20px 0;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  padding: 20px;
  overflow: hidden;
}

.connection-status {
  position: fixed;
  bottom: 20px;
  right: 20px;
  z-index: 1000;
}

.dialog-footer {
  display: flex;
  gap: 10px;
}

/* 响应式设计 */
@media (max-width: 768px) {
  .header-content {
    padding: 0 10px;
  }
  
  .title {
    display: none;
  }
  
  .main-container {
    flex-direction: column;
  }
  
  .analysis-panel {
    width: 100% !important;
    height: 300px;
    margin: 0 20px 20px 20px;
  }
  
  .video-section {
    margin: 20px 20px 0 20px;
  }
}
</style>