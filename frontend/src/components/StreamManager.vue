<template>
  <div class="stream-manager" v-if="store.isAvailable">
    <div class="stream-manager-header">
      <h3>FFmpeg RTSP 推流管理 (实时)</h3>
      <div class="status-indicator" :class="statusClass">
        <span class="status-dot"></span>
        <span class="status-text">{{ store.statusDisplay.text }}</span>
      </div>
    </div>

    <div v-if="store.error" class="error-message">
      错误: {{ store.error }}
    </div>

    <div class="vlc-panel">
      <div class="vlc-config">
        <h4>推流配置 (修改后需点击“更新配置”)</h4>
        <div class="config-grid">

          <!-- 可配置参数 (v-model 绑定到 localConfigBuffer) -->
          <div class="config-item">
            <label>分辨率:</label>
            <el-select v-model="localConfigBuffer.resolution" :disabled="store.isRunning">
              <el-option value="640x480">640x480</el-option>
              <el-option value="1280x720">1280x720</el-option>
            </el-select>
          </div>
          <div class="config-item">
            <label>帧率 (FPS):</label>
            <el-select v-model.number="localConfigBuffer.fps" :disabled="store.isRunning">
              <el-option :value="15">15</el-option>
              <el-option :value="30">30</el-option>
            </el-select>
          </div>
          <div class="config-item">
            <label>视频质量 (CRF, 越小越好):</label>
            <el-input-number v-model.number="localConfigBuffer.crf" :min="18" :max="28" controls-position="right" :disabled="store.isRunning" />
          </div>
          <div class="config-item">
            <label>编码预设 (越快越省CPU):</label>
            <el-select v-model="localConfigBuffer.preset" :disabled="store.isRunning">
              <el-option value="ultrafast">ultrafast</el-option>
              <el-option value="superfast">superfast</el-option>
              <el-option value="medium">medium</el-option>
            </el-select>
          </div>
        </div>
      </div>

      <div class="vlc-controls">
        <el-button
          type="primary"
          @click="store.startStream"
          :disabled="store.isRunning || store.statusText === '启动中...'"
          :loading="store.statusText === '启动中...'"
        >
          开始推流
        </el-button>
        <el-button
          type="danger"
          @click="store.stopStream"
          :disabled="!store.isRunning || store.statusText === '停止中...'"
          :loading="store.statusText === '停止中...'"
        >
          停止推流
        </el-button>
        <el-button
          @click="handleUpdateConfig"
          :disabled="store.isRunning"
          :loading="store.statusText === '更新配置中...'"
        >
          更新配置
        </el-button>
        <el-button @click="store.fetchStatus" :loading="store.statusText === '状态获取失败'">
          (手动)刷新状态
        </el-button>
      </div>

      <!-- 日志显示 (保持不变) -->
      <div v-if="showLogs" class="vlc-logs">
         <div class="logs-header">
           <h4>推流日志 (最近 {{ store.logs.length }} 条)</h4>
           <el-button type="text" @click="showLogs = false" style="padding: 0;">关闭</el-button>
         </div>
         <div class="logs-content">
           <pre v-for="(log, index) in store.logs" :key="index">{{ log }}</pre>
         </div>
       </div>
       <div class="vlc-actions">
         <el-button type="info" plain size="small" @click="toggleLogs">
           {{ showLogs ? '隐藏日志' : '显示日志' }}
         </el-button>
       </div>
    </div>
  </div>
  <div v-else class="stream-manager unavailable-notice">
    <el-alert
      title="FFmpeg RTSP推流模块不可用"
      type="warning"
      description="请检查后端服务器日志，确认FFmpeg推流模块已正确加载。"
      show-icon
      :closable="false"
    />
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onMounted, onUnmounted } from 'vue';
import { useStreamerStore } from '@/stores/useStreamerStore';

const store = useStreamerStore();
const showLogs = ref(false);
const localConfigBuffer = reactive({
  resolution: '640x480',
  fps: 30,
  crf: 28,
  preset: 'ultrafast',
});

watch(() => store.config, (newConfig) => {
  Object.assign(localConfigBuffer, newConfig);
}, { deep: true, immediate: true });

const handleUpdateConfig = () => {
  store.updateConfig({ ...localConfigBuffer });
};

const toggleLogs = () => {
  showLogs.value = !showLogs.value;
};

const statusClass = computed(() => {
    const type = store.statusDisplay.type;
    if (type === 'success') return 'status-success';
    if (type === 'warning' || store.statusText === '启动中...' || store.statusText === '停止中...' || store.statusText === '更新配置中...') return 'status-warning';
    if (type === 'danger') return 'status-error';
    return 'status-inactive';
});

// --- 修正：组件挂载时开始监听实时更新 ---
onMounted(() => {
  // store.startStatusPolling(); // 移除轮询
  store.listenForUpdates(); // 启用 WebSocket 监听
});

// --- 修正：组件卸载时停止监听 ---
onUnmounted(() => {
  // store.stopStatusPolling(); // 移除轮询
  store.stopListening(); // 停止 WebSocket 监听
});
</script>

<style scoped>
/* ... (样式保持不变) ... */
</style>
